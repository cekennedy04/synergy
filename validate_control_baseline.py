"""Score one processed session and say whether it reads normal, low, or unclear.

Built 2026-09-03 to settle whether this pipeline's GDI scale was offset from the
normative cohort's. The specific ~20-point claim did not survive contact with the
full cohort; whether any smaller offset exists is still open, and one subject
known to be uninjured would settle it. The script is kept, and reframed, because
the per-session check it performs turned out to be the useful part.

WHAT IT WAS FOR, AND WHAT HAPPENED
---------------------------------------------------------------------------
Three processed subjects scored 80.20 +/- 8.09 on `reduced6` against the control
cohort's 100.0 +/- 10.0, and two explanations fit: our subjects are impaired, or
the pipeline is systematically ~20 points low. The plan was to settle it by
capturing a subject known to be uninjured.

Over all six processed sessions the cohort means 93.45 +/- 7.44, range
83.36-106.13. Under a uniform -20 offset the true values would run 103-126, i.e.
all twelve limbs above the normative mean -- implausible for a group of unknown
clinical status, though not impossible. The three-subject sample had been the low
tail. Sections 13 and 14 of docs/2026-08-31-gdi-vs-ucm-audit.md carry the
retraction and its precise strength.

NOTE ON THESE THRESHOLDS. The bands below were drawn for a subject KNOWN to be
uninjured. Applied to a session of unknown status they describe the score, not
the person: a SOUND verdict is not evidence that subject is healthy, and reading
it that way is the error section 14 records.

WHAT IT IS FOR NOW
---------------------------------------------------------------------------
A per-session diagnostic. A low pooled score is a finding about that subject --
real impairment, or that session's tracking quality -- not about the pipeline.
The asymmetry guard has proved the most useful part in practice: it flags MS,
whose legs differ by 13.44 points (104.79 vs 91.35) behind an unremarkable
pooled mean of 98.31.

WHAT IT DOES NOT DO
---------------------------------------------------------------------------
It does not correct anything, and no global offset should be fitted to our
participants: there is no uniform offset to fit, and mean-matching a subject
group onto a control reference removes exactly the between-subject variation the
score exists to detect.

Usage:
    python validate_control_baseline.py --session PATH/TO/SESSION \
        --reference context/gdi_reference_2026-08-27

Exit status is the verdict, so this can gate a script:
    0  SOUND            pooled >= 90; reads normal
    1  ACTION REQUIRED  pooled <= 85; investigate that subject's data
    2  INCONCLUSIVE     the 85-90 band, legs disagreeing, or too few strides
    3  could not run    (bad session, missing reference, wrong feature set)
"""
import argparse
import importlib.util
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# A healthy subject is expected here under explanation A. The band is the
# normative SD (10 points, by construction: GDI is scaled so 10 points is one
# SD of the control cohort), so this is "within one SD of the control mean".
SOUND_FLOOR = 90.0

# At or below this, the session is scoring well under the cohort and is worth
# investigating on its own terms. Kept where it was when the bands were framed
# as competing hypotheses about the pipeline, because it still separates the two
# genuinely low sessions (CK 84.30, AN 86.64) from the rest.
BIASED_CEILING = 85.0

# Below this many strides the mean is too noisy to place against bands 20
# points apart, whatever it comes out as.
MIN_STRIDES = 8

# Trials, not strides, are the unit the interval is computed over. Strides
# within a trial are strongly correlated -- the same person, the same walk --
# so a standard error over strides is far too tight and would make a
# near-threshold verdict look certain when it is not. Trials are closer to
# independent. Below this many, no interval is computed and no verdict beyond
# INCONCLUSIVE is reached.
MIN_TRIALS = 5

# What fraction of genuinely uninjured limbs fall below each band, under the
# normative model (scores ~ N(100, 10) by construction). These are the reason a
# verdict is not a statement about a person: roughly one uninjured limb in six
# lands below the SOUND floor.
P_UNINJURED_BELOW_SOUND_FLOOR = 0.159
P_UNINJURED_BELOW_ACTION_CEILING = 0.067

