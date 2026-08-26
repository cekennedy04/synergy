#!/usr/bin/env python
r"""Launch the clinician GUI in the environment it actually needs.

Run this with *any* python -- base, system, whatever is on PATH:

    python launch_gui.py

It locates the `opencap-processing` conda environment and re-executes the GUI
under that interpreter. You do not need to `conda activate` first.

Why this exists: `clinician_gui.py` needs `opensim`, which is installed only in
the `opencap-processing` environment. Launched from the base interpreter the
GUI starts, accepts a session, and only then fails partway through a pipeline
run -- long after the mistake was made and far from where it is visible. This
launcher moves that failure to the launch itself, where the message can say
what to do about it.

Override the interpreter explicitly if your conda lives somewhere unusual:

    SYNERGY_PYTHON=/path/to/python  python launch_gui.py     (bash)
    $env:SYNERGY_PYTHON="C:\path\to\python.exe"; python launch_gui.py   (PowerShell)
"""

import os
import subprocess
import sys
from pathlib import Path

ENV_NAME = "opencap-processing"
GUI_SCRIPT = "clinician_gui.py"
OVERRIDE_VAR = "SYNERGY_PYTHON"

REPO_ROOT = Path(__file__).resolve().parent

# Conda writes envs under one of these, depending on which installer was used.
_INSTALL_DIR_NAMES = ("miniconda3", "anaconda3", "mambaforge", "miniforge3")


class EnvironmentNotFound(RuntimeError):
    """Raised when no usable interpreter for ENV_NAME can be located."""


def _interpreter_in(env_dir: Path, windows: bool) -> Path:
    return env_dir / "python.exe" if windows else env_dir / "bin" / "python"


def _candidate_roots(environ, home: Path):
    """Conda install roots to search, most specific first."""
    conda_exe = environ.get("CONDA_EXE")
    if conda_exe:
        # .../<root>/Scripts/conda.exe on Windows, .../<root>/bin/conda on posix
        yield Path(conda_exe).resolve().parent.parent

    for name in _INSTALL_DIR_NAMES:
        yield home / name


def find_env_python(environ=None, home=None, windows=None) -> Path:
    """Return the interpreter for ENV_NAME, or raise EnvironmentNotFound.

    An explicit SYNERGY_PYTHON override is honoured above all discovery, and a
    broken override is an error rather than a silent fallback -- if someone
    named an interpreter, running a different one is never the helpful answer.
    """
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    windows = (os.name == "nt") if windows is None else windows

    override = environ.get(OVERRIDE_VAR)
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
        raise EnvironmentNotFound(
            f"{OVERRIDE_VAR} is set to {override!r}, but no file is there.\n"
            f"Unset {OVERRIDE_VAR} to fall back to automatic discovery, or point "
            f"it at the python.exe inside your {ENV_NAME} environment."
        )

    for root in _candidate_roots(environ, home):
        candidate = _interpreter_in(root / "envs" / ENV_NAME, windows)
        if candidate.is_file():
            return candidate

    raise EnvironmentNotFound(
        f"Could not find the {ENV_NAME!r} conda environment.\n"
        f"\n"
        f"Looked for an 'envs/{ENV_NAME}' directory under $CONDA_EXE's install "
        f"root and under {', '.join('~/' + n for n in _INSTALL_DIR_NAMES)}.\n"
        f"\n"
        f"Fixes:\n"
        f"  - Create it (see README.opencap-processing.md for full steps):\n"
        f"      conda create -n {ENV_NAME} python=3.11\n"
        f"      conda activate {ENV_NAME}\n"
        f"      conda install -c opensim-org opensim=4.5=py311np123\n"
        f"      pip install -r requirements.txt\n"
        f"  - Or, if it exists somewhere unusual, name it directly:\n"
        f"      {OVERRIDE_VAR}=<path-to-python> python launch_gui.py\n"
        f"    Find the path with:  conda env list"
    )


def _can_import_opensim() -> bool:
    try:
        import opensim  # noqa: F401
    except Exception:
        return False
    return True


def current_interpreter_is_ready() -> bool:
    """True when we are already running somewhere `opensim` is importable."""
    return _can_import_opensim()


def build_command(interpreter, extra_args):
    """Command to launch the GUI, forwarding any extra CLI arguments."""
    return [str(interpreter), str(REPO_ROOT / GUI_SCRIPT), *extra_args]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if current_interpreter_is_ready():
        # Already inside the right env (someone did `conda activate` by hand,
        # or this *is* the env python). Re-executing would be pointless.
        interpreter = Path(sys.executable)
    else:
        try:
            interpreter = find_env_python()
        except EnvironmentNotFound as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    command = build_command(interpreter, argv)
    print(f"launching {GUI_SCRIPT} with {interpreter}")
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
