"""Which archived trials were corrupted by the left/right swap, and which were not.

Built 2026-08-27. Companion to the re-run planned in
`docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md`.

**Why a survey exists at all.** The swap fixed by edit #13 lived inside
`segment_walking`'s `trimend()`: it returned `rHS, rTO, lHS, lTO` while the
only call site unpacked `rHS, lHS, rTO, lTO`. `trimend` is called from exactly
one place -- the auto-trim retry loop -- so a trial whose gait events came back
correctly ordered at prominence 0.3, 0.25 or 0.2 never reached it and was never
corrupted. Re-running the whole archive would therefore redo a large amount of
work that was already right. This module finds the subset that was not.

**Why it is cheap.** `gait_analysis.__init__` takes `fpa_r`/`fpa_l`, which in
the real pipeline come from an OpenSim `AnalyzeTool` pass that costs more than
everything else here combined. But they are only *stored* as coordinate columns
and read by `compute_foot_progression_angle`, which this module never calls.
Segmentation itself uses `markerDict` alone. So the survey passes 0.0 for both
and skips that pass entirely. Verified against the class, not assumed -- if a
future edit makes segmentation depend on FPA, this shortcut becomes wrong and
the constant below is where to look.

**What it deliberately does not do.** It does not judge whether a trial is
gait. The non-gait guardrail was removed on 2026-08-27 and nothing here
reinstates it: `n_gait_cycles` and `cadence` are recorded as *columns* so an
outlier is visible and sortable, never as a threshold that refuses a trial.
Reporting, not blocking.

Usage:
    python rerun_survey.py --session-dir DIR --model MODEL.osim [--out manifest.csv]

Run it with the interpreter that has OpenSim (`envs/opencap-processing`), not
the base environment.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

# Segmentation never reads these; see the module docstring. Named rather than
# inlined so the shortcut is greppable if it ever stops being true.
FPA_PLACEHOLDER = 0.0

# One row per (trial, leg): the archive's curve exports are per-side, produced
# by two separate gait_analysis instances, and each instance makes its own
# independent trip through the retry loop. A trial can be clean on one leg and
# corrupt on the other.
LEGS = ("r", "l")

SURVEY_FIELDS = (
    "trial",
    "leg",
    "verdict",
    "used_auto_trim",
    "n_auto_trims",
    "n_gait_cycles",
    "cadence_steps_per_min",
    "error",
)

# Verdicts. Three buckets, not two -- a trial that fails outright today is
# neither corrupt nor clean, it is unprocessable, and it needs the manual
# event picker rather than a re-run.
CORRUPT = "corrupt"
CLEAN = "clean"
FAILED = "failed"


def classify(used_auto_trim, error):
    """The bucket a surveyed trial belongs in.

    Kept separate from the surveying so the three-way decision can be tested
    without instantiating anything.
    """
    if error:
        return FAILED
    return CORRUPT if used_auto_trim else CLEAN


def _cadence(gait):
    """Mean cadence in steps/min, or None if it cannot be computed.

    Recorded for triage, not for screening. Wrapped because a trial with too
    few cycles raises here, and a survey that dies on its own diagnostic
    column would be worse than one that leaves the cell empty.
    """
    try:
        cadence, _units = gait.compute_cadence()
        return round(float(cadence), 2)
    except Exception:
        return None


def survey_trial(session_dir, trial_name, model_name, leg, gait_module):
    """Segment one trial-leg and report what the retry loop did.

    `gait_module` is the loaded `gait_analysis_UCM_fixed` -- injected rather
    than imported, matching `clinician_gui.run_pipeline`'s seam, because the
    real module needs OpenSim and the tests do not have it.

    Never raises for a bad trial. A survey that stops at the first
    unprocessable recording cannot survey an archive.
    """
    row = {field: None for field in SURVEY_FIELDS}
    row["trial"] = trial_name
    row["leg"] = leg

    try:
        gait = gait_module.gait_analysis(
            session_dir, trial_name, FPA_PLACEHOLDER, FPA_PLACEHOLDER,
            leg=leg, allow_manual_entry=False, modelName=model_name,
        )
    except (KeyboardInterrupt, SystemExit):
        # Never swallowed. This sweeps a whole archive; an operator who hits
        # Ctrl-C has to be able to stop it, and a survey that logged the
        # interrupt as a failed row and carried on would be unstoppable.
        raise
    except BaseException as exc:
        # Otherwise BaseException, not Exception: segment_walking raises bare
        # `Exception` for its own failures, but a KeyError from a missing
        # marker or a native OpenSim abort should land in the manifest as a
        # failed row too, rather than ending the survey.
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["verdict"] = classify(False, row["error"])
        return row

    # Checked, not defaulted: an older checkout of gait_analysis_UCM_fixed has
    # no instrumentation, and reporting "no auto-trim" for it would be a lie.
    # Absent attributes mean the survey cannot answer, which is a failed row.
    if not hasattr(gait, "usedAutoTrim"):
        row["error"] = (
            "gait_analysis has no usedAutoTrim attribute: this build predates the "
            "2026-08-27 instrumentation and cannot report whether the auto-trim "
            "path was taken."
        )
        row["verdict"] = FAILED
        return row

    row["used_auto_trim"] = bool(gait.usedAutoTrim)
    row["n_auto_trims"] = int(getattr(gait, "nAutoTrims", 0))
    row["n_gait_cycles"] = int(getattr(gait, "nGaitCycles", 0))
    row["cadence_steps_per_min"] = _cadence(gait)
    row["verdict"] = classify(row["used_auto_trim"], None)
    return row


def survey_session(session_dir, model_name, gait_module, trial_names=None,
                   progress=None):
    """Every trial-leg in one session, in stable order."""
    session_dir = Path(session_dir)
    if trial_names is None:
        trial_names = discover_trials(session_dir)

    rows = []
    for trial_name in trial_names:
        for leg in LEGS:
            if progress:
                progress(f"Surveying {trial_name} ({leg})...")
            rows.append(
                survey_trial(session_dir, trial_name, model_name, leg, gait_module)
            )
    return rows


def discover_trials(session_dir):
    """Trial names from the session's IK results, in natural order.

    The .mot files are what gait_analysis actually loads, so they are the
    authoritative list -- a .mvnx with no corresponding .mot was never
    converted and has nothing to survey.
    """
    ik_dir = Path(session_dir) / "OpenSimData" / "Kinematics"
    if not ik_dir.is_dir():
        raise FileNotFoundError(
            f"No IK results at {ik_dir}. The survey reads the converted .mot "
            "files, so the session must already have been through conversion."
        )
    return sorted(
        (path.stem for path in ik_dir.glob("*.mot")),
        key=lambda name: [int(part) if part.isdigit() else part.lower()
                          for part in _split_digits(name)],
    )


def _split_digits(text):
    return re.split(r"(\d+)", text)


def write_manifest(rows, path):
    """Write the manifest. Header included, unlike the curve exports.

    The curve matrices are headerless because MATLAB reads them positionally.
    Nothing reads this one positionally -- a human sorts it -- so a header is
    the right call here even though it differs from the convention next door.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SURVEY_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def summarise(rows):
    """Counts per verdict, for the line printed at the end of a run."""
    counts = {CORRUPT: 0, CLEAN: 0, FAILED: 0}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--model", required=True,
                        help="Model filename inside OpenSimData/Model/")
    parser.add_argument("--out", default="rerun_manifest.csv")
    parser.add_argument("--trial", action="append", dest="trials",
                        help="Survey only this trial; repeatable.")
    args = parser.parse_args(argv)

    # Reuse clinician_gui's loader rather than importing the module
    # normally: gait_analysis_UCM_fixed transitively imports opensim and
    # utils.py, and load_module_by_path is what the rest of the repo uses to
    # pull it in regardless of how the process was launched. Imported here,
    # not at module scope, so `import rerun_survey` stays free of OpenSim and
    # the tests can exercise everything above without it.
    import clinician_gui
    gait_module = clinician_gui._load_gait_analysis_ucm_fixed()

    rows = survey_session(args.session_dir, args.model, gait_module,
                          trial_names=args.trials,
                          progress=lambda msg: print(msg, file=sys.stderr))
    path = write_manifest(rows, args.out)
    counts = summarise(rows)
    print(f"{path}: {counts[CORRUPT]} corrupt, {counts[CLEAN]} clean, "
          f"{counts[FAILED]} failed (trial-legs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
