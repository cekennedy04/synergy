"""Run the full pipeline over every scaffolded participant, one at a time.

Built 2026-08-30. The driver for first-pass processing of the participants in
`context/Data for Alex/`, whose sessions were prepared by `session_scaffold.py`.

**One participant per process invocation, and one trial per child process.**
`clinician_gui.run_batch` already isolates each trial in its own interpreter
because a fifteen-trial batch in one process was being killed around trial 11
with no Python error. This adds the outer loop and a resumable ledger: a run
that dies partway through does not restart from zero, and a participant that
fails does not cost the others.

**Both conversion routes, deliberately.** `ik` (OpenSense inverse kinematics
on segment orientations) and `xtoo` (direct remapping of Xsens joint angles)
answer different questions and disagree about exactly the coordinates that
matter -- toes, arms, pelvis translation. Pooling mixes them silently because
their matrices are the same shape, so `combine_curves` keeps them apart by
filename prefix and this driver runs them as separate passes.

Usage:
    python process_participants.py --sessions data/xsens_sessions \\
        --participants "context/Data for Alex" --route ik [--participant AN]

Run with the OpenSim interpreter (`envs/opencap-processing`).
"""
import argparse
import json
import time
from pathlib import Path

LEDGER_NAME = "processing_ledger.json"

# The .mvnx live one level down from the participant folder ("HD Reprocessed").
# Resolved by search rather than hardcoded: the layout is the supervisor's, and
# a second export folder would otherwise be silently ignored.
def find_mvnx_dir(participant_dir):
    participant_dir = Path(participant_dir)
    candidates = sorted({p.parent for p in participant_dir.rglob("*.mvnx")})
    if not candidates:
        raise FileNotFoundError(f"no .mvnx anywhere under {participant_dir}")
    if len(candidates) > 1:
        raise ValueError(
            f"{participant_dir} has .mvnx in {len(candidates)} folders "
            f"({[str(c.relative_to(participant_dir)) for c in candidates]}). "
            "Processing one and ignoring the rest would silently drop trials; "
            "point --participants at the intended level instead."
        )
    return candidates[0]


def load_ledger(path):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        # A truncated ledger must not abort the run; the worst case is
        # redoing work, which is safe.
        return {}


def save_ledger(path, ledger):
    Path(path).write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def participant_key(code, route):
    return f"{code}:{route}"


def process_one(gui, session_dir, mvnx_dir, route, progress=None):
    """One participant, one route. Returns run_batch's own result dict."""
    started = time.monotonic()
    result = gui.run_batch(str(session_dir), str(mvnx_dir), conversion=route,
                           progress_callback=progress)
    result["elapsed_s"] = round(time.monotonic() - started, 1)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sessions", required=True,
                        help="Root holding XsensSession_<CODE> scaffolds.")
    parser.add_argument("--participants", required=True,
                        help="Root holding one .mvnx folder per participant.")
    parser.add_argument("--route", default="ik", choices=("ik", "xtoo"))
    parser.add_argument("--participant", action="append", dest="only")
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--redo", action="store_true",
                        help="Reprocess participants the ledger already records.")
    args = parser.parse_args(argv)

    import clinician_gui as gui

    sessions_root = Path(args.sessions)
    participants_root = Path(args.participants)
    ledger_path = Path(args.ledger) if args.ledger else sessions_root / LEDGER_NAME
    ledger = load_ledger(ledger_path)

    scaffolds = sorted(sessions_root.glob("XsensSession_*"))
    if args.only:
        wanted = {c.upper() for c in args.only}
        scaffolds = [s for s in scaffolds
                     if s.name.replace("XsensSession_", "") in wanted]
    if not scaffolds:
        print(f"no scaffolds matched under {sessions_root}")
        return 1

    for scaffold in scaffolds:
        code = scaffold.name.replace("XsensSession_", "")
        key = participant_key(code, args.route)
        if key in ledger and not args.redo:
            print(f"{code} [{args.route}]: already done, skipping "
                  f"({ledger[key].get('ok_trials', '?')} trials)")
            continue

        try:
            mvnx_dir = find_mvnx_dir(participants_root / code)
        except Exception as exc:
            print(f"{code} [{args.route}]: SKIPPED -- {exc}")
            ledger[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            save_ledger(ledger_path, ledger)
            continue

        print(f"{code} [{args.route}]: {mvnx_dir} -> {scaffold}", flush=True)
        try:
            result = process_one(
                gui, scaffold, mvnx_dir, args.route,
                progress=lambda m: print(f"    {m}", flush=True))
            trials = result.get("trials", [])
            ok = [t for t in trials if t.get("ok")]
            ledger[key] = {
                "ok": True,
                "ok_trials": len(ok),
                "failed_trials": len(trials) - len(ok),
                "elapsed_s": result.get("elapsed_s"),
                "errors": [t.get("error") for t in trials if not t.get("ok")][:5],
            }
            print(f"{code} [{args.route}]: {len(ok)}/{len(trials)} trials in "
                  f"{result.get('elapsed_s')}s", flush=True)
        except BaseException as exc:  # noqa: BLE001 -- one participant must not end the run
            ledger[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(f"{code} [{args.route}]: FAILED -- {type(exc).__name__}: {exc}",
                  flush=True)
        save_ledger(ledger_path, ledger)

    done = sum(1 for v in ledger.values() if v.get("ok"))
    print(f"\nledger: {ledger_path}  ({done}/{len(ledger)} entries ok)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
