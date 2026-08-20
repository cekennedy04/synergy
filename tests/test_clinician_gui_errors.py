"""
Tests map_error_to_message() from clinician_gui.py -- the centralized,
pure error-to-message mapper U2 defines (KTD10, governs R5). No Tk
dependency: these tests never instantiate ClinicianGUI or any Tk widget,
matching the plan's note that widget rendering is a manual smoke check.

Follows this repo's existing test convention (see
tests/test_clinician_gui_inputs.py): load the module under test via
importlib.util.spec_from_file_location against an absolute path.
"""
import importlib.util
import os
import xml.etree.ElementTree as ET

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('clinician_gui_errors_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def test_model_resolution_error_names_missing_or_extra_osim(mod):
    exc = mod.ModelResolutionError(
        "C:/session/OpenSimData/Model: expected exactly one .osim file for model "
        "auto-discovery, found 0 ([])."
    )

    message = mod.map_error_to_message(exc)

    assert "OpenSim model" in message
    assert ".osim" in message
    assert "Details:" in message
    assert "found 0" in message  # original detail preserved, not swallowed


def test_mvnx_parsing_error_from_value_error_names_the_mvnx_file(mod):
    exc = mod.MvnxParsingError(
        "C:/trial.mvnx: root element is <bogus>, expected <mvnx> or <frames> -- "
        "is this really an .mvnx export?"
    )

    message = mod.map_error_to_message(exc)

    assert ".mvnx" in message
    assert "could not be read" in message
    assert "Details:" in message


def test_mvnx_parsing_error_from_xml_parse_error(mod):
    # Confirms the mapper handles the lower-level xml.etree.ElementTree.ParseError
    # shape too (truly invalid XML, not just an unexpected-but-well-formed
    # document) -- both are wrapped into MvnxParsingError by run_pipeline
    # before ever reaching this mapper, but the mapper's own message text
    # shouldn't depend on which one it was.
    try:
        ET.fromstring("not xml at all <<<")
    except ET.ParseError as parse_exc:
        exc = mod.MvnxParsingError(str(parse_exc))
    else:
        pytest.fail("expected ET.fromstring to raise ParseError on garbage input")

    message = mod.map_error_to_message(exc)

    assert ".mvnx" in message
    assert "could not be read" in message


def test_gait_analysis_failed_error_names_gait_event_detection(mod):
    exc = mod.GaitAnalysisFailedError(
        "Automatic gait-event detection failed and manual entry is disabled "
        "(allow_manual_entry=False)."
    )

    message = mod.map_error_to_message(exc)

    assert "gait-event" in message.lower() or "gait event" in message.lower()
    assert "Details:" in message


def test_foot_progression_analysis_error_names_foot_progression(mod):
    exc = mod.FootProgressionAnalysisError(
        "AnalyzeTool failed: no valid gait cycle found in this trial."
    )

    message = mod.map_error_to_message(exc)

    assert "foot progression" in message.lower()
    assert "unexpected error" not in message.lower()
    assert "Details:" in message


@pytest.mark.parametrize("exc", [
    RuntimeError("some totally unrelated internal failure"),
    KeyError("unexpected_key"),
    ValueError("a ValueError that isn't one of the known wrapped kinds"),
    Exception("bare Exception, no special meaning"),
])
def test_unmapped_exception_types_get_generic_readable_fallback(mod, exc):
    message = mod.map_error_to_message(exc)

    assert isinstance(message, str)
    assert message.strip() != ""
    assert "unexpected error" in message.lower()
    # Never a raw traceback -- no "Traceback (most recent call last)" noise.
    assert "Traceback" not in message


def test_mapper_never_raises_and_never_returns_empty(mod):
    for exc in [
        mod.ModelResolutionError(""),
        mod.MvnxParsingError(""),
        mod.GaitAnalysisFailedError(""),
        mod.FootProgressionAnalysisError(""),
        Exception(""),
        ValueError(),
    ]:
        message = mod.map_error_to_message(exc)
        assert isinstance(message, str)
        assert message.strip() != ""
