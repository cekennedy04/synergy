"""Regenerate a GDI normative reference from a pooled control cohort.

Phase 3.3 of `docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md`.
Built 2026-08-27. Replaces the MATLAB that produced the archived matrices.

A GDI reference is three things that must be produced together from one
cohort: an orthonormal basis, that cohort's mean in the projected space, and
the mean and SD of the cohort's log distances from it. `gdi.py` refuses to
score a feature set whose constants were never attributed; this is what
attributes them.

**The method, and the evidence for it.** The archived `matrix_control.csv` is
459x15 with unit-norm, mutually orthogonal columns (off-diagonals of MtM below
1.2e-6), so it is an SVD basis. It is *not* the basis of the pooled
`control_kinematics.csv` in the same folder -- that matrix's own leading 15
left singular vectors sit at principal angles up to 71 degrees from it -- so
the two artefacts come from different control samples and the archived one
cannot be bit-reproduced. What could be established is the preprocessing: the
archived basis captures 97.8% of the raw pooled matrix's energy but only 87.6%
of the mean-centred version's, and the first singular value (3917 against 837
for the second) is the DC direction that centring removes. The SVD is
therefore taken on the **raw** matrix, not a centred one.

**Neither built-in check validates the reference. Both are much weaker than
they look.**

`self_consistency` is a pure identity: `ln_control_mean` and `ln_control_sd`
are *defined* as the control group's own log-distance mean and SD, so that
group scores exactly 100 +/- 10 through any basis whatsoever, a random one
included. It catches an implementation slip and nothing else.

`held_out_report` was written to escape that tautology by scoring cycles the
reference never saw. **On this cohort it does not escape it.** Substituting a
random orthonormal basis -- carrying no information about the controls -- into
the same five-fold procedure gives held-out 99.8 +/- 10.2 against the true
basis's 100.2 +/- 10.3. It also cannot see over-fitting at any component
count, returning ~100 even at 130 components from 132 training columns. The
cause is the data: pooled control gait cycles have median pairwise correlation
0.89, so a held-out cycle already lies almost inside the training span whatever
basis is chosen, and the residual it would need to detect is not there.

So a passing held-out report is not evidence the basis is good. Use it only to
catch the opposite -- a report far from 100 means something is genuinely
broken. Real validation needs an independent control group, which this project
does not have. What the regenerated references do offer is narrower and worth
stating honestly: orthonormality by construction, a recorded component count
and variance captured, and a sidecar naming the cohort and both constants.
That is reproducibility, not validation.

**Regenerating invalidates comparisons.** A new basis, a new control mean and
new constants mean the resulting scores are not comparable to any number
produced against a previous reference. Say so wherever the new scores appear.

Usage:
    python gdi_reference.py --control-matrix POOLED.csv --feature-set reduced6 \\
        --out-dir DIR [--components 15 | --variance 0.98]
"""
import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent


