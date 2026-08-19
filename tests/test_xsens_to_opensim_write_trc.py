"""
Tests write_trc/_trc_header -- the pure-Python half of xsens_to_opensim.py's
marker/.trc export (added 2026-08-19 so OpenCap's own downstream gait-event
code, which reads marker trajectories rather than raw joint angles, can
consume Xsens-derived motion; see get_marker_trajectory's docstring).

Does NOT test get_marker_trajectory itself -- that needs the `opensim`
package to drive a real model through forward kinematics, which isn't
installed in the interpreter these tests run under (see VENDORING.md).
That half was instead verified with a real end-to-end run against real data
in the opencap-processing conda env.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'xsens_to_opensim.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('xsens_to_opensim_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def test_trc_header_line_counts_and_shape(mod, tmp_path):
    trc_path = tmp_path / "out.trc"
    lines = mod._trc_header(str(trc_path), frame_rate=60, n_frames=2, n_markers=2,
                             marker_names=["pelvis", "r_ankle"])
    assert len(lines) == 5
    assert lines[0].startswith("PathFileType\t4\t(X/Y/Z)\tout.trc")
    assert lines[1] == (
        "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\t"
        "OrigDataRate\tOrigDataStartFrame\tOrigNumFrames"
    )
    assert lines[2] == "60\t60\t2\t2\tm\t60\t1\t2"
    # Label row: Frame#, Time, then each marker name repeated across its X/Y/Z columns.
    assert lines[3] == "Frame#\tTime\tpelvis\t\t\tr_ankle\t\t"
    # Sub-label row: blank under Frame#/Time, then X/Y/Z indices per marker.
    assert lines[4] == "\t\tX1\tY1\tZ1\tX2\tY2\tZ2"


def test_write_trc_row_count_and_values(mod, tmp_path):
    trc_path = tmp_path / "out.trc"
    times = [0.0, 1.0 / 60]
    marker_names = ["pelvis", "r_ankle"]
    positions = [
        [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)],
        [(0.11, 0.21, 0.31), (0.41, 0.51, 0.61)],
    ]
    mod.write_trc(str(trc_path), times, marker_names, positions, frame_rate=60)

    lines = trc_path.read_text().splitlines()
    assert len(lines) == 5 + len(times)  # header + one row per frame

    header_meta = lines[2].split("\t")
    assert header_meta[2] == "2"  # NumFrames
    assert header_meta[3] == "2"  # NumMarkers

    frame1 = lines[5].split("\t")
    assert frame1[0] == "1"
    assert frame1[1] == "0.000000"
    assert frame1[2:5] == ["0.100000", "0.200000", "0.300000"]
    assert frame1[5:8] == ["0.400000", "0.500000", "0.600000"]

    frame2 = lines[6].split("\t")
    assert frame2[0] == "2"
    assert frame2[2:5] == ["0.110000", "0.210000", "0.310000"]


def test_write_trc_rejects_mismatched_lengths(mod, tmp_path):
    # Codex review (2026-08-19) flagged that zip(times, positions) silently
    # truncates to the shorter of the two, producing a .trc whose header
    # NumFrames disagrees with the actual row count. Must raise instead.
    trc_path = tmp_path / "out.trc"
    times = [0.0, 1.0 / 60, 2.0 / 60]
    positions = [[(0.0, 0.0, 0.0)], [(0.0, 0.0, 0.01)]]  # one frame short
    with pytest.raises(ValueError, match="times but 2 position frames"):
        mod.write_trc(str(trc_path), times, ["pelvis"], positions, frame_rate=60)


def test_write_markers_trc_frame_rate_from_times(mod, monkeypatch, tmp_path):
    # write_markers_trc derives frame_rate from the actual time spacing
    # rather than assuming a fixed value -- confirm that derivation, without
    # needing opensim, by faking get_marker_trajectory's return.
    fake_times = [0.0, 0.02, 0.04]  # 50 Hz
    fake_positions = [
        [(0.0, 0.0, 0.0)],
        [(0.0, 0.0, 0.01)],
        [(0.0, 0.0, 0.02)],
    ]
    monkeypatch.setattr(
        mod, "get_marker_trajectory",
        lambda model_file, mot_file: (fake_times, ["pelvis"], fake_positions),
    )
    trc_path = tmp_path / "out.trc"
    mod.write_markers_trc("fake_model.osim", "fake.mot", str(trc_path))

    lines = trc_path.read_text().splitlines()
    header_meta = lines[2].split("\t")
    assert header_meta[0] == "50"  # DataRate derived from 0.02s spacing
    assert header_meta[2] == "3"   # NumFrames
