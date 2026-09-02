"""Compare what the Xsens/IMU and OpenCap/video methodologies produce across
multiple trials, from the per-gait-cycle curve matrices both pipelines export.

Motivation (2026-08-25): the clinician GUI processes one trial at a time, but
GDI and any synergy (UCM) index need variance across strides, and the research
question is what each *methodology* yields. This reads the exported curve CSVs
for both and reports them side by side.

Input format. `export_individual_curves_csv` writes a bare numeric matrix via
`np.savetxt` -- no coordinate-name or frame-index columns (the pre-rewrite
version did the same, so this is the established format, not a regression).
Rows are therefore positional: `JOINT_NAMES[i]` occupies rows `i*101` to
`i*101+100`, and each column is one gait cycle. `JOINT_NAMES` is imported from
the driver rather than duplicated here, so a change there cannot silently
desynchronise this module's row mapping.

What this module does NOT do:

  * It does not itself compute a synergy/UCM index (ucm.py and trial_scores.py
    do). No uncontrolled-manifold math
    exists anywhere in this repository or its history, and the task variable
    is an open domain question -- see VENDORING.md. `synergy_status()` reports
    that explicitly rather than returning a placeholder number.
  * It does not invent GDI reference data. `gdi_comparison` computes GDI for
    both methodologies when the normative CSVs are present and reports the
    blockage clearly when they are not.

Both of those are external blockers, and reporting them as such is the point:
a silent zero or a NaN would be indistinguishable from a real result.
"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
POINTS_PER_CYCLE = 101

# Coordinates known to be unusable, with the reason. Recorded here so a
# variance decomposition strips them rather than projecting noise into its
# subspaces -- see VENDORING.md's batch-inspection section for the evidence.
DEGENERATE_ALWAYS = {
    "mtp_angle_r": "unconstrained in both pipelines; frozen at a constant",
    "mtp_angle_l": "unconstrained in both pipelines; frozen at a constant",
}
DEGENERATE_IMU_ONLY = {
    "pelvis_tx": "root translation is pinned by orientation-only IK",
    "pelvis_ty": "root translation is pinned by orientation-only IK",
    "pelvis_tz": "root translation is pinned by orientation-only IK",
}
INVALID_IMU_ONLY = {
    "arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r", "pro_sup_r",
    "arm_flex_l", "arm_add_l", "arm_rot_l", "elbow_flex_l", "pro_sup_l",
}
INVALID_IMU_REASON = (
    "T-pose calibration against an arms-down model default drives the shoulder "
    "coordinates to their joint bounds (arm_flex_l reaches -566 deg, arm_rot_l "
    "+573 deg = 10 rad). Three saturate outright; the rest share the same "
    "corrupted calibration and are coupled through the shoulder Euler triplet."
)


def joint_names(repo_root=REPO_ROOT):
    """JOINT_NAMES from the driver, in export row order.

    Imported rather than copied: the CSVs carry no labels, so this ordering is
    the only thing that maps a row block to a coordinate. A local copy would
    drift silently and mislabel every result.
    """
    # utils.py calls get_token() at import time and blocks on an interactive
    # OpenCap login; the driver's own heavy imports are deferred, but this
    # guard keeps the module importable in any context.
    os.environ.setdefault("API_TOKEN", "methodology-comparison-placeholder")
    driver_path = Path(repo_root) / "Examples" / "gaitAnalysis-UCM.py"
    spec = importlib.util.spec_from_file_location("_ucm_driver_for_comparison", driver_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return list(module.JOINT_NAMES)


def load_curve_matrix(path, names):
    """Load one exported matrix and slice it into {coordinate: (101 x cycles)}."""
    matrix = np.loadtxt(path, delimiter=",", ndmin=2)
    expected = len(names) * POINTS_PER_CYCLE
    if matrix.shape[0] != expected:
        raise ValueError(
            f"{path}: has {matrix.shape[0]} rows but JOINT_NAMES implies "
            f"{expected} ({len(names)} coordinates x {POINTS_PER_CYCLE} points). "
            "The export's coordinate list and this reader have diverged -- the "
            "CSVs carry no labels, so the row mapping would be silently wrong."
        )
    return {
        name: matrix[i * POINTS_PER_CYCLE:(i + 1) * POINTS_PER_CYCLE, :]
        for i, name in enumerate(names)
    }


def across_stride_sd(block):
    """Mean across-stride standard deviation, in the export's units (degrees
    for angles, metres for COM). Returns nan for a single-stride trial, where
    across-stride variance is undefined rather than zero."""
    if block.shape[1] < 2:
        return float("nan")
    return float(np.mean(np.std(block, axis=1)))


def summarise_methodology(curve_dir, prefix, trials, names, side="right"):
    """Per-coordinate stride counts, variability and range for one methodology."""
    curve_dir = Path(curve_dir)
    per_trial, blocks = {}, {name: [] for name in names}
    for trial in trials:
        path = curve_dir / f"{prefix}{trial}_{side}.csv"
        if not path.is_file():
            continue
        loaded = load_curve_matrix(path, names)
        per_trial[trial] = next(iter(loaded.values())).shape[1]
        for name, block in loaded.items():
            blocks[name].append(block)

    if not per_trial:
        raise FileNotFoundError(
            f"No curve files matched {curve_dir}/{prefix}<trial>_{side}.csv for "
            f"trials {list(trials)}. Run the curve export first."
        )

    coordinates = {}
    for name, collected in blocks.items():
        sds = [across_stride_sd(b) for b in collected]
        sds = [v for v in sds if not np.isnan(v)]
        stacked = np.hstack(collected)
        coordinates[name] = {
            "sd": float(np.mean(sds)) if sds else float("nan"),
            "min": float(stacked.min()),
            "max": float(stacked.max()),
        }
    return {
        "trials": per_trial,
        "n_trials": len(per_trial),
        "n_strides": sum(per_trial.values()),
        "coordinates": coordinates,
    }


def classify(name, summary_by_method):
    """Why a coordinate is or is not usable, per methodology."""
    if name in DEGENERATE_ALWAYS:
        return "degenerate (both)", DEGENERATE_ALWAYS[name]
    flags = []
    if name in DEGENERATE_IMU_ONLY:
        flags.append(("imu-degenerate", DEGENERATE_IMU_ONLY[name]))
    if name in INVALID_IMU_ONLY:
        flags.append(("imu-invalid", INVALID_IMU_REASON))
    if flags:
        return flags[0]
    zero = [
        method for method, summary in summary_by_method.items()
        if summary["coordinates"][name]["sd"] == 0.0
    ]
    if len(zero) == len(summary_by_method):
        return "degenerate (both)", "zero across-stride variance in every methodology"
    if zero:
        return f"degenerate ({', '.join(zero)})", "zero across-stride variance"
    return "usable", ""


def gdi_comparison(results_by_method, reference_dir=None, repo_root=REPO_ROOT,
                   feature_set=None, check_digest=True):
    """GDI for each methodology, or a clear statement of what blocks it.

    `results_by_method` maps a methodology label to a run_gait_analysis result
    dict (carrying curves_r/curves_l). Returns a dict whose "available" key
    says whether a score was actually produced -- never a placeholder number.

    `feature_set` selects which GDI variable set and reference pair to use
    (see gdi.FEATURE_SETS); None takes gdi's own default. A set whose
    normative constants were never attributed reports blocked rather than
    scoring, for the same reason a missing reference does: the alternative is
    a plausible wrong number.

    `check_digest` guards the same failure one level deeper: a reference that
    loads cleanly and is a valid orthonormal basis, but belongs to a different
    control cohort than the feature set's constants. Leave it on outside tests.
    """
    spec = importlib.util.spec_from_file_location(
        "_gdi_for_comparison", Path(repo_root) / "gdi.py"
    )
    gdi = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gdi
    spec.loader.exec_module(gdi)

    feature_set = (gdi.DEFAULT_FEATURE_SET if feature_set is None
                   else gdi.get_feature_set(feature_set))

    if reference_dir is None:
        return {
            "available": False,
            "reason": (
                "No GDI reference directory given. GDI is defined as distance from "
                "a normative control group and needs "
                f"{feature_set.matrix_filename} and {feature_set.control_filename} "
                f"for the {feature_set.name!r} feature set; neither is in this "
                "repository. Until they are supplied, neither methodology can "
                "produce a GDI, so there is nothing to compare."
            ),
            "scores": {},
        }
    try:
        reference = gdi.load_gdi_reference(reference_dir, feature_set,
                                           check_digest=check_digest)
    except (gdi.GdiReferenceMissingError, gdi.GdiReferenceMismatchError) as exc:
        # A mismatched reference is reported, not raised: this function's whole
        # contract is that an unusable reference produces a stated reason
        # rather than either an exception or a fabricated score, and "the basis
        # belongs to another cohort" is exactly as unusable as "the file is not
        # there".
        return {"available": False, "reason": str(exc), "scores": {}}

    if not feature_set.can_score:
        # Reference present, calibration absent. Same contract as a missing
        # reference -- report it, never fabricate a score.
        return {
            "available": False,
            "reason": (
                f"Feature set {feature_set.name!r} has no attributed normative "
                "constants, so a projection distance cannot be converted into a "
                "GDI. The reference matrix loaded fine; what is missing is the "
                "control group's ln-distance mean and SD. Regenerate them from "
                "the control cohort, or use a feature set that has them."
            ),
            "scores": {},
        }

    return {
        "available": True,
        "reason": "",
        "scores": {
            method: gdi.gdi_for_trial(results, reference, feature_set)
            for method, results in results_by_method.items()
        },
    }


def synergy_status():
    """Why no synergy index is reported.

    Deliberately not a placeholder value: a zero or a NaN here would be
    indistinguishable from a computed result in a downstream table.
    """
    return {
        "available": True,
        "reason": (
            "An uncontrolled-manifold implementation now exists: ucm.py (built "
            "2026-08-25) provides the nullspace projection and the V_UCM/V_ORT "
            "decomposition, task_functions.py the task-variable Jacobian, and "
            "trial_scores.py drives them per trial for the clinician report. "
            "This function previously stated that none of it existed, which was "
            "true when written and is not now."
        ),
        "caveat": (
            "The TASK VARIABLE remains undecided, and it is not a detail: "
            "measured 2026-08-25, the ranking between methodologies reverses "
            "with it (pelvis-relative COM gives Xsens 0.407 against OpenCap "
            "0.803; foot placement gives 0.475 against 0.179 -- same strides, "
            "same joints, same code). Any reported index must therefore name "
            "its formulation. ucm.py's documented default, pelvis-relative "
            "centre of mass, is what trial_scores.py uses. A global-COM "
            "formulation is available to the OpenCap methodology but NOT to "
            "the IMU one, whose root translation is pinned; the COM columns in "
            "both exports are expressed relative to pelvis translation, which "
            "is what keeps the two methodologies comparable at all."
        ),
    }


def format_report(summary_by_method, names):
    lines = []
    lines.append("Strides available per methodology")
    lines.append(f"  {'methodology':<12}{'trials':>8}{'strides':>10}")
    for method, summary in summary_by_method.items():
        lines.append(f"  {method:<12}{summary['n_trials']:>8}{summary['n_strides']:>10}")

    methods = list(summary_by_method)
    header = f"  {'coordinate':<18}" + "".join(f"{m + ' SD':>14}" for m in methods) + "   status"
    lines.append("")
    lines.append("Across-stride SD by coordinate (degrees; metres for com*)")
    lines.append(header)
    for name in names:
        row = f"  {name:<18}"
        for method in methods:
            row += f"{summary_by_method[method]['coordinates'][name]['sd']:>14.5f}"
        status, _reason = classify(name, summary_by_method)
        lines.append(row + f"   {status}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare Xsens/IMU and OpenCap/video methodologies across trials."
    )
    parser.add_argument("--curve-dir", default=str(REPO_ROOT / "context" / "gait_curves"))
    parser.add_argument("--imu-prefix", default="CK-CK-")
    parser.add_argument("--video-prefix", default="OC-Trial")
    parser.add_argument("--side", default="right", choices=["right", "left"])
    parser.add_argument(
        "--gdi-reference", default=None,
        help="Directory holding matrix_ms_reduced.csv and controlCalc_ms_reduced.csv.",
    )
    args = parser.parse_args(argv)

    names = joint_names()
    summaries = {
        "Xsens": summarise_methodology(
            args.curve_dir, args.imu_prefix,
            [f"{n:03d}" for n in range(1, 16)], names, args.side),
        "OpenCap": summarise_methodology(
            args.curve_dir, args.video_prefix,
            [str(n) for n in range(1, 16)], names, args.side),
    }
    print(format_report(summaries, names))

    gdi_result = gdi_comparison({}, reference_dir=args.gdi_reference)
    print("\nGDI")
    print(f"  available: {gdi_result['available']}")
    if not gdi_result["available"]:
        print(f"  blocked:   {gdi_result['reason']}")

    synergy = synergy_status()
    print("\nSynergy / UCM index")
    print(f"  available: {synergy['available']}")
    print(f"  blocked:   {synergy['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
