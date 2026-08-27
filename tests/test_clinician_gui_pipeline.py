"""
Tests U2 of the clinician trial report GUI plan: background pipeline
execution (run_pipeline/start_pipeline_thread), progress reporting via
queue.Queue, and routing every failure through the centralized
map_error_to_message mapper.

Per KTD9, these tests never drive the real gait_analysis_UCM_fixed.gait_analysis
class through synthetic marker data -- they inject fake xsens_module/
gait_fixed_module/foot_progression_module modules into run_pipeline's own
dependency-injection seam instead, proving this GUI's orchestration,
error-mapping, and progress-reporting logic without needing real
gait-event peak detection (or a real OpenSim install) to succeed on fake
data.

Follows this repo's existing test convention (see
tests/test_clinician_gui_inputs.py, tests/test_xsens_to_opensim_source_selection.py):
load the module under test via importlib.util.spec_from_file_location, and
use monkeypatch.setitem(sys.modules, 'opensim', ...) (never raw assignment)
if opensim needs stubbing -- not actually needed here since every stage that
would import opensim is replaced by a fake module instead.
"""
import importlib.util
import json
import os
import queue
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('clinician_gui_pipeline_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def _resolve_paths_for(session_dir, trial_name="trial1"):
    return {
        "model_file": str(session_dir / "OpenSimData" / "Model" / "model.osim"),
        "results_dir": str(session_dir / "OpenSimData" / "Kinematics"),
        "output_motion_filename": f"{trial_name}.mot",
        "trc_path": str(session_dir / "MarkerData" / f"{trial_name}.trc"),
        "sto_path": str(session_dir / "OpenSimData" / "Kinematics" / f"{trial_name}_orientations.sto"),
    }


def _make_fake_xsens_module(resolve_paths=None, resolve_error=None, build_error=None,
                             sleep_before_calibrate=0.0, write_trc_error=None,
                             calibrate_error=None, run_imu_ik_error=None):
    calls = {"build_orientations_sto": [], "calibrate_model": [], "run_imu_ik": [], "write_markers_trc": []}

    def resolve_session_output_paths(session_dir, trial_name):
        if resolve_error is not None:
            raise resolve_error
        return resolve_paths

    def build_orientations_sto(mvnx_path, sto_path, segment_to_imu_frame, source="segment"):
        calls["build_orientations_sto"].append((mvnx_path, sto_path, source))
        if build_error is not None:
            raise build_error

    def calibrate_model(model_file, sto_path, base_imu_label, base_heading_axis):
        if sleep_before_calibrate:
            time.sleep(sleep_before_calibrate)
        calls["calibrate_model"].append((model_file, sto_path, base_imu_label, base_heading_axis))
        if calibrate_error is not None:
            raise calibrate_error
        return str(Path(model_file).with_name(Path(model_file).stem + "_calibrated.osim"))

    def run_imu_ik(calibrated_model_file, orientations_sto, start_time, end_time,
                   results_dir, output_motion_filename=None):
        calls["run_imu_ik"].append(
            (calibrated_model_file, orientations_sto, start_time, end_time, results_dir, output_motion_filename)
        )
        if run_imu_ik_error is not None:
            raise run_imu_ik_error
        return str(Path(results_dir) / (output_motion_filename or "ik.mot"))

    def write_markers_trc(calibrated_model_file, mot_file, trc_path):
        # The parent-dir-exists contract (run_pipeline's mkdir, per
        # xsens_to_opensim.py's own main() pattern) is checked by the caller
        # test itself, not here -- asserting inside a fake gets caught by
        # run_pipeline's own except-and-wrap and surfaces as a confusing
        # MarkerExportError instead of a clean AssertionError.
        calls["write_markers_trc"].append((calibrated_model_file, mot_file, trc_path))
        if write_trc_error is not None:
            raise write_trc_error

    return types.SimpleNamespace(
        resolve_session_output_paths=resolve_session_output_paths,
        build_orientations_sto=build_orientations_sto,
        calibrate_model=calibrate_model,
        run_imu_ik=run_imu_ik,
        write_markers_trc=write_markers_trc,
        SEGMENT_TO_IMU_FRAME={},
        _calls=calls,
    )


def _make_fake_foot_progression_module(fpa_r=None, fpa_l=None):
    calls = []

    def compute_foot_progression_angles(session_dir, trial_name):
        calls.append((session_dir, trial_name))
        return (fpa_r if fpa_r is not None else [0.0, 0.0],
                fpa_l if fpa_l is not None else [0.0, 0.0])

    return types.SimpleNamespace(
        compute_foot_progression_angles=compute_foot_progression_angles, _calls=calls
    )


def _make_fake_gait_fixed_module(raise_exc=None):
    calls = []

    class _FakeGaitAnalysis:
        def __init__(self, session_dir, trial_name, fpa_r, fpa_l, leg='auto',
                     allow_manual_entry=True, modelName=None, **kwargs):
            calls.append({
                "session_dir": session_dir,
                "trial_name": trial_name,
                "leg": leg,
                "allow_manual_entry": allow_manual_entry,
                "modelName": modelName,
            })
            if raise_exc is not None:
                raise raise_exc
            self.leg = leg

    return types.SimpleNamespace(gait_analysis=_FakeGaitAnalysis, _calls=calls)


def _drain_all(result_queue):
    messages = []
    while True:
        try:
            messages.append(result_queue.get_nowait())
        except queue.Empty:
            break
    return messages


# ---------------------------------------------------------------------------
# Valid run: all stages complete, both leg instantiations happen, a result
# object reaches the queue.
# ---------------------------------------------------------------------------

def test_valid_run_completes_both_legs_and_result_reaches_queue(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths)
    fake_fp = _make_fake_foot_progression_module()
    fake_gait = _make_fake_gait_fixed_module()

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue,
        xsens_module=fake_xsens, gait_fixed_module=fake_gait, foot_progression_module=fake_fp,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    messages = _drain_all(result_queue)
    kinds = [kind for kind, _payload in messages]

    assert "error" not in kinds
    assert kinds[-1] == "result"
    assert kinds.count("progress") >= 1

    result_payload = messages[-1][1]
    assert result_payload["model_file"] == resolve_paths["model_file"]
    assert result_payload["trial_name"] == "trial1"
    assert result_payload["gait_r"] is not None
    assert result_payload["gait_l"] is not None

    # Found in code review: gait_analysis's constructor unconditionally
    # loads MarkerData/<trial>.trc, so a valid run must actually write it
    # (via write_markers_trc) before either gait_analysis instantiation --
    # not just leave resolve_session_output_paths's trc_path unused.
    assert len(fake_xsens._calls["write_markers_trc"]) == 1
    calibrated_model_arg, _mot_file_arg, trc_path_arg = fake_xsens._calls["write_markers_trc"][0]
    assert calibrated_model_arg.endswith("_calibrated.osim")  # the calibrated model, not the raw one
    assert trc_path_arg == resolve_paths["trc_path"]
    assert Path(trc_path_arg).parent.is_dir()

    assert len(fake_gait._calls) == 2, "expected exactly two gait_analysis instantiations (leg='r' and leg='l')"
    legs = {call["leg"] for call in fake_gait._calls}
    assert legs == {"r", "l"}
    for call in fake_gait._calls:
        assert call["allow_manual_entry"] is False
        assert call["modelName"] == "model.osim"
        assert call["trial_name"] == "trial1"


# ---------------------------------------------------------------------------
# Missing .osim -> centralized mapper's message reaches the queue, not a raw
# exception. Covers AE1.
# ---------------------------------------------------------------------------

def test_missing_osim_maps_to_readable_error_on_queue(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")

    model_dir = session_dir / "OpenSimData" / "Model"
    fake_xsens = _make_fake_xsens_module(
        resolve_error=ValueError(
            f"{model_dir}: expected exactly one .osim file for model auto-discovery, found 0 ([])."
        )
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue, xsens_module=fake_xsens,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    messages = _drain_all(result_queue)
    assert len(messages) == 1
    kind, payload = messages[0]
    assert kind == "error"
    assert isinstance(payload, str)
    assert "OpenSim model" in payload
    assert ".osim" in payload
    assert "Traceback" not in payload


# ---------------------------------------------------------------------------
# Malformed .mvnx -> the mapper's specific, readable error message reaches
# the queue. Covers AE1.
# ---------------------------------------------------------------------------

def test_malformed_mvnx_maps_to_readable_error_on_queue(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("not valid xml <<<")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(
        resolve_paths=resolve_paths,
        build_error=ValueError(
            f"{mvnx_path}: root element is <bogus>, expected <mvnx> or <frames> -- "
            "is this really an .mvnx export?"
        ),
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue, xsens_module=fake_xsens,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    messages = _drain_all(result_queue)
    error_messages = [payload for kind, payload in messages if kind == "error"]
    assert len(error_messages) == 1
    payload = error_messages[0]
    assert ".mvnx" in payload
    assert "could not be read" in payload
    assert "Traceback" not in payload


# ---------------------------------------------------------------------------
# An .mvnx that becomes unreadable (deleted/permission error) between
# validate_inputs' check and the Run click also maps to the same specific
# .mvnx-could-not-be-read message, not the generic fallback (found in code
# review: the original except clause only caught ValueError/ET.ParseError).
# ---------------------------------------------------------------------------

def test_mvnx_becoming_unreadable_maps_to_the_same_specific_error(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(
        resolve_paths=resolve_paths,
        build_error=FileNotFoundError(f"[Errno 2] No such file or directory: '{mvnx_path}'"),
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue, xsens_module=fake_xsens,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    error_messages = [payload for kind, payload in _drain_all(result_queue) if kind == "error"]
    assert len(error_messages) == 1
    assert "could not be read" in error_messages[0]
    assert "Traceback" not in error_messages[0]


# ---------------------------------------------------------------------------
# write_markers_trc raising -> its own specific, readable message reaches
# the queue, not the generic "unexpected error" fallback or a misleading
# gait-event-detection message (found in code review: run_pipeline never
# ran this stage at all before, so every real trial would have crashed
# inside gait_analysis's constructor with a raw, unmapped FileNotFoundError).
# ---------------------------------------------------------------------------

def test_marker_export_failure_maps_to_its_own_specific_error_not_gait_analysis(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(
        resolve_paths=resolve_paths,
        write_trc_error=RuntimeError("model has no markers -- can't write a .trc."),
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue, xsens_module=fake_xsens,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    error_messages = [payload for kind, payload in _drain_all(result_queue) if kind == "error"]
    assert len(error_messages) == 1
    payload = error_messages[0]
    assert "marker" in payload.lower()
    # Must NOT be mislabeled as a gait-event-detection failure -- that message
    # actively misdirects the clinician toward re-recording, which doesn't fix this.
    assert "gait-event" not in payload.lower()
    assert "unexpected error" not in payload.lower()
    assert "Traceback" not in payload


# ---------------------------------------------------------------------------
# calibrate_model/run_imu_ik raising -> ImuKinematicsError's own specific
# message reaches the queue, not the generic "unexpected error" fallback
# (found in code review: unlike every other stage, these two had no
# dedicated wrapping at all).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"calibrate_error": RuntimeError("base IMU label 'pelvis_imu' not found.")},
    {"run_imu_ik_error": RuntimeError("inverse kinematics failed to converge.")},
])
def test_imu_kinematics_failure_maps_to_its_own_specific_error(mod, tmp_path, kwargs):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths, **kwargs)

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue, xsens_module=fake_xsens,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    error_messages = [payload for kind, payload in _drain_all(result_queue) if kind == "error"]
    assert len(error_messages) == 1
    payload = error_messages[0]
    assert "calibrate" in payload.lower() or "inverse kinematics" in payload.lower()
    assert "unexpected error" not in payload.lower()
    assert "Traceback" not in payload


# ---------------------------------------------------------------------------
# compute_foot_progression_angles raising (it runs a real osim.AnalyzeTool
# pass per the plan's own Risks section) -> its own specific, readable
# message reaches the queue, not the generic "unexpected error" fallback
# (found in code review: this call wasn't wrapped at all before).
# ---------------------------------------------------------------------------

def test_foot_progression_angle_failure_maps_to_its_own_specific_error(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths)

    def _raising_compute_foot_progression_angles(session_dir, trial_name):
        raise RuntimeError("AnalyzeTool failed: no valid gait cycle found in this trial.")

    fake_fp = types.SimpleNamespace(
        compute_foot_progression_angles=_raising_compute_foot_progression_angles
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue,
        xsens_module=fake_xsens, foot_progression_module=fake_fp,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()

    error_messages = [payload for kind, payload in _drain_all(result_queue) if kind == "error"]
    assert len(error_messages) == 1
    payload = error_messages[0]
    assert "foot progression" in payload.lower()
    assert "unexpected error" not in payload.lower()
    assert "Traceback" not in payload


# ---------------------------------------------------------------------------
# gait_analysis_UCM_fixed raising under allow_manual_entry=False (mocked,
# per KTD9) -> a readable message reaches the queue instead of a hang.
# ---------------------------------------------------------------------------

def test_gait_analysis_failure_maps_to_readable_error_not_a_hang(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths)
    fake_fp = _make_fake_foot_progression_module()
    fake_gait = _make_fake_gait_fixed_module(
        raise_exc=Exception(
            "Automatic gait-event detection failed and manual entry is disabled "
            "(allow_manual_entry=False)."
        )
    )

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue,
        xsens_module=fake_xsens, gait_fixed_module=fake_gait, foot_progression_module=fake_fp,
    )
    thread.join(timeout=10)
    assert not thread.is_alive(), "pipeline thread must terminate, not hang, when gait_analysis raises"

    messages = _drain_all(result_queue)
    kinds = [kind for kind, _payload in messages]
    assert "result" not in kinds
    error_messages = [payload for kind, payload in messages if kind == "error"]
    assert len(error_messages) == 1
    assert "gait" in error_messages[0].lower()
    assert "Traceback" not in error_messages[0]


# ---------------------------------------------------------------------------
# No API_TOKEN set in the OS environment -> importing clinician_gui.py (which
# every later import reaching utils.py depends on) never prompts
# interactively. Covers AE2. Run in a subprocess with API_TOKEN removed and
# stdin closed, under a timeout, so a regression here fails fast rather than
# hanging the test suite or risking a real getpass/network prompt.
# ---------------------------------------------------------------------------

def test_no_api_token_in_environment_sets_placeholder_without_prompting():
    env = os.environ.copy()
    env.pop("API_TOKEN", None)

    script = (
        "import sys\n"
        f"sys.path.insert(0, {REPO_ROOT!r})\n"
        "import clinician_gui\n"
        "import os\n"
        "token = os.environ.get('API_TOKEN')\n"
        "assert token, 'clinician_gui import did not set a placeholder API_TOKEN'\n"
        "print('OK:' + token)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip().startswith("OK:")


# ---------------------------------------------------------------------------
# A slow stage posts a progress message before the final result, and (via
# drain_queue's dispatch, which ClinicianGUI wires the Run button's
# disabled/enabled state to) the terminal message doesn't arrive until the
# slow stage actually finishes. Covers AE4.
# ---------------------------------------------------------------------------

def test_slow_stage_posts_progress_before_final_result(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)

    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths, sleep_before_calibrate=0.4)
    fake_fp = _make_fake_foot_progression_module()
    fake_gait = _make_fake_gait_fixed_module()

    result_queue = queue.Queue()
    thread = mod.start_pipeline_thread(
        str(session_dir), str(mvnx_path), result_queue,
        xsens_module=fake_xsens, gait_fixed_module=fake_gait, foot_progression_module=fake_fp,
    )

    # First progress message: posted right before build_orientations_sto.
    kind1, _payload1 = result_queue.get(timeout=2)
    assert kind1 == "progress"

    # Second progress message: posted right before calibrate_model, which
    # then sleeps for 0.4s in this fake -- proves the background thread is
    # still running (KTD4) and progress is delivered incrementally, not
    # merely correctly ordered after the fact.
    kind2, payload2 = result_queue.get(timeout=2)
    assert kind2 == "progress"
    assert "calibrat" in payload2.lower()

    # Nothing else should be queued yet -- calibrate_model is still asleep.
    with pytest.raises(queue.Empty):
        result_queue.get_nowait()

    thread.join(timeout=10)
    assert not thread.is_alive()

    remaining = _drain_all(result_queue)
    assert remaining, "expected further progress/result messages once the slow stage completed"
    assert remaining[-1][0] == "result", "the terminal message must be the final item on the queue"


# ---------------------------------------------------------------------------
# The Run control's disabled/enabled wiring: proven via drain_queue's plain
# callback dispatch (no Tk widgets instantiated), matching the plan's note
# that Tk rendering itself is a manual smoke check.
# ---------------------------------------------------------------------------

def test_drain_queue_keeps_run_disabled_until_a_terminal_message(mod):
    result_queue = queue.Queue()
    state = {"run_enabled": False}

    def on_progress(_message):
        pass

    def on_result(_payload):
        state["run_enabled"] = True

    def on_error(_message):
        state["run_enabled"] = True

    result_queue.put(("progress", "Starting..."))
    result_queue.put(("progress", "Still going..."))
    terminal = mod.drain_queue(result_queue, on_progress, on_result, on_error)
    assert terminal is False
    assert state["run_enabled"] is False

    result_queue.put(("result", {"ok": True}))
    terminal = mod.drain_queue(result_queue, on_progress, on_result, on_error)
    assert terminal is True
    assert state["run_enabled"] is True


# -- Non-gait guardrail reaches the clinician correctly (2026-08-25) -----
# gait_analysis_UCM_fixed now raises NonGaitTrialError when a trial segments
# but is not walking. Without dedicated handling that fell through
# run_pipeline's generic `except Exception` into GaitAnalysisFailedError,
# whose headline tells the clinician to "try a longer or cleaner recording"
# -- actively wrong advice, since re-recording the same transfer will be
# rejected again for the same reason.


def _make_fake_gait_module_that_rejects_non_gait(message):
    """Mirrors the real module's shape: the exception class hangs off the
    module, because clinician_gui loads it by path at runtime and cannot
    import the class at module level."""
    class NonGaitTrialError(Exception):
        pass

    class _FakeGaitAnalysis:
        def __init__(self, *args, **kwargs):
            raise NonGaitTrialError(message)

    return types.SimpleNamespace(
        gait_analysis=_FakeGaitAnalysis, NonGaitTrialError=NonGaitTrialError
    )


def _run_pipeline_expecting_error(mod, tmp_path, fake_gait):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fake_xsens = _make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir))
    with pytest.raises(Exception) as caught:
        mod.run_pipeline(
            str(session_dir), str(mvnx_path),
            xsens_module=fake_xsens, gait_fixed_module=fake_gait,
            foot_progression_module=_make_fake_foot_progression_module(),
        )
    return caught.value


def test_non_gait_rejection_maps_to_its_own_error_not_generic_gait_failure(mod, tmp_path):
    detail = "Trial rejected: only 1 heel strike(s) detected on the less-covered leg"
    fake_gait = _make_fake_gait_module_that_rejects_non_gait(detail)

    exc = _run_pipeline_expecting_error(mod, tmp_path, fake_gait)

    assert isinstance(exc, mod.NonGaitTrialRejectedError)
    assert not isinstance(exc, mod.GaitAnalysisFailedError)
    assert detail in str(exc)


def test_non_gait_message_does_not_tell_the_clinician_to_re_record(mod):
    """The specific regression this fix exists for. Re-recording the same
    transfer produces the same rejection, so that advice wastes a session."""
    message = mod.map_error_to_message(
        mod.NonGaitTrialRejectedError("Trial rejected: only 1 heel strike(s)")
    )

    assert "longer or cleaner recording" not in message
    assert "will not change this result" in message
    assert "three full gait cycles" in message


def test_a_gait_module_without_the_error_class_still_maps_to_generic_failure(mod, tmp_path):
    """Backward compatibility: run_pipeline pulls NonGaitTrialError off the
    loaded module, so a module that predates it (or a test fake without it)
    must keep working rather than raising AttributeError."""
    fake_gait = _make_fake_gait_fixed_module(raise_exc=Exception("detection failed"))

    exc = _run_pipeline_expecting_error(mod, tmp_path, fake_gait)

    assert isinstance(exc, mod.GaitAnalysisFailedError)


# -- Raw file outputs surfaced to the user (2026-08-25) -------------------
# run_pipeline already computes the .trc and .sto paths but discarded them,
# returning only mot_path. Researchers need the raw files to take into their
# own analysis, so every artefact the run produced is now reported.


def test_run_pipeline_reports_every_file_it_wrote(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)
    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths)

    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=fake_xsens,
        gait_fixed_module=_make_fake_gait_fixed_module(),
        foot_progression_module=_make_fake_foot_progression_module(),
    )

    for key in ("mot_path", "trc_path", "sto_path", "model_file"):
        assert key in result, f"{key} missing from run_pipeline's result"
        assert result[key], f"{key} is empty"


def test_reported_paths_are_the_ones_the_pipeline_actually_used(mod, tmp_path):
    """Recomputing paths for display instead of returning the ones written to
    would drift silently the moment resolve_session_output_paths changes."""
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    resolve_paths = _resolve_paths_for(session_dir)
    fake_xsens = _make_fake_xsens_module(resolve_paths=resolve_paths)

    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=fake_xsens,
        gait_fixed_module=_make_fake_gait_fixed_module(),
        foot_progression_module=_make_fake_foot_progression_module(),
    )

    assert result["trc_path"] == resolve_paths["trc_path"]
    assert result["sto_path"] == resolve_paths["sto_path"]


# -- Gait-cycle curve matrix, the input UCM and GDI actually consume --------
# The .mot is a raw time series over the whole trial. UCM and GDI need the
# stride-normalised matrix: (n_coordinates x 101) rows by one column per gait
# cycle. run_pipeline held the gait_analysis objects that can produce it but
# never built it, so the GUI could not deliver the file the analysis needs.


def _fake_gait_module_with_curves(n_cycles=4):
    class _FakeGaitAnalysis:
        def __init__(self, session_dir, trial_name, fpa_r, fpa_l, leg='auto', **kwargs):
            self.leg = leg

        def get_coordinates_normalized_time(self):
            return {"indiv": [{} for _ in range(n_cycles)], "mean": {}}

    return types.SimpleNamespace(gait_analysis=_FakeGaitAnalysis)


def _fake_fp_module_with_export(recorder):
    def compute_foot_progression_angles(session_dir, trial_name):
        return [0.0, 0.0], [0.0, 0.0]

    def export_individual_curves_csv(results, save_path, subject_id, trial_name):
        recorder.append({"results": results, "save_path": str(save_path),
                         "subject_id": subject_id, "trial_name": trial_name})
        right = Path(save_path) / f"{subject_id}-{trial_name}_right.csv"
        left = Path(save_path) / f"{subject_id}-{trial_name}_left.csv"
        for path in (right, left):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("0.0\n")
        return str(right), str(left)

    return types.SimpleNamespace(
        compute_foot_progression_angles=compute_foot_progression_angles,
        export_individual_curves_csv=export_individual_curves_csv,
    )


def _run_with_curve_export(mod, tmp_path, recorder):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fake_xsens = _make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir))
    return mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=fake_xsens,
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=_fake_fp_module_with_export(recorder),
    )


