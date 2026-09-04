"""Recovering a trial the clinician GUI could not segment.

The picker is the backup plan for auto-trim, and until now it was a backup
plan the product's own users could not reach. The clinician GUI runs Xsens
`.mvnx` sessions; the only wired picker path (`Examples/gaitAnalysis-UCM.py`'s
`run_interactive`) downloads OpenCap sessions. A clinician whose trial failed
detection got "try a longer or cleaner recording" and a dead end, for a trial
that was very often recoverable by hand.

**Why the picker is not simply wired into the GUI instead.** Measured
2026-09-03: the GUI runs its pipeline on a background daemon thread and talks
to Tk through a queue drained by `root.after`. Opening a matplotlib window
from that thread deadlocks -- the worker never returns, and matplotlib warns
"Starting a Matplotlib GUI outside of the main thread will likely fail" on the
way in. Reaching the picker from the GUI would need a cross-thread modal
handshake putting a blocking window in the middle of a clinician's Run, for a
minority of trials, with a documented deadlock as the failure mode. Trading a
clear error message for a possible hang is the wrong trade.

So the recovery lives in its own process, on its main thread, and the GUI's
message names it. `rescue_trial` re-enters the pipeline at the gait stage --
the conversion the GUI already did is still on disk, and it is the expensive
part -- so a recovered trial produces exactly the artefacts a successful run
would have.
"""
import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load("rescue_trial_under_test", "rescue_trial.py")


@pytest.fixture
def converted(tmp_path):
    """A session as the GUI leaves it when gait analysis fails: conversion
    done, .mot and .trc on disk, no gait results."""
    session = tmp_path / "OpenCapData_abc123"
    (session / "OpenSimData" / "Kinematics").mkdir(parents=True)
    (session / "MarkerData").mkdir(parents=True)
    (session / "OpenSimData" / "Kinematics" / "Trial1.mot").write_text("mot")
    (session / "MarkerData" / "Trial1.trc").write_text("trc")
    (session / "model.osim").write_text("osim")
    return session


def _paths_for(session):
    return {
        "model_file": str(session / "model.osim"),
        "results_dir": str(session / "OpenSimData" / "Kinematics"),
        "output_motion_filename": "Trial1.mot",
        "trc_path": str(session / "MarkerData" / "Trial1.trc"),
        "sto_path": str(session / "OpenSimData" / "Trial1.sto"),
    }


@pytest.fixture
def fake_xsens(converted):
    return types.SimpleNamespace(
        resolve_session_output_paths=lambda session_dir, trial_name, **_k:
            _paths_for(converted))


@pytest.fixture
def fake_gui():
    """Stands in for clinician_gui, recording what _run_gait_stages got."""
    calls = []

    def _run_gait_stages(session_dir, mvnx_path, trial_name, paths, mot_path,
                         conversion, gait_fixed_module,
                         foot_progression_module, combine_module, _progress,
                         manual_event_provider=None):
        calls.append({
            "session_dir": session_dir, "trial_name": trial_name,
            "mot_path": mot_path, "conversion": conversion,
            "manual_event_provider": manual_event_provider,
        })
        return {"trial_name": trial_name, "session_dir": session_dir,
                "gait_r": object(), "gait_l": object()}

    return types.SimpleNamespace(_run_gait_stages=_run_gait_stages,
                                 _calls=calls)


# -- refusing to guess -----------------------------------------------------


def test_an_unconverted_trial_is_refused_by_name(mod, converted, fake_xsens):
    """Re-entering at the gait stage assumes the conversion is on disk. If it
    is not, say which file is missing and what produces it -- rather than
    failing later inside OpenSim, where the message is about a file handle."""
    (converted / "MarkerData" / "Trial1.trc").unlink()

    with pytest.raises(mod.TrialNotConvertedError) as raised:
        mod.converted_outputs(str(converted), "Trial1",
                              xsens_module=fake_xsens)

    message = str(raised.value)
    assert "Trial1.trc" in message
    assert "clinician_gui" in message or "GUI" in message


def test_a_missing_motion_file_is_refused_too(mod, converted, fake_xsens):
    (converted / "OpenSimData" / "Kinematics" / "Trial1.mot").unlink()

    with pytest.raises(mod.TrialNotConvertedError, match="Trial1.mot"):
        mod.converted_outputs(str(converted), "Trial1",
                              xsens_module=fake_xsens)


def test_a_converted_trial_yields_its_paths(mod, converted, fake_xsens):
    paths, mot_path = mod.converted_outputs(str(converted), "Trial1",
                                            xsens_module=fake_xsens)

    assert Path(mot_path).is_file()
    assert Path(paths["trc_path"]).is_file()


# -- what it hands the pipeline -------------------------------------------


