"""
Tests U4 of the clinician trial report GUI plan: results review display
(R6, R7, R8) -- the pure, Tk-free data-shaping functions in clinician_gui.py
that turn a completed run_pipeline() result into display-ready structures
for metadata, joint-angle plots, gait metrics, and the confidence
indicator.

Per the plan's Verification note, actual Tk widget rendering (ClinicianGUI's
_render_* methods) is a manual smoke check, not something these tests
attempt -- they exercise shape_metadata_for_display, shape_joint_curves_for_display,
shape_gait_metrics_for_display, shape_confidence_for_display, and the
shape_results_for_display orchestrator directly, against fakes built to
match the real return shapes confirmed by reading gait_analysis_UCM_fixed.py
(get_coordinates_normalized_time(), compute_scalars(), coordinateValues) and
xsens_to_opensim.py (parse_mvnx()).

Follows this repo's existing test convention (see
tests/test_clinician_gui_pipeline.py, tests/test_joint_confidence.py): load
the module under test via importlib.util.spec_from_file_location, and use
the real joint_confidence.py (loaded the same way, via clinician_gui.py's
own _load_joint_confidence() seam) rather than faking it -- joint_confidence.py
has no opensim/heavy dependency, so exercising it for real here proves this
GUI's own orchestration wiring, not just its shaping logic in isolation.
"""
import importlib.util
import os
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('clinician_gui_display_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# Fakes matching the real shapes confirmed by reading gait_analysis_UCM_fixed.py:
#   get_coordinates_normalized_time() -> {'mean': DataFrame, 'sd': DataFrame|None,
#       'indiv': [DataFrame, ...]}, one column per coordinate name, indexed 0-100.
#   compute_scalars(names) -> {name: {'value': ..., 'units': ...}}
#   .coordinateValues -> a plain DataFrame with a 'time' column plus one
#       column per OpenSim coordinate name (utilsKinematics.kinematics.
#       get_coordinate_values()'s return shape, stored as self.coordinateValues
#       by gait_analysis_UCM_fixed.py's own __init__).
# ---------------------------------------------------------------------------

COORDINATE_COLUMNS = [
    "hip_flexion_r", "knee_angle_r", "ankle_angle_r",
    "hip_flexion_l", "knee_angle_l", "ankle_angle_l",
    "lumbar_extension",
]


def _make_normalized_curves(with_sd=True):
    x = np.linspace(0, 100, 101)
    mean_data = {name: 10.0 * np.sin(np.radians(x)) + i for i, name in enumerate(COORDINATE_COLUMNS)}
    mean_df = pd.DataFrame(mean_data)
    sd_df = pd.DataFrame({name: np.full(101, 1.5) for name in COORDINATE_COLUMNS}) if with_sd else None
    return {"mean": mean_df, "sd": sd_df, "indiv": [mean_df.copy()]}


def _make_coordinate_values(n_frames=50, frame_rate=60.0):
    time = np.arange(n_frames) / frame_rate
    data = {"time": time}
    for i, name in enumerate(COORDINATE_COLUMNS):
        data[name] = 10.0 * np.sin(time * 2 * np.pi * 0.5) + i
    return pd.DataFrame(data)


def _make_fake_gait(scalars, curves=None, coordinate_values=None):
    curves = curves if curves is not None else _make_normalized_curves()
    coordinate_values = (
        coordinate_values if coordinate_values is not None else _make_coordinate_values()
    )

    class _FakeGaitAnalysis:
        def compute_scalars(self, names):
            return {name: scalars[name] for name in names if name in scalars}

        def get_coordinates_normalized_time(self):
            return curves

    fake = _FakeGaitAnalysis()
    fake.coordinateValues = coordinate_values
    return fake


def _make_fake_xsens_module(times, joint_angles, frame_rate=60.0, n_segments=23):
    def parse_mvnx(mvnx_path):
        return {
            "times": times,
            "joint_angles": joint_angles,
            "frame_rate": frame_rate,
            "segments": {str(i): f"seg{i}" for i in range(n_segments)},
        }

    return types.SimpleNamespace(parse_mvnx=parse_mvnx)


def _make_full_result(tmp_path, mod, jc):
    session_dir = tmp_path / "OpenCapData_test-subject"
    session_dir.mkdir()
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")

    n_frames = 50
    frame_rate = 60.0
    times = [i / frame_rate for i in range(n_frames)]

    coordinate_values = _make_coordinate_values(n_frames=n_frames, frame_rate=frame_rate)

    joint_index = jc.STANDARD_22_JOINT_ORDER.index("jRightKnee")
    dof_index = jc.JOINT_ANGLE_DOF_NAMES.index("flexion_extension")

    def make_frame(knee_r_value):
        frame = [(0.0, 0.0, 0.0)] * len(jc.STANDARD_22_JOINT_ORDER)
        values = [0.0, 0.0, 0.0]
        values[dof_index] = knee_r_value
        frame[joint_index] = tuple(values)
        return frame

    joint_angles = [make_frame(v) for v in coordinate_values["knee_angle_r"].to_numpy()]

    scalars = {name: {"value": 1.5, "units": "unit"} for name in mod.GAIT_METRIC_NAMES}
    curves = _make_normalized_curves()

    gait_r = _make_fake_gait(scalars, curves=curves, coordinate_values=coordinate_values)
    gait_l = _make_fake_gait(scalars, curves=curves, coordinate_values=coordinate_values)

    fake_xsens = _make_fake_xsens_module(times, joint_angles, frame_rate=frame_rate)

    result = {
        "session_dir": str(session_dir),
        "mvnx_path": str(mvnx_path),
        "trial_name": "trial1",
        "model_file": str(session_dir / "OpenSimData" / "Model" / "model.osim"),
        "mot_path": str(session_dir / "OpenSimData" / "Kinematics" / "trial1.mot"),
        "fpa_r": [0.0] * n_frames,
        "fpa_l": [0.0] * n_frames,
        "gait_r": gait_r,
        "gait_l": gait_l,
    }
    return result, fake_xsens


# ---------------------------------------------------------------------------
# Scenario 1: a completed run's results object shapes into all four content
# areas without error.
# ---------------------------------------------------------------------------

def test_full_results_shape_for_display_without_error(mod, tmp_path):
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)

    shaped = mod.shape_results_for_display(result, xsens_module=fake_xsens)

    assert set(shaped.keys()) == {
        "metadata", "curves", "metrics", "confidence", "outputs",
        "output_folder", "summary_scores",
    }

    metadata = shaped["metadata"]
    assert metadata["subject_session_id"] == Path(result["session_dir"]).name
    assert metadata["trial_name"] == "trial1"
    assert metadata["duration_seconds"] > 0
    assert metadata["sensor_coverage"]
    assert metadata["date"]

    curves = shaped["curves"]
    assert set(curves.keys()) == {spec["label"] for spec in mod.KEY_JOINT_PLOTS}
    for curve in curves.values():
        assert curve["available"] is True
        assert len(curve["x"]) == 101
        assert len(curve["mean"]) == 101
        assert len(curve["sd"]) == 101

    metrics = shaped["metrics"]
    assert set(metrics.keys()) == set(mod.GAIT_METRIC_NAMES)
    for name, row in metrics.items():
        assert row["r"]["available"] is True
        assert row["l"]["available"] is True
        if name in mod.ALREADY_SYMMETRY_METRICS:
            # Already an R/L ratio per-instance -- see
            # test_step_length_symmetry_is_not_re_derived_or_silently_picked.
            assert row["symmetry"]["available"] is False
        else:
            assert row["symmetry"]["available"] is True

    confidence = shaped["confidence"]
    assert confidence["available"] is True
    assert confidence["segments"]["jRightKnee"]["status"] == "scored"
    assert confidence["segments"]["jRightKnee"]["tier"] == "high"
    assert confidence["by_coordinate"]["knee_angle_r"] is confidence["segments"]["jRightKnee"]