def test_run_pipeline_exports_the_gait_cycle_curve_matrix(mod, tmp_path):
    recorder = []

    result = _run_with_curve_export(mod, tmp_path, recorder)

    assert recorder, "export_individual_curves_csv was never called"
    assert result["curves_matrix_r_path"].endswith("_right.csv")
    assert result["curves_matrix_l_path"].endswith("_left.csv")
    assert Path(result["curves_matrix_r_path"]).is_file()


def test_exported_matrix_is_built_from_both_legs_normalised_curves(mod, tmp_path):
    """Both legs must be passed through -- an earlier version of the upstream
    exporter computed curves_l and then only ever saved the right leg."""
    recorder = []

    _run_with_curve_export(mod, tmp_path, recorder)

    passed = recorder[0]["results"]
    assert "curves_r" in passed and "curves_l" in passed
    assert len(passed["curves_r"]["indiv"]) == 4


def test_curve_matrix_appears_in_the_reported_output_files(mod, tmp_path):
    """It is the file a researcher actually needs for UCM/GDI, so it has to be
    listed alongside the .mot and .trc rather than written silently."""
    recorder = []
    result = _run_with_curve_export(mod, tmp_path, recorder)

    labels = {e["label"] for e in mod.shape_output_files_for_display(result)}

    assert any("curve matrix" in label.lower() for label in labels), labels


