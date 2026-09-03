"""Settle whether this pipeline's GDI scale matches the normative cohort's.

Built 2026-09-03. This is the one-command form of the single open question left
by the 2026-08-31 GDI audit, so that whoever captures the control session gets a
verdict without having to interpret anything.

THE QUESTION
---------------------------------------------------------------------------
Our three processed subjects score 80.20 +/- 8.09 on `reduced6`, against the
control cohort's 100.0 +/- 10.0. `reduced6` carries no pelvis terms, so that
20-point deficit has nothing to do with the pelvis convention that got `gdi9`
disabled. Two explanations fit the same numbers:

  A. Our subjects are genuinely impaired, and the pipeline is sound.
  B. This pipeline's kinematics are systematically offset from the optical-
     mocap cohort the reference was built on, and every score we report is
     ~20 points low.

Nothing in the repo distinguishes them, because both predict exactly what we
observe. Only a subject who is *known* to be uninjured separates them: under A
they score ~100, under B they score ~80. That is a capture session, not an
analysis, which is why this script takes a processed session rather than
computing an answer from existing files.

WHAT IT DOES NOT DO
---------------------------------------------------------------------------
It does not correct anything. A frame offset fitted to our own participants
would subtract exactly the impairment GDI exists to measure -- that proposal was
measured and rejected (audit section 12). This only reports which explanation
the evidence supports.

Usage:
    python validate_control_baseline.py --session PATH/TO/SESSION \\
        --reference context/gdi_reference_2026-08-27

Exit status is the verdict, so this can gate a script:
    0  SOUND            the control scores normally; explanation A
    1  ACTION REQUIRED  the control scores like our cohort; explanation B
    2  INCONCLUSIVE     between the two, or not enough strides
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

# At or below this, the control is scoring like our existing cohort (80.20)
# rather than like a healthy subject, which is explanation B. Set above 80
# rather than at it so a control landing between the two hypotheses is called
# inconclusive instead of being forced into the nearer one.
BIASED_CEILING = 85.0

# Below this many strides the mean is too noisy to place against bands 20
# points apart, whatever it comes out as.
MIN_STRIDES = 8

# How far the two legs may disagree before the session stops being usable as
# evidence about the pipeline. One normative SD. A control whose legs differ by
# more than this is either not a clean control or was not captured cleanly, and
# pooling would hide it: left 100 with right 80 pools to exactly 90 and would
# otherwise read as sound, on a session that plainly disagrees with itself.
ASYMMETRY_LIMIT = 10.0

# What our processed subjects score, for the comparison line in the report.
# From audit section 12 (396 strides, 3 subjects, reduced6).
COHORT_MEAN = 80.20
COHORT_SD = 8.09
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


def side_means(scores):
    """Each side's mean GDI, for the asymmetry check."""
    return [entry["mean"] for entry in scores.get("gdi", {}).values()
            if isinstance(entry, dict) and "mean" in entry]


def verdict(strides, sides=None, sound_floor=SOUND_FLOOR,
            biased_ceiling=BIASED_CEILING, min_strides=MIN_STRIDES,
            asymmetry_limit=ASYMMETRY_LIMIT):
    """Which explanation the control subject's scores support.

    Returns (status, mean, detail). `status` is one of "SOUND",
    "ACTION REQUIRED", "INCONCLUSIVE". `sides` is the per-side means; when two
    or more are given and they disagree by more than `asymmetry_limit`, no
    verdict is reached whatever the pooled mean says.
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
    if mean >= sound_floor:
        return ("SOUND", mean,
                f"{mean:.1f} is within one normative SD of {NORMATIVE_MEAN:.0f}, "
                "which is where an uninjured subject belongs.")
    if mean <= biased_ceiling:
        return ("ACTION REQUIRED", mean,
                f"{mean:.1f} is at the level our existing cohort scores "
                f"({COHORT_MEAN:.1f}), not the level a healthy subject should.")
    return ("INCONCLUSIVE", mean,
            f"{mean:.1f} falls between the two explanations "
            f"({biased_ceiling:.0f}-{sound_floor:.0f}); neither is supported "
            "over the other by this subject alone.")


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
    lines.append(f"                   our 3 subjects  {COHORT_MEAN:6.2f} "
                 f"+/- {COHORT_SD:.2f}   (audit section 12)")
    lines.append("")
    lines.append(f"VERDICT: {status}")
    lines.append(f"  {detail}")
    lines.append("")

    if status == "SOUND":
        lines.append("  Reading: the coordinate frame is sound, and the lower "
                     "scores from the existing")
        lines.append("  cohort are real impairment rather than a pipeline "
                     "artefact. GDI may be reported")
        lines.append("  on the published normative scale.")
    elif status == "ACTION REQUIRED":
        lines.append("  Reading: the pipeline carries a systematic offset "
                     "against the optical-mocap")
        lines.append("  cohort, so absolute GDI is not on the published scale "
                     "and every reported score")
        lines.append("  needs rescaling. Do NOT fit a correction to the "
                     "existing participants -- that")
        lines.append("  subtracts the impairment GDI measures (audit section "
                     "12). Rebuild the reference")
        lines.append("  from healthy subjects captured through THIS pipeline, "
                     "or derive a correction")
        lines.append("  from a concurrent-capture study.")
    else:
        lines.append("  Reading: not settled. One more control subject is the "
                     "cheapest way forward.")

    lines.append("")
    lines.append("  Either way, within-pipeline comparison (trial to trial, "
                 "leg to leg, session to")
    lines.append("  session) was never in question and stays valid -- the "
                 "offset, if any, is common")
    lines.append("  to every score and cancels.")

    if mean is not None and len(strides) >= MIN_STRIDES:
        lines.append("")
        lines.append("  Caveat: one subject. The two explanations sit 20 "
                     "points apart against a")
        lines.append("  normative SD of 10, so a single control is suggestive "
                     "rather than conclusive;")
        lines.append("  two or three make it solid.")
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
    status, mean, detail = verdict(strides, side_means(scores))
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
