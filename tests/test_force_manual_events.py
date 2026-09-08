"""Tests the SYNERGY_FORCE_MANUAL_EVENTS test seam.

Why the seam exists: a scan of all 90 processed trials in this dataset on
2026-09-08 found zero auto-trim failures, so the gait-event picker -- and in
particular the clinician GUI's cross-thread modal handshake, the least
covered path in the application -- could not be reached on real data at all.

Why the seam needs its own tests: it changes clinical behaviour when set. The
things that matter are that it is OFF unless explicitly turned on, that it
does not fake a result, and that it says so loudly enough that nobody mistakes
a forced run for a real one.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope="module")
def gf():
    """Loads gait_analysis_UCM_fixed under base python, where it does not
    normally import.

    Importing it pulls in the OpenCap login chain (`utils` -> `utilsAPI` ->
    `utilsAuthentication`), which is documented in VENDORING.md as coupling
    import to an interactive credential prompt, plus opensim itself. None of
    it is reachable from the seam under test -- a single environment-variable
    read -- so the chain is stubbed rather than installed, per this suite's
    convention of stubbing via sys.modules and never requiring a real OpenSim.

    The stubs are discovered rather than listed: naming them freezes today's
    import graph into a test that has no opinion about it, and the next
    dependency added upstream would fail here for no reason anyone could act
    on. The loop is bounded so a genuine import cycle still fails loudly.
    """
    import sys
    import types

    os.environ.setdefault("API_TOKEN", "test-placeholder-token")
    # utilsAPI does `from decouple import config`, so a bare module object is
    # not enough for this one.
    added = []
    if "decouple" not in sys.modules:
        decouple = types.ModuleType("decouple")
        added.append("decouple")

        def _config(key, *args, **kwargs):
            # Emulates python-decouple: the environment first, KeyError when
            # absent. Both halves matter. utilsAuthentication.get_token reads
            # API_TOKEN through here rather than through os.environ, so a stub
            # that always raises drops into the interactive login prompt; and
            # utilsAPI wraps its own call in a try/except, so raising for the
            # absent API_URL is what lets it fall back to its real default.
            # Returning "" instead reaches `API_URL[-1]` and fails on import.
            return os.environ[key]

        decouple.config = _config
        sys.modules["decouple"] = decouple

    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    module = None
    try:
        for _ in range(20):
            try:
                spec = importlib.util.spec_from_file_location(
                    "gait_fixed_for_force_test",
                    os.path.join(REPO_ROOT, "gait_analysis_UCM_fixed.py"))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                break
            except ModuleNotFoundError as exc:
                if not exc.name or exc.name in sys.modules:
                    raise
                sys.modules[exc.name] = types.ModuleType(exc.name)
                added.append(exc.name)
        if module is None:
            raise RuntimeError(
                "gait_analysis_UCM_fixed still would not import after 20 "
                "stubs; the import chain has changed shape rather than "
                "merely grown.")
        yield module
    finally:
        # Every stub is removed again. Without this the fakes outlive this
        # file: tests/test_gait_analysis_picker_end_to_end.py skips its whole
        # suite when opensim is absent, and a leaked stub made it run against
        # fakes and fail instead -- fourteen skips became fourteen failures
        # that had nothing to do with the code under test. A fixture that
        # stubs an import graph has to put it back.
        for name in added:
            sys.modules.pop(name, None)


def test_it_is_off_by_default(gf, monkeypatch):
    """The default must be normal operation. A seam that is on unless
    disabled is a behaviour change wearing a test's clothes."""
    monkeypatch.delenv(gf.FORCE_MANUAL_EVENTS_VAR, raising=False)
    assert gf.forced_manual_entry() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_the_usual_spellings_of_yes_all_work(gf, monkeypatch, value):
    """An operator typing 'true' and getting silence would conclude the seam
    is broken, then conclude the picker is broken."""
    monkeypatch.setenv(gf.FORCE_MANUAL_EVENTS_VAR, value)
    assert gf.forced_manual_entry() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_anything_else_is_off(gf, monkeypatch, value):
    monkeypatch.setenv(gf.FORCE_MANUAL_EVENTS_VAR, value)
    assert gf.forced_manual_entry() is False


def test_an_empty_variable_does_not_count_as_set(gf, monkeypatch):
    """`SYNERGY_FORCE_MANUAL_EVENTS=` in a shell profile is not consent."""
    monkeypatch.setenv(gf.FORCE_MANUAL_EVENTS_VAR, "")
    assert gf.forced_manual_entry() is False


def test_the_variable_is_named_in_the_source_of_truth(gf):
    """The message the operator reads names the variable to unset, so the
    constant and the docs cannot drift apart."""
    assert gf.FORCE_MANUAL_EVENTS_VAR == "SYNERGY_FORCE_MANUAL_EVENTS"
    assert gf.FORCE_MANUAL_EVENTS_VAR in gf.forced_manual_entry.__doc__


def test_it_forces_the_handover_not_the_answer(gf):
    """It must not fabricate events. The docstring is the contract here --
    the function only reports whether the switch is on; every event still
    comes from the picker, and therefore from a human."""
    doc = gf.forced_manual_entry.__doc__
    assert "does not fake a result" in doc
    # And it does not return, construct, or touch any event data.
    import inspect
    source = inspect.getsource(gf.forced_manual_entry)
    for name in ("rHS", "lHS", "rTO", "lTO", "mark(", "picker"):
        assert name not in source.split('"""')[-1]