def test_curve_export_failure_does_not_lose_the_rest_of_the_run(mod, tmp_path):
    """The matrix is the last stage. If it fails, the joint angles, markers and
    gait metrics are all still valid and must still be returned."""
    def exploding_export(*args, **kwargs):
        raise RuntimeError("disk full")

    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fp = _fake_fp_module_with_export([])
    fp.export_individual_curves_csv = exploding_export

    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=_make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir)),
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=fp,
    )

    assert result["mot_path"]
    assert result.get("curves_matrix_r_path") is None


def test_curve_matrix_filename_uses_a_short_session_id(mod, tmp_path):
    """The exporter names files '<subject_id>-<trial>_side.csv'. Passing the
    whole session folder produced a 60-character name embedding the full
    session UUID -- unwieldy, and it puts the session ID into a file that gets
    shared. A short traceable prefix is enough."""
    recorder = []
    # A realistic session folder -- the tmp fixture's "OpenCapData_test" is
    # already short and could never have caught this.
    session_dir = tmp_path / "OpenCapData_ca505b02-a59a-4f35-836f-f211475f18b8"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=_make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir)),
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=_fake_fp_module_with_export(recorder),
    )

    name = Path(result["curves_matrix_r_path"]).name
    assert len(name) < 40, f"filename is unwieldy: {name}"
    assert "trial1" in name
    assert "ca505b02" in name, "should still trace back to the session"


