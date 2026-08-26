"""Tests for launch_gui.py -- the environment-resolving GUI launcher.

The launcher's whole job is to answer one question correctly: which python
interpreter should run clinician_gui.py? Getting it wrong is the failure this
module exists to prevent -- the base interpreter has no `opensim`, so the GUI
dies partway through a run rather than at launch.

These tests never touch the real conda install. Every candidate location is a
tmp_path fixture, so they pass on a machine with no conda at all.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "launch_gui", REPO_ROOT / "launch_gui.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch_gui = _load()


def _make_env(root: Path, name: str = "opencap-processing", windows: bool = True):
    """Create a fake conda env tree and return its interpreter path."""
    env = root / "envs" / name
    if windows:
        interpreter = env / "python.exe"
    else:
        interpreter = env / "bin" / "python"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("")
    return interpreter


class TestExplicitOverride:
    def test_synergy_python_wins_over_everything(self, tmp_path):
        override = tmp_path / "chosen" / "python.exe"
        override.parent.mkdir(parents=True)
        override.write_text("")
        _make_env(tmp_path / "miniconda3")

        found = launch_gui.find_env_python(
            environ={"SYNERGY_PYTHON": str(override)},
            home=tmp_path,
        )
        assert found == override

    def test_override_pointing_at_nothing_is_an_error_not_a_fallback(self, tmp_path):
        """A typo'd override must fail loudly. Silently falling back to a
        discovered env would run the GUI under an interpreter the user did not
        ask for, which is exactly the confusion this launcher removes."""
        _make_env(tmp_path / "miniconda3")

        with pytest.raises(launch_gui.EnvironmentNotFound) as excinfo:
            launch_gui.find_env_python(
                environ={"SYNERGY_PYTHON": str(tmp_path / "nope" / "python.exe")},
                home=tmp_path,
            )
        assert "SYNERGY_PYTHON" in str(excinfo.value)


class TestDiscovery:
    @pytest.mark.parametrize(
        "install_dir",
        ["miniconda3", "anaconda3", "mambaforge", "miniforge3"],
    )
    def test_finds_env_under_each_standard_install_dir(self, tmp_path, install_dir):
        interpreter = _make_env(tmp_path / install_dir)
        found = launch_gui.find_env_python(environ={}, home=tmp_path)
        assert found == interpreter

    def test_uses_conda_exe_when_install_is_somewhere_nonstandard(self, tmp_path):
        conda_root = tmp_path / "opt" / "custom-conda"
        interpreter = _make_env(conda_root)
        conda_exe = conda_root / "Scripts" / "conda.exe"
        conda_exe.parent.mkdir(parents=True, exist_ok=True)
        conda_exe.write_text("")

        found = launch_gui.find_env_python(
            environ={"CONDA_EXE": str(conda_exe)}, home=tmp_path
        )
        assert found == interpreter

    def test_raises_with_actionable_message_when_env_is_absent(self, tmp_path):
        with pytest.raises(launch_gui.EnvironmentNotFound) as excinfo:
            launch_gui.find_env_python(environ={}, home=tmp_path)

        message = str(excinfo.value)
        # The message has to carry the fix, not just the complaint.
        assert launch_gui.ENV_NAME in message
        assert "SYNERGY_PYTHON" in message

    def test_ignores_an_env_directory_with_no_interpreter_in_it(self, tmp_path):
        """A half-deleted or partially-created env directory must not be
        mistaken for a usable one."""
        (tmp_path / "miniconda3" / "envs" / launch_gui.ENV_NAME).mkdir(parents=True)

        with pytest.raises(launch_gui.EnvironmentNotFound):
            launch_gui.find_env_python(environ={}, home=tmp_path)

    def test_posix_layout_is_supported(self, tmp_path):
        interpreter = _make_env(tmp_path / "miniconda3", windows=False)
        found = launch_gui.find_env_python(environ={}, home=tmp_path, windows=False)
        assert found == interpreter


class TestAlreadyInTheRightEnv:
    def test_reports_ready_when_opensim_imports(self, monkeypatch):
        monkeypatch.setattr(launch_gui, "_can_import_opensim", lambda: True)
        assert launch_gui.current_interpreter_is_ready() is True

    def test_reports_not_ready_when_opensim_is_missing(self, monkeypatch):
        monkeypatch.setattr(launch_gui, "_can_import_opensim", lambda: False)
        assert launch_gui.current_interpreter_is_ready() is False


class TestBuildCommand:
    def test_forwards_extra_arguments_to_the_gui(self, tmp_path):
        interpreter = tmp_path / "python.exe"
        cmd = launch_gui.build_command(interpreter, ["--batch", "S01"])
        assert cmd[0] == str(interpreter)
        assert cmd[1].endswith("clinician_gui.py")
        assert cmd[2:] == ["--batch", "S01"]

    def test_targets_the_gui_next_to_the_launcher_not_the_cwd(self, tmp_path):
        cmd = launch_gui.build_command(tmp_path / "python.exe", [])
        assert Path(cmd[1]) == REPO_ROOT / "clinician_gui.py"


class TestRealRepoWiring:
    def test_the_gui_the_launcher_points_at_actually_exists(self):
        assert (REPO_ROOT / "clinician_gui.py").is_file()

    def test_env_name_matches_what_the_docs_promise(self):
        assert launch_gui.ENV_NAME == "opencap-processing"
