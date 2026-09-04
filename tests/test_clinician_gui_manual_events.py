"""The GUI asking a human, without deadlocking on its own worker thread.

The GUI's fallback chain is now the pipeline's full chain: prominence
escalation, then auto-trim retries, then a person. The last rung is the hard
one to reach from here, and the reason is threading, not policy.

`run_pipeline` runs on a background daemon thread (`start_pipeline_thread`)
and talks to Tk through a `queue.Queue` drained by `root.after`. Measured
2026-09-03: creating a matplotlib window on that worker thread deadlocks --
the worker never returns, and matplotlib warns "Starting a Matplotlib GUI
outside of the main thread will likely fail" on the way in. So the worker
never opens the picker. It posts a `ManualEventRequest` and blocks on an
Event; the main thread picks the request up in its existing poll, opens the
window there, and releases the worker.

Nearly all of these pin the handshake without Tk: every piece of it is a plain
queue, a plain Event, and plain callables, which is the same seam `drain_queue`
and `start_pipeline_thread` were already factored for. The last one is the
exception, and has to be -- the deadlock only exists when a real mainloop and a
real worker thread are both running, so proving it is gone needs both. It skips
where there is no display, which includes CI.
"""
import importlib.util
import queue
import sys
import threading
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "clinician_gui_manual_events", REPO_ROOT / "clinician_gui.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["clinician_gui_manual_events"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def picker_mod():
    spec = importlib.util.spec_from_file_location(
        "gait_event_picker_for_gui", REPO_ROOT / "gait_event_picker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gait_event_picker_for_gui"] = module
    spec.loader.exec_module(module)
    return module


class _Timeline:
    def __init__(self, name="Trial1", n_rows=60):
        self.name, self.n_rows, self.signals = name, n_rows, {}

    def time_at(self, row):
        return round(row * 0.016667, 6)


def _picker(picker_mod, name="Trial1"):
    return picker_mod.GaitEventPicker(_Timeline(name))


# -- the handshake ---------------------------------------------------------


def test_the_worker_blocks_until_the_main_thread_answers(mod, picker_mod):
    """The provider is called synchronously from inside segment_walking, so it
    has to still be blocking after it hands the picker over -- returning early
    would let segmentation read an empty picker as a decline."""
    events = queue.Queue()
    provider = mod.queue_manual_event_provider(events)
    picker = _picker(picker_mod)
    returned = []

    worker = threading.Thread(
        target=lambda: returned.append(provider(picker)), daemon=True)
    worker.start()

    kind, request = events.get(timeout=5)
    assert kind == "manual_events"
    worker.join(timeout=0.3)
    assert worker.is_alive(), "the provider returned before it was answered"

    request.picker.mark("rHS", 4)
    request.answer()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert returned == [None], "the contract is to mark the picker and return None"
    assert picker.rows("rHS") == [4]


def test_the_request_carries_the_workers_own_picker(mod, picker_mod):
    """Not a copy: collect_manual_events reads the picker it built, and marks
    made on anything else would be discarded silently."""
    events = queue.Queue()
    picker = _picker(picker_mod)
    threading.Thread(
        target=lambda: mod.queue_manual_event_provider(events)(picker),
        daemon=True).start()

    _kind, request = events.get(timeout=5)
    request.answer()

    assert request.picker is picker


def test_a_failure_on_the_main_thread_reaches_the_worker(mod, picker_mod):
    """A picker that cannot be shown must fail the trial with its own reason,
    not leave the worker blocked forever on an answer that is never coming."""
    events = queue.Queue()
    picker = _picker(picker_mod)
    raised = []

    def _run():
        try:
            mod.queue_manual_event_provider(events)(picker)
        except Exception as exc:          # noqa: BLE001 -- that is the assertion
            raised.append(exc)

    threading.Thread(target=_run, daemon=True).start()
    _kind, request = events.get(timeout=5)
    request.fail(RuntimeError("no display"))

    for _ in range(50):
        if raised:
            break
        threading.Event().wait(0.05)

    assert raised and isinstance(raised[0], RuntimeError)
    assert "no display" in str(raised[0])


