"""Combine every gait-cycle trial from one participant-session into one matrix.

Each trial's export is `(n_coordinates x 101)` rows by one column per gait
cycle. Pooling a session means concatenating along the stride axis: the rows
are identical across trials, only the number of columns differs.

Two decisions worth knowing before changing anything here.

**The combined file has no header row.** The per-trial exports do not have one
either -- row position identifies the coordinate, column position identifies
the stride -- and the downstream MATLAB (`matrix_general.m`) reads positionally
and hard-codes row indices to strip. A header would shift every one of them by
a line, so the combined file stays drop-in compatible.

**Provenance goes in a sidecar instead.** Plain concatenation loses which trial
each stride came from, which makes a pooled result unauditable. A
`<name>_index.csv` alongside maps every column back to its trial and its
position within that trial. Nothing has to read it, and nothing breaks if it is
ignored.

Trials are sorted naturally, so `T10` follows `T2` rather than preceding it.
Lexical ordering would silently reorder a session while producing a file of
exactly the right shape.

Usage:
    python combine_curves.py --curve-dir DIR [--prefix CK-] [--out DIR]
"""
import argparse
import csv
import hashlib
import re
from pathlib import Path

import numpy as np


def _natural_key(text):
    """Sort key that orders embedded numbers numerically."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def discover_trial_files(curve_dir, side="right", prefix=None):
    """Curve files for one side, in natural trial order.

    `prefix` selects a single pipeline when several have written into the same
    directory -- pooling across routes would mix incomparable kinematics.
    """
    curve_dir = Path(curve_dir)
    suffix = f"_{side}.csv"
    files = [
        path for path in curve_dir.glob(f"*{suffix}")
        if prefix is None or path.name.startswith(prefix)
    ]
    return sorted(files, key=lambda path: _natural_key(path.name))


DUPLICATE_POLICIES = ("error", "keep_newest")


def _resolve_duplicates(files, on_duplicate):
    """Refuse, or drop, files whose contents are byte-identical.

    Detection is by content rather than by name because the real case has no
    naming in common: a trial exported before and after a filename change
    yields `OpenCapData_<uuid>-CK-001_right.csv` and `ca505b02-CK-001_right.csv`,
    which share no stem. Pooling both double-counts that trial and produces a
    matrix with the correct row count, the expected shape, and no error.

    Two genuinely different trials will not be byte-identical, so this cannot
    fire on a normal session.
    """
    if on_duplicate not in DUPLICATE_POLICIES:
        raise ValueError(
            f"unknown on_duplicate policy {on_duplicate!r}; expected one of "
            f"{list(DUPLICATE_POLICIES)}."
        )

    by_digest = {}
    for path in files:
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        by_digest.setdefault(digest, []).append(path)

    duplicates = {d: paths for d, paths in by_digest.items() if len(paths) > 1}
    if not duplicates:
        return files

    if on_duplicate == "error":
        listing = "; ".join(
            " and ".join(path.name for path in paths) for paths in duplicates.values()
        )
        raise ValueError(
            f"These files hold the same strides: {listing}. Pooling them would "
            "count that trial twice while producing a matrix of exactly the right "
            "shape, so it is refused. Delete the stale copy, or pass "
            "on_duplicate='keep_newest' to keep only the most recently written."
        )

    drop = set()
    for paths in duplicates.values():
        newest = max(paths, key=lambda path: path.stat().st_mtime)
        drop.update(path for path in paths if path is not newest)
    return [path for path in files if path not in drop]


def combine_curve_matrices(curve_dir, side="right", prefix=None, on_duplicate="error"):
    """-> (combined matrix, index rows).

    The index is a list of {column, trial, stride_in_trial}, one entry per
    column, using 1-based numbering to match how the columns are referred to
    in a spreadsheet.
    """
    files = discover_trial_files(curve_dir, side=side, prefix=prefix)
    files = _resolve_duplicates(files, on_duplicate)
    if not files:
        raise FileNotFoundError(
            f"No curve files matched {curve_dir}/*_{side}.csv"
            + (f" with prefix {prefix!r}" if prefix else "")
            + ". Run the per-trial export first."
        )

    blocks, index, expected_rows = [], [], None
    for path in files:
        matrix = np.loadtxt(path, delimiter=",", ndmin=2)
        if expected_rows is None:
            expected_rows = matrix.shape[0]
        elif matrix.shape[0] != expected_rows:
            # Row count encodes the coordinate list. Concatenating a
            # 36-coordinate export with a 38-coordinate one misaligns every
            # coordinate below the divergence while still producing a file
            # that loads cleanly.
            raise ValueError(
                f"{path.name} has {matrix.shape[0]} rows but the earlier files have "
                f"{expected_rows}. These exports use different coordinate lists and "
                "cannot be pooled -- combining them would misalign every coordinate "
                "after the first difference."
            )
        trial = path.name[: -len(f"_{side}.csv")]
        for stride in range(matrix.shape[1]):
            index.append({
                "column": len(index) + 1,
                "trial": trial,
                "stride_in_trial": stride + 1,
            })
        blocks.append(matrix)

    return np.hstack(blocks), index


def write_combined(path, combined, index):
    """Write the matrix and its sidecar index. Returns both paths."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same writer the per-trial export uses, so the combined file is
    # indistinguishable in format from the files it was built from.
    np.savetxt(path, combined, delimiter=",", fmt="%f")

    index_path = path.with_name(f"{path.stem}_index.csv")
    with open(index_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["column", "trial", "stride_in_trial"])
        writer.writeheader()
        writer.writerows(index)
    return {"matrix_path": str(path), "index_path": str(index_path)}


def combine_session(curve_dir, out_dir, name="combined", prefix=None,
                    sides=("right", "left"), on_duplicate="error"):
    """Combine both sides of a session and report what was written."""
    written = {}
    for side in sides:
        combined, index = combine_curve_matrices(
            curve_dir, side=side, prefix=prefix, on_duplicate=on_duplicate
        )
        target = Path(out_dir) / f"{name}_{side}.csv"
        written[side] = write_combined(target, combined, index)
        written[side].update({
            "rows": combined.shape[0],
            "strides": combined.shape[1],
            "trials": len({entry["trial"] for entry in index}),
        })
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curve-dir", required=True,
                        help="Directory holding the per-trial *_right.csv / *_left.csv exports.")
    parser.add_argument("--out", default=None,
                        help="Where to write the combined files (default: alongside the inputs).")
    parser.add_argument("--prefix", default=None,
                        help="Only combine files starting with this, to select one pipeline.")
    parser.add_argument("--name", default="combined",
                        help="Base name for the output, e.g. the participant and date.")
    args = parser.parse_args(argv)

    out_dir = args.out or args.curve_dir
    written = combine_session(args.curve_dir, out_dir, name=args.name, prefix=args.prefix)
    for side, info in written.items():
        print(f"  {side:<6} {info['rows']} rows x {info['strides']} strides "
              f"from {info['trials']} trials")
        print(f"         {info['matrix_path']}")
        print(f"         {info['index_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