# -- XtoO as a selectable conversion route (2026-08-25) -------------------
# Two ways to get from .mvnx to a .mot: OpenSense IK on segment orientations,
# or XtoO's direct remapping of Xsens's own joint angles. They differ in what
# they can produce -- the IK route pins root translation, freezes the toes and
# saturates the arms -- so the route has to be a user choice, and the report
# has to say which one produced its numbers.


def _make_fake_xtoo_module(recorder):
    def convert_mvnx_to_mot(mvnx_path, mot_path, legacy_axes=False):
        recorder.append({"mvnx": str(mvnx_path), "mot": str(mot_path),
                         "legacy_axes": legacy_axes})
        Path(mot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(mot_path).write_text("Coordinates\nendheader\ntime\n0.0\n")
        return str(mot_path)

    return types.SimpleNamespace(convert_mvnx_to_mot=convert_mvnx_to_mot)


def _run_route(mod, tmp_path, conversion, xtoo_recorder=None):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fake_xsens = _make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir))
    kwargs = {}
    if xtoo_recorder is not None:
        kwargs["xtoo_module"] = _make_fake_xtoo_module(xtoo_recorder)
    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        conversion=conversion,
        xsens_module=fake_xsens,
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=_fake_fp_module_with_export([]),
        **kwargs,
    )
    return result, fake_xsens


