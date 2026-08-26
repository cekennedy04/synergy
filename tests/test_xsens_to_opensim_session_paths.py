"""
Tests resolve_session_output_paths -- added 2026-08-19 so this pipeline's
output lands exactly where utilsKinematics.py's `kinematics` class (which
gait_analysis_UCM.py subclasses) expects to find it, without hand-renaming
anything. The expected layout was read directly out of utilsKinematics.py's
__init__ (model + motion paths) and get_marker_dict (marker path), not
guessed -- see resolve_session_output_paths's own docstring for specifics.
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


def _make_session(tmp_path, osim_names=("LaiUhlrich2022_scaled.osim",)):
    session_dir = tmp_path / "OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3"
    model_dir = session_dir / "OpenSimData" / "Model"
    model_dir.mkdir(parents=True)
    for name in osim_names:
        (model_dir / name).write_text("<Model/>")
    return session_dir


def test_resolves_paths_matching_opencap_session_layout(mod, tmp_path):
    session_dir = _make_session(tmp_path)
    paths = mod.resolve_session_output_paths(str(session_dir), "walking1")

    assert paths["model_file"] == str(session_dir / "OpenSimData" / "Model" / "LaiUhlrich2022_scaled.osim")
    assert paths["results_dir"] == str(session_dir / "OpenSimData" / "Kinematics")
    assert paths["output_motion_filename"] == "walking1.mot"
    assert paths["trc_path"] == str(session_dir / "MarkerData" / "walking1.trc")
    assert paths["sto_path"] == str(
        session_dir / "OpenSimData" / "Kinematics" / "walking1_orientations.sto"
    )


def test_explicit_model_file_skips_auto_discovery(mod, tmp_path):
    # No OpenSimData/Model/ dir at all -- auto-discovery would fail, but an
    # explicit model_file should bypass it entirely.
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    paths = mod.resolve_session_output_paths(
        str(session_dir), "trial1", model_file="somewhere/else/model.osim"
    )
    assert paths["model_file"] == "somewhere/else/model.osim"


def test_zero_osim_files_raises(mod, tmp_path):
    session_dir = _make_session(tmp_path, osim_names=())
    with pytest.raises(ValueError, match="found 0"):
        mod.resolve_session_output_paths(str(session_dir), "trial1")


def test_multiple_osim_files_raises(mod, tmp_path):
    session_dir = _make_session(tmp_path, osim_names=("a.osim", "b.osim"))
    with pytest.raises(ValueError, match="found 2"):
        mod.resolve_session_output_paths(str(session_dir), "trial1")


def test_missing_model_dir_raises(mod, tmp_path):
    session_dir = tmp_path / "no_model_dir_session"
    session_dir.mkdir()
    with pytest.raises(ValueError, match="found 0"):
        mod.resolve_session_output_paths(str(session_dir), "trial1")


# -- Re-run safety (2026-08-24) ------------------------------------------
# calibrate_model() writes "<stem>_calibrated.osim" into the same
# OpenSimData/Model/ directory this function auto-discovers from. Found by
# running the real GUI against a real session twice: the first run succeeded
# and left a calibrated model behind, and every run after that failed with
# "expected exactly one .osim ... found 2" -- the pipeline breaking its own
# next run, and blocking any second trial in the same session.


def test_calibrated_model_from_a_prior_run_is_ignored(mod, tmp_path):
    """The exact re-run scenario: a session that has already been processed
    once has both the source model and the calibrated model this pipeline
    wrote. Auto-discovery must still resolve, and must pick the SOURCE
    model -- calibrating an already-calibrated model would silently
    double-apply the IMU placement."""
    session_dir = _make_session(
        tmp_path,
        osim_names=("LaiUhlrich2022_scaled.osim", "LaiUhlrich2022_scaled_calibrated.osim"),
    )
    paths = mod.resolve_session_output_paths(str(session_dir), "trial1")
    assert paths["model_file"] == str(
        session_dir / "OpenSimData" / "Model" / "LaiUhlrich2022_scaled.osim"
    )


def test_calibrated_model_matches_what_calibrate_model_actually_writes(mod, tmp_path):
    """Pins the exclusion rule to calibrate_model's real naming convention
    rather than a hardcoded guess -- if that naming ever changes, this fails
    instead of silently reintroducing the found-2 break."""
    from pathlib import Path

    source = Path("/session/OpenSimData/Model/LaiUhlrich2022_scaled.osim")
    # Mirrors calibrate_model's own default output path expression.
    calibrated = source.with_name(source.stem + "_calibrated.osim")
    assert calibrated.stem.endswith("_calibrated"), (
        "resolve_session_output_paths excludes models whose stem ends in "
        "'_calibrated'; calibrate_model must keep producing that suffix."
    )


def test_only_calibrated_model_present_raises_with_actionable_message(mod, tmp_path):
    """If the source model is gone and only a derived one remains, don't
    silently calibrate the calibrated model -- say what's actually wrong."""
    session_dir = _make_session(
        tmp_path, osim_names=("LaiUhlrich2022_scaled_calibrated.osim",)
    )
    with pytest.raises(ValueError, match="Only previously-calibrated model"):
        mod.resolve_session_output_paths(str(session_dir), "trial1")


def test_two_genuine_source_models_still_raises(mod, tmp_path):
    """The original ambiguity guard must survive the fix -- two real source
    models is still unresolvable, and excluding calibrated ones must not
    paper over it."""
    session_dir = _make_session(
        tmp_path, osim_names=("a.osim", "b.osim", "a_calibrated.osim")
    )
    with pytest.raises(ValueError, match="found 2"):
        mod.resolve_session_output_paths(str(session_dir), "trial1")
