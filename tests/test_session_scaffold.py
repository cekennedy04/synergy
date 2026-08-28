"""Tests for session_scaffold.py.

Every fixture is synthetic, and the names used are fabricated -- the real
subjectIDs are personal names and this repository is public.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "session_scaffold_under_test", REPO_ROOT / "session_scaffold.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _opencap_session(root, folder, subject_id, models=("LaiUhlrich2022_scaled.osim",)):
    session = Path(root) / folder
    (session / "OpenSimData" / "Model").mkdir(parents=True, exist_ok=True)
    (session / "sessionMetadata.yaml").write_text(
        f"height_m: 1.75\nmass_kg: 70.0\nsubjectID: {subject_id}\n", encoding="utf-8")
    for name in models:
        (session / "OpenSimData" / "Model" / name).write_text("<OpenSimDocument/>")
    return session


def _participant(root, code, n_trials=3):
    folder = Path(root) / code / "HD Reprocessed"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_trials + 1):
        (folder / f"{code}-{i:03d}.mvnx").write_text("<mvnx/>")
    return folder.parent


# -- identifying who a session belongs to ----------------------------------


def test_a_full_name_reduces_to_its_initials(mod):
    """OpenCap sessions carry subjectID as a code for some subjects and a full
    name for others; both must resolve to the participant folder name."""
    assert mod.initials("Ada Lovelace") == "AL"
    assert mod.initials("HH") == "HH"
    assert mod.initials("  grace  hopper ") == "GH"


def test_subject_id_is_read_from_the_metadata(mod, tmp_path):
    session = _opencap_session(tmp_path, "OpenCapData_abc", "Ada Lovelace")

    assert mod.read_subject_id(session) == "Ada Lovelace"


def test_a_session_without_metadata_is_skipped_not_fatal(mod, tmp_path):
    _opencap_session(tmp_path, "OpenCapData_abc", "Ada Lovelace")
    (tmp_path / "not_a_session").mkdir()

    sessions = mod.discover_opencap_sessions(tmp_path)

    assert [s["code"] for s in sessions] == ["AL"]


# -- matching refuses to guess ---------------------------------------------


def test_an_ambiguous_match_is_refused(mod, tmp_path):
    """Two subjects reducing to the same initials. Putting the wrong person's
    model on a session produces a complete, plausible, wrong result."""
    _opencap_session(tmp_path, "OpenCapData_1", "Ada Lovelace")
    _opencap_session(tmp_path, "OpenCapData_2", "Alan Lovelace")
    sessions = mod.discover_opencap_sessions(tmp_path)

    with pytest.raises(mod.ScaffoldError, match="Refusing to guess"):
        mod.match_session("AL", sessions)


def test_no_match_names_what_was_available(mod, tmp_path):
    _opencap_session(tmp_path, "OpenCapData_1", "Ada Lovelace")
    sessions = mod.discover_opencap_sessions(tmp_path)

    with pytest.raises(mod.ScaffoldError) as caught:
        mod.match_session("ZZ", sessions)

    assert "'AL'" in str(caught.value) or "AL" in str(caught.value)


# -- picking the model -----------------------------------------------------


def test_a_calibrated_model_is_never_taken_as_the_source(mod, tmp_path):
    """calibrate_model writes <stem>_calibrated.osim alongside the source.
    Using one as input would stack two IMU calibrations."""
    session = _opencap_session(
        tmp_path, "OpenCapData_1", "Ada Lovelace",
        models=("LaiUhlrich2022_scaled.osim",
                "LaiUhlrich2022_scaled_calibrated.osim"))

    model = mod.find_source_model(session)

    assert model.name == "LaiUhlrich2022_scaled.osim"


def test_two_source_models_is_an_error_not_a_pick(mod, tmp_path):
    session = _opencap_session(tmp_path, "OpenCapData_1", "Ada Lovelace",
                               models=("a_scaled.osim", "b_scaled.osim"))

    with pytest.raises(mod.ScaffoldError, match="exactly one"):
        mod.find_source_model(session)


# -- building --------------------------------------------------------------


def test_a_scaffold_has_the_layout_the_converter_writes_into(mod, tmp_path):
    opencap = tmp_path / "opencap"
    session = _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    participant = _participant(tmp_path / "participants", "AL", n_trials=15)

    result = mod.build_scaffold("AL", participant,
                                {"path": session, "subject_id": "Ada Lovelace",
                                 "code": "AL"},
                                tmp_path / "out")

    assert result["n_trials"] == 15
    for subdir in mod.SESSION_SUBDIRS:
        assert (result["session_dir"] / subdir).is_dir()
    assert result["model"].is_file()
    assert result["model"].parent.name == "Model"


def test_the_scaffold_is_named_by_code_and_never_by_name(mod, tmp_path):
    """subjectID may be a real person's name and this repository is public.
    Nothing personal may reach a path."""
    opencap = tmp_path / "opencap"
    session = _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    participant = _participant(tmp_path / "participants", "AL")

    result = mod.build_scaffold("AL", participant,
                                {"path": session, "subject_id": "Ada Lovelace",
                                 "code": "AL"}, tmp_path / "out")

    full_path = str(result["session_dir"].resolve())
    assert "Ada" not in full_path and "Lovelace" not in full_path
    assert "AL" in result["session_dir"].name


def test_the_model_is_copied_so_the_session_survives_the_export_moving(mod,
                                                                      tmp_path):
    opencap = tmp_path / "opencap"
    session = _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    participant = _participant(tmp_path / "participants", "AL")

    result = mod.build_scaffold("AL", participant,
                                {"path": session, "subject_id": "Ada Lovelace",
                                 "code": "AL"}, tmp_path / "out")
    import shutil
    shutil.rmtree(opencap)

    assert result["model"].is_file()  # still there


def test_an_existing_scaffold_is_not_silently_overwritten(mod, tmp_path):
    """A conversion may already have run against the model in place; replacing
    it would leave results that no longer match it."""
    opencap = tmp_path / "opencap"
    session = _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    participant = _participant(tmp_path / "participants", "AL")
    args = ("AL", participant, {"path": session, "subject_id": "Ada Lovelace",
                                "code": "AL"}, tmp_path / "out")
    mod.build_scaffold(*args)

    with pytest.raises(mod.ScaffoldError, match="already exists"):
        mod.build_scaffold(*args)

    mod.build_scaffold(*args, force=True)  # explicit replacement is allowed


def test_a_participant_with_no_trials_is_rejected(mod, tmp_path):
    opencap = tmp_path / "opencap"
    session = _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    empty = tmp_path / "participants" / "AL"
    empty.mkdir(parents=True)

    with pytest.raises(mod.ScaffoldError, match="no .mvnx"):
        mod.build_scaffold("AL", empty,
                           {"path": session, "subject_id": "Ada Lovelace",
                            "code": "AL"}, tmp_path / "out")


def test_trials_are_ordered_naturally(mod, tmp_path):
    participant = _participant(tmp_path / "participants", "AL", n_trials=0)
    folder = participant / "HD Reprocessed"
    for name in ("AL-10", "AL-2", "AL-1"):
        (folder / f"{name}.mvnx").write_text("<mvnx/>")

    trials = mod.find_trials(participant)

    assert [t.stem for t in trials] == ["AL-1", "AL-2", "AL-10"]


# -- the batch path --------------------------------------------------------


def test_one_unmatched_participant_does_not_stop_the_others(mod, tmp_path):
    opencap = tmp_path / "opencap"
    _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    participants = tmp_path / "participants"
    _participant(participants, "AL")
    _participant(participants, "ZZ")

    results, failures = mod.build_all(participants, opencap, tmp_path / "out")

    assert [r["participant"] for r in results] == ["AL"]
    assert [f["participant"] for f in failures] == ["ZZ"]


def test_only_selects_a_subset(mod, tmp_path):
    opencap = tmp_path / "opencap"
    _opencap_session(opencap, "OpenCapData_1", "Ada Lovelace")
    _opencap_session(opencap, "OpenCapData_2", "Grace Hopper")
    participants = tmp_path / "participants"
    _participant(participants, "AL")
    _participant(participants, "GH")

    results, failures = mod.build_all(participants, opencap, tmp_path / "out",
                                      only=["gh"])

    assert [r["participant"] for r in results] == ["GH"]
    assert failures == []
