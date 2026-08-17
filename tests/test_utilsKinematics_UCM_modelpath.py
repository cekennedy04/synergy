"""
Verifies the two fixes made to utilsKinematics_UCM.py's kinematics.__init__ (2026-08-16):

1. `self.modelPath = modelPath` was restored (had been dropped relative to upstream).
2. The model-path-resolution block (isMono detection + the 4 modelName/isMono branches) was
   reformatted from inconsistent ~3-4 space indentation to standard 4-space indentation.

Real OpenSim is not installed on this machine (see VENDORING.md / MEMORY), so this test stubs
`opensim` (and `utils`, `utilsProcessing`, `utilsTRC`, which utilsKinematics_UCM.py imports at
module load time) rather than exercising the real thing. The stub `opensim.Model(...)` raises a
sentinel exception carrying the path it was called with, which lets the test both (a) confirm
`self.modelPath` was actually set before that call, and (b) confirm the resolved path is correct
-- i.e. that the reformatting didn't change behavior.

Deliberately kept small (2 tests, not a full parametrized suite per branch): nothing in this repo
currently imports utilsKinematics_UCM.py (see VENDORING.md's "Import-name mismatch" section), so
this is dead code until something wires it in. A smoke test for the actual regression
(self.modelPath missing) plus one pass covering all 5 modelName/isMono combinations in a loop is
enough confidence for now without over-investing in a file nothing runs yet; expand this if/when
utilsKinematics_UCM.py actually gets imported by the pipeline.

Also deliberately does NOT test anything past the `opensim.Model(modelPath)` call (motion-file
loading, filtering, etc.) -- that code wasn't touched by these fixes and would need a real
OpenSim install (and real session data) to exercise honestly. Same reasoning for skipping the
missing-model-file negative case: it's an existing upstream behavior this edit didn't touch.
"""
import importlib.util
import os
import sys
import types

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'utilsKinematics_UCM.py')


class ModelConstructed(Exception):
    """Raised by the fake opensim.Model(...) the instant it's called, carrying the path it
    received, so the test can stop right there and inspect the partially-built instance."""
    def __init__(self, model_path):
        super().__init__(model_path)
        self.model_path = model_path


def _install_stub_modules(monkeypatch):
    """Stub out opensim/utils/utilsProcessing/utilsTRC in sys.modules before importing
    utilsKinematics_UCM, so we never touch the real opensim (not installed) or the real utils.py
    (which tries to log in to app.opencap.ai / prompt for credentials at import time).

    Uses monkeypatch.setitem rather than writing sys.modules directly, so pytest restores the
    real (or absent) entries automatically at the end of the test -- without this, a stub
    `opensim`/`utils` module leaks into every later test in the same process."""
    fake_opensim = types.ModuleType('opensim')

    class _FakeLogger:
        @staticmethod
        def setLevelString(level):
            pass

    def _fake_model(model_path):
        raise ModelConstructed(model_path)

    fake_opensim.Logger = _FakeLogger
    fake_opensim.Model = _fake_model
    monkeypatch.setitem(sys.modules, 'opensim', fake_opensim)

    fake_utils = types.ModuleType('utils')
    fake_utils.get_model_name_from_metadata = lambda session_dir: 'metadata_model.osim'
    monkeypatch.setitem(sys.modules, 'utils', fake_utils)

    fake_utils_processing = types.ModuleType('utilsProcessing')
    fake_utils_processing.lowPassFilter = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, 'utilsProcessing', fake_utils_processing)

    fake_utils_trc = types.ModuleType('utilsTRC')
    fake_utils_trc.trc_2_dict = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, 'utilsTRC', fake_utils_trc)


def _load_kinematics_class(monkeypatch):
    _install_stub_modules(monkeypatch)
    spec = importlib.util.spec_from_file_location('utilsKinematics_UCM_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kinematics


def _construct_up_to_model_load(kinematics_cls, session_dir, trial_name, model_name=None):
    """Manually allocate + __init__ a kinematics instance, catching the sentinel raised by the
    stubbed opensim.Model(...). Returns (instance, model_path_the_stub_was_called_with)."""
    obj = object.__new__(kinematics_cls)
    try:
        obj.__init__(session_dir, trial_name, modelName=model_name)
    except ModelConstructed as exc:
        return obj, exc.model_path
    raise AssertionError('kinematics.__init__ did not reach opensim.Model(...) as expected')


@pytest.fixture
def kinematics_cls(monkeypatch):
    return _load_kinematics_class(monkeypatch)


def test_self_modelPath_is_set_before_model_construction(kinematics_cls, tmp_path):
    """The core regression this fix addresses: self.modelPath must exist on the instance."""
    session_dir = tmp_path / 'session'
    model_base = session_dir / 'OpenSimData' / 'Model'
    model_base.mkdir(parents=True)
    osim_file = model_base / 'metadata_model.osim'
    osim_file.write_text('<OpenSimDocument/>')

    obj, called_with = _construct_up_to_model_load(kinematics_cls, str(session_dir), 'trial1')

    assert hasattr(obj, 'modelPath'), 'self.modelPath was not set (the regression this test guards against)'
    assert obj.modelPath == called_with == str(osim_file)


def test_modelPath_resolution_all_branches(kinematics_cls, tmp_path):
    """One test, looping over all 5 modelName/isMono combinations -- confirms the indentation
    reformat didn't change the branching logic, without spinning up 5 separate test instances."""
    cases = [
        ('modelName=None, mono session', None, True, 'trialSpecific.osim'),
        ('modelName=None, non-mono session', None, False, 'metadata_model.osim'),
        ('modelName given (no .osim suffix), mono session', 'CustomModel', True, 'CustomModel.osim'),
        ('modelName given (no .osim suffix), non-mono session', 'CustomModel', False, 'CustomModel.osim'),
        ('modelName given WITH .osim suffix, non-mono session', 'CustomModel.osim', False, 'CustomModel.osim'),
    ]

    for i, (case_name, model_name, make_trial_subfolder, osim_filename) in enumerate(cases):
        session_dir = tmp_path / 'session{}'.format(i)
        trial_name = 'trial1'
        model_base = session_dir / 'OpenSimData' / 'Model'
        model_base.mkdir(parents=True)

        target_dir = (model_base / trial_name) if make_trial_subfolder else model_base
        if make_trial_subfolder:
            target_dir.mkdir()

        osim_path = target_dir / osim_filename
        osim_path.write_text('<OpenSimDocument/>')

        obj, called_with = _construct_up_to_model_load(
            kinematics_cls, str(session_dir), trial_name, model_name=model_name
        )

        assert called_with == str(osim_path), '{}: expected {}, got {}'.format(
            case_name, osim_path, called_with
        )
        assert obj.modelPath == called_with
