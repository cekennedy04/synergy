"""
clinician_gui.py

U1 of the clinician trial report GUI plan: the tkinter window where a
clinician selects an existing OpenCap session directory and a new Xsens
.mvnx trial file, with the Run control enabled only once both inputs are
valid, and a visible reason shown when they aren't.

KTD6: the API_TOKEN placeholder below MUST be the very first thing this
module does, before any other import. utils.py calls get_token() at module
import time (see utils.py:41 / utilsAuthentication.py), which otherwise
fires an interactive OpenCap login prompt -- fine in a terminal, fatal in a
GUI with no terminal for the prompt to appear in. Setting a placeholder here
means that if anything imported later (this unit or a future one) transitively
imports utils.py, the login prompt never fires.
"""
import os

os.environ.setdefault("API_TOKEN", "clinician-gui-placeholder-token")

# Every other import must come after the os.environ.setdefault call above.
import importlib.util
import queue
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_XSENS_TO_OPENSIM_PATH = os.path.join(REPO_ROOT, "xsens_to_opensim.py")
_GAIT_ANALYSIS_UCM_FIXED_PATH = os.path.join(REPO_ROOT, "gait_analysis_UCM_fixed.py")
_GAIT_ANALYSIS_EXAMPLE_PATH = os.path.join(REPO_ROOT, "Examples", "gaitAnalysis-UCM.py")

# opensense heading-correction defaults, matching xsens_to_opensim.py's own
# main()/argparse defaults (see that file's --base-imu/--base-heading-axis
# help text for why 'x', not the OpenSense reference example's 'z', is
# correct here -- confirmed empirically against real data).
DEFAULT_BASE_IMU_LABEL = "pelvis_imu"
DEFAULT_BASE_HEADING_AXIS = "x"


