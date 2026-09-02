"""Tests for raw_drift.py -- the pre-processing session check.

Synthetic MVNX files with a planted drift, so what is tested is whether a
known drift is found, an absent one is not claimed, and the angle handling
survives the +/-180 seam that produced a 296-degree artefact by hand.
"""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "raw_drift_under_test", REPO_ROOT / "raw_drift.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _quat_yaw(degrees):
    half = math.radians(degrees) / 2.0
    return (math.cos(half), 0.0, 0.0, math.sin(half))


def _write_mvnx(path, pelvis_yaw, right_yaw, left_yaw, right_hip=10.0,
                n_frames=6, n_segments=23, n_joints=22):
    quats = [(1.0, 0.0, 0.0, 0.0)] * n_segments
    quats[0], quats[17], quats[21] = (_quat_yaw(pelvis_yaw),
                                      _quat_yaw(right_yaw), _quat_yaw(left_yaw))
    orientation = " ".join(f"{v:.9f}" for q in quats for v in q)
    angles = [0.0] * (n_joints * 3)
    angles[14 * 3 + 2] = right_hip
    joint_text = " ".join(f"{v:.6f}" for v in angles)
    frames = "".join(
        f'<frame time="{i}" index="{i}" type="normal">'
        f"<orientation>{orientation}</orientation>"
        f"<jointAngle>{joint_text}</jointAngle></frame>"
        for i in range(n_frames))
    segments = "".join(f'<segment label="S{i}" id="{i}"/>' for i in range(n_segments))
    path.write_text(
        f"<mvnx><subject><segments>{segments}</segments>"
        f'<frames>{frames}</frames></subject></mvnx>', encoding="utf-8")
    return path


def _session(tmp_path, n=10, pelvis_step=0.0, right_step=0.0, hip_step=0.0,
             pelvis0=0.0, right0=10.0):
    folder = tmp_path / "HD Reprocessed"
    folder.mkdir(parents=True, exist_ok=True)
    for trial in range(1, n + 1):
        _write_mvnx(folder / f"P-{trial:03d}.mvnx",
                    pelvis_yaw=pelvis0 + pelvis_step * trial,
                    right_yaw=pelvis0 + right0 + (pelvis_step + right_step) * trial,
                    left_yaw=pelvis0 + pelvis_step * trial,
                    right_hip=10.0 + hip_step * trial)
    return folder


# -- angle handling, which is where the hand analysis went wrong ------------


def test_a_difference_across_the_seam_is_wrapped(mod):
    """Differencing raw atan2 outputs reported a 296-degree drift by hand. A
    foot either side of +/-180 reads as a full turn without this."""
    assert mod.wrap_degrees(179.0 - (-179.0)) == pytest.approx(-2.0)
    assert mod.wrap_degrees(-179.0 - 179.0) == pytest.approx(2.0)


def test_the_circular_mean_does_not_land_opposite_the_data(mod):
    """An arithmetic mean of 179 and -179 is 0 -- the far side of the circle."""
    assert abs(mod.circular_mean([179.0, -179.0])) == pytest.approx(180.0, abs=1e-6)


def test_a_flexion_series_is_not_unwrapped(mod):
    """Flexion is bounded and sagittal; unwrapping would invent 360-degree
    jumps in a quantity that has none."""
    # A series that genuinely crosses the seam: as headings these rise
    # steadily (150 -> 205); read literally they lurch downward at the seam.
    # Eight points, because `change` compares the first three against the last
    # three and would be identically zero on a three-point series.
    order = list(range(1, 9))
    values = [mod.wrap_degrees(150.0 + 8.0 * i) for i in range(8)]

    circular_r, circular_change = mod.trend(order, values, circular=True)
    plain_r, plain_change = mod.trend(order, values, circular=False)

    assert circular_r == pytest.approx(1.0)      # unwrapped: rising
    assert plain_r < 0                            # literal: apparently falling
    assert circular_change > 0 > plain_change     # opposite signs entirely


# -- finding a planted drift -----------------------------------------------


def test_absolute_heading_drift_is_reported_but_not_alarming(mod, tmp_path):
    """Shared heading drift cancels out of joint angles; the session should be
    flagged as having it without claiming it reaches results."""
    folder = _session(tmp_path, pelvis_step=2.0)

    report = mod.session_report(folder)
    text = mod.format_report(report)

    assert report["measures"]["pelvis"]["alert"] is True
    assert report["measures"]["right_minus_pelvis"]["alert"] is False
    assert "mostly cancels" in text


def test_a_foot_drifting_against_the_pelvis_is_the_alarm(mod, tmp_path):
    folder = _session(tmp_path, pelvis_step=2.0, right_step=1.0)

    report = mod.session_report(folder)
    text = mod.format_report(report)

    assert report["measures"]["right_minus_pelvis"]["alert"] is True
    assert "will reach the results" in text


def test_hip_flexion_drift_is_caught_too(mod, tmp_path):
    """A yaw-only check misses this: one real participant has no foot yaw
    drift at all, yet its right hip flexion moves -6.2 deg at r = -0.951 and
    that is what takes its score down."""
    folder = _session(tmp_path, hip_step=-0.8)

    report = mod.session_report(folder)

    assert report["measures"]["right_hip_flexion"]["alert"] is True
    assert report["measures"]["left_hip_flexion"]["alert"] is False


def test_a_clean_session_raises_nothing(mod, tmp_path):
    folder = _session(tmp_path)

    report = mod.session_report(folder)

    assert not any(m["alert"] for m in report["measures"].values())


def test_a_small_drift_is_not_alarming_however_correlated(mod, tmp_path):
    """A perfectly monotonic tenth of a degree per trial is still nothing."""
    folder = _session(tmp_path, pelvis_step=0.05)

    report = mod.session_report(folder)

    assert report["measures"]["pelvis"]["r"] > 0.99
    assert report["measures"]["pelvis"]["alert"] is False


def test_a_short_session_gets_no_trend(mod, tmp_path):
    folder = _session(tmp_path, n=4, pelvis_step=5.0)

    report = mod.session_report(folder)

    assert "note" in report
    assert report["measures"] == {}


def test_segment_indices_come_from_the_file(mod, tmp_path):
    folder = _session(tmp_path, n=6)
    labels = mod.segment_indices(sorted(folder.glob("*.mvnx"))[0])

    assert labels["S0"] == 0 and labels["S17"] == 17


def test_calibration_frames_are_excluded(mod, tmp_path):
    """npose/tpose frames are not walking and would bias the per-trial mean."""
    folder = tmp_path / "HD Reprocessed"
    folder.mkdir(parents=True)
    path = _write_mvnx(folder / "P-001.mvnx", 0.0, 10.0, 0.0)
    text = path.read_text(encoding="utf-8").replace(
        '<frames>', '<frames><frame time="0" index="-3" type="npose">'
        '<orientation>' + " ".join(["1 0 0 0"] * 23) + '</orientation></frame>')
    path.write_text(text, encoding="utf-8")

    values = mod.trial_yaws(path)

    assert values["right_minus_pelvis"] == pytest.approx(10.0, abs=0.01)


def test_no_mvnx_files_says_so(mod, tmp_path):
    with pytest.raises(FileNotFoundError, match="no .mvnx"):
        mod.session_report(tmp_path)
