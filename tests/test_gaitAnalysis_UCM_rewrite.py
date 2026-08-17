"""Tests for the 2026-08-17 rewrite of Examples/gaitAnalysis-UCM.py.

Covers the pure-logic pieces that don't need OpenSim or gait_analysis_UCM.py
(still missing from this repo -- see VENDORING.md's "Critical gap" section):
path/session-ID parsing, trial discovery, and the individual-curves CSV
matrix builder. Also asserts the module itself imports cleanly despite
gait_analysis_UCM.py being absent -- the whole point of deferring that import
into run_gait_analysis() rather than the module top level.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "Examples" / "gaitAnalysis-UCM.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gaitAnalysis_UCM", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gait_module():
    return _load_module()


def test_module_imports_without_gait_analysis_UCM_or_scipy(gait_module):
    # gait_analysis_UCM.py doesn't exist in this repo yet; scipy's Rotation
    # is only imported lazily inside compute_foot_progression_angles. If the
    # module-level import structure ever regresses back to eager imports,
    # this import will raise before we even get here.
    assert "gait_analysis_UCM" not in sys.modules
    assert hasattr(gait_module, "run_batch")
    assert hasattr(gait_module, "compute_foot_progression_angles")


@pytest.mark.parametrize("path,expected", [
    ("Data/OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2", "b39b10d1-17c7-4976-b06c-a6aaf33fead2"),
    ("OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2_subject-slug.zip",
     "b39b10d1-17c7-4976-b06c-a6aaf33fead2"),
    ("OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2.zip", "b39b10d1-17c7-4976-b06c-a6aaf33fead2"),
    ("not_a_session_folder", None),
])
def test_parse_session_id(gait_module, path, expected):
    assert gait_module.parse_session_id(path) == expected


def test_parse_subject_id_and_zip_root(gait_module):
    zip_path = Path("C:/Users/x/Downloads/S01/OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2_S01.zip")
    subject_id, extraction_root, folder_name = gait_module.parse_subject_id_and_zip_root(zip_path)
    assert subject_id == "S01"
    assert folder_name == "OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2"
    assert extraction_root == zip_path.parent / folder_name


def test_resolve_data_folder_is_inside_repo_root(gait_module):
    data_folder = gait_module.resolve_data_folder()
    assert data_folder == gait_module.REPO_ROOT / "Data"
    # Regression guard for the pre-rewrite off-by-one: the old
    # `os.path.join(os.getcwd(), '..')` resolved to the repo's *parent*.
    assert data_folder.parent == gait_module.REPO_ROOT


def test_discover_trials_excludes_neutral_and_sorts(gait_module, tmp_path):
    for name in ["walk_2", "neutral", "walk_1", "sts_1"]:
        (tmp_path / f"{name}.mot").write_text("placeholder")
    (tmp_path / "not_a_trial.txt").write_text("placeholder")

    assert gait_module.discover_trials(tmp_path) == ["sts_1", "walk_1", "walk_2"]


def test_build_individual_curves_matrix_applies_known_adjustments(gait_module):
    joint_names_backup = gait_module.JOINT_NAMES
    try:
        gait_module.JOINT_NAMES = ["pelvis_tilt", "pelvis_rotation", "pelvis_tx", "comx"]
        cycle = {
            "pelvis_tilt": [10.0] * 101,
            "pelvis_rotation": [190.0] * 101,
            "pelvis_tx": [1.0] * 101,
            "comx": [5.0] * 101,
        }
        curves_side = {"indiv": [cycle], "mean": cycle}

        matrix = gait_module._build_individual_curves_matrix(curves_side, curves_side["mean"])

        assert matrix.shape == (4 * 101, 1)
        assert np.allclose(matrix[0:101, 0], 30.0)   # pelvis_tilt + 20
        assert np.allclose(matrix[101:202, 0], 10.0)  # pelvis_rotation - 180 (wrapped since > 180)
        assert np.allclose(matrix[202:303, 0], 1.0)   # pelvis_tx unchanged
        assert np.allclose(matrix[303:404, 0], 4.0)   # comx - pelvis_tx = 5 - 1
    finally:
        gait_module.JOINT_NAMES = joint_names_backup


def test_build_individual_curves_matrix_leaves_pelvis_rotation_under_180_alone(gait_module):
    joint_names_backup = gait_module.JOINT_NAMES
    try:
        gait_module.JOINT_NAMES = ["pelvis_rotation"]
        cycle = {"pelvis_rotation": [90.0] * 101}
        curves_side = {"indiv": [cycle], "mean": cycle}

        matrix = gait_module._build_individual_curves_matrix(curves_side, curves_side["mean"])

        assert np.allclose(matrix[:, 0], 90.0)
    finally:
        gait_module.JOINT_NAMES = joint_names_backup


def test_run_batch_rejects_missing_zip_and_data_dir(gait_module):
    with pytest.raises(ValueError, match="requires either zip_path or data_dir"):
        gait_module.run_batch()


def test_run_batch_rejects_missing_trial_selection(gait_module, tmp_path, monkeypatch):
    session_dir = tmp_path / "OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2"
    session_dir.mkdir()
    (session_dir / "walk_1.mot").write_text("placeholder")

    with pytest.raises(ValueError, match="--trial NAME"):
        gait_module.run_batch(data_dir=str(session_dir))


def test_run_batch_rejects_unknown_trial(gait_module, tmp_path):
    session_dir = tmp_path / "OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2"
    session_dir.mkdir()
    (session_dir / "walk_1.mot").write_text("placeholder")

    with pytest.raises(ValueError, match="not found"):
        gait_module.run_batch(data_dir=str(session_dir), trial_names=["walk_99"])
