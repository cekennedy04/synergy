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


def _trials(value, n=15, spread=0.0):
    """Per-trial means for the clustering unit. `spread` widens the interval:
    with spread=0 the CI collapses to a point, which is what most band tests
    want; a non-zero spread is how a straddling interval is built."""
    if not spread:
        return [value] * n
    step = spread / (n - 1)
    return [value - spread / 2 + i * step for i in range(n)]


# -- the two explanations the check exists to separate ---------------------


def test_a_control_scoring_normally_says_the_frame_is_sound(baseline):
    """Explanation A: the pipeline is fine and the existing cohort's low
    scores are real impairment."""
    status, mean, detail = baseline.verdict(_strides(100.0),
                                            trials=_trials(100.0))

    assert status == "SOUND"
    assert mean == pytest.approx(100.0)
    assert "uninjured" in detail


def test_a_control_scoring_like_our_cohort_says_the_pipeline_is_offset(baseline):
    """Explanation B: a subject known to be uninjured scoring where our
    participants score means the scale, not the subjects, is the problem."""
    status, mean, detail = baseline.verdict(_strides(80.2),
                                            trials=_trials(80.2))

    assert status == "ACTION REQUIRED"
    assert mean == pytest.approx(80.2)
    assert "cohort" in detail


def test_a_control_between_the_two_is_not_forced_into_the_nearer_one(baseline):
    """The failure mode this guards: a score at 87 is closer to 85 than to 100,
    but 'closer to' is not evidence. Both explanations remain live, and saying
    so is the honest answer."""
    status, mean, _ = baseline.verdict(_strides(87.0), trials=_trials(87.0))

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
    status, _, _ = baseline.verdict(_strides(value), trials=_trials(value))

    assert status == expected


def test_too_few_strides_is_inconclusive_whatever_the_mean(baseline):
    """A perfect-looking mean over three strides is not evidence about bands
    20 points apart. Pinned because 'it said 100' is exactly the kind of result
    someone would act on without checking n."""
    status, mean, detail = baseline.verdict(_strides(100.0, n=3),
                                            trials=_trials(100.0))

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
    assert baseline.verdict(strides, trials=_trials(90.0))[0] == "SOUND"
    status, _, detail = baseline.verdict(strides, sides, _trials(90.0))
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
    status, mean, detail = baseline.verdict(strides, trials=_trials(100.0))

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
    status, mean, detail = baseline.verdict(strides, trials=_trials(80.0))

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert status == "ACTION REQUIRED"
    assert "THIS SUBJECT" in text
    assert "refuted" in text
    assert "Do NOT fit a global offset" in text


# -- the interval, which is what makes a verdict honest --------------------


def test_a_mean_above_the_floor_is_not_sound_if_the_interval_straddles_it(baseline):
    """The defect this fixes. A session averaging 91 used to be SOUND on the
    strength of a point estimate one point clear of the floor. With realistic
    trial-to-trial spread the interval covers 90, so the session cannot be
    placed on either side of it -- and saying so is the honest answer."""
    trials = _trials(91.0, spread=12.0)
    mean, lo, hi = baseline.mean_interval(trials)

    assert mean == pytest.approx(91.0)
    assert lo < baseline.SOUND_FLOOR < hi, "the interval must span the floor"

    status, _, detail = baseline.verdict(_strides(91.0), trials=trials)

    assert status == "INCONCLUSIVE"
    assert "straddles" in detail


def test_the_interval_is_computed_over_trials_not_strides(baseline):
    """Strides within a trial are the same person on the same walk, so a
    standard error over them is several times too tight. Pinned by construction:
    100 strides that vary exactly as much as 15 trials must give the wider
    interval for the trials, because n is smaller."""
    values = [88.0, 92.0] * 8            # same spread either way
    over_trials = baseline.mean_interval(values[:16])
    over_strides = baseline.mean_interval(values * 7)

    trial_width = over_trials[2] - over_trials[1]
    stride_width = over_strides[2] - over_strides[1]

    assert trial_width > stride_width * 2, (
        "using strides as the unit would shrink the interval by roughly "
        "sqrt(n_strides/n_trials); that is the overconfidence this avoids."
    )


def test_no_verdict_without_enough_trials_to_form_an_interval(baseline):
    """A point estimate cannot be placed against a threshold. Previously a
    session with any number of strides got a confident verdict; now too few
    trials is INCONCLUSIVE however good the mean looks."""
    status, mean, detail = baseline.verdict(_strides(100.0),
                                            trials=_trials(100.0, n=3))

    assert status == "INCONCLUSIVE"
    assert mean == pytest.approx(100.0)
    assert "interval" in detail