def test_ik_remains_the_default_route(mod, tmp_path):
    result, fake_xsens = _run_route(mod, tmp_path, conversion=None)

    assert fake_xsens._calls["run_imu_ik"], "default must still run inverse kinematics"
    assert result["conversion"] == "ik"


def test_xtoo_route_skips_calibration_and_inverse_kinematics(mod, tmp_path):
    """The whole point: no IMUPlacer, no IK, no model solve. Calling them
    anyway would waste ~40 s per trial and reintroduce the pinned root."""
    recorder = []
    _result, fake_xsens = _run_route(mod, tmp_path, "xtoo", xtoo_recorder=recorder)

    assert recorder, "xtoo.convert_mvnx_to_mot was never called"
    assert not fake_xsens._calls["calibrate_model"]
    assert not fake_xsens._calls["run_imu_ik"]
    assert not fake_xsens._calls["build_orientations_sto"]


def test_xtoo_route_still_writes_markers_for_the_gait_stage(mod, tmp_path):
    """gait_analysis loads MarkerData/<trial>.trc unconditionally, so the .trc
    is required whichever route produced the .mot."""
    recorder = []
    _result, fake_xsens = _run_route(mod, tmp_path, "xtoo", xtoo_recorder=recorder)

    assert fake_xsens._calls["write_markers_trc"]


def test_xtoo_route_uses_the_uncalibrated_model_for_markers(mod, tmp_path):
    """There is no calibrated model on this route -- nothing calibrated one.
    Passing a non-existent '_calibrated.osim' would fail at the marker stage."""
    recorder = []
    _result, fake_xsens = _run_route(mod, tmp_path, "xtoo", xtoo_recorder=recorder)

    model_used = fake_xsens._calls["write_markers_trc"][0][0]
    assert "_calibrated" not in str(model_used)


def test_route_is_reported_in_the_result(mod, tmp_path):
    recorder = []
    result, _ = _run_route(mod, tmp_path, "xtoo", xtoo_recorder=recorder)

    assert result["conversion"] == "xtoo"


def test_unknown_route_is_rejected_rather_than_silently_defaulting(mod, tmp_path):
    """Silently falling back to IK would produce a pinned-root report while
    the user believed they had asked for real translation."""
    with pytest.raises(ValueError, match="unknown conversion"):
        _run_route(mod, tmp_path, "magic")


def test_provenance_reflects_the_route_that_actually_ran(mod, tmp_path):
    """The spatial caveat is true for IK and false for XtoO. Stamping the IK
    disclaimer onto an XtoO report would understate data that is genuinely
    displacement-derived; the reverse would be far worse."""
    ik = mod.spatial_provenance_for("ik")
    xtoo = mod.spatial_provenance_for("xtoo")

    assert ik["spatial_displacement_validated"] is False
    assert "Pinned root" in ik["translation_type"]
    assert xtoo["spatial_displacement_validated"] is True
    assert "Pinned root" not in xtoo["translation_type"]
    assert "proxy" not in xtoo["gait_speed_method"].lower()


