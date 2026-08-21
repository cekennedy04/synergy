"""
Tests clinician_gui.py's _resolve_data_font() (2026-08-21 design-consultation
styling diff, code-review finding: this function's 3-way fallback chain --
Cascadia Code -> Consolas -> "monospace" -- had zero test coverage despite
being the one new function in that diff with real conditional logic).

Follows this repo's existing test convention (see
test_clinician_gui_display.py): load clinician_gui.py via
importlib.util.spec_from_file_location. _resolve_data_font takes a `root`
argument only to pass through to tkinter.font.families(root) -- monkeypatching
that function means `root` itself is never touched, so a plain sentinel
object stands in for it, consistent with this suite's no-Tk-instantiation
convention (ClinicianGUI's own docstring: Tk widget rendering is a manual
smoke check, not a unit test).
"""
import importlib.util
import os
import tkinter.font as tkfont

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('clinician_gui_design_system_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def test_resolve_data_font_prefers_cascadia_code_when_available(mod, monkeypatch):
    monkeypatch.setattr(tkfont, 'families', lambda root: ('Cascadia Code', 'Consolas', 'Arial'))
    assert mod._resolve_data_font(object()) == ('Cascadia Code', 10)


def test_resolve_data_font_falls_back_to_consolas_when_cascadia_missing(mod, monkeypatch):
    monkeypatch.setattr(tkfont, 'families', lambda root: ('Consolas', 'Arial'))
    assert mod._resolve_data_font(object()) == ('Consolas', 10)


def test_resolve_data_font_falls_back_to_monospace_when_neither_available(mod, monkeypatch):
    monkeypatch.setattr(tkfont, 'families', lambda root: ('Arial', 'Times New Roman'))
    assert mod._resolve_data_font(object()) == ('monospace', 10)
