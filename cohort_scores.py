"""GDI and the UCM synergy index for every Xsens session, in one table.

Built 2026-09-02. `session_report.py` answers "what does this participant look
like" and writes one PDF per session. This answers "what does this cohort look
like", and it is the level at which the two metrics can be compared against each
other at all: a correlation between GDI and the synergy index needs more than one
participant, and the synergy index needs a whole session's strides before it is
worth quoting once.

**What this adds over calling `session_report.session_scores` six times.**

1. **The synergy index is computed per side.** `session_scores` runs UCM on the
   right-side pooled matrix only (`session_report.py:135`) because its output is
   a single-participant PDF where one figure is enough. GDI is a per-limb score
   by definition, so a GDI-vs-synergy comparison that pairs a left GDI with a
   right synergy index is comparing two different limbs. Both sides, always.
2. **Nothing is recomputed twice.** GDI comes from the same pooled
   `*_all-trials_*` matrices and the same `curve_features.score_curves` call the
   per-session reports use, so this file cannot disagree with them.
3. **The per-phase decomposition is kept.** `summarise_cycle` collapses the cycle
   to means; which parts of the cycle the joints co-vary over is the substance of
   a UCM analysis and the cohort figure that shows it needs the 101 values.

Writes one JSON. Rendering is `cohort_figures.py`'s job -- kept apart so a figure
can be restyled without re-running OpenSim, and so the numbers in the report are
a file on disk that can be diffed between runs.

Run with the OpenSim interpreter (`envs/opencap-processing`) -- the synergy
Jacobian needs a model.

Usage:
    python cohort_scores.py [--sessions Data/xsens_sessions]
        [--reference context/gdi_reference_2026-08-27] [--conversion ik]
        [--out context/cohort/cohort_scores.json]
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session_model(session_dir):
    """The scaled model, not the calibrated one.

    `session_report.py` makes the same choice. The calibrated file is the IMU
    placer's output and carries the sensor frames; the scaled one is the
    skeleton, which is what a Jacobian about a joint configuration needs.
    """
    model_dir = Path(session_dir) / "OpenSimData" / "Model"
    models = [p for p in sorted(model_dir.glob("*.osim"))
              if not p.stem.endswith("_calibrated")]
    return str(models[0]) if models else None


def score_session(session_dir, reference_dir, conversion="ik", feature_set=None,
                  session_report=None):
    """Every number this cohort report quotes for one session.

    Both sides get both metrics. A side that has no pooled matrix is absent from
    the result rather than present with a placeholder -- the report prints what
    is missing, and a NaN in a results table is indistinguishable from a
    measurement.
    """
    session_report = session_report or _load("_sr_for_cohort", "session_report.py")
    scores_mod = _load("_scores_for_cohort", "trial_scores.py")

    # GDI, the trial breakdown and the stride counts, from the same call the
    # per-session PDFs use. Its own synergy result is discarded: it is
    # right-side-only, and this function computes both sides below.
    scores = session_report.session_scores(
        session_dir, reference_dir, conversion, feature_set, model_path=None)

    model_path = session_model(session_dir)
    paths = session_report.pooled_paths(session_dir, conversion)
    scores["model"] = model_path
    scores["synergy"] = {}
    if model_path:
        for side, entry in paths.items():
            scores["synergy"][side] = scores_mod.synergy_for_trial(
                str(entry["matrix"]), model_path)
    scores["participant"] = Path(session_dir).name.replace("XsensSession_", "")
    return scores


def _correlate(x, y):
    """Pearson r, Spearman rho and both p-values -- or None.

    Returned rather than printed so the report states the same number the
    figure draws, and so a degenerate case (fewer than three points, or a
    constant series) reads as "not computed" instead of "nan".

    Spearman as well as Pearson because the cohort is six participants: one
    limb sitting away from the rest can carry a Pearson r on its own, and if
    the two measures disagree that is the finding, not a detail.
    """
    from scipy import stats

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if x.size < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    r, p = stats.pearsonr(x, y)
    rho, rho_p = stats.spearmanr(x, y)
    return {"r": float(r), "p": float(p), "rho": float(rho),
            "rho_p": float(rho_p), "n": int(x.size)}


def cohort_summary(sessions):
    """Cohort-level aggregates, computed once so figures and prose agree."""
    rows = []
    for scores in sessions:
        for side in ("right", "left"):
            gdi = scores["gdi"].get(side)
            syn = (scores.get("synergy") or {}).get(side)
            if not gdi:
                continue
            rows.append({
                "participant": scores["participant"],
                "side": side,
                "gdi": gdi["mean"],
                "gdi_sd": gdi.get("sd"),
                "n_strides": gdi["n_strides"],
                "n_trials": len(scores.get("by_trial", {}).get(side, {})),
                "delta_v": syn["mean_delta_v"] if syn else None,
                "delta_v_z": syn["mean_delta_v_z"] if syn else None,
                "v_ucm": syn["mean_v_ucm"] if syn else None,
                "v_ort": syn["mean_v_ort"] if syn else None,
                "phases_with_synergy": syn["phases_with_synergy"] if syn else None,
                "n_phases": syn["n_phases"] if syn else None,
            })

    paired = [r for r in rows if r["delta_v"] is not None]
    gdi_all = [r["gdi"] for r in rows]
    return {
        "n_participants": len({r["participant"] for r in rows}),
        "n_legs": len(rows),
        "n_strides": int(sum(r["n_strides"] for r in rows)),
        "gdi_mean": float(np.mean(gdi_all)) if gdi_all else None,
        "gdi_sd": float(np.std(gdi_all, ddof=1)) if len(gdi_all) > 1 else None,
        "gdi_min": float(np.min(gdi_all)) if gdi_all else None,
        "gdi_max": float(np.max(gdi_all)) if gdi_all else None,
        "delta_v_mean": float(np.mean([r["delta_v"] for r in paired])) if paired else None,
        "delta_v_sd": (float(np.std([r["delta_v"] for r in paired], ddof=1))
                       if len(paired) > 1 else None),
        "delta_v_min": float(np.min([r["delta_v"] for r in paired])) if paired else None,
        "delta_v_max": float(np.max([r["delta_v"] for r in paired])) if paired else None,
        # The question the report exists to ask: does a limb that deviates more
        # from the normative pattern also organise its joints differently?
        #
        # Both levels, because neither answers on its own. The limb-level fit
        # has twelve points but they are six pairs -- a participant contributes
        # twice and the two contributions are not independent. The
        # participant-level fit is honest about n and has six points. Quoting
        # only the first would overstate the evidence; only the second would
        # discard the within-participant structure figures 1 and 2 show.
        "gdi_vs_delta_v": _correlate([r["gdi"] for r in paired],
                                     [r["delta_v"] for r in paired]),
        "gdi_vs_delta_v_participant": _participant_correlation(paired),
        # Delta-V is scale-free, so it should not track how much a limb varies
        # at all. Reported so a reader can check that it doesn't, rather than
        # assume it.
        "delta_v_vs_total_variance": _correlate(
            [np.log10(r["v_ucm"] + r["v_ort"]) for r in paired],
            [r["delta_v"] for r in paired]),
        "asymmetry": _limb_asymmetry(rows),
        "rows": rows,
    }


def _participant_correlation(paired):
    """The same correlation with each participant counted once."""
    by_participant = {}
    for row in paired:
        by_participant.setdefault(row["participant"], []).append(row)
    names = sorted(by_participant)
    return _correlate(
        [float(np.mean([r["gdi"] for r in by_participant[n]])) for n in names],
        [float(np.mean([r["delta_v"] for r in by_participant[n]])) for n in names])


def _limb_asymmetry(rows):
    """Right-minus-left per participant, for both metrics."""
    by_participant = {}
    for row in rows:
        by_participant.setdefault(row["participant"], {})[row["side"]] = row
    out = {}
    for name, sides in sorted(by_participant.items()):
        if "right" not in sides or "left" not in sides:
            continue
        right, left = sides["right"], sides["left"]
        out[name] = {
            "gdi": right["gdi"] - left["gdi"],
            "delta_v": (right["delta_v"] - left["delta_v"]
                        if right["delta_v"] is not None
                        and left["delta_v"] is not None else None),
        }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sessions", default="Data/xsens_sessions")
    parser.add_argument("--reference", default="context/gdi_reference_2026-08-27")
    parser.add_argument("--conversion", default="ik")
    parser.add_argument("--feature-set", default=None)
    parser.add_argument("--out", default="context/cohort/cohort_scores.json")
    args = parser.parse_args(argv)

    session_report = _load("_sr_for_cohort", "session_report.py")
    directories = sorted(p for p in Path(args.sessions).iterdir()
                         if p.is_dir() and p.name.startswith("XsensSession_"))
    if not directories:
        print(f"no XsensSession_* directories under {args.sessions}", file=sys.stderr)
        return 1

    sessions, failed = [], []
    for directory in directories:
        started = time.time()
        try:
            scores = score_session(directory, args.reference, args.conversion,
                                   args.feature_set, session_report)
        except BaseException as exc:  # noqa: BLE001 -- one session must not end the run
            failed.append({"session": directory.name,
                           "error": f"{type(exc).__name__}: {exc}"})
            print(f"{directory.name}: FAILED -- {type(exc).__name__}: {exc}",
                  flush=True)
            continue
        sessions.append(scores)
        gdi = scores["gdi"]
        syn = scores.get("synergy") or {}
        print(f"{scores['participant']}: "
              f"GDI R {gdi.get('right', {}).get('mean', float('nan')):6.2f} / "
              f"L {gdi.get('left', {}).get('mean', float('nan')):6.2f}   "
              f"dV R {syn.get('right', {}).get('mean_delta_v', float('nan')):+.3f} / "
              f"L {syn.get('left', {}).get('mean_delta_v', float('nan')):+.3f}   "
              f"({time.time() - started:.1f}s)", flush=True)

    payload = {
        "generated": time.strftime("%Y-%m-%d"),
        "sessions_root": str(args.sessions),
        "reference": args.reference,
        "conversion": args.conversion,
        "feature_set": sessions[0]["feature_set"] if sessions else None,
        "task_variable": next(
            (s["synergy"][side]["task_variable"]
             for s in sessions for side in s.get("synergy", {})), None),
        "failed": failed,
        "summary": cohort_summary(sessions),
        "sessions": sessions,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"-> {out}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