def test_a_shutdown_releases_a_waiting_worker(mod, picker_mod):
    """Closing the GUI while a picker is open must not leave a daemon thread
    parked on an Event that nothing will ever set."""
    events = queue.Queue()
    picker = _picker(picker_mod)
    finished = threading.Event()

    def _run():
        try:
            mod.queue_manual_event_provider(events)(picker)
        except Exception:                 # noqa: BLE001
            pass
        finished.set()

    threading.Thread(target=_run, daemon=True).start()
    _kind, request = events.get(timeout=5)
    request.abandon()

    assert finished.wait(timeout=5), "the worker was never released"


# -- routing ---------------------------------------------------------------


def test_drain_queue_routes_a_manual_event_request(mod):
    """It is not a terminal message: the run continues after the answer, so
    the poll must keep polling."""
    events = queue.Queue()
    seen = []
    sentinel = object()
    events.put(("manual_events", sentinel))

    terminal = mod.drain_queue(
        events, on_progress=lambda _m: None, on_result=lambda _r: None,
        on_error=lambda _e: None, on_manual_events=seen.append)

    assert seen == [sentinel]
    assert terminal is False, (
        "a manual-event request ended the poll loop, so the pipeline's own "
        "result would never be collected")


def test_an_unhandled_request_is_declined_rather_than_hanging(mod, picker_mod):
    """Older three-callback callers exist. One that cannot show a picker must
    release the worker as a decline -- auto-trim's failure is then reported --
    instead of parking it forever."""
    events = queue.Queue()
    picker = _picker(picker_mod)
    finished = threading.Event()

    def _run():
        try:
            mod.queue_manual_event_provider(events)(picker)
        except Exception:                 # noqa: BLE001
            pass
        finished.set()

    threading.Thread(target=_run, daemon=True).start()
    events.get(timeout=5)                 # the request, taken by nobody
    events.put(("manual_events", _LastRequest.instance))

    mod.drain_queue(events, on_progress=lambda _m: None,
                    on_result=lambda _r: None, on_error=lambda _e: None)

    assert finished.wait(timeout=5), (
        "drain_queue dropped a manual-event request with no handler, leaving "
        "the pipeline thread blocked")


class _LastRequest:
    """Set by the fixture below; the test above needs the request object that
    the provider actually posted."""
    instance = None