def _load_xsens_to_opensim():
    """Load xsens_to_opensim.py by absolute path, matching this repo's own
    test-loading convention (see tests/test_xsens_to_opensim_session_paths.py)
    rather than a normal `import xsens_to_opensim`, so this module works
    regardless of how/where it's launched from."""
    spec = importlib.util.spec_from_file_location(
        "xsens_to_opensim_for_clinician_gui", _XSENS_TO_OPENSIM_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_gait_analysis_ucm_fixed():
    """Load gait_analysis_UCM_fixed.py (KTD3: the bug-fixed copy, not the
    original gait_analysis_UCM.py -- see that file's own module docstring
    for the full list of fixes, including allow_manual_entry=False turning
    a blocking input() prompt into a catchable exception). Loaded lazily, by
    absolute path, only when a real pipeline run needs it -- this module
    transitively imports opensim and utils.py (via utilsKinematics.py), so
    importing clinician_gui.py itself never requires either to be
    installed/configured.

    U2's own tests (KTD9) never call this for real -- they monkeypatch it
    (or pass a fake module directly to run_pipeline's gait_fixed_module
    parameter) instead of driving the real gait_analysis class through
    synthetic marker data."""
    spec = importlib.util.spec_from_file_location(
        "gait_analysis_ucm_fixed_for_clinician_gui", _GAIT_ANALYSIS_UCM_FIXED_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_gait_analysis_example():
    """Load Examples/gaitAnalysis-UCM.py by absolute path, for
    compute_foot_progression_angles (the only function of that module this
    GUI calls -- see its docstring around line 230). NOTE: importing this
    module runs its own module-level os.chdir() to the repo root (harmless
    here since clinician_gui.py already lives at the repo root) -- tests
    that don't need the real function monkeypatch this loader instead of
    calling it, both to avoid that side effect and to avoid needing a real
    OpenSim install (compute_foot_progression_angles itself needs
    opensim.AnalyzeTool)."""
    spec = importlib.util.spec_from_file_location(
        "gait_analysis_example_for_clinician_gui", _GAIT_ANALYSIS_EXAMPLE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModelResolutionError(Exception):
    """Wraps resolve_session_output_paths' ValueError: the session directory
    has no .osim model file, or more than one, so model auto-discovery
    can't pick one (R5/AE1)."""


class MvnxParsingError(Exception):
    """Wraps a failure to read/parse the selected .mvnx file -- either
    parse_mvnx's own ValueError (malformed/unexpected structure) or a
    lower-level xml.etree.ElementTree.ParseError (not valid XML at all),
    both raised (transitively, via build_orientations_sto) while converting
    the trial (R5/AE1)."""


class GaitAnalysisFailedError(Exception):
    """Wraps gait_analysis_UCM_fixed.gait_analysis raising while
    allow_manual_entry=False -- automatic gait-event (heel-strike/toe-off)
    detection failed and, since this GUI always disables manual entry
    (KTD3), the class raises a catchable exception instead of blocking on
    stdin (R5)."""


def map_error_to_message(exc):
    """Centralized, pure error-to-message mapper (KTD10, governs R5).

    No Tk dependency: takes an exception, returns a plain-language string --
    never raises, never returns None/empty, never a raw traceback. This is
    the one place U2's own pipeline stages route their failures through
    before reaching tkinter.messagebox.showerror; later units (U4's display
    code, U5's PDF export) are expected to route their own caught failures
    through this same function rather than inventing their own messages.
    """
    detail = str(exc).strip()

    if isinstance(exc, ModelResolutionError):
        message = (
            "No OpenSim model (.osim) file was found for this session -- or "
            "more than one was found. This tool needs exactly one .osim file "
            "directly inside the session's OpenSimData/Model/ folder to know "
            "which model to calibrate and run IK against. Check that you "
            "selected the correct OpenCap session directory, and that it has "
            "already been scaled (exactly one .osim present)."
        )
    elif isinstance(exc, MvnxParsingError):
        message = (
            "The selected .mvnx file could not be read. It may be corrupted, "
            "truncated, or not a valid Xsens MVNX export. Try re-exporting "
            "the trial from the Xsens recording software, or select a "
            "different .mvnx file."
        )
    elif isinstance(exc, GaitAnalysisFailedError):
        message = (
            "Automatic gait-event (heel-strike/toe-off) detection failed for "
            "this trial, so gait-cycle metrics could not be computed. This "
            "can happen with a very short recording, non-walking motion, or "
            "noisy/incomplete tracking data. Try a longer or cleaner "
            "recording of the same activity."
        )
    else:
        message = (
            "The trial could not be processed due to an unexpected error "
            f"({type(exc).__name__}). If this keeps happening, note what you "
            "were doing and contact support -- this is not a known, "
            "specifically-handled failure mode."
        )

    if detail:
        message = f"{message}\n\nDetails: {detail}"
    return message


def _resolve_trial_name(mvnx_path):
    # Mirrors validate_inputs' placeholder trial-name derivation (U1) --
    # output files are named after the .mvnx's own stem (KTD8: re-running
    # the same .mvnx overwrites its own prior output, by design).
    return Path(mvnx_path).stem or "trial"


def run_pipeline(session_dir, mvnx_path, progress_callback=None,
                  xsens_module=None, gait_fixed_module=None,
                  foot_progression_module=None):
    """Runs the full conversion + gait-analysis pipeline for one trial
    (KTD3, KTD4's Approach step 1): build_orientations_sto -> calibrate_model
    -> run_imu_ik (xsens_to_opensim.py), then compute_foot_progression_angles,
    then two gait_analysis_UCM_fixed.gait_analysis instantiations (leg='r'
    and leg='l', both fed the same foot-progression-angle output), each with
    allow_manual_entry=False and modelName=Path(model_file).name.

    Pure w.r.t. Tk: takes/returns plain data, reports progress via a plain
    callback(str) rather than touching any widget, and raises one of this
    module's own wrapped exception types (or the underlying exception, for
    anything not specifically mapped) rather than showing a message box
    itself -- callers (start_pipeline_thread) are responsible for routing
    whatever it raises through map_error_to_message.

    The xsens_module/gait_fixed_module/foot_progression_module parameters
    are the seam KTD9's tests use: pass fake modules/classes in tests
    instead of driving the real (heavy, opensim-dependent) stages -- default
    None loads the real ones lazily via the _load_* functions above.
    """
    def _progress(message):
        if progress_callback is not None:
            progress_callback(message)

    xsens = xsens_module if xsens_module is not None else _load_xsens_to_opensim()
    trial_name = _resolve_trial_name(mvnx_path)

    try:
        paths = xsens.resolve_session_output_paths(session_dir, trial_name)
    except ValueError as exc:
        raise ModelResolutionError(str(exc)) from exc

    _progress("Converting Xsens orientations to OpenSim format...")
    try:
        xsens.build_orientations_sto(
            mvnx_path, paths["sto_path"], xsens.SEGMENT_TO_IMU_FRAME, source="segment"
        )
    except (ValueError, ET.ParseError) as exc:
        raise MvnxParsingError(str(exc)) from exc

    _progress("Calibrating model against IMU orientations...")
    calibrated_model = xsens.calibrate_model(
        paths["model_file"], paths["sto_path"],
        DEFAULT_BASE_IMU_LABEL, DEFAULT_BASE_HEADING_AXIS,
    )

    _progress("Running IMU inverse kinematics...")
    mot_path = xsens.run_imu_ik(
        calibrated_model, paths["sto_path"], None, None, paths["results_dir"],
        output_motion_filename=paths["output_motion_filename"],
    )

    _progress("Computing foot progression angles...")
    foot_progression = (
        foot_progression_module if foot_progression_module is not None
        else _load_gait_analysis_example()
    )
    fpa_r, fpa_l = foot_progression.compute_foot_progression_angles(session_dir, trial_name)

    gait_fixed = gait_fixed_module if gait_fixed_module is not None else _load_gait_analysis_ucm_fixed()
    model_name = Path(paths["model_file"]).name

    try:
        _progress("Analyzing gait (right leg)...")
        gait_r = gait_fixed.gait_analysis(
            session_dir, trial_name, fpa_r, fpa_l, leg="r",
            allow_manual_entry=False, modelName=model_name,
        )
        _progress("Analyzing gait (left leg)...")
        gait_l = gait_fixed.gait_analysis(
            session_dir, trial_name, fpa_r, fpa_l, leg="l",
            allow_manual_entry=False, modelName=model_name,
        )
    except Exception as exc:
        raise GaitAnalysisFailedError(str(exc)) from exc

    _progress("Finalizing results...")
    return {
        "session_dir": session_dir,
        "mvnx_path": mvnx_path,
        "trial_name": trial_name,
        "model_file": paths["model_file"],
        "mot_path": mot_path,
        "fpa_r": fpa_r,
        "fpa_l": fpa_l,
        "gait_r": gait_r,
        "gait_l": gait_l,
    }


def start_pipeline_thread(session_dir, mvnx_path, result_queue, **pipeline_kwargs):
    """Starts (and returns) a background threading.Thread running
    run_pipeline(), posting progress/result/error messages onto
    result_queue as (kind, payload) tuples: ("progress", str),
    ("result", dict), or ("error", str) -- the error string is always
    already routed through map_error_to_message (KTD4, KTD10).

    Factored out of ClinicianGUI so tests can drive it directly against a
    real queue.Queue with injected fake pipeline_kwargs (xsens_module=...,
    etc.), without instantiating any Tk widgets.
    """
    def progress_callback(message):
        result_queue.put(("progress", message))

    def _target():
        try:
            result = run_pipeline(
                session_dir, mvnx_path, progress_callback=progress_callback, **pipeline_kwargs
            )
        except Exception as exc:  # noqa: BLE001 -- centralized mapping (KTD10) is the point here.
            result_queue.put(("error", map_error_to_message(exc)))
            return
        result_queue.put(("result", result))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def drain_queue(result_queue, on_progress, on_result, on_error):
    """Synchronously drains result_queue, dispatching each message to the
    matching callback. No Tk dependency -- ClinicianGUI's
    _poll_pipeline_queue schedules this via root.after(...) and wires
    Tk-specific callbacks into it; tests call this directly against a real
    queue.Queue with plain Python callables to prove ordering/dispatch
    without instantiating Tk widgets.

    Returns True once a terminal message (result or error) was dispatched,
    False if the queue only had (zero or more) progress messages so far.
    """
    terminal = False
    while True:
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            break
        if kind == "progress":
            on_progress(payload)
        elif kind == "result":
            on_result(payload)
            terminal = True
        elif kind == "error":
            on_error(payload)
            terminal = True
    return terminal


def validate_inputs(session_dir, mvnx_path):
    """Pure validation function, no Tk dependency -- importable and testable
    standalone (plan U1 requirement).

    Given a session directory path and an .mvnx path, returns (ready, reason):
      - ready=True, reason="" only when the session directory resolves to
        exactly one .osim model (via xsens_to_opensim.py's
        resolve_session_output_paths -- not reimplemented here) AND the
        .mvnx path exists on disk.
      - ready=False with a human-readable reason otherwise. When
        resolve_session_output_paths raises (zero or multiple .osim files),
        its own message is surfaced verbatim as the reason.
    """
    if not session_dir:
        return False, "Select an existing OpenCap session directory."
    if not mvnx_path:
        return False, "Select an .mvnx trial file."

    xsens_to_opensim = _load_xsens_to_opensim()
    # trial_name doesn't affect model auto-discovery/raising -- any
    # placeholder derived from the .mvnx filename is fine here since this
    # function only cares about resolving the .osim model.
    trial_name = Path(mvnx_path).stem or "trial"
    try:
        xsens_to_opensim.resolve_session_output_paths(session_dir, trial_name)
    except ValueError as exc:
        return False, str(exc)

    mvnx_file = Path(mvnx_path)
    if not mvnx_file.exists():
        return False, f".mvnx file not found: {mvnx_path}"

    return True, ""


class ClinicianGUI:
    """The persistent tkinter main window. Construction builds real Tk
    widgets, so tests must not instantiate this class -- they exercise
    validate_inputs() directly instead (see tests/test_clinician_gui_inputs.py
    and the plan's note that Tk widget rendering is a manual smoke check,
    not a unit test)."""

    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title("Clinician Trial Report")

        self.session_dir = ""
        self.mvnx_path = ""
        self.last_result = None
        self._pipeline_queue = None
        self._pipeline_thread = None

        self._build_widgets()
        self._revalidate()

    def _build_widgets(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="OpenCap session directory:").grid(
            row=0, column=0, sticky="w"
        )
        self.session_dir_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.session_dir_var, width=50, state="readonly").grid(
            row=1, column=0, sticky="we"
        )
        ttk.Button(frame, text="Browse...", command=self._pick_session_dir).grid(
            row=1, column=1, padx=(6, 0)
        )

        ttk.Label(frame, text="Xsens .mvnx trial file:").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        self.mvnx_path_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.mvnx_path_var, width=50, state="readonly").grid(
            row=3, column=0, sticky="we"
        )
        ttk.Button(frame, text="Browse...", command=self._pick_mvnx_file).grid(
            row=3, column=1, padx=(6, 0)
        )

        self.reason_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.reason_var, foreground="red", wraplength=400).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        self.run_button = ttk.Button(frame, text="Run", state="disabled", command=self._on_run_clicked)
        self.run_button.grid(row=5, column=0, columnspan=2, pady=(10, 0))

        # U2: visible progress while the background pipeline thread runs
        # (R4/KTD4) -- separate from reason_var above, which only ever shows
        # why Run is currently disabled before a run starts.
        self.progress_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.progress_var, wraplength=400).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _pick_session_dir(self):
        # Mirrors Examples/gaitAnalysis-UCM.py's
        # _select_extracted_folder_interactively picker pattern.
        selected = filedialog.askdirectory(parent=self.root)
        if selected:
            self.session_dir = selected
            self.session_dir_var.set(selected)
            self._revalidate()

    def _pick_mvnx_file(self):
        # Mirrors Examples/gaitAnalysis-UCM.py's _select_zip_interactively
        # picker pattern.
        selected = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Xsens MVNX", "*.mvnx"), ("All files", "*.*")]
        )
        if selected:
            self.mvnx_path = selected
            self.mvnx_path_var.set(selected)
            self._revalidate()

    def _revalidate(self):
        ready, reason = validate_inputs(self.session_dir, self.mvnx_path)
        self.run_button.configure(state="normal" if ready else "disabled")
        self.reason_var.set(reason)
        return ready, reason

    def _on_run_clicked(self):
        # U2 (KTD4): starts the background thread and disables Run for the
        # run's duration -- no cancel/abort in v1 (see plan's Scope
        # Boundaries). Re-validates first so a stale enabled state (e.g. the
        # session dir changing underneath the process) can't start a doomed
        # run; _revalidate's own message then explains why nothing happened.
        ready, _reason = self._revalidate()
        if not ready:
            return

        self.run_button.configure(state="disabled")
        self.progress_var.set("Starting...")
        self._pipeline_queue = queue.Queue()
        self._pipeline_thread = start_pipeline_thread(
            self.session_dir, self.mvnx_path, self._pipeline_queue
        )
        self.root.after(100, self._poll_pipeline_queue)

    def _poll_pipeline_queue(self):
        terminal = drain_queue(
            self._pipeline_queue,
            on_progress=self.progress_var.set,
            on_result=self._on_pipeline_result,
            on_error=self._on_pipeline_error,
        )
        if not terminal:
            self.root.after(100, self._poll_pipeline_queue)

    def _on_pipeline_result(self, result):
        self.last_result = result
        self.progress_var.set("Done.")
        # Re-enable Run (re-validated, in case inputs changed mid-run) now
        # that a result reached the queue (KTD4's Approach step 2).
        self._revalidate()

    def _on_pipeline_error(self, message):
        self.progress_var.set("")
        self._revalidate()
        messagebox.showerror("Run failed", message)


def main():
    app = ClinicianGUI()
    app.root.mainloop()


if __name__ == "__main__":
    main()
