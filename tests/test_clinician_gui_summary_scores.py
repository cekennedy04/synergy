"""Tests the GUI's GDI scoring: clinician_gui.compute_summary_scores.

Why this exists at all. report_export.py has been able to draw a summary
page and a GDI figure since 2026-09-01, but shape_results_for_display never
produced a "summary_scores" key, so on the GUI's Export path those three
builders were unreachable. A clinician clicking "Export to PDF" got joint
angles and a metrics table and neither of the two numbers the analysis exists
to produce. Wired 2026-09-04.

The cases that matter here are the degradations, not the happy path. The
normative reference lives under context/, which is gitignored -- so on a
fresh clone there is no reference and this must come back with a stated
reason rather than an exception that costs the operator the joint angles and
metrics that did compute.

Loads clinician_gui.py by path per this repo's convention.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'clinician_gui_summary_scores_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


class _FakeGdiScoring:
    """Stands in for gdi_scoring.score_pooled_gdi."""

    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    def score_pooled_gdi(self, session_dir, reference_dir, conversion):
        self.calls.append((str(session_dir), str(reference_dir), conversion))
        if self._raises is not None:
            raise self._raises
        return self._result


def _scored(n_right=4, n_left=4):
    return {"gdi": {
        "right": {"mean": 88.0, "sd": 1.2, "n_strides": n_right,
                  "per_stride": [86.4, 88.1, 89.5, 88.0][:n_right]},
        "left": {"mean": 78.2, "sd": 1.4, "n_strides": n_left,
                 "per_stride": [76.0, 79.4, 78.2, 79.1][:n_left]},
        "feature_set": "reduced6",
    }, "by_trial": {}}


def _real_trial_scores(mod):
    return mod._load_trial_scores()


# ---------------------------------------------------------------------------
# Degradations. These are what a fresh clone actually hits.
# ---------------------------------------------------------------------------

def test_a_missing_reference_directory_is_a_reason_not_an_exception(mod, tmp_path):
    """context/ is gitignored, so this is the default state of a new clone."""
    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(tmp_path / "no_such_reference"),
        gdi_scoring=_FakeGdiScoring(_scored()),
        trial_scores=_real_trial_scores(mod))

    assert "unavailable" in result
    assert "no_such_reference" in result["unavailable"]
    assert "gdi" not in result


def test_an_unpooled_session_is_a_reason_naming_what_to_run(mod, tmp_path):
    reference = tmp_path / "reference"
    reference.mkdir()
    fake = _FakeGdiScoring(
        raises=FileNotFoundError("no pooled '_all-trials_ik_' matrix in X"))

    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(reference), gdi_scoring=fake,
        trial_scores=_real_trial_scores(mod))

    assert "unavailable" in result
    assert "all-trials" in result["unavailable"]


def test_an_unexpected_scoring_failure_never_costs_the_rest_of_the_run(
        mod, tmp_path):
    """The joint angles, metrics and confidence already computed must survive
    a scoring bug."""
    reference = tmp_path / "reference"
    reference.mkdir()
    fake = _FakeGdiScoring(raises=ValueError("matrix has 12 rows, expected 18"))

    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(reference), gdi_scoring=fake,
        trial_scores=_real_trial_scores(mod))

    assert "unavailable" in result
    assert "ValueError" in result["unavailable"]
    assert "12 rows" in result["unavailable"]


# ---------------------------------------------------------------------------
# The scored path.
# ---------------------------------------------------------------------------

def test_scores_reach_the_shape_report_export_already_consumes(mod, tmp_path):
    reference = tmp_path / "reference"
    reference.mkdir()

    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(reference),
        gdi_scoring=_FakeGdiScoring(_scored()),
        trial_scores=_real_trial_scores(mod))

    assert "88.0" in result["gdi"]["right_display"]
    assert "78.2" in result["gdi"]["left_display"]
    # The figure builder needs the raw per-stride values, not the strings.
    assert result["gdi_detail"]["right"]["per_stride"]


def test_the_basis_says_the_score_is_the_session_not_this_trial(mod, tmp_path):
    """The GUI pools every trial processed so far, so this number moves as
    more trials are added. Labelling it as the trial's would be wrong in a
    way a reader could not detect."""
    reference = tmp_path / "reference"
    reference.mkdir()

    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(reference),
        gdi_scoring=_FakeGdiScoring(_scored(n_right=4, n_left=4)),
        trial_scores=_real_trial_scores(mod))

    basis = result["gdi"]["basis"]
    assert "not this trial" in basis
    assert "8 strides" in basis, "the stride count behind the score is missing"


def test_the_absent_synergy_index_is_stated_rather_than_silently_dropped(
        mod, tmp_path):
    """A page headed 'Summary scores' carrying one score reads as though the
    other failed. It is a deliberate omission and must say so."""
    reference = tmp_path / "reference"
    reference.mkdir()

    result = mod.compute_summary_scores(
        tmp_path, reference_dir=str(reference),
        gdi_scoring=_FakeGdiScoring(_scored()),
        trial_scores=_real_trial_scores(mod))

    assert "synergy_detail" not in result
    assert "session_report" in result["synergy_note"]


def test_the_conversion_route_reaches_the_scorer(mod, tmp_path):
    """An IK matrix and a direct-remapping matrix are not interchangeable --
    they differ in precisely the coordinates GDI reads."""
    reference = tmp_path / "reference"
    reference.mkdir()
    fake = _FakeGdiScoring(_scored())

    mod.compute_summary_scores(tmp_path, conversion="xtoo",
                               reference_dir=str(reference), gdi_scoring=fake,
                               trial_scores=_real_trial_scores(mod))

    assert fake.calls[0][2] == "xtoo"


# ---------------------------------------------------------------------------
# The reason this module exists rather than a session_report import.
# ---------------------------------------------------------------------------

def test_scoring_does_not_drag_agg_into_the_gui_process():
    """session_report.py computes the same GDI, and calls matplotlib.use("Agg")
    at import -- process-wide. Importing it from the GUI would switch this
    process to a backend that never opens a window, silently disabling the
    gait-event picker. gdi_scoring exists so the GUI's import is safe."""
    import matplotlib
    before = matplotlib.get_backend()

    spec = importlib.util.spec_from_file_location(
        "gdi_scoring_backend_check", os.path.join(REPO_ROOT, "gdi_scoring.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert matplotlib.get_backend() == before
