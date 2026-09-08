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

## The smoke run

The plan's Verification Contract requires this before the GUI can be called
done, and it is not CI-automatable: Tk widget rendering is not practically
testable headlessly on this platform, so **no test in this suite has ever
instantiated a window**. Everything below lives in that gap. The unit tests
cover the data shaping underneath it; they cannot tell you the window works.

Run it after any change to `clinician_gui.py`, `report_export.py`,
`gait_event_picker_tk.py`, or the pipeline stages the GUI drives.

### Launching it so it survives

`clinician_gui.py` blocks until the window closes, so do not start it in a
foreground shell you need back, and do not start it as a background job owned
by an agent turn -- it dies when the turn ends. Detach it:

```powershell
Start-Process -FilePath "C:\Users\cladi\miniconda3\python.exe" `
  -ArgumentList "launch_gui.py" -WorkingDirectory "C:\Users\cladi\synergy" -PassThru
```

Two processes is correct: the launcher under base python, and the GUI itself
re-executed under `opencap-processing`. Confirm the window is real rather than
a process that started and hung:

```powershell
Get-Process python | Where-Object { $_.MainWindowTitle -ne "" } |
  Select-Object Id, MainWindowTitle, Responding
```

Expect `Clinician Trial Report` and `Responding: True`.

### What to check, and why each one is here

Needs a real OpenCap session with a scaled model, plus an `.mvnx` trial.

1. **Pick a session and trial, and Run.** Watch the progress messages.
2. **Does the window stay responsive the whole way through?** Specifically
   during `Running inverse kinematics` / the AnalyzeTool stage. The plan flags
   this as an open empirical question: it is not confirmed whether
   `osim.AnalyzeTool` releases the GIL, and if it does not, the worker thread
   will not keep the UI responsive during that one stage even though every
   other stage is fine. Try dragging the window while it runs. **Note the
   answer on issue #1**, which exists for this and cannot be closed without it.
3. **Do all four report areas render?** Metadata, joint-angle curves, gait
   metrics, per-segment confidence. The confidence chips should be
   tier-coloured -- green / amber / red / grey, not four identical grey ones.
4. **Export to PDF, then open the PDF.** Not just "the dialog said it saved".
   Page 1 metadata, **page 2 the summary scores with GDI per limb**, then the
   curve pages, metrics, confidence. Page 2 is the newest and least exercised:
   if the session has no pooled matrix yet, or no reference under `context/`,
   it must say *why* rather than being absent.
5. **The gait-event picker, if a trial fails to auto-segment.** This is the
   highest-risk path in the GUI and the least covered: the worker thread posts
   a `ManualEventRequest`, the main thread opens a modal `Toplevel` from its
   `root.after` poll, and the worker blocks until it is answered. Check the
   window opens, that the *rest* of the GUI is properly blocked while it is up,
   that picking events and pressing "Use these events" lets the run finish, and
   that closing it with the X button falls back to auto-trim rather than
   hanging the worker forever.
6. **Re-run the same trial.** v1 overwrites rather than versioning output
   (KTD8, deliberate). Confirm it still overwrites cleanly and does not
   half-write.

### Record the result

The smoke run is only worth doing if its outcome is written down. Note in the
PR or the plan doc: which session and trial, whether the UI stalled during
AnalyzeTool, and anything that rendered wrong. A smoke run whose result lives
only in someone's memory is one that will be demanded again next month.

### Not the same as the render gallery

`render_gallery.py` (see the `render-and-look` skill) renders every figure and
PDF page headlessly, and catches occlusion, clipping and colour mistakes
without a window. It is much cheaper and should be run first -- but it drives
the *builders* directly with fixtures. It cannot tell you the button is wired
to them, that the thread handoff works, or that the window stays responsive.
Do both: the gallery for what the output looks like, this for whether the
application works.

## Testing the gait-event picker on demand

The picker is the fallback for automatic gait-event detection failing, and it
is the least covered path in the application: the worker thread posts a
`ManualEventRequest`, the main thread opens a modal `Toplevel` from its
`root.after` poll, and the worker blocks until it is answered. Nothing
automated exercises that handshake.

It also cannot be reached by waiting. A scan of all 90 processed trials in
this dataset on 2026-09-08 found **zero** auto-trim failures, so there is no
trial to test it on.

Set the switch instead:

```powershell
$env:SYNERGY_FORCE_MANUAL_EVENTS = "1"
Start-Process -FilePath "C:\Users\cladi\miniconda3\python.exe" `
  -ArgumentList "launch_gui.py" -WorkingDirectory "C:\Users\cladi\synergy" -PassThru
```

Every trial then reports that detection found no usable cycle and hands over
to the picker, exactly as a genuinely unsegmentable trial would. **Unset it
afterwards** -- it must be set before the GUI starts, so closing and
relaunching without it is the way back.

It forces the *handover*, not the answer: the events that come back are the
ones actually picked in the window. What it cannot tell you is whether
detection would have failed on its own.

### What to check once the window opens

1. **It opens at all**, and the run pauses rather than continuing behind it.
2. **The rest of the GUI is blocked** while it is up -- Run and Export should
   not be clickable, and the window should refuse to close underneath it.
3. **Picking works**: click on the curves, right-click to erase, the verdict
   line updates, the picked list on the left agrees with the markers.
4. **"Use these events" lets the run finish**, and the resulting trial produces
   the same artefacts a normal one does -- curve matrix, metrics, PDF.
5. **The X button falls back to auto-trim** rather than hanging the worker.
   This is the failure mode worth the most attention: the worker is blocked on
   an answer, and a close that never sends one leaves it blocked forever.
6. **One window per trial, not two.** `run_gait_analysis` builds
   `gait_analysis` twice per trial (right leg, then left), so without
   `reuse_across_legs` the same question is asked twice about the same curves
   and can come back with two different answers.

### The standalone picker, without the GUI

`rescue_trial.py` runs the picker on one already-converted trial in its own
process, re-entering at the gait stage:

```
python rescue_trial.py --session <session folder> --trial <trial name>
```

Cheaper than a GUI run -- it reuses the `.mot` on disk instead of redoing
conversion and IK -- and the right tool for checking the picker window itself.
It does **not** exercise the GUI's cross-thread handshake, which is the risky
part, so it is a complement to the switch above rather than a substitute.
