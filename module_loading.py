"""
module_loading.py

Shared "load a sibling repo-root module by absolute path" helper, used by
both clinician_gui.py and report_export.py so there is exactly one loading
mechanism and one process-wide cache -- previously report_export.py
reimplemented the same spec_from_file_location/module_from_spec/exec_module
sequence independently (found in code review), which meant a module needed
by both files (e.g. report_formatting.py) was loaded and executed twice
instead of once.

No tkinter, no matplotlib, no opensim -- pure stdlib, safe to import from
either a Tk-dependent or Tk-free module.
"""
import importlib.util

_LOADED_MODULE_CACHE = {}


def load_module_by_path(register_name, path):
    """Loads the Python file at `path` via importlib and gives it the name
    `register_name` (via spec_from_file_location), matching this repo's own
    test-loading convention (see tests/test_xsens_to_opensim_session_paths.py)
    rather than a normal `import`, so callers work regardless of how/where
    they're launched from. Cached by `path` in _LOADED_MODULE_CACHE below,
    not registered in sys.modules -- a caller cannot look the module up via
    sys.modules[register_name].

    Cached per path (not per call): a real pipeline run touches the same
    modules repeatedly (validate_inputs, run_pipeline, shape_results_for_display,
    the PDF export path), some transitively importing opensim/utils.py, and
    this GUI's window is persistent across multiple trials in one session --
    without caching, every dependent module would be re-parsed and
    re-executed from scratch on every single call, every single run.
    """
    if path not in _LOADED_MODULE_CACHE:
        spec = importlib.util.spec_from_file_location(register_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED_MODULE_CACHE[path] = module
    return _LOADED_MODULE_CACHE[path]