def test_the_rescue_runs_the_gait_stages_with_a_picker(mod, converted,
                                                        fake_xsens, fake_gui):
    """The whole point: allow_manual_entry is only honoured when a provider
    reaches gait_analysis, and _run_gait_stages is the one place that decides."""
    mod.rescue(str(converted), "Trial1", xsens_module=fake_xsens,
               gui_module=fake_gui)

    assert len(fake_gui._calls) == 1
    assert fake_gui._calls[0]["manual_event_provider"] is not None
    assert fake_gui._calls[0]["trial_name"] == "Trial1"


def test_the_provider_asks_once_per_trial_not_once_per_leg(mod, converted,
                                                            fake_xsens,
                                                            fake_gui):
    """_run_gait_stages builds gait_analysis twice. The provider it is handed
    has to be the reuse-wrapped one or a rescued trial opens two windows."""
    opened = []

    class _Timeline:
        name, n_rows, signals = "Trial1", 40, {}

        def time_at(self, row):
            return row * 0.016667

    picker_mod = _load("gait_event_picker_for_rescue", "gait_event_picker.py")

    def scripted(model):
        opened.append(model.picker.motion.name)
        model.pick_at(4.0)

    mod.rescue(str(converted), "Trial1", xsens_module=fake_xsens,
               gui_module=fake_gui, show=scripted)

    provider = fake_gui._calls[0]["manual_event_provider"]
    for _leg in ("r", "l"):
        provider(picker_mod.GaitEventPicker(_Timeline()))

    assert opened == ["Trial1"], (
        "the rescue handed the pipeline an unwrapped provider, so one trial "
        "would open two picker windows")


def test_the_route_reaches_the_pipeline(mod, converted, fake_xsens, fake_gui):
    """ik and xtoo write differently-named curve files and must not be
    pooled together, so a rescue that forgot the route would corrupt the
    session's combined matrix."""
    mod.rescue(str(converted), "Trial1", conversion="xtoo",
               xsens_module=fake_xsens, gui_module=fake_gui)

    assert fake_gui._calls[0]["conversion"] == "xtoo"


# -- the backend trap ------------------------------------------------------


def test_importing_the_rescue_does_not_disable_the_picker(mod):
    """`make_reports.py` and friends call matplotlib.use('Agg') at import, and
    the picker cannot open a window under it -- the failure mode its own
    provider raises about. A recovery tool that imported one of those would
    disable the thing it exists to run."""
    # Parsed, not grepped: the module names below appear in this file's own
    # prose explaining the trap, and a substring check would flag the
    # explanation as the offence.
    source = (REPO_ROOT / "rescue_trial.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forces_agg = {"make_reports", "make_comparison_figures", "session_report",
                  "cohort_figures"}
    assert not (imported & forces_agg), (
        "%s force(s) Agg process-wide at import; importing one here would "
        "leave the picker unable to open a window."
        % sorted(imported & forces_agg))

    calls_use = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "use"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "matplotlib"
    ]
    assert not calls_use, "rescue_trial calls matplotlib.use itself"


# -- the GUI names the recourse -------------------------------------------


def test_the_gui_failure_message_names_the_recovery_tool():
    """A clinician whose trial fails detection is one command away from
    recovering it, and previously had no way to learn that."""
    source = (REPO_ROOT / "clinician_gui.py").read_text(encoding="utf-8")
    start = source.index("elif isinstance(exc, GaitAnalysisFailedError):")
    message = source[start:start + 1800]

    assert "rescue_trial" in message, (
        "the gait-detection failure message is a dead end: it does not tell "
        "the clinician that the trial can be recovered by hand-picking.")


def test_the_gui_never_opens_a_picker_on_its_pipeline_thread():
    """The GUI does ask a human now -- but through the ManualEventRequest
    handshake, which opens the window on the main thread. Calling a picker
    directly from clinician_gui would put it back on the worker thread, where
    it deadlocks.

    So the module must reach the picker only via the queue provider, never via
    the pyplot window `Examples/gaitAnalysis-UCM.py` and `rescue_trial.py` use.
    """
    source = (REPO_ROOT / "clinician_gui.py").read_text(encoding="utf-8")

    assert "make_manual_event_provider" not in source, (
        "clinician_gui reaches the standalone pyplot picker, which calls "
        "plt.show() -- a second Tk mainloop, from the pipeline thread.")
    assert "queue_manual_event_provider" in source
    assert "show_picker_in_tk" in source, (
        "the GUI must open the Tk-embedded picker, not a pyplot window.")


