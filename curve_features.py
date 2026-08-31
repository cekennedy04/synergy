"""Turn exported gait-cycle curve matrices into GDI feature vectors.

Built 2026-08-30. Phase 3.2, and the bridge Phase 3.4 needs: nothing connected
the pipeline's own exports to `gdi.py` before this.

**Two different layouts, and they are not the same shape.** The pipeline
exports `(38 coordinates x 101 points) = 3838` rows, one column per stride.
GDI is defined on `(9 canonical variables x 51 points) = 459`, from which the
reduced sets take rows. Neither the coordinate list nor the sampling agrees,
so a feature vector cannot be sliced out of an export -- it has to be built by
name, at the right points, in the canonical order.

**Row position is the only label.** The exported CSVs carry no header, by
deliberate design in `combine_curves` (the downstream MATLAB reads
positionally and hard-codes row indices). So the coordinate ordering is read
from the same `JOINT_NAMES` list the exporter used, rather than assumed here.
If that list changes, this module follows it; if it is hardcoded in two
places, they drift and every score silently shifts by one coordinate.

**Why the export is not simply reduced to 6.** Rows 33-35 are `comx/comy/comz`
and rows 20-22 are the lumbar coordinates. UCM's intended configuration is 18
DOFs including lumbar and both legs, plus a pelvis-relative COM task variable;
GDI uses none of them. Shrinking the shared export to GDI's six would delete
the UCM inputs to save disk. The projection therefore happens here, at
feature-build time, and the export stays wide.

Usage:
    python curve_features.py --curves COMBINED.csv --side right \\
        --reference DIR [--feature-set reduced6]
"""
import argparse
import importlib.util
import re
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent

# The exporter writes one 101-point block per coordinate, in this order.
EXPORT_POINTS_PER_COORDINATE = 101

# Which leg's coordinates a "left"/"right" curve file carries. The exports are
# named by side, and a GDI feature set is built per side.
SIDE_SUFFIX = {"right": "r", "left": "l", "r": "r", "l": "l"}


def _load_gdi():
    spec = importlib.util.spec_from_file_location("_gdi_for_curves",
                                                  REPO_ROOT / "gdi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exported_row_order(repo_root=REPO_ROOT):
    """Coordinate ordering of the exported matrices, read from the driver.

    Deliberately parsed from `Examples/gaitAnalysis-UCM.py`'s JOINT_NAMES
    rather than duplicated, for the reason in the module docstring. This is
    the same source `make_comparison_figures.joint_names` reads.
    """
    source = (Path(repo_root) / "Examples" / "gaitAnalysis-UCM.py").read_text(
        encoding="utf-8")
    match = re.search(r"JOINT_NAMES = \[(.*?)\]", source, re.S)
    if match is None:
        raise ValueError(
            f"no JOINT_NAMES list found in {repo_root}/Examples/"
            "gaitAnalysis-UCM.py. The exported CSVs are headerless, so without "
            "it row position cannot be resolved to a coordinate at all."
        )
    return [name.strip().strip("'\"")
            for name in match.group(1).replace("\n", " ").split(",")
            if name.strip()]


def load_curve_matrix(path, row_order=None):
    """One exported curve matrix as (n_coordinates x 101, n_strides).

    Validated against the coordinate list, because a matrix whose row count is
    not a whole number of coordinates has come from a different exporter and
    every row index below would be wrong.
    """
    row_order = row_order or exported_row_order()
    matrix = np.atleast_2d(np.genfromtxt(str(path), delimiter=","))
    if matrix.shape[0] == 1 and matrix.shape[1] > 1:
        matrix = matrix.T  # a single-stride file reads back as one long row

    expected = len(row_order) * EXPORT_POINTS_PER_COORDINATE
    if matrix.shape[0] != expected:
        raise ValueError(
            f"{path} has {matrix.shape[0]} rows; an exported curve matrix must "
            f"have {expected} ({len(row_order)} coordinates x "
            f"{EXPORT_POINTS_PER_COORDINATE} points). Row position is the only "
            "thing identifying a coordinate in these files, so a different row "
            "count means the ordering cannot be trusted."
        )
    if not np.isfinite(matrix).all():
        raise ValueError(f"{path} contains non-finite values.")
    return matrix


def coordinate_block(matrix, name, row_order):
    """The (101, n_strides) block for one coordinate."""
    try:
        index = row_order.index(name)
    except ValueError:
        raise KeyError(
            f"coordinate {name!r} is not in the exported row order "
            f"({len(row_order)} coordinates). GDI cannot be built from this "
            "export without it."
        ) from None
    start = index * EXPORT_POINTS_PER_COORDINATE
    return matrix[start:start + EXPORT_POINTS_PER_COORDINATE, :]


def to_feature_vectors(matrix, side, feature_set=None, gdi=None, row_order=None):
    """Feature vectors for every stride: (vector_length, n_strides).

    Sampled at GDI's own 51 points and assembled in the feature set's order,
    with the per-variable adjustments applied through the same table `gdi.py`
    uses -- so a reduced set that drops pelvis drops the adjustments with it.
    """
    gdi = gdi or _load_gdi()
    feature_set = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    row_order = row_order or exported_row_order()
    suffix = SIDE_SUFFIX.get(str(side).lower())
    if suffix is None:
        raise ValueError(f"side must be one of {sorted(SIDE_SUFFIX)}, got {side!r}")

    points = np.array(gdi.GDI_CYCLE_POINTS, dtype=int)
    blocks = []
    for template in feature_set.features:
        name = template.format(side=suffix)
        block = coordinate_block(matrix, name, row_order)[points, :]
        adjust = gdi._CURVE_ADJUSTMENTS.get(template)
        if adjust is not None:
            block = np.vectorize(adjust)(block)
        blocks.append(block)

    vectors = np.vstack(blocks)
    assert vectors.shape[0] == feature_set.vector_length, vectors.shape
    return vectors


def score_curves(matrix, side, reference, feature_set=None, gdi=None,
                 row_order=None):
    """GDI for every stride in an exported curve matrix."""
    gdi = gdi or _load_gdi()
    feature_set = gdi.get_feature_set(
        feature_set or reference.get("feature_set", gdi.DEFAULT_FEATURE_SET))
    vectors = to_feature_vectors(matrix, side, feature_set, gdi, row_order)
    return np.array([gdi.compute_gdi(vectors[:, i], reference, feature_set)
                     for i in range(vectors.shape[1])])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--curves", required=True,
                        help="An exported curve matrix (headerless).")
    parser.add_argument("--side", default="right", choices=sorted(SIDE_SUFFIX))
    parser.add_argument("--reference", required=True,
                        help="Directory holding the GDI reference pair.")
    parser.add_argument("--feature-set", default=None)
    args = parser.parse_args(argv)

    gdi = _load_gdi()
    feature_set = gdi.get_feature_set(args.feature_set or gdi.DEFAULT_FEATURE_SET)
    reference = gdi.load_gdi_reference(args.reference, feature_set)
    matrix = load_curve_matrix(args.curves)
    scores = score_curves(matrix, args.side, reference, feature_set, gdi)

    print(f"{Path(args.curves).name}  [{feature_set.name}, {args.side}]")
    print(f"  strides {scores.size}")
    print(f"  GDI     mean {scores.mean():.1f}  sd {scores.std():.1f}  "
          f"range {scores.min():.1f}-{scores.max():.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
