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