# ---------------------------------------------------------------------------
# shape_results_for_display's own parse_mvnx call (the one it threads through
# to shape_metadata_for_display/score_confidence) raising -> wrapped into
# MvnxParsingError, not left to fall through to the generic mapper fallback
# (found in code review: the .mvnx could become unreadable between
# run_pipeline's own parse and this post-run display parse).
# ---------------------------------------------------------------------------

def test_shape_results_for_display_wraps_parse_mvnx_failure(mod, tmp_path):
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)

    def broken_parse_mvnx(mvnx_path):
        raise ValueError(f"{mvnx_path}: root element is <bogus>, expected <mvnx> or <frames>")

    fake_xsens.parse_mvnx = broken_parse_mvnx

    with pytest.raises(mod.MvnxParsingError):
        mod.shape_results_for_display(result, xsens_module=fake_xsens)


# ---------------------------------------------------------------------------
# Scenario 2: a scalar-metric dict missing one leg's values reports "not
# available" for that section instead of raising.
# ---------------------------------------------------------------------------

def test_metrics_missing_one_metric_on_one_leg_reports_not_available(mod):
    scalars_r = {name: {"value": 10.0, "units": "u"} for name in mod.GAIT_METRIC_NAMES}
    scalars_l = {
        name: {"value": 10.0, "units": "u"}
        for name in mod.GAIT_METRIC_NAMES
        if name != "cadence"
    }

    metrics = mod.shape_gait_metrics_for_display(scalars_r, scalars_l)

    assert metrics["cadence"]["l"]["available"] is False
    assert metrics["cadence"]["l"]["status"] == "not available"
    assert metrics["cadence"]["symmetry"]["available"] is False
    assert metrics["cadence"]["symmetry"]["status"] == "not available"
    # Unaffected metrics still compute normally.
    assert metrics["gait_speed"]["l"]["available"] is True
    assert metrics["gait_speed"]["symmetry"]["available"] is True


