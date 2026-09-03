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

  * It does not compute a synergy/UCM index. No uncontrolled-manifold math
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
import math
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
# The upper limb WAS listed here, from 2026-08-25 until the calibration-pose
# defect behind it was fixed on 2026-09-02. It is deliberately empty rather
# than deleted: an empty set with this comment says "we looked, and the arms
# are no longer excluded", which is a different statement from a missing
# constant.
#
# What changed: IMUPlacer was calibrating the Xsens T-pose against an
# arms-down model default, burying 90 deg of shoulder abduction in the arm IMU
# offsets and driving arm_flex/arm_rot to the model's +/-572.96 deg bounds.
# xsens_to_opensim.CALIBRATION_POSES now poses the model to match the
# calibration frame. Post-fix the arms agree with Xsens's own <jointAngle>
# solver to within a few degrees and their across-stride SDs sit in the same
# range as OpenCap's -- see VENDORING.md's 2026-09-02 entry for the numbers.
#
# `saturated_coordinates` below is the general form of this check, and is what
# should catch the next one: exclude on measured evidence, not on a list.
INVALID_IMU_ONLY = set()
INVALID_IMU_REASON = (
    "No coordinate is excluded outright for the IMU route. The arm coordinates "
    "were, until the 2026-09-02 calibration-pose fix; run the bound-saturation "
    "check (see saturated_coordinates) rather than reinstating a fixed list."
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


def read_model_coordinate_ranges(model_file):
    """{coordinate name: (min_deg, max_deg)} from an .osim file's own
    <Coordinate> ranges, for the rotational coordinates.

    Read out of the XML with the standard library rather than through the
    opensim bindings, so the saturation check below runs in any interpreter --
    the whole point of it is to be cheap enough to run over an export nobody
    is currently suspicious of.

    OpenSim stores rotational coordinate ranges in RADIANS; they are returned
    here in degrees, because that is the unit the exported curve matrices are
    in and comparing the two in different units is exactly the kind of silent
    mistake this function exists to catch elsewhere.

    Translational coordinates (pelvis_tx/ty/tz) are left out for that same
    reason: their ranges are metres, and radians-to-degrees on a metre reads
    as a plausible +/-5729 rather than as an error. Which coordinates are
    translational is taken from each joint's own SpatialTransform -- a
    <TransformAxis name="translation1..3"> names the coordinate it drives --
    rather than from the names, since a 4.x .osim carries no motion_type
    element and "anything called _t*" is a guess about this one model.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(str(model_file)).getroot()

    translational = set()
    for axis in root.iter("TransformAxis"):
        if not (axis.get("name") or "").startswith("translation"):
            continue
        driven = axis.findtext("coordinates", default="")
        translational.update(driven.split())

    ranges = {}
    for coordinate in root.iter("Coordinate"):
        name = coordinate.get("name")
        range_el = coordinate.find("range")
        if name is None or name in translational:
            continue
        if range_el is None or range_el.text is None:
            continue
        low, high = (float(v) for v in range_el.text.split())
        ranges[name] = (math.degrees(low), math.degrees(high))
    return ranges


def saturated_coordinates(summary, model_ranges, tolerance_deg=1.0):
    """Coordinates in `summary` whose exported values reach a model bound.

    Returns {coordinate: {"bound": "min"|"max", "limit": deg, "reached": deg}}
    for every coordinate that came within `tolerance_deg` of one of its own
    joint limits. Empty is the healthy answer.

    WHY (2026-09-02). A coordinate pinned against its bound is not a
    measurement: it is the IK solver reporting that it ran out of room, and in
    a table of degrees it looks exactly like a real number. The arm defect
    fixed on 2026-09-02 sat in the exports for two weeks reading -566 deg
    against a -572.96 deg bound, visible only in a prose note, because nothing
    in the code ever compared an export against the model's own limits. It
    does now.

    A coordinate with no entry in `model_ranges` is skipped rather than
    guessed at -- comx/comy/comz and the computed fpa_r/fpa_l are in the
    export but are not model coordinates, and translations have no meaningful
    degree bound.

    Tolerance rather than exact equality because IK stops just shy of a limit
    rather than exactly on it. One degree is tight enough not to fire on real
    motion that happens to use a joint's full range and loose enough to catch
    a pinned coordinate.
    """
    flagged = {}
    for name, values in summary["coordinates"].items():
        limits = model_ranges.get(name)
        if limits is None:
            continue
        low, high = limits
        if values["min"] <= low + tolerance_deg:
            flagged[name] = {"bound": "min", "limit": low, "reached": values["min"]}
        elif values["max"] >= high - tolerance_deg:
            flagged[name] = {"bound": "max", "limit": high, "reached": values["max"]}
    return flagged


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
        "available": False,
        "reason": (
            "No uncontrolled-manifold implementation exists in this repository or "
            "its history -- no nullspace projection, no V_UCM/V_ORT decomposition, "
            "no task-variable Jacobian. The task variable is also undecided. Note "
            "that a global-COM formulation is available to the OpenCap methodology "
            "but NOT to the IMU one, whose root translation is pinned; the COM "
            "columns in both exports are expressed relative to pelvis translation."
        ),
    }


def format_report(summary_by_method, names, model_ranges=None,
                  saturation_tolerance_deg=1.0):
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

    if model_ranges:
        lines.append("")
        lines.append("Coordinates pinned against a model joint bound "
                     f"(within {saturation_tolerance_deg:g} deg)")
        any_flagged = False
        for method, summary in summary_by_method.items():
            flagged = saturated_coordinates(summary, model_ranges,
                                            tolerance_deg=saturation_tolerance_deg)
            for name, entry in sorted(flagged.items()):
                any_flagged = True
                lines.append(
                    f"  {method:<10}{name:<18}{entry['bound']:>4} bound "
                    f"{entry['limit']:>9.2f}, reached {entry['reached']:>9.2f}"
                )
        if not any_flagged:
            lines.append("  none -- every coordinate stays inside its own joint limits")
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
    parser.add_argument(
        "--model", default=None,
        help="Scaled .osim whose coordinate ranges the bound-saturation check "
             "uses. Omitting it skips the check and says so, rather than "
             "printing nothing and reading as a clean result.",
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
    model_ranges = read_model_coordinate_ranges(args.model) if args.model else None
    print(format_report(summaries, names, model_ranges))
    if model_ranges is None:
        print("\nCoordinates pinned against a model joint bound")
        print("  not checked -- pass --model <scaled .osim> to run it. Skipping "
              "it silently is how a coordinate saturating against its own "
              "limit stayed in these exports unnoticed for two weeks "
              "(see the 2026-09-02 calibration-pose fix).")

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
