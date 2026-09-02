"""Tests for make_reports.py -- per-trial PDF generation.

The real pipeline needs OpenSim, so clinician_gui and report_export are
injected as fakes. What is pinned is the report generator's own contract:
one PDF per trial per route, figures actually built, and one bad trial not
costing the rest.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "make_reports_under_test", REPO_ROOT / "make_reports.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_gui(curves=None, raises=None):
    curves = curves if curves is not None else {
        "knee_angle_r": {"available": True},
        "ankle_angle_r": {"available": False},
    }
    built = []

    def run_pipeline(session_dir, mvnx_path, conversion=None, combine_module=None):
        if raises is not None:
            raise raises
        return {"session_dir": session_dir, "conversion": conversion}

    def shape_results_for_display(result):
        return {"curves": curves, "metrics": {}, "metadata": {}}

    def build_curve_figure(curve):
        if not curve.get("available"):
            return None          # the real one returns None here
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        figure = Figure()
        built.append(figure)
        return figure

    return types.SimpleNamespace(
        run_pipeline=run_pipeline,
        shape_results_for_display=shape_results_for_display,
        build_curve_figure=build_curve_figure,
        _NO_COMBINE=object(), _built=built)


def _fake_export():
    written = []

    def export_report_to_pdf(pdf_path, shaped_results, figures=None):
        Path(pdf_path).write_bytes(b"%PDF-1.4 fake")
        written.append({"path": pdf_path, "figures": dict(figures or {})})

    return types.SimpleNamespace(export_report_to_pdf=export_report_to_pdf,
                                 _written=written)


def _mvnx_dir(tmp_path, names=("T-001", "T-002", "T-010")):
    folder = tmp_path / "mvnx"
    folder.mkdir(exist_ok=True)
    for name in names:
        (folder / f"{name}.mvnx").write_text("<mvnx/>")
    return folder


# -- ordering and naming ---------------------------------------------------


def test_trials_are_taken_in_natural_order(mod, tmp_path):
    folder = _mvnx_dir(tmp_path)

    names = [p.stem for p in mod.trial_mvnx_files(folder)]

    assert names == ["T-001", "T-002", "T-010"]


def test_a_report_is_named_by_trial_and_route(mod, tmp_path):
    """ik and xtoo give different numbers for the same trial; one silently
    overwriting the other leaves a report whose contents contradict its name."""
    ik = mod.report_path(tmp_path, "/s/XsensSession_AL", "T-001", "ik")
    xtoo = mod.report_path(tmp_path, "/s/XsensSession_AL", "T-001", "xtoo")

    assert ik != xtoo
    assert "ik" in ik.name and "xtoo" in xtoo.name and "AL" in ik.name


def test_no_mvnx_files_says_so(mod, tmp_path):
    with pytest.raises(FileNotFoundError, match="no .mvnx"):
        mod.trial_mvnx_files(tmp_path)


# -- figures ---------------------------------------------------------------


def test_figures_are_built_rather_than_left_to_the_placeholder_pages(mod,
                                                                     tmp_path):
    """export_report_to_pdf accepts figures=None and writes 'not available'
    pages, producing a PDF that looks complete and contains nothing."""
    gui, export = _fake_gui(), _fake_export()

    mod.make_report(gui, export, tmp_path / "sess", tmp_path / "T-001.mvnx",
                    tmp_path / "out")

    assert export._written[0]["figures"]           # not empty
    assert "knee_angle_r" in export._written[0]["figures"]


def test_an_unavailable_curve_contributes_no_figure(mod, tmp_path):
    """build_curve_figure returns None for those; a None in the dict would
    reach the exporter as a Figure and fail there."""
    gui, export = _fake_gui(), _fake_export()

    mod.make_report(gui, export, tmp_path / "sess", tmp_path / "T-001.mvnx",
                    tmp_path / "out")

    figures = export._written[0]["figures"]
    assert "ankle_angle_r" not in figures
    assert all(f is not None for f in figures.values())


# -- writing ---------------------------------------------------------------


def test_a_pdf_is_written_per_trial(mod, tmp_path):
    gui, export = _fake_gui(), _fake_export()

    path = mod.make_report(gui, export, tmp_path / "sess",
                           tmp_path / "T-001.mvnx", tmp_path / "out")

    assert path.exists() and path.suffix == ".pdf"


def test_an_existing_report_is_not_silently_rebuilt(mod, tmp_path):
    gui, export = _fake_gui(), _fake_export()
    args = (gui, export, tmp_path / "sess", tmp_path / "T-001.mvnx",
            tmp_path / "out")
    mod.make_report(*args)

    assert mod.make_report(*args) is None          # skipped
    assert mod.make_report(*args, overwrite=True) is not None


def test_one_failing_trial_does_not_stop_the_run(mod, tmp_path, monkeypatch,
                                                 capsys):
    folder = _mvnx_dir(tmp_path, names=("T-001", "T-002"))
    gui = _fake_gui(raises=RuntimeError("opensim exploded"))
    monkeypatch.setitem(sys.modules, "clinician_gui", gui)
    monkeypatch.setitem(sys.modules, "report_export", _fake_export())

    code = mod.main(["--session", str(tmp_path / "sess"),
                     "--mvnx-dir", str(folder), "--out", str(tmp_path / "out")])

    output = capsys.readouterr().out
    assert code == 1
    assert output.count("FAILED") == 2       # both attempted, neither aborted
    assert "opensim exploded" in output