def test_metrics_with_entire_leg_missing_reports_not_available(mod):
    scalars_r = {name: {"value": 5.0, "units": "u"} for name in mod.GAIT_METRIC_NAMES}

    metrics = mod.shape_gait_metrics_for_display(scalars_r, None)

    for name in mod.GAIT_METRIC_NAMES:
        assert metrics[name]["r"]["available"] is True
        assert metrics[name]["l"]["available"] is False
        assert metrics[name]["l"]["status"] == "not available"
        assert metrics[name]["symmetry"]["available"] is False


# ---------------------------------------------------------------------------
# Scenario 3: with scalars_r/scalars_l both present, the symmetry metric is
# computed from both -- not from one leg alone.
# ---------------------------------------------------------------------------

def test_symmetry_is_computed_from_both_legs_not_one_alone(mod):
    scalars_r = {"cadence": {"value": 120.0, "units": "steps/min"}}
    scalars_l_a = {"cadence": {"value": 100.0, "units": "steps/min"}}
    scalars_l_b = {"cadence": {"value": 60.0, "units": "steps/min"}}

    metrics_a = mod.shape_gait_metrics_for_display(scalars_r, scalars_l_a, metric_names=["cadence"])
    metrics_b = mod.shape_gait_metrics_for_display(scalars_r, scalars_l_b, metric_names=["cadence"])

    assert metrics_a["cadence"]["symmetry"]["value"] == pytest.approx(120.0)
    assert metrics_b["cadence"]["symmetry"]["value"] == pytest.approx(200.0)
    # Same r value, different l value -> different symmetry: proves the
    # computation reads both legs, not r (or l) alone.
    assert metrics_a["cadence"]["symmetry"]["value"] != metrics_b["cadence"]["symmetry"]["value"]