# How far the two legs may disagree before the session stops being usable as
# evidence about the pipeline. One normative SD. A control whose legs differ by
# more than this is either not a clean control or was not captured cleanly, and
# pooling would hide it: left 100 with right 80 pools to exactly 90 and would
# otherwise read as sound, on a session that plainly disagrees with itself.
ASYMMETRY_LIMIT = 10.0

# What our processed sessions score, for the comparison line in the report.
# All six sessions on reduced6, audit section 13. The earlier 80.20 +/- 8.09
# figure was three subjects who were the low tail, and is superseded.
COHORT_MEAN = 93.45
COHORT_SD = 7.44
NORMATIVE_MEAN = 100.0
NORMATIVE_SD = 10.0


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControlBaselineError(RuntimeError):
    """The check could not be run. Distinct from a verdict: a verdict means
    the measurement happened and says something, this means it did not."""


def pooled_strides(scores):
    """Every stride from both legs, as one list.

    Pooled deliberately. The question is about the pipeline's scale, which is a
    property of the whole capture-and-convert route rather than of one limb, so
    both legs are evidence about the same thing. Per-leg means are still
    reported, because a large left/right split is itself a reason to distrust
    the session.
    """
    strides = []
    for side, entry in scores.get("gdi", {}).items():
        if isinstance(entry, dict) and "per_stride" in entry:
            strides.extend(entry["per_stride"])
    return strides


def trial_means(scores):
    """One mean per TRIAL -- the clustering unit -- with the legs averaged.

    Two levels of clustering have to be collapsed, and missing either one
    narrows the interval dishonestly:

      strides within a trial   the same person on the same walk
      legs within a trial      also the same walk, so left and right are not
                               two independent observations of this session

    Collapsing only the first (pooling 15 left and 15 right trial means as 30
    units) understates the interval by about 1.4x. So a trial contributes one
    value: the mean of whichever sides reported it.
    """
    by_trial = {}
    for side, entry in (scores.get("by_trial") or {}).items():
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            mean = value.get("mean") if isinstance(value, dict) else value
            if isinstance(mean, (int, float)):
                # Strip the side so the same walk's legs land on one key.
                trial = str(key).replace("_left", "").replace("_right", "")
                trial = trial.replace("-left", "").replace("-right", "")
                by_trial.setdefault(trial, []).append(float(mean))
    return [sum(v) / len(v) for _, v in sorted(by_trial.items())]


# Two-sided 95% t multipliers by degrees of freedom (n - 1). Table rather than
# scipy because the suite runs on an interpreter without it. Anything past the
# table uses the normal limit; anything between entries takes the LOWER df,
# which widens the interval -- the safe direction for a gate.
_T_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
    14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
    20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
_T_95_LARGE = 1.960


def t_multiplier(n):
    """Two-sided 95% t multiplier for a sample of `n`.

    Was hardcoded at 2.145 (df=14, the 15-trial protocol), which is wrong at
    every other count and wrong in the dangerous direction below it: at n=5 the
    correct multiplier is 2.776, so a fixed 2.145 produced an interval 23%
    too narrow -- reintroducing exactly the overconfidence the interval exists
    to remove.
    """
    df = max(1, n - 1)
    if df in _T_95:
        return _T_95[df]
    if df > 30:
        return _T_95_LARGE
    return max(_T_95.values())


def mean_interval(values):
    """(mean, lo, hi) for the session's level, over the clustering unit.

    A two-sided 95% interval, so each one-sided bound the verdict gates on
    carries 97.5% coverage. That is deliberately conservative and is named here
    because "95%" alone would misdescribe the decision rule.

    **What this interval does not cover.** Between-trial sampling variation
    only. It says nothing about uncertainty in the normative reference itself,
    about pipeline-versus-reference mismatch, about the score model, or about
    bias from which trials were retained. A tight interval here means the trials
    agreed, not that the number is right.
    """
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return (mean, None, None)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    half = t_multiplier(n) * sd / math.sqrt(n)
    return (mean, mean - half, mean + half)