# -- Combined session matrix from the GUI (2026-08-26) --------------------
# The GUI processes one trial at a time, so the per-trial matrices accumulate
# in the session's GaitCurves folder. Every run now also rebuilds the combined
# matrix across everything processed so far -- which is what a pooled analysis
# actually consumes, and what previously only existed by running a script.


def _fake_combine_module(recorder, fail=None):
    def combine_session(curve_dir, out_dir, name="combined", prefix=None,
                        sides=("right", "left"), on_duplicate="error"):
        if fail is not None:
            raise fail
        recorder.append({"curve_dir": str(curve_dir), "out_dir": str(out_dir),
                         "name": name, "prefix": prefix, "on_duplicate": on_duplicate})
        written = {}
        for side in sides:
            path = Path(out_dir) / f"{name}_{side}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("0.0\n")
            written[side] = {"matrix_path": str(path),
                             "index_path": str(path.with_name(f"{path.stem}_index.csv")),
                             "rows": 3838, "strides": 9, "trials": 2}
        return written

    return types.SimpleNamespace(combine_session=combine_session)


def _run_with_combine(mod, tmp_path, recorder, fail=None):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    return mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=_make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir)),
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=_fake_fp_module_with_export([]),
        combine_module=_fake_combine_module(recorder, fail=fail),
    )


def test_every_run_rebuilds_the_combined_session_matrix(mod, tmp_path):
    recorder = []

    result = _run_with_combine(mod, tmp_path, recorder)

    assert recorder, "combine_session was never called"
    assert result["combined_matrix_r_path"].endswith("_right.csv")
    assert result["combined_matrix_l_path"].endswith("_left.csv")


def test_combining_reads_the_sessions_own_curve_folder(mod, tmp_path):
    """Pooling must draw on the trials processed for THIS session, not a
    batch directory that may hold other participants or other routes."""
    recorder = []

    _run_with_combine(mod, tmp_path, recorder)

    assert recorder[0]["curve_dir"].endswith("GaitCurves")
    assert "OpenCapData_test" in recorder[0]["curve_dir"]


def test_combining_refuses_duplicates_rather_than_double_counting(mod, tmp_path):
    """A stale export from a naming change holds the same strides under a
    different filename. Silently dropping one is the wrong default when the
    alternative is a pool that counts a trial twice."""
    recorder = []

    _run_with_combine(mod, tmp_path, recorder)

    assert recorder[0]["on_duplicate"] == "error"


def test_a_failed_combine_does_not_lose_the_run(mod, tmp_path):
    """Combining is the last stage. If it fails -- most likely because a
    duplicate was found -- the joint angles, markers, metrics and this trial's
    own curve matrix are all still valid and must still be returned."""
    result = _run_with_combine(mod, tmp_path, [], fail=ValueError("same strides"))

    assert result["mot_path"]
    assert result["curves_matrix_r_path"]
    assert result.get("combined_matrix_r_path") is None


def test_the_combined_matrix_is_listed_in_the_output_files(mod, tmp_path):
    recorder = []
    result = _run_with_combine(mod, tmp_path, recorder)

    labels = {e["label"] for e in mod.shape_output_files_for_display(result)}

    assert any("combined" in label.lower() for label in labels), labels


def test_combine_still_runs_when_the_per_trial_export_failed(mod, tmp_path):
    """Stage 5 binds the curves directory inside its own try block. Reusing
    that binding meant a failed per-trial export left it undefined, so the
    combine stage reported a NameError instead of the real cause."""
    recorder = []
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_path = tmp_path / "trial1.mvnx"
    mvnx_path.write_text("<mvnx/>")
    fp = _fake_fp_module_with_export([])
    fp.export_individual_curves_csv = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))

    result = mod.run_pipeline(
        str(session_dir), str(mvnx_path),
        xsens_module=_make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir)),
        gait_fixed_module=_fake_gait_module_with_curves(),
        foot_progression_module=fp,
        combine_module=_fake_combine_module(recorder),
    )

    assert result.get("curves_matrix_r_path") is None      # stage 5 failed
    assert recorder, "stage 6 must still attempt to combine"
    assert result["combined_matrix_r_path"]


# -- Route is encoded in the filenames (2026-08-26) -----------------------
# Both conversion routes write per-trial curve files into the same session
# folder. Without the route in the name they are indistinguishable, so
# running one trial through IK and the next through direct remapping pools
# two incompatible kinematic sources into one matrix -- silently, with the
# right shape. The routes differ in exactly the coordinates a synergy or GDI
# analysis reads.


def test_per_trial_curve_filename_records_the_route(mod, tmp_path):
    recorder = []
    result = _run_with_combine(mod, tmp_path, recorder)

    name = Path(result["curves_matrix_r_path"]).name
    assert "ik" in name.split("-"), f"route missing from {name}"


def test_the_two_routes_produce_different_filenames(mod, tmp_path):
    """The whole point: an IK trial and a direct-remapping trial must not
    collide, and must not look alike to the pooling step."""
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
    ik = _run_route(mod, tmp_path / "a", conversion="ik")[0]
    xtoo = _run_route(mod, tmp_path / "b", conversion="xtoo", xtoo_recorder=[])[0]

    ik_name = Path(ik["curves_matrix_r_path"]).name
    xtoo_name = Path(xtoo["curves_matrix_r_path"]).name
    assert ik_name != xtoo_name
    assert "xtoo" in xtoo_name and "xtoo" not in ik_name


def test_pooling_is_restricted_to_one_route(mod, tmp_path):
    """combine_session is asked for a prefix, so a folder holding both routes
    yields one combined file per route rather than one mixed file."""
    recorder = []
    _run_with_combine(mod, tmp_path, recorder)

    assert recorder[0]["prefix"] is not None
    assert "ik" in recorder[0]["prefix"]


def test_combined_filename_records_the_route_too(mod, tmp_path):
    recorder = []
    result = _run_with_combine(mod, tmp_path, recorder)

    assert "ik" in Path(result["combined_matrix_r_path"]).name


