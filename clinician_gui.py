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
import sys
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# U4: matplotlib is already a hard dependency of this repo (KTD1/KTD2 --
# tkinter + matplotlib.backends.backend_pdf are stdlib/already-required, no
# new dependency added). Imported at module level, not lazily like the
# opensim-dependent stages below, because neither of these imports touches
# opensim/utils.py or does any real work at import time -- they're safe for
# every existing test that loads this whole module via
# importlib.util.spec_from_file_location, same as the tkinter import above.
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_XSENS_TO_OPENSIM_PATH = os.path.join(REPO_ROOT, "xsens_to_opensim.py")
_GAIT_ANALYSIS_UCM_FIXED_PATH = os.path.join(REPO_ROOT, "gait_analysis_UCM_fixed.py")
_GAIT_ANALYSIS_EXAMPLE_PATH = os.path.join(REPO_ROOT, "Examples", "gaitAnalysis-UCM.py")
_JOINT_CONFIDENCE_PATH = os.path.join(REPO_ROOT, "joint_confidence.py")
_REPORT_EXPORT_PATH = os.path.join(REPO_ROOT, "report_export.py")
_REPORT_FORMATTING_PATH = os.path.join(REPO_ROOT, "report_formatting.py")
_MODULE_LOADING_PATH = os.path.join(REPO_ROOT, "module_loading.py")