def test_the_sound_verdict_says_it_is_not_a_health_claim(baseline):
    """About one uninjured limb in six falls below the floor, so SOUND cannot
    mean the subject is uninjured. The detail line has to say so, because the
    word 'SOUND' on its own plainly implies otherwise."""
    _, _, detail = baseline.verdict(_strides(100.0), trials=_trials(100.0))

    assert "not that the subject is uninjured" in detail
    assert baseline.P_UNINJURED_BELOW_SOUND_FLOOR == pytest.approx(0.159, abs=0.01)


def test_the_report_states_the_thresholds_are_unvalidated(baseline):
    """No sensitivity or specificity has been measured, because that needs
    known-uninjured and known-impaired samples through this pipeline and none
    exist. A gate that does not say so invites being read as a classifier."""
    scores = {"session": "CTRL-03", "feature_set": "reduced6",
              "conversion": "ik",
              "gdi": {"left": {"mean": 99.0, "sd": 2.0, "n_strides": 20,
                               "per_stride": _strides(99.0, n=20)}}}
    strides = baseline.pooled_strides(scores)
    status, mean, detail = baseline.verdict(strides, trials=_trials(99.0))

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert "sensitivity or specificity" in text
    assert "prompt to look rather than a classification" in text


def test_the_t_multiplier_follows_the_sample_size(baseline):
    """It was hardcoded at 2.145 (df=14, the 15-trial protocol), which is wrong
    at every other count and wrong in the dangerous direction below it: at n=5
    the correct multiplier is 2.776, so a fixed 2.145 gave an interval 23% too
    narrow -- reintroducing the overconfidence the interval exists to remove."""
    assert baseline.t_multiplier(5) == pytest.approx(2.776, abs=0.001)
    assert baseline.t_multiplier(10) == pytest.approx(2.262, abs=0.001)
    assert baseline.t_multiplier(15) == pytest.approx(2.145, abs=0.001)
    assert baseline.t_multiplier(20) == pytest.approx(2.093, abs=0.001)
    assert baseline.t_multiplier(400) == pytest.approx(1.960, abs=0.001)

    # Monotone decreasing in n: a smaller sample must never buy a tighter bound.
    widths = [baseline.t_multiplier(n) for n in range(2, 40)]
    assert widths == sorted(widths, reverse=True)


def test_a_small_sample_widens_the_interval_rather_than_the_reverse(baseline):
    """The regression the hardcoded multiplier caused, pinned end to end."""
    spread = [88.0, 92.0, 90.0, 94.0, 86.0]
    _, lo5, hi5 = baseline.mean_interval(spread)
    _, lo15, hi15 = baseline.mean_interval(spread * 3)

    assert (hi5 - lo5) > (hi15 - lo15), (
        "five trials must give a wider interval than fifteen of the same "
        "spread; a fixed multiplier broke that."
    )


def test_inconclusive_tells_the_operator_what_to_do_next(baseline):
    """INCONCLUSIVE is a no-call, and a no-call with no follow-up is a quiet
    pass. The report has to name the next step, because 'cannot be placed' is a
    reason to look rather than to move on."""
    scores = {"session": "CTRL-04", "feature_set": "reduced6",
              "conversion": "ik",
              "gdi": {"left": {"mean": 87.0, "sd": 3.0, "n_strides": 20,
                               "per_stride": _strides(87.0, n=20)}}}
    strides = baseline.pooled_strides(scores)
    status, mean, detail = baseline.verdict(strides, trials=_trials(87.0))

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert status == "INCONCLUSIVE"
    assert "no-call, not a pass" in text
    assert "session_drift.py" in text


def test_the_caveat_names_what_the_interval_excludes(baseline):
    """A tight interval means the trials agreed, not that the number is right.
    Without saying so the CI invites being read as total uncertainty."""
    scores = {"session": "CTRL-05", "feature_set": "reduced6",
              "conversion": "ik",
              "gdi": {"left": {"mean": 100.0, "sd": 2.0, "n_strides": 20,
                               "per_stride": _strides(100.0, n=20)}}}
    strides = baseline.pooled_strides(scores)
    status, mean, detail = baseline.verdict(strides, trials=_trials(100.0))

    text = baseline.format_report(scores, status, mean, detail, strides)

    assert "trial-to-trial variation ONLY" in text
    assert "exchangeable" in text


def test_the_two_legs_of_one_trial_are_one_observation(baseline):
    """Two levels of clustering, and missing either narrows the interval
    dishonestly. Left and right of the same walk are not two independent
    observations of the session: pooling 15 left and 15 right trial means as 30
    units understates the interval by about 1.4x."""
    scores = {"by_trial": {
        "left":  {"s-001": 90.0, "s-002": 94.0, "s-003": 92.0},
        "right": {"s-001": 80.0, "s-002": 84.0, "s-003": 82.0},
    }}

    trials = baseline.trial_means(scores)

    assert len(trials) == 3, "three walks, not six observations"
    assert trials == pytest.approx([85.0, 89.0, 87.0]), "legs averaged per trial"
