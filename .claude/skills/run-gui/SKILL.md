---
name: run-gui
description: Use when launching, running, restarting, or screenshotting the Synergy clinician GUI, when running this repo's tests, or when a run fails with "No module named 'opensim'" or "No module named 'pytest'"
---

# Running the Synergy clinician GUI

## Launch

```
python launch_gui.py
```

Any python works — base, system, whatever is on PATH. **Do not `conda activate`
first**; `launch_gui.py` locates the `opencap-processing` environment and
re-executes the GUI under it. On Windows, `launch_gui.bat` does the same and can
be double-clicked.

The launcher prints the interpreter it chose. That line is the confirmation the
right environment was found:

```
launching clinician_gui.py with C:\Users\cladi\miniconda3\envs\opencap-processing\python.exe
```

## Two interpreters, two jobs

This repo needs both. Using one for the other's job is the mistake this skill exists to prevent.

| Task | Interpreter | Why |
|---|---|---|
| Run the GUI / any pipeline stage | `opencap-processing` env | Only place `opensim` is installed |
| Run the test suite | **base** (`~/miniconda3/python.exe`) | Only place `pytest` is installed |

```
# tests -- base python, NOT the env
~/miniconda3/python.exe -m pytest tests -q
```

Neither interpreter is on PATH as `python` on the primary machine; use the full
path, or `launch_gui.py`, rather than assuming `python` resolves to either.

## When the environment is somewhere else

Point at an interpreter directly:

```bash
SYNERGY_PYTHON=/path/to/python python launch_gui.py            # bash
$env:SYNERGY_PYTHON="C:\path\to\python.exe"; python launch_gui.py   # PowerShell
```

Find the path with `conda env list`. A `SYNERGY_PYTHON` that points at nothing is
a hard error, not a fallback — the launcher will not quietly run a different
interpreter than the one you named.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'opensim'` | GUI launched under base python | `python launch_gui.py` |
| `No module named 'pytest'` | Tests run under the env python | Run tests under base python |
| GUI opens, then fails partway into a pipeline run | Same as the first row — the wrong interpreter fails late, not at startup | `python launch_gui.py` |
| `Could not find the 'opencap-processing' conda environment` | Env not created, or conda installed somewhere unusual | Create it (below), or set `SYNERGY_PYTHON` |

## Creating the environment

There is no `environment.yml`. Per `README.opencap-processing.md`:

```
conda create -n opencap-processing python=3.11
conda activate opencap-processing
conda install -c opensim-org opensim=4.5=py311np123
pip install -r requirements.txt
```

## Notes for automated runs

- `clinician_gui.py` opens a Tk window and blocks until closed. It ignores CLI
  arguments, including `--help` — passing one still opens the GUI. Do not launch
  it in a foreground shell you need back.
- To check the GUI merely *imports* cleanly without opening a window, exec the
  module rather than launching it — that catches syntax and import errors
  without a blocking window.
- Batch processing of a whole session is a button in the GUI (`run_batch()`),
  not a command-line flag.
