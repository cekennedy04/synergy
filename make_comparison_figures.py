"""Generate the three-way pipeline comparison figures.

Reads the exported per-gait-cycle curve matrices for all three routes and
renders the panels described in VENDORING.md:

  jointcheck_26.png       the 26 coordinates jointcheck.m plots
  jointcheck_com.png      the 3 pelvis-relative centre-of-mass channels
  jointcheck_rescued.png  the coordinates direct remapping recovers that
                          inverse kinematics cannot

Lives in the repository rather than a scratch directory on purpose: the first
version of this script was written to a temp folder and lost to a Windows
cleanup, taking the figures with it. The inputs (context/gait_curves/) and the
plotting module (jointcheck.py) both survived because they were tracked.

Usage:
    python make_comparison_figures.py [--curve-dir DIR] [--out DIR]
"""
import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # no display assumed

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import jointcheck as jc  # noqa: E402

# Which file prefix belongs to which pipeline, and how its trials are named.
PIPELINES = (
    ("OpenSim IK", "CK-CK-{trial}", [f"{n:03d}" for n in range(1, 16)]),
    ("XtoO direct", "XT-XT-{trial}", [f"{n:03d}" for n in range(1, 16)]),
    ("OpenCap video", "OC-Trial{trial}", [str(n) for n in range(1, 16)]),
)

# Coordinates the 26-panel grid omits. Translation and toes still carry the
# argument for the direct-remapping route. The arm panels were here for a
# third reason -- IK saturation -- which was a calibration-pose bug fixed on
# 2026-09-02; they are kept because the three routes are now worth comparing
# on the arms rather than because one of them is broken.
RESCUED_COORDINATES = (
    "pelvis_tx", "pelvis_ty", "pelvis_tz",
    "mtp_angle_r", "mtp_angle_l",
    "arm_flex_l", "arm_rot_l", "pro_sup_r",
)


def joint_names(repo_root=REPO_ROOT):
    """Row ordering of the exported matrices, read from the driver.

    The CSVs carry no labels -- row position is the only thing identifying a
    coordinate -- so this must come from the same list the exporter used.
    """
    source = (Path(repo_root) / "Examples" / "gaitAnalysis-UCM.py").read_text()
    block = re.search(r"JOINT_NAMES = \[(.*?)\]", source, re.S).group(1)
    return [n.strip().strip("'\"") for n in block.replace("\n", " ").split(",") if n.strip()]


def pooled_curves(curve_dir, pattern, trials, names, side="right"):
    """-> {coordinate: (n_strides, 101)}, strides pooled across trials."""
    curve_dir = Path(curve_dir)
    index = {name: i for i, name in enumerate(names)}
    collected = {name: [] for name in names}
    found = 0
    for trial in trials:
        path = curve_dir / f"{pattern.format(trial=trial)}_{side}.csv"
        if not path.is_file():
            continue
        found += 1
        matrix = np.loadtxt(path, delimiter=",", ndmin=2)
        expected = len(names) * 101
        if matrix.shape[0] != expected:
            raise ValueError(
                f"{path}: {matrix.shape[0]} rows but JOINT_NAMES implies {expected}. "
                "The exporter's coordinate list and this reader have diverged."
            )
        for name in names:
            block = matrix[index[name] * 101:(index[name] + 1) * 101, :]   # (101, strides)
            collected[name].append(block.T)                                 # (strides, 101)
    if not found:
        return {}
    return {name: np.vstack(blocks) for name, blocks in collected.items() if blocks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curve-dir", default=str(REPO_ROOT / "context" / "gait_curves"))
    parser.add_argument("--out", default=str(REPO_ROOT / "context" / "figures"))
    parser.add_argument("--side", default="right", choices=["right", "left"])
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = joint_names()

    datasets = {}
    for label, pattern, trials in PIPELINES:
        curves = pooled_curves(args.curve_dir, pattern, trials, names, args.side)
        if not curves:
            print(f"  {label:<16} no curve files found -- skipped")
            continue
        datasets[label] = curves
        n_strides = len(next(iter(curves.values())))
        print(f"  {label:<16} {len(curves)} coordinates, {n_strides} strides pooled")

    if not datasets:
        raise SystemExit(f"No curve matrices found under {args.curve_dir}.")

    for filename, coordinates, columns, title in (
        ("jointcheck_26.png", jc.COMPARISON_COORDINATES, 5,
         "Three pipelines, 26 coordinates (mean +/- 1 SD across strides)"),
        ("jointcheck_com.png", jc.COM_CHANNELS, 3,
         "Centre of mass, pelvis-relative"),
        ("jointcheck_rescued.png", RESCUED_COORDINATES, 4,
         "What direct remapping recovers that inverse kinematics cannot"),
    ):
        figure = jc.plot_comparison(datasets, coordinates, columns=columns)
        figure.suptitle(title, y=0.995)
        figure.savefig(out_dir / filename, dpi=130, bbox_inches="tight")
        print(f"  wrote {out_dir / filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
