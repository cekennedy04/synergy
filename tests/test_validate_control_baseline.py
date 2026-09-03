"""Tests for validate_control_baseline.py.

The verdict logic is pure, so it is tested directly on stride lists rather than
through a processed session: the boundaries are the thing that matters, and a
real session cannot be constructed in a fixture. `check_session`'s guards are
tested through the module, which is where a wrong feature set would slip past.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "validate_control_baseline.py"


@pytest.fixture(scope="module")
def baseline():
    spec = importlib.util.spec_from_file_location("baseline_under_test",
                                                  MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gdi():
    spec = importlib.util.spec_from_file_location(
        "gdi_for_baseline_test",
        Path(__file__).resolve().parent.parent / "gdi.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _strides(value, n=20):
    return [value] * n


# -- the two explanations the check exists to separate ---------------------


def test_a_control_scoring_normally_says_the_frame_is_sound(baseline):
    """Explanation A: the pipeline is fine and the existing cohort's low
    scores are real impairment."""
    status, mean, detail = baseline.verdict(_strides(100.0))

    assert status == "SOUND"
    assert mean == pytest.approx(100.0)
    assert "uninjured" in detail


def test_a_control_scoring_like_our_cohort_says_the_pipeline_is_offset(baseline):
    """Explanation B: a subject known to be uninjured scoring where our
    participants score means the scale, not the subjects, is the problem."""
    status, mean, detail = baseline.verdict(_strides(80.2))

    assert status == "ACTION REQUIRED"
    assert mean == pytest.approx(80.2)
    assert "cohort" in detail


def test_a_control_between_the_two_is_not_forced_into_the_nearer_one(baseline):
    """The failure mode this guards: a score at 87 is closer to 85 than to 100,
    but 'closer to' is not evidence. Both explanations remain live, and saying
    so is the honest answer."""
    status, mean, _ = baseline.verdict(_strides(87.0))

    assert status == "INCONCLUSIVE"
    assert mean == pytest.approx(87.0)


# -- boundaries ------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (89.9, "INCONCLUSIVE"),
    (90.0, "SOUND"),            # the floor is inclusive
    (85.0, "ACTION REQUIRED"),  # the ceiling is inclusive
    (85.1, "INCONCLUSIVE"),
])
def test_the_band_edges_are_where_the_constants_say(baseline, value, expected):
    status, _, _ = baseline.verdict(_strides(value))

    assert status == expected


def test_too_few_strides_is_inconclusive_whatever_the_mean(baseline):
    """A perfect-looking mean over three strides is not evidence about bands
    20 points apart. Pinned because 'it said 100' is exactly the kind of result
    someone would act on without checking n."""
    status, mean, detail = baseline.verdict(_strides(100.0, n=3))

    assert status == "INCONCLUSIVE"
    assert mean is None
    assert "stride" in detail


def test_the_verdict_uses_every_stride_from_both_legs(baseline):
    """Pooled, because the question is about the pipeline's scale rather than
    one limb. A left leg at 100 and a right at 80 average to inconclusive, and
    should: that session disagrees with itself."""
    scores = {"gdi": {
        "left": {"mean": 100.0, "per_stride": _strides(100.0, n=10)},
        "right": {"mean": 80.0, "per_stride": _strides(80.0, n=10)},
        "feature_set": "reduced6",
    }}

    strides = baseline.pooled_strides(scores)
    sides = baseline.side_means(scores)

    assert len(strides) == 20
    # Pooled they average to exactly 90.0, which lands on the SOUND floor --
    # so without the asymmetry guard this session would pass.
    assert baseline.verdict(strides)[0] == "SOUND"
    status, _, detail = baseline.verdict(strides, sides)
    assert status == "INCONCLUSIVE"
    assert "disagree" in detail


# -- guards ----------------------------------------------------------------


def test_a_feature_set_with_pelvis_terms_is_refused(baseline, tmp_path):
    """The argument only holds on a pelvis-free set: that is what makes a
    deficit here independent of the pelvis convention that disabled gdi9.
    Running this on a set with pelvis terms would confound the two questions
    and produce a confident, meaningless answer."""
    with pytest.raises(baseline.ControlBaselineError) as excinfo:
        baseline.check_session(tmp_path, tmp_path, feature_set="gdi9")

    message = str(excinfo.value)
    assert "gdi9" in message
    # gdi9 is disabled outright, so the refusal comes from the feature-set
    # guard rather than this module's own pelvis check. Either way it must not
    # score, and the message must name the set.
    assert "disabled" in message or "pelvis" in message


def test_the_shipped_default_is_pelvis_free_so_the_check_can_run(baseline, gdi):
    """If the project default ever gained a pelvis term, this check would
    refuse to run at all -- which is correct, and worth failing loudly here
    rather than discovering it during a capture session."""
    default = gdi.DEFAULT_FEATURE_SET

    assert not any("pelvis" in name for name in default.features)
    assert not default.is_disabled


def test_exit_status_encodes_the_verdict(baseline):
    """The status codes are the point of the script for anyone wiring it into
    a post-capture script, so they are pinned."""
    assert baseline.STATUS_EXIT["SOUND"] == 0
    assert baseline.STATUS_EXIT["ACTION REQUIRED"] == 1
    assert baseline.STATUS_EXIT["INCONCLUSIVE"] == 2


# -- the report ------------------------------------------------------------


def test_the_report_says_what_the_verdict_does_not_establish(baseline):
    """A verdict that reads as more certain than it is would be worse than no
    verdict. One subject against two hypotheses 20 points apart is suggestive,
    and the report has to say so."""
    scores = {"session": "CTRL-01", "feature_set": "reduced6",
              "conversion": "ik",
              "gdi": {"left": {"mean": 99.0, "sd": 4.0, "n_strides": 10,
                               "per_stride": _strides(99.0, n=10)},
                      "right": {"mean": 101.0, "sd": 4.0, "n_strides": 10,
                                "per_stride": _strides(101.0, n=10)}}}
    strides = baseline.pooled_strides(scores)
    status, mean, detail = baseline.verdict(strides)

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert "caveat" in text.lower()
    assert "Relative comparison" in text
    assert "CTRL-01" in text


def test_the_action_required_report_points_at_the_subject_not_the_pipeline(baseline):
    """A low score used to be reported as evidence the pipeline was offset.
    That was refuted over all six sessions (audit section 13), so the report
    must now send the reader to that session's data rather than to a rescaling
    exercise -- while still forbidding the global-offset fix, which stays wrong
    for a second reason: there is no uniform offset to fit."""
    scores = {"session": "CTRL-02", "feature_set": "reduced6",
              "conversion": "ik",
              "gdi": {"left": {"mean": 80.0, "sd": 5.0, "n_strides": 20,
                               "per_stride": _strides(80.0, n=20)}}}
    strides = baseline.pooled_strides(scores)
    status, mean, detail = baseline.verdict(strides)

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert status == "ACTION REQUIRED"
    assert "THIS SUBJECT" in text
    assert "refuted" in text
    assert "Do NOT fit a global offset" in text