def side_means(scores):
    """Each side's mean GDI, for the asymmetry check."""
    return [entry["mean"] for entry in scores.get("gdi", {}).values()
            if isinstance(entry, dict) and "mean" in entry]


def verdict(strides, sides=None, trials=None, sound_floor=SOUND_FLOOR,
            biased_ceiling=BIASED_CEILING, min_strides=MIN_STRIDES,
            asymmetry_limit=ASYMMETRY_LIMIT, min_trials=MIN_TRIALS):
    """Where this session's level sits relative to the two bands.

    Returns (status, mean, detail). `status` is "SOUND", "ACTION REQUIRED" or
    "INCONCLUSIVE".

    **The verdict is on an interval, not a point.** A session mean is an
    estimate, and a point estimate one tenth of a point above a threshold is not
    meaningfully different from one a tenth below. SOUND requires the whole
    interval to clear `sound_floor`; ACTION REQUIRED requires it to fall
    entirely below `biased_ceiling`; anything straddling a band is
    INCONCLUSIVE, which is the honest answer for a session that cannot be
    placed.

    The interval is computed over `trials` (see `trial_means`), not over
    strides. Strides within a trial are strongly correlated, so a standard
    error over strides would be several times too tight and would turn "close
    to the line" into a confident verdict. Without enough trials no verdict
    beyond INCONCLUSIVE is reached.
    """
    n = len(strides)
    if n < min_strides:
        return ("INCONCLUSIVE", None,
                f"only {n} stride(s); at least {min_strides} are needed before "
                "a mean can be placed against bands 20 points apart.")

    mean = sum(strides) / n

    if sides and len(sides) >= 2:
        gap = max(sides) - min(sides)
        if gap > asymmetry_limit:
            return ("INCONCLUSIVE", mean,
                    f"the legs disagree by {gap:.1f} points "
                    f"({min(sides):.1f} vs {max(sides):.1f}), more than the "
                    f"{asymmetry_limit:.0f}-point normative SD. A subject "
                    "that asymmetric is not a clean control, and the pooled "
                    f"mean of {mean:.1f} would hide it.")

    if not trials or len(trials) < min_trials:
        have = len(trials) if trials else 0
        return ("INCONCLUSIVE", mean,
                f"the session mean is {mean:.1f}, but only {have} trial(s) are "
                f"available and {min_trials} are needed to put an interval "
                "around it. A point estimate cannot be placed against a "
                "threshold without one -- strides are too correlated to "
                "substitute.")

    _, lo, hi = mean_interval(trials)
    span = f"{mean:.1f} (95% CI {lo:.1f}-{hi:.1f} over {len(trials)} trials)"

    if lo >= sound_floor:
        return ("SOUND", mean,
                f"{span} sits entirely at or above {sound_floor:.0f}. Note "
                f"that {sound_floor:.0f} is about the "
                f"{P_UNINJURED_BELOW_SOUND_FLOOR * 100:.0f}th percentile of the "
                "normative distribution, so this says the session reads normal "
                "-- not that the subject is uninjured.")
    if hi <= biased_ceiling:
        return ("ACTION REQUIRED", mean,
                f"{span} sits entirely at or below {biased_ceiling:.0f}, well "
                f"under the cohort mean ({COHORT_MEAN:.1f}). Worth "
                "investigating this session on its own terms.")
    return ("INCONCLUSIVE", mean,
            f"{span} straddles a band edge "
            f"({biased_ceiling:.0f}/{sound_floor:.0f}), so this session cannot "
            "be placed on either side of it.")


