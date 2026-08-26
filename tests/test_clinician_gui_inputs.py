"""
Tests validate_inputs() from clinician_gui.py -- U1 of the clinician trial
report GUI plan. Only exercises the pure validation function (no Tk
dependency); actual widget rendering/enabling is a manual smoke check per
the plan, not something these tests attempt.

Follows this repo's existing test convention (see
tests/test_xsens_to_opensim_session_paths.py): load the module under test
via importlib.util.spec_from_file_location against an absolute path, not a
normal import.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('clinician_gui_under_test', MODULE_PATH)
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


def _make_mvnx(tmp_path, name="trial1.mvnx"):
    mvnx_path = tmp_path / name
    mvnx_path.write_text("<mvnx/>")
    return mvnx_path


def test_setting_api_token_placeholder_before_other_imports(mod):
    # KTD6: importing clinician_gui.py must set a placeholder API_TOKEN
    # env var so that any later import reaching utils.py's module-level
    # get_token() call never fires an interactive login prompt.
    assert os.environ.get("API_TOKEN")


def test_ready_when_one_osim_and_existing_mvnx(mod, tmp_path):
    session_dir = _make_session(tmp_path)
    mvnx_path = _make_mvnx(tmp_path)

    ready, reason = mod.validate_inputs(str(session_dir), str(mvnx_path))

    assert ready is True
    assert reason == ""


def test_not_ready_when_zero_osim_files(mod, tmp_path):
    session_dir = _make_session(tmp_path, osim_names=())
    mvnx_path = _make_mvnx(tmp_path)

    ready, reason = mod.validate_inputs(str(session_dir), str(mvnx_path))

    assert ready is False
    assert "found 0" in reason


def test_not_ready_when_multiple_osim_files(mod, tmp_path):
    session_dir = _make_session(tmp_path, osim_names=("a.osim", "b.osim"))
    mvnx_path = _make_mvnx(tmp_path)

    ready, reason = mod.validate_inputs(str(session_dir), str(mvnx_path))

    assert ready is False
    assert "found 2" in reason


def test_not_ready_when_mvnx_missing(mod, tmp_path):
    session_dir = _make_session(tmp_path)
    missing_mvnx = tmp_path / "does_not_exist.mvnx"

    ready, reason = mod.validate_inputs(str(session_dir), str(missing_mvnx))

    assert ready is False
    assert "does_not_exist.mvnx" in reason


def test_not_ready_when_session_dir_blank(mod, tmp_path):
    mvnx_path = _make_mvnx(tmp_path)

    ready, reason = mod.validate_inputs("", str(mvnx_path))

    assert ready is False
    assert reason


def test_not_ready_when_mvnx_blank(mod, tmp_path):
    session_dir = _make_session(tmp_path)

    ready, reason = mod.validate_inputs(str(session_dir), "")

    assert ready is False
    assert reason
