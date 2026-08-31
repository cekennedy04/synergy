"""Tests for process_participants.py, the unattended first-pass driver.

The real pipeline needs OpenSim, so `clinician_gui` is injected as a fake
through the same seam `run_batch` itself uses. What is pinned here is the
driver's own contract: the ledger resumes, one participant's failure does not
end the run, and trials are never silently dropped.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "process_participants_under_test", REPO_ROOT / "process_participants.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeGui:
    """Stands in for clinician_gui. Records what it was asked to do."""

    def __init__(self, trials_ok=15, trials_failed=0, raises=None):
        self.calls = []
        self._ok, self._failed, self._raises = trials_ok, trials_failed, raises

    def run_batch(self, session_dir, mvnx_dir, conversion=None,
                  progress_callback=None):
        self.calls.append({"session_dir": session_dir, "mvnx_dir": mvnx_dir,
                           "conversion": conversion})
        if self._raises is not None:
            raise self._raises
        trials = ([{"trial": f"T{i}", "ok": True, "error": None}
                   for i in range(self._ok)]
                  + [{"trial": f"F{i}", "ok": False, "error": "boom"}
                     for i in range(self._failed)])
        return {"trials": trials, "succeeded": self._ok,
                "failed": self._failed, "conversion": conversion}


def _participant(root, code, n=3, subdir="HD Reprocessed"):
    folder = Path(root) / code / subdir
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (folder / f"{code}-{i:03d}.mvnx").write_text("<mvnx/>")
    return folder


# -- locating the trials ---------------------------------------------------


def test_the_mvnx_folder_is_found_one_level_down(mod, tmp_path):
    folder = _participant(tmp_path, "AL")

    assert mod.find_mvnx_dir(tmp_path / "AL") == folder


def test_two_mvnx_folders_is_an_error_not_a_pick(mod, tmp_path):
    """Processing one and ignoring the other would silently drop trials, and
    a short session looks exactly like a normal one downstream."""
    _participant(tmp_path, "AL", subdir="HD Reprocessed")
    _participant(tmp_path, "AL", subdir="Raw")

    with pytest.raises(ValueError, match="silently drop trials"):
        mod.find_mvnx_dir(tmp_path / "AL")


def test_a_participant_with_no_trials_is_reported(mod, tmp_path):
    (tmp_path / "AL").mkdir()

    with pytest.raises(FileNotFoundError, match="no .mvnx"):
        mod.find_mvnx_dir(tmp_path / "AL")


# -- the ledger ------------------------------------------------------------


def test_the_ledger_round_trips(mod, tmp_path):
    path = tmp_path / "ledger.json"
    mod.save_ledger(path, {"AL:ik": {"ok": True, "ok_trials": 15}})

    assert mod.load_ledger(path)["AL:ik"]["ok_trials"] == 15


def test_a_missing_ledger_starts_empty(mod, tmp_path):
    assert mod.load_ledger(tmp_path / "nothing.json") == {}


def test_a_truncated_ledger_does_not_abort_the_run(mod, tmp_path):
    """Worst case is redoing work, which is safe; refusing to start is not."""
    path = tmp_path / "ledger.json"
    path.write_text('{"AL:ik": {"ok"', encoding="utf-8")

    assert mod.load_ledger(path) == {}


def test_route_is_part_of_the_ledger_key(mod):
    """ik and xtoo are separate passes over the same participant; keying on
    the code alone would mark a participant done after only one route."""
    assert mod.participant_key("AL", "ik") != mod.participant_key("AL", "xtoo")


# -- the run loop ----------------------------------------------------------


def _run(mod, monkeypatch, tmp_path, gui, argv_extra=()):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    monkeypatch.setitem(sys.modules, "clinician_gui", gui)
    return mod.main([
        "--sessions", str(sessions),
        "--participants", str(tmp_path / "participants"),
        *argv_extra,
    ])


def test_each_participant_is_processed_once_with_its_own_folders(mod, tmp_path,
                                                                 monkeypatch):
    for code in ("AL", "GH"):
        (tmp_path / "sessions" / f"XsensSession_{code}").mkdir(parents=True)
        _participant(tmp_path / "participants", code)
    gui = _FakeGui()

    _run(mod, monkeypatch, tmp_path, gui)

    assert len(gui.calls) == 2
    assert all(call["conversion"] == "ik" for call in gui.calls)
    # each session paired with its own participant's trials, not another's
    for call in gui.calls:
        code = Path(call["session_dir"]).name.replace("XsensSession_", "")
        assert code in call["mvnx_dir"]


def test_a_participant_that_raises_does_not_end_the_run(mod, tmp_path,
                                                        monkeypatch):
    """The whole point of the outer loop. A dead participant is one ledger
    row, not the end of an hour of unattended compute."""
    for code in ("AL", "GH"):
        (tmp_path / "sessions" / f"XsensSession_{code}").mkdir(parents=True)
    _participant(tmp_path / "participants", "GH")   # AL has no trials

    _run(mod, monkeypatch, tmp_path, _FakeGui())
    ledger = mod.load_ledger(tmp_path / "sessions" / mod.LEDGER_NAME)

    assert ledger["AL:ik"]["ok"] is False
    assert ledger["GH:ik"]["ok"] is True


def test_a_second_run_skips_what_the_ledger_records(mod, tmp_path, monkeypatch):
    (tmp_path / "sessions" / "XsensSession_AL").mkdir(parents=True)
    _participant(tmp_path / "participants", "AL")

    _run(mod, monkeypatch, tmp_path, _FakeGui())
    second = _FakeGui()
    _run(mod, monkeypatch, tmp_path, second)

    assert second.calls == []


def test_redo_reprocesses_a_recorded_participant(mod, tmp_path, monkeypatch):
    (tmp_path / "sessions" / "XsensSession_AL").mkdir(parents=True)
    _participant(tmp_path / "participants", "AL")

    _run(mod, monkeypatch, tmp_path, _FakeGui())
    second = _FakeGui()
    _run(mod, monkeypatch, tmp_path, second, argv_extra=("--redo",))

    assert len(second.calls) == 1


def test_failed_trials_are_counted_not_hidden(mod, tmp_path, monkeypatch):
    (tmp_path / "sessions" / "XsensSession_AL").mkdir(parents=True)
    _participant(tmp_path / "participants", "AL")

    _run(mod, monkeypatch, tmp_path, _FakeGui(trials_ok=13, trials_failed=2))
    ledger = mod.load_ledger(tmp_path / "sessions" / mod.LEDGER_NAME)

    assert ledger["AL:ik"]["ok_trials"] == 13
    assert ledger["AL:ik"]["failed_trials"] == 2
    assert ledger["AL:ik"]["errors"]  # the reasons survive into the ledger


def test_the_two_routes_are_separate_ledger_entries(mod, tmp_path, monkeypatch):
    (tmp_path / "sessions" / "XsensSession_AL").mkdir(parents=True)
    _participant(tmp_path / "participants", "AL")

    _run(mod, monkeypatch, tmp_path, _FakeGui())
    _run(mod, monkeypatch, tmp_path, _FakeGui(), argv_extra=("--route", "xtoo"))
    ledger = mod.load_ledger(tmp_path / "sessions" / mod.LEDGER_NAME)

    assert set(ledger) == {"AL:ik", "AL:xtoo"}


def test_participant_filter_selects_a_subset(mod, tmp_path, monkeypatch):
    for code in ("AL", "GH"):
        (tmp_path / "sessions" / f"XsensSession_{code}").mkdir(parents=True)
        _participant(tmp_path / "participants", code)
    gui = _FakeGui()

    _run(mod, monkeypatch, tmp_path, gui, argv_extra=("--participant", "gh"))

    assert len(gui.calls) == 1
    assert "GH" in gui.calls[0]["session_dir"]


def test_no_matching_scaffold_is_a_nonzero_exit(mod, tmp_path, monkeypatch):
    (tmp_path / "participants").mkdir(parents=True)

    assert _run(mod, monkeypatch, tmp_path, _FakeGui()) == 1