def _bootstrap_load_module_loading():
    # One-off bootstrap for module_loading.py itself, by the same
    # by-path mechanism it then provides for everything else -- it can't
    # load itself via its own not-yet-loaded function. Registered under the
    # same fixed sys.modules key ("module_loading") that report_export.py's
    # own bootstrap uses, so both entry points share the exact same module
    # object -- and therefore the same _LOADED_MODULE_CACHE dict -- instead
    # of each getting an independent module_loading instance with its own
    # empty cache (found in code review: that gap meant report_formatting.py
    # was still loaded and executed twice, once per cache, defeating the
    # "one process-wide cache" this module's docstring promises).
    existing = sys.modules.get("module_loading")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("module_loading", _MODULE_LOADING_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["module_loading"] = module
    spec.loader.exec_module(module)
    return module


_load_module_by_path = _bootstrap_load_module_loading().load_module_by_path

# opensense heading-correction defaults, matching xsens_to_opensim.py's own
# main()/argparse defaults (see that file's --base-imu/--base-heading-axis
# help text for why 'x', not the OpenSense reference example's 'z', is
# correct here -- confirmed empirically against real data).
DEFAULT_BASE_IMU_LABEL = "pelvis_imu"
DEFAULT_BASE_HEADING_AXIS = "x"


def _load_xsens_to_opensim():
    return _load_module_by_path("xsens_to_opensim_for_clinician_gui", _XSENS_TO_OPENSIM_PATH)


def _load_gait_analysis_ucm_fixed():
    """KTD3: the bug-fixed copy, not the original gait_analysis_UCM.py --
    see that file's own module docstring for the full list of fixes,
    including allow_manual_entry=False turning a blocking input() prompt
    into a catchable exception. Loaded lazily, only when a real pipeline
    run needs it -- this module transitively imports opensim and utils.py
    (via utilsKinematics.py), so importing clinician_gui.py itself never
    requires either to be installed/configured.

    U2's own tests (KTD9) never call this for real -- they monkeypatch it
    (or pass a fake module directly to run_pipeline's gait_fixed_module
    parameter) instead of driving the real gait_analysis class through
    synthetic marker data."""
    return _load_module_by_path(
        "gait_analysis_ucm_fixed_for_clinician_gui", _GAIT_ANALYSIS_UCM_FIXED_PATH
    )


def _load_gait_analysis_example():
    """For compute_foot_progression_angles (the only function of
    Examples/gaitAnalysis-UCM.py this GUI calls -- see its docstring around
    line 230). NOTE: importing this module runs its own module-level
    os.chdir() to the repo root (harmless here since clinician_gui.py
    already lives at the repo root) -- tests that don't need the real
    function monkeypatch this loader instead of calling it, both to avoid
    that side effect and to avoid needing a real OpenSim install
    (compute_foot_progression_angles itself needs opensim.AnalyzeTool)."""
    return _load_module_by_path(
        "gait_analysis_example_for_clinician_gui", _GAIT_ANALYSIS_EXAMPLE_PATH
    )


def _load_joint_confidence():
    """joint_confidence.py (U3) has no opensim/utils.py dependency chain at
    all (pure numpy) -- loaded the same way anyway for consistency, and so
    tests can inject a fake module through shape_results_for_display's own
    joint_confidence_module parameter the same way run_pipeline's callers
    inject fake pipeline stages (KTD9's pattern applied to U4's own
    display-shaping seam)."""
    return _load_module_by_path("joint_confidence_for_clinician_gui", _JOINT_CONFIDENCE_PATH)


def _load_report_export():
    """report_export.py (U5), like joint_confidence.py, has no
    opensim/tkinter dependency chain -- loaded the same way anyway for
    consistency, and so this file (and tests exercising its export button
    handler) can swap in a fake module the same way run_pipeline's/
    shape_results_for_display's own dependency-injection seams do (KTD9's
    pattern)."""
    return _load_module_by_path("report_export_for_clinician_gui", _REPORT_EXPORT_PATH)


def _load_report_formatting():
    """report_formatting.py holds the metric/symmetry text-formatting rules
    shared between this file's on-screen metrics grid and report_export.py's
    PDF metrics table, so there is exactly one place that decides how a
    shaped metric entry renders as text."""
    return _load_module_by_path("report_formatting_for_clinician_gui", _REPORT_FORMATTING_PATH)


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


class FootProgressionAnalysisError(Exception):
    """Wraps compute_foot_progression_angles raising -- it runs a real
    osim.AnalyzeTool pass (flagged as a real risk in the plan's Risks &
    Dependencies section) that can fail on its own, independent of the
    later gait_analysis stage (R5)."""


class MarkerExportError(Exception):
    """Wraps write_markers_trc raising while writing the .trc marker file
    gait_analysis_UCM_fixed.gait_analysis's constructor unconditionally
    requires (via get_marker_dict -> trc_2_dict -> MarkerData/<trial>.trc,
    with no existence check). Found in code review: run_pipeline never ran
    this stage, so every real trial would fail inside gait_analysis's
    constructor with a raw FileNotFoundError mapped to the generic fallback
    (or, worse, misread as a gait-event-detection failure) (R2, R5)."""


class ImuKinematicsError(Exception):
    """Wraps calibrate_model or run_imu_ik raising -- unlike every other
    pipeline stage, these two had no dedicated wrapping, so a bad IMU
    orientation/sensor-placement failure here fell through to the generic
    fallback message instead of a specific, actionable one (found in code
    review) (R5)."""


class ReportExportError(Exception):
    """Wraps an OSError raised while writing the PDF report file itself
    (e.g. a Windows PermissionError when the destination file is still open
    in another program) -- distinct from a shaped-results problem, which
    would already have surfaced before Export was ever clickable (R10,
    found in code review)."""


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
    elif isinstance(exc, FootProgressionAnalysisError):
        message = (
            "Foot progression angle analysis failed for this trial. This "
            "step runs an OpenSim analysis pass against the converted "
            "motion and can fail on very short recordings or trials with "
            "incomplete tracking data. Try a longer or cleaner recording "
            "of the same activity."
        )
    elif isinstance(exc, MarkerExportError):
        message = (
            "Could not generate marker positions from the converted motion, "
            "a required step before gait metrics can be computed. This is "
            "usually a problem with the calibrated model or the .mot file "
            "from the previous step, not with the recording itself."
        )
    elif isinstance(exc, ImuKinematicsError):
        message = (
            "Could not calibrate the model against the IMU orientations, or "
            "could not run inverse kinematics from them. This usually means "
            "a sensor was misplaced or misoriented during recording, or the "
            "model's base IMU label/heading axis doesn't match this trial's "
            "sensor setup."
        )
    elif isinstance(exc, ReportExportError):
        message = (
            "Could not save the PDF report to the selected location. If the "
            "file is already open in another program (e.g. a PDF viewer), "
            "close it and try exporting again. Otherwise, check that the "
            "destination folder is writable."
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
    # ValueError/ET.ParseError: parse_mvnx's own malformed-structure and
    # invalid-XML cases. OSError (covers FileNotFoundError, PermissionError,
    # etc.): the .mvnx could be deleted or become unreadable between
    # validate_inputs' check and this Run click -- without this, that case
    # fell through to the generic "unexpected error" fallback instead of
    # this stage's specific, more helpful message (found in code review).
    except (ValueError, ET.ParseError, OSError) as exc:
        raise MvnxParsingError(str(exc)) from exc

    # Unlike every other stage below, calibrate_model/run_imu_ik previously
    # had no dedicated wrapping, so a failure here fell through to
    # map_error_to_message's generic fallback instead of a specific message
    # (found in code review).
    try:
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
    except Exception as exc:
        raise ImuKinematicsError(str(exc)) from exc

    # gait_analysis_UCM_fixed.gait_analysis's constructor unconditionally
    # loads MarkerData/<trial_name>.trc (get_marker_dict -> trc_2_dict, no
    # existence check) -- without writing it here first, every real trial
    # fails inside that constructor. Mirrors xsens_to_opensim.py's own
    # main() stage 4 exactly (found missing in code review).
    _progress("Writing marker positions...")
    try:
        Path(paths["trc_path"]).parent.mkdir(parents=True, exist_ok=True)
        xsens.write_markers_trc(calibrated_model, mot_path, paths["trc_path"])
    except Exception as exc:
        raise MarkerExportError(str(exc)) from exc

    _progress("Computing foot progression angles...")
    foot_progression = (
        foot_progression_module if foot_progression_module is not None
        else _load_gait_analysis_example()
    )
    # The plan's own Risks section flags this call as running a real
    # osim.AnalyzeTool pass that can fail -- wrapped so a failure here gets
    # this stage's own specific message instead of falling through to
    # map_error_to_message's generic "unexpected error" fallback (found in
    # code review).
    try:
        fpa_r, fpa_l = foot_progression.compute_foot_progression_angles(session_dir, trial_name)
    except Exception as exc:
        raise FootProgressionAnalysisError(str(exc)) from exc

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
    trial_name = _resolve_trial_name(mvnx_path)
    try:
        xsens_to_opensim.resolve_session_output_paths(session_dir, trial_name)
    except ValueError as exc:
        return False, str(exc)

    mvnx_file = Path(mvnx_path)
    if not mvnx_file.exists():
        return False, f".mvnx file not found: {mvnx_path}"

    return True, ""


# ---------------------------------------------------------------------------
# U4: results review display -- pure, Tk-free data-shaping functions.
#
# These turn a completed run_pipeline() result (plus a fresh parse_mvnx()
# call and each leg's own compute_scalars()/get_coordinates_normalized_time()/
# coordinateValues) into plain dict/list structures ready for widget
# rendering. No tkinter, no matplotlib Figure objects, no file I/O beyond
# the same parse_mvnx()/os.path.getmtime() calls U1/U2 already make
# elsewhere in this file. ClinicianGUI's _render_* methods (below the class
# definition) are the only code that turns these structures into widgets --
# that split is what tests/test_clinician_gui_display.py exercises directly,
# per the plan's Verification note that Tk widget rendering itself is a
# manual smoke check, not a unit test.
# ---------------------------------------------------------------------------

# Duplicated (not imported) from Examples/gaitAnalysis-UCM.py's SCALAR_NAMES
# constant (as of 2026-08-20, lines 148-152) -- same "duplicate a hyphenated,
# non-import-able script's constant" rule joint_confidence.py's
# MOT_COORDINATE_NAMES_USED follows (KTD5). Kept as an ordered list here
# (that file defines it as a set) so the metrics grid renders in a stable,
# deterministic order rather than whatever order set iteration happens to
# produce.
GAIT_METRIC_NAMES = [
    "gait_speed",
    "stride_length",
    "step_width",
    "cadence",
    "single_support_time",
    "double_support_time",
    "step_length_symmetry",
    "foot_progression_angle",
]

# Key joints plotted for R7 -- hip/knee/ankle flexion, both legs. Coordinate
# names are real OpenSim .mot column names (confirmed against
# Examples/gaitAnalysis-UCM.py's JOINT_NAMES and joint_confidence.py's
# MOT_COORDINATE_NAMES_USED, both already grounded in the same real model).
# "leg" picks which of gait_r/gait_l's own get_coordinates_normalized_time()
# result to read the curve from -- each leg's normalization is over that
# leg's own ipsilateral gait cycle, so a right-side joint's curve should come
# from gait_r's normalization and a left-side joint's from gait_l's, not
# both from the same instance.
KEY_JOINT_PLOTS = [
    {"label": "Hip Flexion (R)", "coordinate_name": "hip_flexion_r", "leg": "r"},
    {"label": "Knee Flexion (R)", "coordinate_name": "knee_angle_r", "leg": "r"},
    {"label": "Ankle Flexion (R)", "coordinate_name": "ankle_angle_r", "leg": "r"},
    {"label": "Hip Flexion (L)", "coordinate_name": "hip_flexion_l", "leg": "l"},
    {"label": "Knee Flexion (L)", "coordinate_name": "knee_angle_l", "leg": "l"},
    {"label": "Ankle Flexion (L)", "coordinate_name": "ankle_angle_l", "leg": "l"},
]

# Fixed visual encoding for confidence tiers (U4 Approach step 4). Every
# state (including "not_scored", used both for joint_confidence.py's own
# not_scored segments and for a mapped coordinate with no confidence data at
# all) gets an explicit, distinguishable color pair -- never an unstyled
# fallback.
#
# Values match DESIGN.md's light-mode semantic table exactly (2026-08-21
# design-consultation) -- this is the single source of truth for these
# colors; DESIGN.md documents them, it doesn't define a second copy.
TIER_COLORS = {
    "high": {"bg": "#E3F3E8", "fg": "#1F6B3B"},
    "medium": {"bg": "#FBF0D9", "fg": "#8A5A00"},
    "low": {"bg": "#FBE4E2", "fg": "#A32E24"},
    "not_scored": {"bg": "#ECEDEC", "fg": "#565D5A"},
}

# DESIGN.md tokens (light theme only -- tkinter/ttk has no reliable
# automatic OS dark-mode hook the way a browser does, and DESIGN.md's dark
# variant was approved as a preview-page nicety, not a v1 requirement for
# this native app; revisit if a real need for it shows up).
DESIGN_BG = "#F4F5F3"
DESIGN_SURFACE = "#FFFFFF"
DESIGN_SURFACE_2 = "#F0F1EE"
DESIGN_BORDER = "#D8DBD7"
DESIGN_TEXT = "#1F2421"
DESIGN_TEXT_2 = "#5C6560"
DESIGN_ACCENT = "#0F6B66"
DESIGN_ACCENT_HOVER = "#0B4F4B"

# Times New Roman is a standard Windows-installed font (this app's actual
# deployment target) -- no bundling/install step needed. Cascadia Code
# (falling back to Consolas, then any monospace) is likewise pre-installed
# on any machine with VS Code/Windows Terminal, which this dev environment
# has; a genuinely fresh Windows box without either still gets a real
# monospace via the "monospace" family-class fallback tkinter honors.
DESIGN_FONT_BODY = ("Times New Roman", 10)
DESIGN_FONT_HEADER = ("Times New Roman", 10, "bold")
# No DESIGN_FONT_TITLE: this window has no in-widget hero heading (the
# "Display" role) to apply it to -- the only title-like text is
# root.title(), which is OS window-chrome text tkinter cannot font-style.


def _resolve_data_font(root):
    """Cascadia Code isn't guaranteed present outside a dev machine -- probe
    with tkinter's own font.families() and fall back through Consolas to
    the platform monospace class rather than silently rendering data values
    in the body serif font (which would defeat the point of a distinct,
    tabular-aligned data typeface). This is the actual data-font source of
    truth -- there is no separate DESIGN_FONT_DATA constant, since a fixed
    tuple can't express the availability fallback this function performs."""
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    for family in ("Cascadia Code", "Consolas"):
        if family in available:
            return (family, 10)
    return ("monospace", 10)


def apply_design_system(root):
    """Applies DESIGN.md's color/typography tokens to the whole widget tree
    via ttk styles (2026-08-21 design-consultation). 'clam' is used as the
    base ttk theme because Windows' default 'vista'/'xpnative' themes
    largely ignore background/foreground style options on ttk.Button and
    ttk.Labelframe -- 'clam' is the standard workaround for actually being
    able to recolor ttk widgets on Windows.

    Deliberately conservative about what changes: widget geometry/layout
    (grid positions, padding values already in _build_widgets/_render_*) is
    untouched -- this only touches color and font, per the DESIGN.md scope
    the design-consultation skill produced."""
    style = ttk.Style(root)
    style.theme_use("clam")

    data_font = _resolve_data_font(root)

    root.configure(background=DESIGN_BG)

    style.configure("TFrame", background=DESIGN_BG)
    style.configure("TLabel", background=DESIGN_BG, foreground=DESIGN_TEXT, font=DESIGN_FONT_BODY)
    style.configure(
        "TLabelframe", background=DESIGN_BG, bordercolor=DESIGN_BORDER, relief="solid", borderwidth=1
    )
    style.configure(
        "TLabelframe.Label", background=DESIGN_BG, foreground=DESIGN_TEXT_2, font=DESIGN_FONT_HEADER
    )
    style.configure(
        "TEntry", fieldbackground=DESIGN_SURFACE, foreground=DESIGN_TEXT, font=DESIGN_FONT_BODY
    )
    # 'clam' ships a built-in state map for TEntry's fieldbackground
    # (readonly/disabled -> its own theme gray) that overrides the plain
    # configure() above -- both Entry widgets in this window are permanently
    # readonly (session_dir_var, mvnx_path_var), so without this map the
    # DESIGN_SURFACE field color above silently never renders (found in
    # code review: two independent reviewers hit this).
    style.map(
        "TEntry",
        fieldbackground=[("readonly", DESIGN_SURFACE), ("disabled", DESIGN_SURFACE_2)],
    )

    # Padding values come from DESIGN.md's 8px spacing scale (sm=8, md=12),
    # not arbitrary pixel counts (found in code review).
    style.configure(
        "TButton", background=DESIGN_SURFACE, foreground=DESIGN_TEXT,
        bordercolor=DESIGN_BORDER, font=DESIGN_FONT_BODY, padding=(12, 8),
    )
    style.map("TButton", background=[("active", DESIGN_SURFACE_2)])

    # Run/Export are the two primary actions in this window -- the one place
    # DESIGN.md's teal accent shows up, matching the approved preview's
    # "Export PDF Report" primary-button treatment. The "Browse..." buttons
    # deliberately keep the plain "TButton" style above (bordered, neutral)
    # -- that IS this window's secondary-button tier per DESIGN.md's
    # "secondary (bordered, neutral)" component note, not a missing tier.
    style.configure(
        "Primary.TButton", background=DESIGN_ACCENT, foreground="white",
        font=DESIGN_FONT_HEADER, padding=(12, 8),
    )
    style.map(
        "Primary.TButton",
        background=[("active", DESIGN_ACCENT_HOVER), ("disabled", DESIGN_SURFACE_2)],
        foreground=[("disabled", DESIGN_TEXT_2)],
    )

    # Metadata-panel labels (the "k" column in _render_metadata) render in
    # text-secondary per DESIGN.md's component notes, distinct from the
    # primary-text-colored value column (found in code review).
    style.configure("Secondary.TLabel", background=DESIGN_BG, foreground=DESIGN_TEXT_2, font=DESIGN_FONT_BODY)

    # Numeric values (gait metrics grid, data-shaped metadata) get the
    # monospace data font per DESIGN.md's typography role split -- kept as
    # a distinct style rather than folded into TLabel so only genuinely
    # numeric/tabular values opt in, not every label in the window.
    style.configure("Data.TLabel", background=DESIGN_BG, foreground=DESIGN_TEXT, font=data_font)

    # Tier chips already carry their own bg/fg per-tier (see
    # ClinicianGUI._tier_style_name) -- only the font needs to come from the
    # design system here, so tier styles are configured with the data font
    # afterward, once per tier, in _tier_style_name itself.
    return data_font

_TIER_WORDS = {"high": "High", "medium": "Medium", "low": "Low", "not_scored": "Not scored"}


def tier_colors(tier):
    """Pure lookup, never raises -- an unrecognized/None tier is treated the
    same as 'not_scored' (gray), never left unstyled."""
    return TIER_COLORS.get(tier, TIER_COLORS["not_scored"])


def confidence_label_text(tier):
    """The clinician-facing label text for a confidence tier. Always
    includes 'agreement with the suit's own onboard estimate' per KTD5 --
    this indicator is not a claim of ground-truth accuracy, and that framing
    must survive wherever the score is surfaced (see joint_confidence.py's
    own module docstring)."""
    word = _TIER_WORDS.get(tier, _TIER_WORDS["not_scored"])
    return f"{word} agreement with the suit's own onboard estimate"


def shape_metadata_for_display(session_dir, mvnx_path, xsens_module=None, parsed_mvnx=None):
    """U4 Approach step 1: subject/session ID and trial name come from the
    inputs the clinician already picked (U1), not from parse_mvnx (which has
    no subject/trial/date fields of its own); date comes from the .mvnx
    file's OS modification time; duration and sensor coverage come from
    parse_mvnx's own frame data (`times`, `frame_rate`, `segments`).

    xsens_module is the same dependency-injection seam run_pipeline uses
    (default None loads the real xsens_to_opensim.py lazily) so tests can
    pass a fake module exposing parse_mvnx() instead of needing a real
    .mvnx file with real timestamps.

    parsed_mvnx, when supplied, is used instead of calling parse_mvnx again --
    shape_results_for_display already parses the trial once for the
    confidence indicator and passes that same result here, so a real trial's
    .mvnx (real XML parsing over its full frame list) is never parsed twice
    for one display render.
    """
    if parsed_mvnx is not None:
        parsed = parsed_mvnx
    else:
        xsens = xsens_module if xsens_module is not None else _load_xsens_to_opensim()
        parsed = xsens.parse_mvnx(mvnx_path)

    times = parsed.get("times") or []
    frame_rate = parsed.get("frame_rate")
    n_segments = len(parsed.get("segments") or {})
    n_frames = len(times)
    duration_seconds = (times[-1] - times[0]) if len(times) >= 2 else 0.0

    mtime = os.path.getmtime(mvnx_path)
    date_display = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

    minutes, seconds = divmod(duration_seconds, 60)
    duration_display = f"{int(minutes)}:{seconds:04.1f}" if minutes else f"{seconds:.1f} s"

    sensor_coverage = f"{n_segments} tracked segments"
    if frame_rate:
        sensor_coverage += f" at {frame_rate:.0f} Hz"

    return {
        "subject_session_id": Path(session_dir).name,
        "trial_name": Path(mvnx_path).stem,
        "date": date_display,
        "duration_seconds": duration_seconds,
        "duration_display": duration_display,
        "sensor_coverage": sensor_coverage,
        "frame_count": n_frames,
    }


def shape_joint_curves_for_display(gait_r, gait_l, joint_specs=None):
    """U4 Approach step 2: build display-ready gait-cycle curves (x = 0-100%
    of gait cycle, mean +/- sd) for each key joint in `joint_specs` (default
    KEY_JOINT_PLOTS), reading each joint's curve from the matching leg's own
    get_coordinates_normalized_time() result.

    Pure data only -- no matplotlib Figure objects here (those are built by
    ClinicianGUI._render_curves, which consumes this function's output).
    A joint whose coordinate isn't present in that leg's curves (e.g. an
    unscaled/incomplete model) is reported as unavailable rather than
    raising a KeyError.
    """
    if joint_specs is None:
        joint_specs = KEY_JOINT_PLOTS

    normalized_by_leg = {}
    curves = {}
    for spec in joint_specs:
        leg = spec["leg"]
        coordinate_name = spec["coordinate_name"]
        gait_obj = gait_r if leg == "r" else gait_l

        if leg not in normalized_by_leg:
            normalized_by_leg[leg] = gait_obj.get_coordinates_normalized_time()
        normalized = normalized_by_leg[leg]
        mean_df = normalized.get("mean")
        sd_df = normalized.get("sd")

        if mean_df is None or coordinate_name not in mean_df.columns:
            curves[spec["label"]] = {
                "coordinate_name": coordinate_name,
                "leg": leg,
                "available": False,
                "reason": f"'{coordinate_name}' is not present in this trial's gait-cycle curves.",
                "x": None,
                "mean": None,
                "sd": None,
            }
            continue

        curves[spec["label"]] = {
            "coordinate_name": coordinate_name,
            "leg": leg,
            "available": True,
            "reason": None,
            "x": list(range(0, 101)),
            "mean": mean_df[coordinate_name].tolist(),
            "sd": (
                sd_df[coordinate_name].tolist()
                if sd_df is not None and coordinate_name in sd_df.columns
                else None
            ),
        }

    return curves


def _shape_scalar_entry(entry):
    if entry is None:
        return {"available": False, "status": "not available", "value": None, "units": None}
    return {
        "available": True,
        "status": "ok",
        "value": entry.get("value"),
        "units": entry.get("units"),
    }


# gait_analysis_UCM_fixed.py's compute_step_length_symmetry() already
# returns an R/L ratio percentage computed from a single instance (it reads
# both feet's marker data internally) -- calling scalars_r/scalars_l on
# EITHER leg's gait_analysis instance returns the same already-symmetric
# value. Re-applying the generic r_val/l_val*100 symmetry formula to that
# value would be a "symmetry of symmetry" figure with no real meaning, so
# this metric is reported directly instead (see shape_gait_metrics_for_display).
ALREADY_SYMMETRY_METRICS = {"step_length_symmetry"}


def _symmetry_unavailable(reason):
    return {
        "available": False,
        "status": "not available",
        "value": None,
        "units": None,
        "reason": reason,
    }


def _compute_symmetry_entry(r_entry, l_entry):
    if not r_entry["available"] or not l_entry["available"]:
        return _symmetry_unavailable("not available")

    r_val, l_val = r_entry["value"], l_entry["value"]
    if not isinstance(r_val, (int, float)) or not isinstance(l_val, (int, float)):
        return _symmetry_unavailable("not applicable for this metric")
    if l_val == 0:
        return _symmetry_unavailable("left-side value is zero")

    return {
        "available": True,
        "status": "ok",
        "value": (r_val / l_val) * 100.0,
        "units": "% (R/L)",
        "reason": None,
    }


def shape_gait_metrics_for_display(scalars_r, scalars_l, metric_names=None):
    """U4 Approach step 3: render both legs' compute_scalars(...) dicts as a
    label-grid-ready structure, plus an explicit symmetry figure per metric
    computed by comparing scalars_r/scalars_l (KTD3's two-leg instantiation
    is what makes this comparison possible at all -- a single instance
    cannot produce it).

    scalars_r/scalars_l may each be None or missing a given metric name
    entirely (a real, possible shape -- not every compute_* call is
    guaranteed to have run) -- reported as "not available" for that leg and
    for symmetry, never raised.
    """
    if metric_names is None:
        metric_names = GAIT_METRIC_NAMES

    rows = {}
    for name in metric_names:
        r_entry = _shape_scalar_entry((scalars_r or {}).get(name))
        l_entry = _shape_scalar_entry((scalars_l or {}).get(name))
        if name in ALREADY_SYMMETRY_METRICS:
            # gait_r/gait_l each compute this as an R/L ratio from their own
            # instance -- and each instance anchors gait-cycle detection on
            # a different leg (self.gaitEvents['ipsilateralLeg']), so the two
            # values are NOT guaranteed to agree on a real trial. Reporting
            # one and silently discarding the other would hide a real
            # disagreement from the clinician; the Right/Left columns above
            # already show each instance's own value, so the Symmetry column
            # is marked not-applicable here rather than re-deriving or
            # picking a "winner."
            symmetry_entry = _symmetry_unavailable(
                "already an R/L ratio -- see Right/Left columns"
            )
        else:
            symmetry_entry = _compute_symmetry_entry(r_entry, l_entry)
        rows[name] = {"r": r_entry, "l": l_entry, "symmetry": symmetry_entry}
    return rows


def shape_confidence_for_display(confidence_result):
    """U4 Approach step 4: turn joint_confidence.score_confidence()'s result
    into display-ready rows, applying the fixed tier -> color encoding
    (TIER_COLORS) and the clinician-facing label text
    (confidence_label_text) up front, so ClinicianGUI's rendering code never
    has to know about tiers/colors itself.

    When the whole trial is confidence-unavailable (score_confidence's own
    `available: False`), returns a single banner instead of N per-segment
    rows (U3 Approach step 2 / this unit's own test scenario).
    """
    if not confidence_result.get("available", False):
        return {
            "available": False,
            "banner": (
                confidence_result.get("reason")
                or "Confidence indicator is not available for this recording."
            ),
            "segments": {},
            "by_coordinate": {},
        }

    segments_out = {}
    by_coordinate = {}
    for segment_name, seg in confidence_result.get("segments", {}).items():
        display_tier = seg.get("tier") if seg.get("status") == "scored" else "not_scored"
        row = {
            "status": seg.get("status"),
            "tier": seg.get("tier"),
            "display_tier": display_tier,
            "coordinate_name": seg.get("coordinate_name"),
            "rms_deg": seg.get("rms_deg"),
            "n_aligned_samples": seg.get("n_aligned_samples"),
            "reason": seg.get("reason"),
            "colors": tier_colors(display_tier),
            "label_text": confidence_label_text(display_tier),
        }
        segments_out[segment_name] = row
        if row["coordinate_name"]:
            by_coordinate[row["coordinate_name"]] = row

    return {"available": True, "banner": None, "segments": segments_out, "by_coordinate": by_coordinate}


def _mot_series_from_coordinate_values(coordinate_values):
    """Extracts (mot_times, mot_coordinates) from a gait_analysis instance's
    own already-loaded `coordinateValues` DataFrame -- a plain DataFrame
    with a 'time' column plus one column per OpenSim coordinate name, in
    degrees (see utilsKinematics.kinematics.get_coordinate_values(), which
    gait_analysis_UCM_fixed.py's __init__ calls and stores as
    self.coordinateValues). This is the real, already-available `.mot`
    time-series data source the plan's Sources/Research section pointed at
    -- reused here rather than writing a new `.mot` file reader, since
    run_pipeline already has this loaded via gait_r/gait_l.
    """
    mot_times = coordinate_values["time"].to_numpy()
    mot_coordinates = {
        column: coordinate_values[column].to_numpy()
        for column in coordinate_values.columns
        if column != "time"
    }
    return mot_times, mot_coordinates


def shape_results_for_display(result, xsens_module=None, joint_confidence_module=None):
    """Orchestrates all four U4 content areas from one run_pipeline() result
    dict. Pure w.r.t. Tk (no widgets built here); ClinicianGUI._render_results
    is the only caller that turns this function's output into widgets.

    xsens_module/joint_confidence_module are the same kind of
    dependency-injection seam run_pipeline's xsens_module/gait_fixed_module/
    foot_progression_module parameters are (KTD9's pattern) -- tests pass
    fakes instead of driving the real, heavier modules.
    """
    xsens = xsens_module if xsens_module is not None else _load_xsens_to_opensim()
    joint_confidence = (
        joint_confidence_module if joint_confidence_module is not None else _load_joint_confidence()
    )

    gait_r = result["gait_r"]
    gait_l = result["gait_l"]

    # Parsed once and threaded through -- shape_metadata_for_display would
    # otherwise call parse_mvnx a second time on the same file. Wrapped the
    # same way run_pipeline's own build_orientations_sto call is: the .mvnx
    # could have been deleted/become unreadable between the pipeline's own
    # parse and this post-run display parse, and without this the failure
    # fell through to the generic fallback message instead of the specific
    # one this exact failure mode already has (found in code review).
    try:
        parsed = xsens.parse_mvnx(result["mvnx_path"])
    except (ValueError, ET.ParseError, OSError) as exc:
        raise MvnxParsingError(str(exc)) from exc

    metadata = shape_metadata_for_display(
        result["session_dir"], result["mvnx_path"], xsens_module=xsens, parsed_mvnx=parsed
    )
    curves = shape_joint_curves_for_display(gait_r, gait_l)

    scalars_r = gait_r.compute_scalars(GAIT_METRIC_NAMES)
    scalars_l = gait_l.compute_scalars(GAIT_METRIC_NAMES)
    metrics = shape_gait_metrics_for_display(scalars_r, scalars_l)

    mot_times, mot_coordinates = _mot_series_from_coordinate_values(gait_r.coordinateValues)
    confidence_raw = joint_confidence.score_confidence(
        parsed["joint_angles"], parsed["times"], mot_coordinates, mot_times,
    )
    confidence = shape_confidence_for_display(confidence_raw)

    return {"metadata": metadata, "curves": curves, "metrics": metrics, "confidence": confidence}


def build_curve_figure(curve):
    """Builds a matplotlib Figure for one shaped joint-angle curve dict
    (one value of shape_joint_curves_for_display's return dict), or returns
    None if the curve is unavailable.

    Factored out of ClinicianGUI._render_curves so the exact same
    Figure-building logic backs both the on-screen FigureCanvasTkAgg widget
    (U4) and U5's PDF export -- report_export.export_report_to_pdf reuses
    the same Figure objects ClinicianGUI._render_curves builds (via
    self._current_figures) rather than re-plotting from scratch (KTD2).

    No Tk dependency -- takes/returns plain matplotlib objects, so it's
    callable from tests without instantiating any widget.
    """
    if not curve.get("available"):
        return None

    figure = Figure(figsize=(3, 2.2), dpi=100)
    axis = figure.add_subplot(111)
    axis.plot(curve["x"], curve["mean"])
    if curve.get("sd"):
        mean_values = curve["mean"]
        sd_values = curve["sd"]
        axis.fill_between(
            curve["x"],
            [m - s for m, s in zip(mean_values, sd_values)],
            [m + s for m, s in zip(mean_values, sd_values)],
            alpha=0.2,
        )
    axis.set_xlabel("% gait cycle")
    axis.set_ylabel("deg")
    figure.tight_layout()
    return figure


class ClinicianGUI:
    """The persistent tkinter main window. Construction builds real Tk
    widgets, so tests must not instantiate this class -- they exercise
    validate_inputs() directly instead (see tests/test_clinician_gui_inputs.py
    and the plan's note that Tk widget rendering is a manual smoke check,
    not a unit test)."""

    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title("Clinician Trial Report")
        self._data_font = apply_design_system(self.root)

        self.session_dir = ""
        self.mvnx_path = ""
        self.last_result = None
        self.last_shaped = None
        self._pipeline_queue = None
        self._pipeline_thread = None
        self._results_frame = None
        self._tier_styles_ready = set()
        # U5: the same Figure objects built for on-screen display, keyed by
        # curve label (matching shaped_results["curves"]'s keys) -- reused
        # by the Export button's PDF export instead of re-plotting (KTD2).
        # Repopulated by _render_curves on every run; None for an
        # unavailable curve.
        self._current_figures = {}

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
        # Uses the same tier-low red as the confidence banner (_render_curves)
        # rather than a hardcoded "red" -- one error/warning color across the
        # window instead of two unrelated reds.
        ttk.Label(
            frame, textvariable=self.reason_var, foreground=TIER_COLORS["low"]["fg"], wraplength=400
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.run_button = ttk.Button(
            frame, text="Run", state="disabled", command=self._on_run_clicked,
            style="Primary.TButton",
        )
        self.run_button.grid(row=5, column=0, columnspan=2, pady=(10, 0))

        # U2: visible progress while the background pipeline thread runs
        # (R4/KTD4) -- separate from reason_var above, which only ever shows
        # why Run is currently disabled before a run starts.
        self.progress_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.progress_var, wraplength=400).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        # U5: only enabled once a result has been successfully rendered
        # (self.last_shaped/self.last_result set -- see _on_pipeline_result).
        self.export_button = ttk.Button(
            frame, text="Export to PDF", state="disabled", command=self._on_export_clicked,
            style="Primary.TButton",
        )
        self.export_button.grid(row=7, column=0, columnspan=2, pady=(6, 0))

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
        # Disable Export the moment a new run starts, not just while it's
        # in flight: if this run fails, last_shaped still points at a PRIOR
        # trial's results, and leaving Export enabled would let the
        # clinician export that stale report while believing it reflects
        # the trial they just attempted (found in code review). Export is
        # re-enabled only by this run's own success, in _on_pipeline_result.
        self.export_button.configure(state="disabled")
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
        # Re-enable Run (re-validated, in case inputs changed mid-run) now
        # that a result reached the queue (KTD4's Approach step 2).
        self._revalidate()

        # U4: shape the result for display and render it. Shaping failures
        # (e.g. a malformed .mot/.mvnx surviving long enough for the
        # pipeline stages to "succeed" but not this stage) are routed
        # through the same centralized mapper as every other caught failure
        # (KTD10) rather than crashing the GUI or showing a raw traceback.
        try:
            shaped = shape_results_for_display(result)
        except Exception as exc:  # noqa: BLE001 -- centralized mapping (KTD10) is the point here.
            self.progress_var.set("")
            messagebox.showerror("Could not display results", map_error_to_message(exc))
            return

        self.last_shaped = shaped
        self.progress_var.set("Done.")
        self._render_results(shaped)
        # U5: only enable Export once a result has actually been rendered
        # (self.last_shaped/self.last_result are both set at this point).
        self.export_button.configure(state="normal")

    def _on_pipeline_error(self, message):
        self.progress_var.set("")
        self._revalidate()
        messagebox.showerror("Run failed", message)

    # -- U5: one-action PDF export --------------------------------------

    def _on_export_clicked(self):
        # Defensive: the button is only enabled once last_shaped is set (see
        # _on_pipeline_result), but guard here too in case this is ever
        # wired to fire before that (e.g. a stray callback).
        if self.last_shaped is None:
            return

        trial_name = self.last_shaped["metadata"].get("trial_name") or "trial"
        save_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export report to PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            # The PDF carries real clinical data -- default to the session
            # directory the clinician is already reviewing, not an
            # arbitrary OS default location.
            initialdir=self.session_dir or None,
            initialfile=f"{trial_name}_report.pdf",
        )
        if not save_path:
            return

        report_export = _load_report_export()
        try:
            export_info = report_export.export_report_to_pdf(
                save_path, self.last_shaped, self._current_figures
            )
        # OSError (covers PermissionError): report_export.py's own docstring
        # says it never raises except for "an unwritable pdf_path" -- e.g. a
        # Windows PermissionError when the destination file is still open in
        # another program, a common re-export workflow. Without this it fell
        # through to the generic fallback message (found in code review).
        except OSError as exc:
            messagebox.showerror("Export failed", map_error_to_message(ReportExportError(str(exc))))
            return
        except Exception as exc:  # noqa: BLE001 -- centralized mapping (KTD10) is the point here.
            messagebox.showerror("Export failed", map_error_to_message(exc))
            return

        messagebox.showinfo(
            "Export complete", f"Report saved to:\n{export_info['pdf_path']}"
        )

    # -- U4: results review display (widget-building; Tk-only, no logic --
    # see the module-level shape_*_for_display functions above for the
    # actual data-shaping, which is what's unit-tested). ---------------

    def _tier_style_name(self, tier):
        style_name = f"Tier{tier}.TLabel"
        if style_name not in self._tier_styles_ready:
            colors = tier_colors(tier)
            # Tier chip label text uses the data font (small, monospace,
            # consistent with every other numeric/status readout in the
            # window) rather than the body serif -- per DESIGN.md's
            # component notes for confidence chips.
            ttk.Style().configure(
                style_name, background=colors["bg"], foreground=colors["fg"], font=self._data_font
            )
            self._tier_styles_ready.add(style_name)
        return style_name

    def _render_results(self, shaped):
        # Re-running a trial (KTD8: overwrites the prior trial's output)
        # should also replace the prior trial's displayed results, not stack
        # a second copy underneath it.
        if self._results_frame is not None:
            self._results_frame.destroy()

        self._results_frame = ttk.Frame(self.root, padding=12)
        self._results_frame.grid(row=1, column=0, sticky="nsew")

        # Reset per-run: re-running a trial (KTD8) rebuilds every curve's
        # Figure from scratch, so a stale Figure from a prior run is never
        # left behind for U5's export to pick up.
        self._current_figures = {}

        self._render_metadata(self._results_frame, shaped["metadata"])
        self._render_curves(self._results_frame, shaped["curves"], shaped["confidence"])
        self._render_metrics(self._results_frame, shaped["metrics"])

    def _render_metadata(self, parent, metadata):
        # Uppercased per DESIGN.md's section-header scale note ("12-13px
        # uppercase, letter-spacing ~0.06em") -- ttk has no letter-spacing
        # option, so casing is the one part of that rule tkinter can express
        # (found in code review).
        frame = ttk.LabelFrame(parent, text="TRIAL METADATA", padding=8)
        frame.grid(row=0, column=0, sticky="we", pady=(0, 8))

        rows = [
            ("Subject / session", metadata["subject_session_id"]),
            ("Trial", metadata["trial_name"]),
            ("Date", metadata["date"]),
            ("Duration", metadata["duration_display"]),
            ("Sensor coverage", metadata["sensor_coverage"]),
        ]
        for row_index, (label, value) in enumerate(rows):
            ttk.Label(frame, text=f"{label}:", style="Secondary.TLabel").grid(
                row=row_index, column=0, sticky="w"
            )
            ttk.Label(frame, text=str(value), style="Data.TLabel").grid(
                row=row_index, column=1, sticky="w", padx=(6, 0)
            )

    def _render_curves(self, parent, curves, confidence):
        frame = ttk.LabelFrame(parent, text="JOINT-ANGLE CURVES (% GAIT CYCLE)", padding=8)
        frame.grid(row=1, column=0, sticky="we", pady=(0, 8))

        row_offset = 0
        if not confidence.get("available", False):
            # Whole-trial confidence-unavailable: one banner, not N
            # per-segment tiles (U4 Approach step 4 / U3's no-data
            # fallback).
            ttk.Label(
                frame,
                text=confidence.get("banner", "Confidence indicator is not available."),
                foreground=TIER_COLORS["low"]["fg"],
                wraplength=620,
            ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
            row_offset = 1

        by_coordinate = confidence.get("by_coordinate", {})
        columns = 3
        for index, (label, curve) in enumerate(curves.items()):
            col = index % columns
            row = row_offset + (index // columns)
            cell = ttk.Frame(frame)
            cell.grid(row=row, column=col, padx=6, pady=6, sticky="n")
            ttk.Label(cell, text=label).pack()

            figure = build_curve_figure(curve)
            self._current_figures[label] = figure

            if figure is None:
                ttk.Label(cell, text="Not available", foreground="gray").pack()
                continue

            canvas = FigureCanvasTkAgg(figure, master=cell)
            canvas.draw()
            canvas.get_tk_widget().pack()

            tier_row = by_coordinate.get(curve["coordinate_name"])
            display_tier = tier_row["display_tier"] if tier_row else "not_scored"
            label_text = tier_row["label_text"] if tier_row else confidence_label_text("not_scored")
            ttk.Label(
                cell, text=label_text, style=self._tier_style_name(display_tier),
                wraplength=190, anchor="center",
            ).pack(fill="x", pady=(4, 0))

    def _render_metrics(self, parent, metrics):
        report_formatting = _load_report_formatting()
        frame = ttk.LabelFrame(parent, text="GAIT-CYCLE METRICS", padding=8)
        frame.grid(row=2, column=0, sticky="we")

        # Value columns (Right/Left/Symmetry) are right-aligned per
        # DESIGN.md's "value right-aligned (data font, tabular)" component
        # note -- headers align with their own column's values, not left
        # like the Metric label column (found in code review).
        headers = ["Metric", "Right", "Left", "Symmetry (R/L)"]
        header_sticky = ["w", "e", "e", "e"]
        for col, text in enumerate(headers):
            ttk.Label(frame, text=text, font=DESIGN_FONT_HEADER).grid(
                row=0, column=col, sticky=header_sticky[col], padx=4, pady=(0, 4)
            )

        for row_index, (name, row) in enumerate(metrics.items(), start=1):
            ttk.Label(frame, text=name.replace("_", " ")).grid(
                row=row_index, column=0, sticky="w", padx=4
            )
            ttk.Label(
                frame, text=report_formatting.format_metric_value(row["r"]), style="Data.TLabel"
            ).grid(row=row_index, column=1, sticky="e", padx=4)
            ttk.Label(
                frame, text=report_formatting.format_metric_value(row["l"]), style="Data.TLabel"
            ).grid(row=row_index, column=2, sticky="e", padx=4)
            ttk.Label(
                frame, text=report_formatting.format_symmetry_value(row["symmetry"]),
                style="Data.TLabel",
            ).grid(row=row_index, column=3, sticky="e", padx=4)


def main():
    app = ClinicianGUI()
    app.root.mainloop()


if __name__ == "__main__":
    main()
