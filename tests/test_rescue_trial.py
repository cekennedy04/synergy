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


def test_the_gui_still_runs_unattended_by_default():
    """Naming the tool must not have wired a window into the GUI's own
    pipeline thread, where it deadlocks."""
    source = (REPO_ROOT / "clinician_gui.py").read_text(encoding="utf-8")

    assert "make_manual_event_provider" not in source
    assert source.count("allow_manual_entry=False") >= 1