def _spread(strides):
    """Stride-to-stride SD, or None when a single stride makes it undefined."""
    n = len(strides)
    if n < 2:
        return None
    mean = sum(strides) / n
    return math.sqrt(sum((v - mean) ** 2 for v in strides) / n)


def format_report(scores, status, mean, detail, strides):
    """The whole verdict as text, including what it does not establish."""
    lines = []
    lines.append(f"Control baseline check -- session {scores.get('session')!r}")
    lines.append(f"  feature set   {scores.get('feature_set')}")
    lines.append(f"  conversion    {scores.get('conversion')}")
    lines.append("")

    for side in sorted(scores.get("gdi", {})):
        entry = scores["gdi"][side]
        if not isinstance(entry, dict) or "mean" not in entry:
            continue
        sd = entry.get("sd")
        sd_text = f"+/- {sd:4.2f}" if sd is not None else "  (1 stride)"
        lines.append(f"  {side:<6} GDI {entry['mean']:6.2f} {sd_text}"
                     f"   n={entry['n_strides']}")

    spread = _spread(strides)
    if mean is not None:
        spread_text = f" +/- {spread:.2f}" if spread is not None else ""
        lines.append(f"  {'pooled':<6} GDI {mean:6.2f}{spread_text}"
                     f"   n={len(strides)}")
    lines.append("")
    lines.append(f"  for comparison   healthy cohort  {NORMATIVE_MEAN:6.2f} "
                 f"+/- {NORMATIVE_SD:.2f}   (by construction)")
    lines.append(f"                   our 6 sessions  {COHORT_MEAN:6.2f} "
                 f"+/- {COHORT_SD:.2f}   (audit section 13)")
    lines.append("")
    lines.append(f"VERDICT: {status}")
    lines.append(f"  {detail}")
    lines.append("")

    if status == "SOUND":
        lines.append("  Reading: this session reads normal. Nothing to "
                     "investigate on the score alone.")
        lines.append("  It does NOT say the subject is uninjured: about "
                     "1 uninjured limb in 6 falls")
        lines.append("  below this floor, so a SOUND verdict is a statement "
                     "about the score.")
    elif status == "ACTION REQUIRED":
        lines.append("  Reading: this session scores well below the cohort. "
                     "That is a finding about")
        lines.append("  THIS SUBJECT -- real impairment, or this session's "
                     "tracking quality -- not about")
        lines.append("  the pipeline: a uniform pipeline offset was refuted "
                     "over all six sessions, which")
        lines.append("  span 83.36 to 106.13 (audit section 13). Look at this "
                     "session's marker coverage,")
        lines.append("  calibration frame and event detection before reading "
                     "the score as clinical.")
        lines.append("")
        lines.append("  Do NOT fit a global offset to the participants. There "
                     "is no uniform offset to")
        lines.append("  fit, and mean-matching a subject group onto a control "
                     "reference removes exactly")
        lines.append("  the between-subject variation the score exists to "
                     "detect.")
    else:
        lines.append("  Reading: not settled by the score alone. INCONCLUSIVE "
                     "is a no-call, not a pass --")
        lines.append("  it says this session cannot be placed, which is a "
                     "reason to look, not to move on.")
        lines.append("")
        lines.append("  Do next, in order:")
        lines.append("    1. session_drift.py on this session. An interval "
                     "straddling a band is often a")
        lines.append("       session that moved during it, and a trend is "
                     "visible where a mean is not.")
        lines.append("    2. If the legs disagree, treat that as the finding. "
                     "It is a per-limb signal a")
        lines.append("       pooled mean hides.")
        lines.append("    3. Check marker coverage, calibration frame and "
                     "event detection for this session")
        lines.append("       before reading the score as anything about the "
                     "subject.")

    lines.append("")
    lines.append("  Relative comparison (trial to trial, leg to leg, session "
                 "to session) was never in")
    lines.append("  question and stays valid regardless of this verdict.")
    lines.append("")
    lines.append("  Scope: these bands were drawn against a normative "
                 "reference, not validated on")
    lines.append("  known-uninjured and known-impaired samples through this "
                 "pipeline. Until that")
    lines.append("  exists there is no measured sensitivity or specificity, "
                 "and a verdict is a")
    lines.append("  prompt to look rather than a classification. "
                 "ACTION REQUIRED in particular does")
    lines.append("  not separate impairment from data quality from "
                 "calibration -- it says only")
    lines.append("  that this session sits low.")

    if mean is not None and len(strides) >= MIN_STRIDES:
        lines.append("")
        lines.append("  Caveat: the interval covers trial-to-trial variation "
                     "ONLY. It excludes uncertainty")
        lines.append("  in the normative reference, pipeline-versus-reference "
                     "mismatch, the score model,")
        lines.append("  and bias from which trials were retained. A tight "
                     "interval means the trials")
        lines.append("  agreed, not that the number is right. It also assumes "
                     "trials are exchangeable,")
        lines.append("  which a drifting session violates -- run "
                     "session_drift.py before trusting it.")
    return "\n".join(lines)