def test_step_length_symmetry_is_not_re_derived_or_silently_picked(mod):
    # gait_analysis_UCM_fixed.py's compute_step_length_symmetry() already
    # returns an R/L ratio percentage computed from a single instance.
    # Applying the generic r/l*100 symmetry formula to it a second time
    # would produce a meaningless "symmetry of symmetry" figure (a bug found
    # during a simplify pass). A follow-up code-review pass then found that
    # gait_r and gait_l each anchor gait-cycle detection on a different leg,
    # so their two step_length_symmetry values are NOT guaranteed to agree
    # on a real trial -- silently reporting one and discarding the other
    # would hide a real disagreement. This proves neither happens: the
    # Right/Left columns still carry each instance's own (possibly
    # different) value, and the Symmetry column is marked not-applicable
    # rather than re-deriving or picking a "winner."
    scalars_r = {"step_length_symmetry": {"value": 87.5, "units": "% (R/L)"}}
    scalars_l = {"step_length_symmetry": {"value": 91.0, "units": "% (R/L)"}}

    metrics = mod.shape_gait_metrics_for_display(
        scalars_r, scalars_l, metric_names=["step_length_symmetry"]
    )

    row = metrics["step_length_symmetry"]
    assert row["r"]["value"] == pytest.approx(87.5)
    assert row["l"]["value"] == pytest.approx(91.0)
    assert row["symmetry"]["available"] is False
    assert row["symmetry"]["value"] is None
    assert "Right/Left" in row["symmetry"]["reason"]


# ---------------------------------------------------------------------------
# Scenario 4: joint_confidence.score_confidence()'s whole-trial
# `available: False` result shapes into one banner, not per-segment tiers.
# ---------------------------------------------------------------------------

def test_confidence_unavailable_produces_single_banner_not_per_segment_tiers(mod):
    confidence_raw = {
        "available": False,
        "reason": "This recording's .mvnx has no onboard <jointAngle> data.",
        "segments": {},
    }

    shaped = mod.shape_confidence_for_display(confidence_raw)

    assert shaped["available"] is False
    assert shaped["banner"] == confidence_raw["reason"]
    assert shaped["segments"] == {}
    assert shaped["by_coordinate"] == {}


def test_confidence_available_shapes_per_segment_tiers_with_fixed_colors(mod):
    confidence_raw = {
        "available": True,
        "reason": None,
        "segments": {
            "jRightKnee": {
                "status": "scored", "reason": None, "coordinate_name": "knee_angle_r",
                "rms_deg": 2.0, "n_aligned_samples": 50, "tier": "high",
            },
            "jLeftKnee": {
                "status": "scored", "reason": None, "coordinate_name": "knee_angle_l",
                "rms_deg": 30.0, "n_aligned_samples": 50, "tier": "low",
            },
            "jRightWrist": {
                "status": "not_scored", "reason": "No mapping defined.",
                "coordinate_name": None, "rms_deg": None, "n_aligned_samples": None, "tier": None,
            },
        },
    }

    shaped = mod.shape_confidence_for_display(confidence_raw)

    assert shaped["available"] is True
    assert shaped["banner"] is None
    assert shaped["segments"]["jRightKnee"]["display_tier"] == "high"
    assert shaped["segments"]["jLeftKnee"]["display_tier"] == "low"
    assert shaped["segments"]["jRightWrist"]["display_tier"] == "not_scored"

    # Fixed visual encoding: every tier maps to a distinct, non-empty color pair.
    colors_seen = {
        row["display_tier"]: (row["colors"]["bg"], row["colors"]["fg"])
        for row in shaped["segments"].values()
    }
    assert len(set(colors_seen.values())) == len(colors_seen)
    for bg, fg in colors_seen.values():
        assert bg and fg

    # Label text keeps the "agreement with the suit's own estimate" framing
    # (KTD5) intact for every tier, not just the scored ones.
    for row in shaped["segments"].values():
        assert "agreement with the suit's own onboard estimate" in row["label_text"].lower()

    assert shaped["by_coordinate"]["knee_angle_r"]["display_tier"] == "high"
    assert shaped["by_coordinate"]["knee_angle_l"]["display_tier"] == "low"
    assert "knee_angle_r" not in {None}  # sanity: not_scored segment has no coordinate_name
    assert None not in shaped["by_coordinate"]