@pytest.fixture(autouse=True)
def _capture_requests(mod, monkeypatch):
    original = mod.ManualEventRequest

    class _Recording(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _LastRequest.instance = self

    monkeypatch.setattr(mod, "ManualEventRequest", _Recording)


# -- what reaches gait_analysis -------------------------------------------


def _fake_gait_module():
    calls = []

    class _FakeGaitAnalysis:
        def __init__(self, session_dir, trial_name, fpa_r, fpa_l, leg='auto',
                     allow_manual_entry=True, modelName=None, **kwargs):
            calls.append({"leg": leg,
                          "allow_manual_entry": allow_manual_entry,
                          "manual_event_provider":
                              kwargs.get("manual_event_provider")})

    return types.SimpleNamespace(gait_analysis=_FakeGaitAnalysis, _calls=calls)


def test_a_gui_run_now_permits_manual_entry(mod, tmp_path):
    """The point of the change: the GUI's own run reaches the third rung. It
    is only safe because a provider comes with it -- allow_manual_entry with
    nothing to answer the prompt is how a run blocks forever on stdin."""
    fake_gait = _fake_gait_module()
    provider = object()
    paths = {"model_file": str(tmp_path / "m.osim"),
             "results_dir": str(tmp_path), "output_motion_filename": "t.mot",
             "trc_path": str(tmp_path / "t.trc"),
             "sto_path": str(tmp_path / "t.sto")}

    mod._run_gait_stages(
        str(tmp_path), None, "Trial1", paths, str(tmp_path / "t.mot"), "ik",
        fake_gait,
        types.SimpleNamespace(
            compute_foot_progression_angles=lambda *_a: ([0.0], [0.0])),
        None, lambda _m: None, manual_event_provider=provider)

    assert len(fake_gait._calls) == 2
    for call in fake_gait._calls:
        assert call["allow_manual_entry"] is True
        assert call["manual_event_provider"] is provider


def test_a_batch_run_still_refuses_manual_entry(mod, tmp_path):
    """run_batch isolates trials in their own interpreters with no GUI to show
    a picker. Manual entry there is what allow_manual_entry=False exists to
    prevent, and nothing in this change may reach it."""
    fake_gait = _fake_gait_module()
    paths = {"model_file": str(tmp_path / "m.osim"),
             "results_dir": str(tmp_path), "output_motion_filename": "t.mot",
             "trc_path": str(tmp_path / "t.trc"),
             "sto_path": str(tmp_path / "t.sto")}

    mod._run_gait_stages(
        str(tmp_path), None, "Trial1", paths, str(tmp_path / "t.mot"), "ik",
        fake_gait,
        types.SimpleNamespace(
            compute_foot_progression_angles=lambda *_a: ([0.0], [0.0])),
        None, lambda _m: None)

    for call in fake_gait._calls:
        assert call["allow_manual_entry"] is False
        assert call["manual_event_provider"] is None


def test_the_thread_supplies_a_reusing_provider(mod, tmp_path):
    """_run_gait_stages builds gait_analysis twice, and a trial that failed
    auto-trim failed for both legs -- so an unwrapped provider would open two
    windows and take two answers for one trial."""
    events = queue.Queue()
    captured = {}

    def _fake_run_pipeline(_session, _mvnx, progress_callback=None, **kwargs):
        captured["provider"] = kwargs.get("manual_event_provider")
        return {}

    original = mod.run_pipeline
    mod.run_pipeline = _fake_run_pipeline
    try:
        mod.start_pipeline_thread("s", "m", events).join(timeout=5)
    finally:
        mod.run_pipeline = original

    provider = captured["provider"]
    assert provider is not None

    # Drive it twice, as the two legs would, answering only the first.
    picker_spec = importlib.util.spec_from_file_location(
        "gait_event_picker_reuse_check", REPO_ROOT / "gait_event_picker.py")
    picker_module = importlib.util.module_from_spec(picker_spec)
    picker_spec.loader.exec_module(picker_module)

    def _drive():
        for _leg in ("r", "l"):
            provider(picker_module.GaitEventPicker(_Timeline()))

    # The stubbed run_pipeline already posted its ("result", {}); skip past it
    # to the request the two legs actually raise.
    threading.Thread(target=_drive, daemon=True).start()
    request = None
    while request is None:
        kind, payload = events.get(timeout=5)
        if kind == "manual_events":
            request = payload
    request.picker.mark("rHS", 3)
    request.answer()

    with pytest.raises(queue.Empty):
        while True:
            kind, _payload = events.get(timeout=1.5)
            assert kind != "manual_events", (
                "the second leg raised its own request, so one trial would "
                "open two picker windows")


# -- the deadlock this replaces -------------------------------------------


@pytest.fixture
def tk_root():
    """A real Tk root, or a skip. CI is headless ubuntu with no DISPLAY, and
    no other test in this repo builds a widget -- that is why clinician_gui is
    factored so its logic is reachable without one."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except Exception:                     # noqa: BLE001 -- TclError, no display
        pytest.skip("no display for Tk")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except Exception:                 # noqa: BLE001
            pass


def test_the_picker_opens_without_deadlocking_the_pipeline_thread(mod,
                                                                   picker_mod,
                                                                   tk_root):
    """The whole reason the GUI could not ask a human.

    Building a matplotlib window on the pipeline's worker thread deadlocks:
    the worker never returns, and matplotlib warns "Starting a Matplotlib GUI
    outside of the main thread will likely fail" on the way in. Measured
    2026-09-03, and reproduced by putting `show_picker_in_tk` inside `worker`
    below instead of inside the poll.

    This drives the real structure instead -- mainloop on the main thread,
    pipeline on a worker, the window opened from the root.after poll -- and
    the worker has to come back with the operator's events.
    """
    pytest.importorskip("matplotlib")
    import tkinter as tk

    events = queue.Queue()
    outcome = []

    class _Signals:
        name, n_rows = "ProbeTrial", 120
        signals = {name: [0.0] * 120
                   for name in ("r_calc", "r_toe", "l_calc", "l_toe")}

        def time_at(self, row):
            return row * 0.016667

    picker = picker_mod.GaitEventPicker(_Signals())

    def worker():
        try:
            mod.queue_manual_event_provider(events)(picker)
            outcome.append(("returned", picker.counts()))
        except Exception as exc:          # noqa: BLE001
            outcome.append(("raised", repr(exc)))
        tk_root.after(0, tk_root.quit)

    def on_manual(request):
        from gait_event_picker_tk import show_picker_in_tk
        from gait_event_picker_ui import EventPickerModel

        model = EventPickerModel(request.picker)

        def drive():
            """Stands in for the operator: two clicks, then close."""
            model.pick_at(10.0)
            model.pick_at(40.0)
            for child in tk_root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()

        tk_root.after(400, drive)
        show_picker_in_tk(model, tk_root)
        request.answer()

    def poll():
        if not mod.drain_queue(events, lambda _m: None, lambda _r: None,
                               lambda _e: None, on_manual_events=on_manual):
            tk_root.after(50, poll)

    threading.Thread(target=worker, daemon=True).start()
    tk_root.after(50, poll)
    # Watchdog: a regression must fail this test, not hang the suite.
    tk_root.after(30000, tk_root.quit)
    tk_root.mainloop()

    assert outcome, "the pipeline thread never returned -- the deadlock is back"
    kind, detail = outcome[0]
    assert kind == "returned", detail
    assert detail["rHS"] == 2, (
        "the operator's picks did not reach the picker the pipeline thread "
        "is holding")


# -- reachable however clinician_gui was loaded ---------------------------


def test_the_picker_modules_load_without_the_repo_root_on_sys_path(mod,
                                                                    monkeypatch):
    """Caught by CI, not locally, on 2026-09-04.

    The picker modules import their siblings by plain name -- gait_event_picker_ui
    does `from gait_event_picker import ...` -- so loading them by path is not
    enough on its own: it resolves the file we name, not the imports that file
    then makes. Whether that works depends on how the process was started.

    `python -m pytest` puts the working directory on sys.path; a bare `pytest
    tests/` does not, and CI runs the bare form. Every local run was green
    while CI failed on eleven tests with ModuleNotFoundError. This pins the
    loader rather than the launcher.
    """
    without_root = [entry for entry in sys.path
                    if Path(entry or ".").resolve() != REPO_ROOT]
    monkeypatch.setattr(sys, "path", without_root)

    picker_ui = mod._load_gait_event_picker_ui()

    assert hasattr(picker_ui, "reuse_across_legs")
    assert hasattr(picker_ui, "EventPickerModel")


def test_the_thread_can_build_its_provider_without_the_repo_root(mod,
                                                                  monkeypatch):
    """The same failure, at the site that actually hit it: start_pipeline_thread
    builds the provider before the run begins, so this broke every pipeline
    test rather than only the manual-entry ones."""
    without_root = [entry for entry in sys.path
                    if Path(entry or ".").resolve() != REPO_ROOT]
    monkeypatch.setattr(sys, "path", without_root)

    captured = {}

    def _fake_run_pipeline(_session, _mvnx, progress_callback=None, **kwargs):
        captured["provider"] = kwargs.get("manual_event_provider")
        return {}

    monkeypatch.setattr(mod, "run_pipeline", _fake_run_pipeline)
    mod.start_pipeline_thread("s", "m", queue.Queue()).join(timeout=5)

    assert captured.get("provider") is not None