def check_session(session_dir, reference_dir, conversion="ik",
                  feature_set=None):
    """Score one processed session and judge it. Raises ControlBaselineError
    when the check cannot be run at all."""
    gdi = _load("_gdi_for_baseline", "gdi.py")
    report = _load("_session_report_for_baseline", "session_report.py")

    try:
        resolved = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    except Exception as exc:
        raise ControlBaselineError(str(exc)) from None

    # The whole argument rests on the feature set being pelvis-free: that is
    # what makes a deficit here independent of the pelvis convention that
    # disabled gdi9. A set with pelvis terms would confound the two questions.
    adjusted = set(getattr(gdi, "_CURVE_ADJUSTMENTS", {}))
    pelvis = [f for f in resolved.features if "pelvis" in f]
    if pelvis:
        raise ControlBaselineError(
            f"feature set {resolved.name!r} carries pelvis terms {pelvis}. "
            "This check exists to separate a pipeline-wide frame offset from "
            "the pelvis convention question, so it must run on a pelvis-free "
            "set (reduced6, reduced5, reduced4). Adjusted coordinates in this "
            f"build: {sorted(adjusted)}."
        )

    try:
        scores = report.session_scores(session_dir, reference_dir,
                                       conversion=conversion,
                                       feature_set=resolved)
    except FileNotFoundError as exc:
        raise ControlBaselineError(str(exc)) from None

    strides = pooled_strides(scores)
    status, mean, detail = verdict(strides, side_means(scores),
                                   trial_means(scores))
    return scores, status, mean, detail, strides


STATUS_EXIT = {"SOUND": 0, "ACTION REQUIRED": 1, "INCONCLUSIVE": 2}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        epilog="Exit status: 0 sound, 1 action required, 2 inconclusive, "
               "3 could not run.")
    parser.add_argument("--session", required=True,
                        help="A processed session directory (the one holding "
                             "GaitCurves/).")
    parser.add_argument("--reference", required=True,
                        help="Directory holding the GDI reference pair.")
    parser.add_argument("--conversion", default="ik")
    parser.add_argument("--feature-set", default=None,
                        help="Must be pelvis-free; defaults to the project "
                             "default (reduced6).")
    args = parser.parse_args(argv)

    try:
        scores, status, mean, detail, strides = check_session(
            args.session, args.reference, args.conversion, args.feature_set)
    except ControlBaselineError as exc:
        # Every one of these is a full sentence naming what to do, and a stack
        # trace buries it. Same reasoning as edit #14 in VENDORING.md.
        print("Cannot run the control baseline check.")
        print()
        print(str(exc))
        return 3

    print(format_report(scores, status, mean, detail, strides))
    return STATUS_EXIT[status]


if __name__ == "__main__":
    raise SystemExit(main())