# -- Batch: process a whole folder of trials (2026-08-26) -----------------
# One trial at a time meant fifteen runs of ~50 s each to build a session.
# run_batch iterates the folder and pools once at the end.


def _batch_env(tmp_path, n_trials=3):
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_dir = tmp_path / "mvnx"
    mvnx_dir.mkdir()
    for n in range(1, n_trials + 1):
        (mvnx_dir / f"CK-{n:03d}.mvnx").write_text("<mvnx/>")
    return session_dir, mvnx_dir


def _batch_modules(tmp_path, session_dir, recorder, fail_on=None):
    class _Gait:
        def __init__(self, session, trial, fpa_r, fpa_l, leg='auto', **kw):
            if fail_on and trial in fail_on:
                raise RuntimeError(f"no gait events in {trial}")
            self.leg = leg

        def get_coordinates_normalized_time(self):
            return {"indiv": [{}, {}, {}, {}], "mean": {}}

    return {
        "xsens_module": _make_fake_xsens_module(resolve_paths=_resolve_paths_for(session_dir)),
        "gait_fixed_module": types.SimpleNamespace(gait_analysis=_Gait),
        "foot_progression_module": _fake_fp_module_with_export([]),
        "combine_module": _fake_combine_module(recorder),
    }


def test_batch_processes_every_mvnx_in_the_folder(mod, tmp_path):
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=3)
    recorder = []

    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           **_batch_modules(tmp_path, session_dir, recorder))

    assert [t["trial"] for t in result["trials"]] == ["CK-001", "CK-002", "CK-003"]
    assert result["succeeded"] == 3


def test_batch_pools_once_at_the_end_not_per_trial(mod, tmp_path):
    """Rebuilding the combined matrix after every trial would be N times the
    work for the same answer, and only the last one survives anyway."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=4)
    recorder = []

    mod.run_batch(str(session_dir), str(mvnx_dir),
                  **_batch_modules(tmp_path, session_dir, recorder))

    assert len(recorder) == 1


def test_one_failing_trial_does_not_abandon_the_rest(mod, tmp_path):
    """A trial that fails gait detection -- a mis-recorded or non-walking
    file -- must be logged and skipped, not end a fifteen-trial run."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=3)
    recorder = []

    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           **_batch_modules(tmp_path, session_dir, recorder,
                                            fail_on={"CK-002"}))

    assert result["succeeded"] == 2
    assert result["failed"] == 1
    failed = [t for t in result["trials"] if not t["ok"]]
    assert failed[0]["trial"] == "CK-002"
    assert "no gait events" in failed[0]["error"]


def test_batch_still_pools_when_some_trials_failed(mod, tmp_path):
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=3)
    recorder = []

    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           **_batch_modules(tmp_path, session_dir, recorder,
                                            fail_on={"CK-001"}))

    assert recorder, "the surviving trials must still be pooled"
    assert result["combined_matrix_r_path"]