def test_the_tk_picker_is_only_opened_from_the_main_thread():
    """`_on_manual_events` is a root.after callback -- the main thread -- and
    is the only place the window is built. A pipeline-thread call site would
    reintroduce the deadlock this whole handshake exists to remove."""
    source = (REPO_ROOT / "clinician_gui.py").read_text(encoding="utf-8")
    opener = source.index("show_picker_in_tk")
    handler = source.index("def _on_manual_events")

    assert opener > handler, (
        "show_picker_in_tk is reached outside _on_manual_events; only the "
        "main thread may build the window.")


# -- the whole recovery, on a trial that genuinely fails -------------------
#
# Everything above uses fakes. This drives the real thing: a real session, a
# real conversion on disk, real prominence escalation and auto-trim retries
# failing for real, the picker asked, and gait cycles coming out the far end.
#
# Trial9 of session dc490fa4 is the trial the picker exists for -- it fails
# ordering at every prominence. It is an OpenCap session rather than an Xsens
# one because no Xsens trial in Data/ currently fails detection, and
# resolve_session_output_paths computes the same layout for both, which is why
# the rescue works on either.
#
# Copied into tmp_path rather than run in place. _run_gait_stages writes the
# session's per-trial curve matrices AND rebuilds its pooled matrix, so
# running this against Data/ would silently rewrite real session artefacts
# every time the suite ran.

DATA_ROOT = REPO_ROOT / "Data"
FAILING_SESSION_GLOB = "OpenCapData_dc490fa4*"
FAILING_TRIAL = "Trial9"


@pytest.fixture(scope="module")
def failing_session_copy(tmp_path_factory):
    """The minimum of a real failing session, somewhere writes do no harm."""
    import shutil

    pytest.importorskip("opensim",
                        reason="needs the opencap-processing environment")
    sessions = list(DATA_ROOT.glob(FAILING_SESSION_GLOB)) if DATA_ROOT.is_dir() else []
    if not sessions:
        pytest.skip("the known detection-failure session is not in Data/")
    source = sessions[0]
    if not (source / "MarkerData" / (FAILING_TRIAL + ".trc")).is_file():
        pytest.skip("%s is not in the session" % FAILING_TRIAL)

    target = tmp_path_factory.mktemp("session") / source.name
    (target / "OpenSimData" / "Kinematics").mkdir(parents=True)
    (target / "MarkerData").mkdir(parents=True)
    shutil.copytree(source / "OpenSimData" / "Model",
                    target / "OpenSimData" / "Model")
    for relative in (Path("OpenSimData") / "Kinematics" / (FAILING_TRIAL + ".mot"),
                     Path("MarkerData") / (FAILING_TRIAL + ".trc"),
                     Path("sessionMetadata.yaml")):
        if (source / relative).is_file():
            shutil.copy2(source / relative, target / relative)
    return target


@pytest.fixture(scope="module")
def rescued(mod, failing_session_copy):
    import os

    opened = []

    def scripted_operator(model):
        """The human at the window, clicking a clean cycle."""
        motion = model.picker.motion
        opened.append(motion.name)
        for event_type, fraction in (
                ('rHS', 0.10), ('lTO', 0.16), ('lHS', 0.30), ('rTO', 0.36),
                ('rHS', 0.50), ('lTO', 0.56), ('lHS', 0.70), ('rTO', 0.76),
                ('rHS', 0.90)):
            model.select(event_type)
            model.pick_at(float(int(motion.n_rows * fraction)))

    # utils.py runs get_token() at import; nothing on this path calls the API.
    os.environ.setdefault("API_TOKEN", "placeholder-no-api-calls-on-this-path")
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        result = mod.rescue(str(failing_session_copy), FAILING_TRIAL,
                            show=scripted_operator)
    finally:
        os.chdir(cwd)
    return result, opened


def test_a_trial_the_pipeline_gave_up_on_is_recovered(rescued):
    """The claim the whole feature rests on: a trial no automatic rung could
    segment produces gait cycles once a human picks its events."""
    result, _opened = rescued

    for side in ("r", "l"):
        cycles = result["gait_" + side].gaitEvents["ipsilateralIdx"]
        assert len(cycles) >= 1, "the %s leg recovered no gait cycle" % side


def test_the_recovery_asks_the_operator_once(rescued):
    """Both legs fail together, so the rescue must not open two windows."""
    _result, opened = rescued

    assert opened == [FAILING_TRIAL], (
        "the picker opened %d times for one trial" % len(opened))


def test_the_recovery_writes_the_same_artefacts_a_normal_run_would(rescued):
    """It re-enters _run_gait_stages rather than re-implementing it, so a
    recovered trial has to be as complete as an ordinary one -- per-trial
    curve matrices and the session's pooled matrix included."""
    result, _opened = rescued

    for key in ("curves_matrix_r_path", "curves_matrix_l_path",
                "combined_matrix_r_path", "combined_matrix_l_path"):
        assert result[key], "%s was not written" % key
        assert Path(result[key]).is_file()