def _load_gdi():
    spec = importlib.util.spec_from_file_location(
        "_gdi_for_reference", REPO_ROOT / "gdi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pooled_matrix(path, gdi=None, feature_set=None):
    """A pooled cohort matrix as (vector_length x n_cycles), rows selected.

    The file is expected in canonical 9-variable order -- 459 rows, one column
    per gait cycle -- because that is what the curve-export path produces and
    what `control_kinematics.csv` is. Reduced sets take a row subset.
    """
    gdi = gdi or _load_gdi()
    matrix = np.genfromtxt(str(path), delimiter=",")
    matrix = np.atleast_2d(matrix)

    canonical_rows = len(gdi._CANONICAL_9) * gdi.GDI_N_POINTS
    if matrix.shape[0] != canonical_rows:
        raise ValueError(
            f"{path} has {matrix.shape[0]} rows; a pooled cohort matrix must have "
            f"{canonical_rows} ({len(gdi._CANONICAL_9)} canonical variables x "
            f"{gdi.GDI_N_POINTS} points), one column per gait cycle. A file with "
            "already-reduced rows cannot be used here, because which variables "
            "were dropped is not recoverable from the row count alone."
        )
    if not np.isfinite(matrix).all():
        raise ValueError(
            f"{path} contains non-finite values. An SVD over them yields a basis "
            "of NaNs that fails silently downstream."
        )

    if feature_set is not None:
        matrix = matrix[gdi.canonical_row_indices(feature_set), :]
    return matrix


def choose_components(singular_values, n_components=None, variance=None):
    """How many singular vectors to keep, and what that captures.

    One of `n_components` or `variance` must be given. The archived matrices
    kept 14, 15, 26, 27, 28, 30, 31 and 34 across variants, which says this was
    tuned rather than fixed -- so it is an explicit argument here, and the
    variance actually captured is always reported rather than assumed.
    """
    if (n_components is None) == (variance is None):
        raise ValueError(
            "give exactly one of n_components or variance: the number of "
            "retained components is a real modelling choice and must not be "
            "defaulted silently."
        )
    energy = np.square(singular_values)
    total = float(energy.sum())
    if n_components is None:
        cumulative = np.cumsum(energy) / total
        n_components = int(np.searchsorted(cumulative, variance) + 1)
    n_components = int(min(n_components, len(singular_values)))
    captured = float(energy[:n_components].sum() / total)
    return n_components, captured


def build_reference(control_matrix, n_components=None, variance=None):
    """Basis, control mean and normative constants from one control cohort.

    `control_matrix` is (vector_length x n_cycles), already row-selected for
    the feature set. Returns the pieces `gdi.compute_gdi` needs plus the
    diagnostics needed to write an honest provenance record.
    """
    control_matrix = np.asarray(control_matrix, dtype=float)
    length, n_cycles = control_matrix.shape
    if n_cycles < 2:
        raise ValueError(
            f"a control cohort of {n_cycles} cycle(s) cannot define a normative "
            "distribution: the SD of its log distances is undefined."
        )

    # Raw, not mean-centred -- see the module docstring for the evidence.
    basis_full, singular_values, _ = np.linalg.svd(control_matrix,
                                                   full_matrices=False)
    n_components, captured = choose_components(singular_values, n_components,
                                               variance)
    basis = basis_full[:, :n_components]          # (length x n_components)

    projected = basis.T @ control_matrix          # (n_components x n_cycles)
    control_mean = projected.mean(axis=1)

    # ANSWERED 2026-09-01: one column is ONE STRIDE -- a single gait cycle of a
    # single limb. Not a subject, not a per-limb average. So the per-column
    # treatment below is correct and the constants stay as they are.
    #
    # Three independent lines of evidence agreed:
    #
    # 1. The method. Herrera-Valenzuela et al. 2022 (10.3389/fbioe.2022.874074),
    #    which re-derives GDI for SCI and is the closest published analogue of
    #    this project's `sciflag` path: "a matrix with kinematic data from
    #    several walking strides where each column vector is a stride
    #    represented by nine joint angles of a whole gait cycle extracted at 2%
    #    increments". Its own control group is counted the same way -- "446
    #    strides from adults without gait pathologies". Sinovas-Alonso et al.
    #    2022 (10.3389/fnhum.2022.826333) states the distance is taken to "the
    #    average of a set of healthy control strides". Both trace to Schwartz &
    #    Rozumalski 2008, whose basis came from >6,000 CP strides.
    #    The same sources independently confirm 9 variables x 51 points = 459,
    #    15 retained features, and that the ninth variable is the foot
    #    progression angle -- corroborating the fpa-not-subtalar recovery.
    #
    # 2. The supervisor's own code. `context/replay-os-small/gaitAnalysis.py`
    #    lines 763-810 build `indiv_data` as 459 x (n_right_cycles +
    #    n_left_cycles), one column per gait cycle per limb, right block then
    #    left block, and write it unsuffixed. That is this file's shape.
    #
    # 3. The file. 166 columns carry an 83-pair structure -- cohort-centred
    #    correlation +0.37..+0.73 within pairs against ~+0.04 across pair
    #    boundaries, present at lag 1 only. Adjacent strides sharing a subject
    #    is exactly what pooling per-trial exports produces.
    #
    # WHAT THIS RETIRES. An earlier reading of the pairing suggested rebuilding
    # the reference at 83 units, which would have moved every score by about
    # +3.9 points and 7% of scale. That rebuild is NOT correct and must not be
    # done: the stride is the unit the method defines, so 166 is the right
    # count. The pairing still means the effective sample is nearer 83 than 166
    # for any confidence interval on these constants -- it bears on precision,
    # not on the unit.
    #
    # STILL OPEN, and narrower: this file was not written by the driver above.
    # The driver adds +20 to pelvis_tilt; this file's column-mean pelvis_tilt is
    # 11.99, i.e. raw. It is an earlier artefact of the collaborator's, so which
    # cohort and which pipeline produced it remains unestablished. See the
    # pelvis_tilt note in gdi.py, which is a live defect for `gdi9`.
    distances = np.linalg.norm(projected - control_mean[:, None], axis=0)
    if np.any(distances <= 0.0):
        raise ValueError(
            "at least one control cycle projects exactly onto the control mean, "
            "so ln(0) is undefined. This usually means duplicate columns in the "
            "pooled matrix."
        )
    log_distances = np.log(distances)

    return {
        "basis": basis,
        "control_mean": control_mean,
        # Population SD (ddof=0): these constants describe the cohort that
        # defines the norm, not a sample drawn from a wider one.
        "ln_control_mean": float(log_distances.mean()),
        "ln_control_sd": float(log_distances.std(ddof=0)),
        "n_components": n_components,
        "n_cycles": int(n_cycles),
        "vector_length": int(length),
        "variance_captured": captured,
        "singular_values": singular_values,
    }


def score_against(reference, matrix):
    """GDI for every column of `matrix` against a built reference."""
    projected = reference["basis"].T @ np.asarray(matrix, dtype=float)
    distances = np.linalg.norm(projected - reference["control_mean"][:, None],
                               axis=0)
    z = (np.log(distances) - reference["ln_control_mean"]) / reference["ln_control_sd"]
    return 100.0 - 10.0 * z


def self_consistency(reference, control_matrix):
    """The by-construction identity, asserted as arithmetic.

    Scoring the defining cohort against its own reference must give mean 100
    and SD 10 for *any* basis, so this catches an implementation slip and
    nothing else. It is not evidence that the reference is good.
    """
    scores = score_against(reference, control_matrix)
    return {"mean": float(scores.mean()), "sd": float(scores.std(ddof=0))}


def held_out_report(control_matrix, n_components=None, variance=None, folds=5,
                    seed=0):
    """Build on part of the cohort, score the rest. The real check.

    Unseen controls should still land near 100 with a spread near 10. A large
    gap says the reference does not generalise past the cycles that built it --
    usually too many components for the cohort size.
    """
    control_matrix = np.asarray(control_matrix, dtype=float)
    n_cycles = control_matrix.shape[1]
    if folds < 2 or n_cycles < folds * 2:
        raise ValueError(
            f"{n_cycles} cycles cannot support {folds} folds with at least two "
            "columns held out per fold."
        )

    order = np.random.default_rng(seed).permutation(n_cycles)
    held_scores = []
    for fold in range(folds):
        test_idx = order[fold::folds]
        train_idx = np.setdiff1d(order, test_idx)
        reference = build_reference(control_matrix[:, train_idx],
                                    n_components=n_components, variance=variance)
        held_scores.append(score_against(reference, control_matrix[:, test_idx]))

    held = np.concatenate(held_scores)
    return {
        "n_held_out": int(held.size),
        "mean": float(held.mean()),
        "sd": float(held.std(ddof=0)),
        "min": float(held.min()),
        "max": float(held.max()),
    }


def write_reference(reference, out_dir, feature_set, gdi=None):
    """Write the matrix/controlCalc pair plus a provenance sidecar.

    Filenames come from the feature set, so a reference can only be written
    where `gdi.load_gdi_reference` will look for it. The sidecar is the thing
    the archived files lack: without it, a matrix on disk carries no record of
    which cohort, how many components, or which constants belong with it --
    which is how the 4.443685139 pair ended up attached to nothing.
    """
    gdi = gdi or _load_gdi()
    feature_set = gdi.get_feature_set(feature_set)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if reference["vector_length"] != feature_set.vector_length:
        raise ValueError(
            f"reference was built for {reference['vector_length']}-value vectors "
            f"but feature set {feature_set.name!r} needs "
            f"{feature_set.vector_length}."
        )

    matrix_path = out_dir / feature_set.matrix_filename
    with open(matrix_path, "w", newline="") as handle:
        csv.writer(handle).writerows(reference["basis"])
    control_path = out_dir / feature_set.control_filename
    with open(control_path, "w", newline="") as handle:
        csv.writer(handle).writerow(reference["control_mean"])

    sidecar = out_dir / f"{feature_set.name}_reference.json"
    with open(sidecar, "w", encoding="utf-8") as handle:
        json.dump({
            "feature_set": feature_set.name,
            "features": list(feature_set.features),
            "vector_length": reference["vector_length"],
            "n_components": reference["n_components"],
            "n_control_cycles": reference["n_cycles"],
            "variance_captured": reference["variance_captured"],
            "ln_control_mean": reference["ln_control_mean"],
            "ln_control_sd": reference["ln_control_sd"],
            "matrix_file": feature_set.matrix_filename,
            "control_file": feature_set.control_filename,
            # One column of the pooled cohort is one gait cycle, so both
            # constants above are moments of per-cycle log distances and only
            # a per-cycle score is calibrated against them. Recorded here
            # because it is not recoverable from the matrix.
            "scoring_unit": gdi.SCORING_UNIT_CYCLE,
            # Paste this onto the feature set in gdi.py alongside the
            # constants: load_gdi_reference refuses a matrix whose digest does
            # not match, which is the only check that can tell a correct basis
            # from a correct-looking one belonging to another cohort.
            "reference_digest": gdi.reference_digest(
                reference["basis"].T, reference["control_mean"]),
            "note": (
                "Scores from this reference are not comparable to any produced "
                "against a different one. Set ln_control_mean/ln_control_sd on "
                "the feature set in gdi.py to these values to enable scoring, "
                "and reference_digest to the value above."
            ),
        }, handle, indent=2)
    return matrix_path, control_path, sidecar


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--control-matrix", required=True,
                        help="Pooled control cohort, 459 rows x n_cycles.")
    parser.add_argument("--feature-set", default="reduced6")
    parser.add_argument("--out-dir", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--components", type=int)
    group.add_argument("--variance", type=float)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args(argv)

    gdi = _load_gdi()
    feature_set = gdi.get_feature_set(args.feature_set)
    matrix = load_pooled_matrix(args.control_matrix, gdi, feature_set)

    reference = build_reference(matrix, n_components=args.components,
                                variance=args.variance)
    check = self_consistency(reference, matrix)
    held = held_out_report(matrix, n_components=args.components,
                           variance=args.variance, folds=args.folds)
    paths = write_reference(reference, args.out_dir, feature_set, gdi)

    print(f"feature set      {feature_set.name} "
          f"({feature_set.n_features} vars x {gdi.GDI_N_POINTS} = "
          f"{reference['vector_length']})")
    print(f"control cycles   {reference['n_cycles']}")
    print(f"components       {reference['n_components']} "
          f"({reference['variance_captured']:.4%} of variance)")
    print(f"ln_control_mean  {reference['ln_control_mean']:.6f}")
    print(f"ln_control_sd    {reference['ln_control_sd']:.6f}")
    print(f"self-check       mean {check['mean']:.4f} / sd {check['sd']:.4f} "
          "(100 / 10 by construction -- an arithmetic check, not a validation)")
    print(f"held-out         n={held['n_held_out']} mean {held['mean']:.2f} / "
          f"sd {held['sd']:.2f}, range {held['min']:.1f}-{held['max']:.1f}")
    for path in paths:
        print(f"wrote            {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
