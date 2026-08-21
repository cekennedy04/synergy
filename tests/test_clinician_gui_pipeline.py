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
                             sleep_before_calibrate=0.0, write_trc_error=None):
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
        return str(Path(model_file).with_name(Path(model_file).stem + "_calibrated.osim"))

    def run_imu_ik(calibrated_model_file, orientations_sto, start_time, end_time,
                   results_dir, output_motion_filename=None):
        calls["run_imu_ik"].append(
            (calibrated_model_file, orientations_sto, start_time, end_time, results_dir, output_motion_filename)
        )
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