def test_batch_reports_progress_per_trial(mod, tmp_path):
    """A fifteen-trial run is minutes long; a silent window reads as a hang."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=3)
    messages = []

    mod.run_batch(str(session_dir), str(mvnx_dir),
                  progress_callback=messages.append,
                  **_batch_modules(tmp_path, session_dir, [], ))

    joined = " ".join(messages)
    assert "1 of 3" in joined and "3 of 3" in joined


def test_batch_refuses_an_empty_folder(mod, tmp_path):
    session_dir = tmp_path / "OpenCapData_test"
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="No .mvnx"):
        mod.run_batch(str(session_dir), str(empty))


def test_batch_trials_run_in_natural_order(mod, tmp_path):
    """CK-010 must follow CK-002. Column order in the pooled matrix follows
    processing order, so a lexical sort would reorder the session."""
    session_dir = tmp_path / "OpenCapData_test"
    mvnx_dir = tmp_path / "mvnx"
    mvnx_dir.mkdir()
    for name in ("CK-010", "CK-002"):
        (mvnx_dir / f"{name}.mvnx").write_text("<mvnx/>")

    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           **_batch_modules(tmp_path, session_dir, []))

    assert [t["trial"] for t in result["trials"]] == ["CK-002", "CK-010"]


def test_drain_queue_dispatches_a_batch_summary_as_terminal(mod):
    """A batch ends with its own message kind. Treating it as non-terminal
    would leave the poller running forever and the Run button disabled."""
    q = queue.Queue()
    q.put(("progress", "Trial 1 of 3..."))
    q.put(("batch", {"succeeded": 3, "failed": 0}))
    seen = {"progress": [], "batch": [], "result": [], "error": []}

    terminal = mod.drain_queue(
        q,
        on_progress=seen["progress"].append,
        on_result=seen["result"].append,
        on_error=seen["error"].append,
        on_batch=seen["batch"].append,
    )

    assert terminal is True
    assert seen["batch"] and seen["batch"][0]["succeeded"] == 3
    assert not seen["result"] and not seen["error"]


def test_drain_queue_still_works_without_a_batch_handler(mod):
    """on_batch is optional -- existing callers pass three handlers."""
    q = queue.Queue()
    q.put(("result", {"ok": True}))

    terminal = mod.drain_queue(q, on_progress=lambda m: None,
                               on_result=lambda r: None, on_error=lambda e: None)

    assert terminal is True


# -- Trial isolation (2026-08-27) -----------------------------------------
# A fifteen-trial batch was killed around trial 11-12 with exit 127 and no
# Python traceback -- twice, from a clean start. Because the process died
# rather than raising, run_batch's skip-and-continue path never ran and the
# batch ended early with pooling silently skipped. Each trial now gets its
# own interpreter, which turns that death into an ordinary per-trial failure.


def test_a_child_that_dies_without_an_exception_is_a_trial_failure_not_a_crash(mod):
    """The exit-127 case. There is no Python exception to report, so the
    outcome must still be a recorded failure rather than an invented one."""
    ok, result, error = mod._decode_trial_outcome(127, payload=None, stderr_tail="")

    assert ok is False
    assert result is None
    assert "127" in error and "without reporting a Python error" in error


def test_a_dead_child_keeps_its_last_output_for_diagnosis(mod):
    ok, _result, error = mod._decode_trial_outcome(
        127, payload=None, stderr_tail="Processing 6 gait cycles, leg: l.")

    assert ok is False
    assert "Processing 6 gait cycles" in error


def test_a_child_reporting_its_own_exception_keeps_that_message(mod):
    ok, _result, error = mod._decode_trial_outcome(
        1, payload={"ok": False, "error": "NonGaitTrialError: only 1 heel strike"})

    assert ok is False
    assert error == "NonGaitTrialError: only 1 heel strike"


def test_a_successful_child_returns_its_result(mod):
    ok, result, error = mod._decode_trial_outcome(
        0, payload={"ok": True, "result": {"trial_name": "CK-001"}})

    assert ok is True
    assert result == {"trial_name": "CK-001"}
    assert error is None


def test_isolated_results_name_the_live_objects_they_had_to_drop(mod):
    """gait_r/gait_l cannot cross a process boundary. Dropping them silently
    would read as the pipeline having failed to produce them."""
    trimmed = mod._serialisable_result(
        {"trial_name": "CK-001", "mot_path": "a.mot",
         "gait_r": object(), "gait_l": object()})

    assert trimmed["trial_name"] == "CK-001"
    assert "gait_r" not in trimmed and "gait_l" not in trimmed
    assert trimmed["dropped_by_isolation"] == ["gait_r", "gait_l"]
    assert json.dumps(trimmed), "an isolated result must be serialisable"


def test_a_result_without_live_objects_gains_no_dropped_key(mod):
    trimmed = mod._serialisable_result({"trial_name": "CK-001"})

    assert trimmed == {"trial_name": "CK-001"}


def test_isolation_really_spawns_a_process_and_reads_its_payload(mod, tmp_path):
    """Proves the plumbing -- argv config in, JSON payload out -- with a
    stand-in child, since the real pipeline needs OpenSim."""
    child = (
        "import json, sys\n"
        "config = json.loads(sys.argv[1])\n"
        "payload = {'ok': True, 'result': {'trial_name': config['mvnx_path'],\n"
        "                                  'conversion': config['conversion']}}\n"
        "open(config['out_path'], 'w').write(json.dumps(payload))\n"
    )

    ok, result, error = mod._run_trial_isolated(
        str(tmp_path), "CK-007.mvnx", "ik", child_source=child)

    assert ok is True, error
    assert result == {"trial_name": "CK-007.mvnx", "conversion": "ik"}


def test_a_real_child_process_dying_silently_is_survived(mod, tmp_path):
    """os._exit writes no payload and raises nothing -- the shape of the
    failure that killed the fifteen-trial run."""
    child = "import os\nos._exit(127)\n"

    ok, _result, error = mod._run_trial_isolated(
        str(tmp_path), "CK-011.mvnx", "ik", child_source=child)

    assert ok is False
    assert "127" in error


def test_batch_isolates_by_default(mod, tmp_path, monkeypatch):
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=2)
    seen = []

    def _fake_isolated(session, path, conversion):
        seen.append(Path(path).stem)
        return True, {"trial_name": Path(path).stem}, None

    monkeypatch.setattr(mod, "_run_trial_isolated", _fake_isolated)
    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           combine_module=_fake_combine_module([]))

    assert seen == ["CK-001", "CK-002"], "each trial must get its own process"
    assert result["succeeded"] == 2


def test_a_dead_trial_does_not_abandon_the_rest_of_the_batch(mod, tmp_path, monkeypatch):
    """The regression this whole change exists for: trial 2 of 3 dies with no
    exception, and trial 3 must still run and the session must still pool."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=3)
    recorder = []

    def _fake_isolated(session, path, conversion):
        if Path(path).stem == "CK-002":
            return False, None, "TrialProcessDied: exited with code 127"
        return True, {"trial_name": Path(path).stem}, None

    monkeypatch.setattr(mod, "_run_trial_isolated", _fake_isolated)
    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           combine_module=_fake_combine_module(recorder))

    assert result["succeeded"] == 2 and result["failed"] == 1
    assert [t["trial"] for t in result["trials"]] == ["CK-001", "CK-002", "CK-003"]
    assert recorder, "the surviving trials must still be pooled"


def test_a_dead_trial_is_reported_in_the_progress_log(mod, tmp_path, monkeypatch):
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=1)
    messages = []

    monkeypatch.setattr(mod, "_run_trial_isolated",
                        lambda s, p, c: (False, None, "TrialProcessDied: code 127"))
    mod.run_batch(str(session_dir), str(mvnx_dir), progress_callback=messages.append,
                  combine_module=_fake_combine_module([]))

    assert any("TrialProcessDied" in m for m in messages)


def test_injected_modules_force_in_process_execution(mod, tmp_path, monkeypatch):
    """Live module objects cannot cross a process boundary, so injection
    must keep the in-process path rather than being silently discarded --
    which would run the real OpenSim pipeline instead of the fake."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=2)

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("isolation ran despite injected modules")

    monkeypatch.setattr(mod, "_run_trial_isolated", _must_not_run)
    result = mod.run_batch(str(session_dir), str(mvnx_dir),
                           **_batch_modules(tmp_path, session_dir, []))

    assert result["succeeded"] == 2


def test_demanding_isolation_alongside_injection_is_refused(mod, tmp_path):
    """Silently choosing one over the other would mislead either way."""
    session_dir, mvnx_dir = _batch_env(tmp_path, n_trials=1)

    with pytest.raises(ValueError, match="cannot cross a process boundary"):
        mod.run_batch(str(session_dir), str(mvnx_dir), isolate_trials=True,
                      **_batch_modules(tmp_path, session_dir, []))


def test_isolation_drops_values_that_merely_fail_to_serialise(mod):
    """The first version listed gait_r/gait_l by name and still died on the
    numpy arrays in fpa_r/fpa_l. Type, not name, decides."""
    trimmed = mod._serialisable_result(
        {"trial_name": "CK-001", "fpa_r": {1, 2, 3}, "gait_r": object()})

    assert trimmed["trial_name"] == "CK-001"
    assert sorted(trimmed["dropped_by_isolation"]) == ["fpa_r", "gait_r"]
    assert json.dumps(trimmed)