# ---------------------------------------------------------------------------
# Additional coverage: metadata and joint-curve shaping in isolation, plus
# the pure tier_colors()/confidence_label_text() lookups.
# ---------------------------------------------------------------------------

def test_shape_metadata_for_display_reads_session_trial_and_frame_data(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_abc"
    session_dir.mkdir()
    mvnx_path = tmp_path / "walk_trial.mvnx"
    mvnx_path.write_text("<mvnx/>")

    fake_xsens = _make_fake_xsens_module(
        times=[i / 60.0 for i in range(120)],
        joint_angles=[None] * 120,
        frame_rate=60.0,
        n_segments=23,
    )

    metadata = mod.shape_metadata_for_display(str(session_dir), str(mvnx_path), xsens_module=fake_xsens)

    assert metadata["subject_session_id"] == "OpenCapData_abc"
    assert metadata["trial_name"] == "walk_trial"
    assert metadata["frame_count"] == 120
    assert metadata["duration_seconds"] == pytest.approx(119 / 60.0)
    assert "23" in metadata["sensor_coverage"]
    assert "60" in metadata["sensor_coverage"]


def test_shape_joint_curves_for_display_reports_missing_coordinate_as_unavailable(mod):
    curves_without_ankle = _make_normalized_curves()
    curves_without_ankle["mean"] = curves_without_ankle["mean"].drop(columns=["ankle_angle_r"])

    gait_r = _make_fake_gait(
        scalars={}, curves=curves_without_ankle, coordinate_values=_make_coordinate_values()
    )
    gait_l = _make_fake_gait(scalars={}, coordinate_values=_make_coordinate_values())

    curves = mod.shape_joint_curves_for_display(gait_r, gait_l)

    assert curves["Ankle Flexion (R)"]["available"] is False
    assert curves["Ankle Flexion (R)"]["reason"]
    assert curves["Knee Flexion (R)"]["available"] is True
    assert curves["Knee Flexion (L)"]["available"] is True


def test_tier_colors_and_label_text_cover_every_known_tier(mod):
    for tier in ("high", "medium", "low", "not_scored"):
        colors = mod.tier_colors(tier)
        assert colors["bg"] and colors["fg"]
        assert "agreement with the suit's own onboard estimate" in mod.confidence_label_text(tier).lower()

    # Unknown/None tier falls back to the same encoding as "not_scored"
    # rather than being left unstyled.
    assert mod.tier_colors(None) == mod.tier_colors("not_scored")


# -- Spatial provenance travels with the shaped result (2026-08-25) -----


def test_shape_metadata_carries_the_spatial_provenance_flags(mod, tmp_path):
    """Stamped at shaping time so every consumer -- the on-screen panel and
    the exported PDF alike -- gets the caveat without having to know to ask
    for it."""
    session_dir = tmp_path / "OpenCapData_abc"
    session_dir.mkdir()
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fake_xsens = _make_fake_xsens_module(
        times=[i / 60.0 for i in range(120)],
        joint_angles=[None] * 120,
        frame_rate=60.0,
        n_segments=23,
    )

    metadata = mod.shape_metadata_for_display(
        str(session_dir), str(mvnx_path), xsens_module=fake_xsens
    )

    assert metadata["spatial_displacement_validated"] is False
    assert "Pinned root" in metadata["translation_type"]
    assert "Stance-phase" in metadata["gait_speed_method"]
    # and the constant is the single source of truth, not duplicated literals
    for key, value in mod.SPATIAL_PROVENANCE.items():
        assert metadata[key] == value


# -- Raw output files surfaced for the user (2026-08-25) -----------------


def test_shaped_results_list_the_raw_output_files(mod, tmp_path):
    """A researcher needs the .mot and .trc to take into their own analysis.
    Reported from what run_pipeline actually wrote, not recomputed."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    result["trc_path"] = str(tmp_path / "MarkerData" / "trial1.trc")
    result["sto_path"] = str(tmp_path / "Kinematics" / "trial1_orientations.sto")

    outputs = mod.shape_results_for_display(result, xsens_module=fake_xsens)["outputs"]

    by_label = {entry["label"]: entry for entry in outputs}
    assert "Joint angles (.mot)" in by_label
    assert "Markers (.trc)" in by_label
    assert by_label["Markers (.trc)"]["path"] == result["trc_path"]


def test_output_entries_flag_whether_the_file_is_actually_there(mod, tmp_path):
    """A path that looks fine but points at nothing is the confusing case --
    the panel should be able to say so rather than sending the user to an
    empty folder."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    real = tmp_path / "real.mot"
    real.write_text("x")
    result["mot_path"] = str(real)
    result["trc_path"] = str(tmp_path / "missing.trc")

    outputs = mod.shape_results_for_display(result, xsens_module=fake_xsens)["outputs"]
    by_label = {entry["label"]: entry for entry in outputs}

    assert by_label["Joint angles (.mot)"]["exists"] is True
    assert by_label["Markers (.trc)"]["exists"] is False


def test_output_folder_is_reported_for_opening(mod, tmp_path):
    """The panel offers an 'open folder' action, so the shaped result has to
    name a directory that exists rather than leaving the GUI to guess."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)

    shaped = mod.shape_results_for_display(result, xsens_module=fake_xsens)

    assert shaped["outputs"]
    assert Path(shaped["output_folder"]).name == Path(result["session_dir"]).name


def test_missing_optional_paths_do_not_break_shaping(mod, tmp_path):
    """Older result dicts (or a partial run) may lack trc/sto. Shaping must
    degrade rather than raise -- the rest of the report is still valid."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    result.pop("trc_path", None)
    result.pop("sto_path", None)

    outputs = mod.shape_results_for_display(result, xsens_module=fake_xsens)["outputs"]

    assert any(entry["label"] == "Joint angles (.mot)" for entry in outputs)
    assert all(entry["path"] for entry in outputs)


def test_metadata_provenance_follows_the_conversion_route(mod, tmp_path):
    """An XtoO run carries real translation, so stamping the IK disclaimer on
    it would understate genuinely displacement-derived data."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    result["conversion"] = "xtoo"

    metadata = mod.shape_results_for_display(result, xsens_module=fake_xsens)["metadata"]

    assert metadata["spatial_displacement_validated"] is True
    assert "Pinned root" not in metadata["translation_type"]


def test_metadata_defaults_to_the_ik_caveat_when_no_route_is_recorded(mod, tmp_path):
    """Older results predate the route field. Defaulting to the cautious
    wording is the safe direction to be wrong in."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    result.pop("conversion", None)

    metadata = mod.shape_results_for_display(result, xsens_module=fake_xsens)["metadata"]

    assert metadata["spatial_displacement_validated"] is False


def test_conversion_route_is_shown_in_the_metadata(mod, tmp_path):
    """The report has to say which pipeline produced its numbers."""
    jc = mod._load_joint_confidence()
    result, fake_xsens = _make_full_result(tmp_path, mod, jc)
    result["conversion"] = "xtoo"

    metadata = mod.shape_results_for_display(result, xsens_module=fake_xsens)["metadata"]

    assert "conversion_route" in metadata
    assert "remapping" in metadata["conversion_route"].lower()
