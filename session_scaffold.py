"""Build an OpenSim session directory for a participant's Xsens trials.

Built 2026-08-28. Unblocks first-pass processing of the participants in
`context/Data for Alex/`, which are raw `.mvnx` with no session structure and
no model.

**The problem this solves.** `xsens_to_opensim.py` consumes a scaled `.osim`;
it does not produce one. A participant recorded only on Xsens therefore has
nothing to run against. The three ways out were: scale a model from the
`.mvnx` segment geometry (real work, new error source), use the generic
unscaled model (defensible for angles, but a documented approximation), or
find a scaled model that already belongs to that participant.

The third turned out to be available. Every Xsens participant also has an
OpenCap session, and OpenCap scales a model per subject as part of its own
pipeline. So a participant's Xsens session borrows *their own* scaled model
rather than a generic one or a re-derived one. No approximation, no new
estimation step, and the two modalities end up sharing a model -- which is
what makes them comparable in the first place.

**Matching is by subject identity, and it refuses to guess.** A session's
`sessionMetadata.yaml` carries a `subjectID` that is sometimes the
participant code and sometimes a full name; the code is then its initials.
Both forms are accepted, but an ambiguous match -- two sessions that could
both be the participant -- is an error rather than a coin flip. Putting the
wrong person's model on a session produces a complete, plausible, wrong
result, which is the failure mode this project keeps running into.

**On personal data:** `subjectID` may be a real name. Nothing here writes it
into a scaffold, a filename, or a log line -- scaffolds are named by
participant code only. The repository is public.

Usage:
    python session_scaffold.py --participants "context/Data for Alex" \\
        --opencap data --out data/xsens_sessions [--participant AN]
"""
import argparse
import re
import shutil
from pathlib import Path

METADATA_NAME = "sessionMetadata.yaml"

# The layout xsens_to_opensim.py --session-dir writes into, and the layout
# gait_analysis reads back. Created empty; the converter fills them.
SESSION_SUBDIRS = ("OpenSimData/Model", "OpenSimData/Kinematics", "MarkerData")

# A model already calibrated against one set of IMU orientations must not be
# reused as the source for another run -- calibrate_model writes
# "<stem>_calibrated.osim" alongside, and picking it up would stack two
# calibrations. Same exclusion xsens_to_opensim's auto-discovery applies.
_CALIBRATED_SUFFIX = "_calibrated"


class ScaffoldError(Exception):
    """A scaffold could not be built, with the reason stated."""


def read_subject_id(session_dir):
    """The `subjectID` recorded in a session's metadata, or None.

    Parsed with a line regex rather than a YAML library: the value is a single
    scalar on one line in every OpenCap export seen, and this module is
    imported by tests that must not require pyyaml.
    """
    metadata = Path(session_dir) / METADATA_NAME
    if not metadata.is_file():
        return None
    for line in metadata.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"\s*subjectID\s*:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip().strip("'\"") or None
    return None


def initials(subject_id):
    """Initials of a name, uppercased. 'Ada Lovelace' -> 'AL'.

    A subject_id that is already a short code comes back unchanged, so the
    same function handles both forms a session may carry.
    """
    parts = [p for p in re.split(r"[\s_-]+", str(subject_id).strip()) if p]
    if len(parts) == 1:
        return parts[0].upper()
    return "".join(part[0] for part in parts).upper()


def discover_opencap_sessions(opencap_root):
    """Every OpenCap session under a root, with the subject it belongs to."""
    root = Path(opencap_root)
    if not root.is_dir():
        raise ScaffoldError(f"OpenCap root {root} is not a directory.")
    sessions = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        subject_id = read_subject_id(path)
        if subject_id is None:
            continue
        sessions.append({"path": path, "subject_id": subject_id,
                         "code": initials(subject_id)})
    return sessions


def match_session(participant_code, sessions):
    """The one session belonging to this participant.

    Refuses on zero or several. A silently wrong model is worse than a stop:
    it yields a complete result that is wrong in a way no downstream check
    would catch.
    """
    code = str(participant_code).strip().upper()
    matches = [s for s in sessions if s["code"] == code]
    if not matches:
        available = sorted({s["code"] for s in sessions})
        raise ScaffoldError(
            f"no OpenCap session matches participant {code!r}. Sessions found "
            f"resolve to {available}. Either that participant has no OpenCap "
            "recording -- in which case they need a model from somewhere else "
            "-- or their subjectID does not reduce to this code."
        )
    if len(matches) > 1:
        raise ScaffoldError(
            f"{len(matches)} OpenCap sessions resolve to participant {code!r} "
            f"({[str(m['path'].name) for m in matches]}). Refusing to guess "
            "which model belongs to this participant; pass the session "
            "explicitly."
        )
    return matches[0]


def find_source_model(session_dir):
    """The one scaled, uncalibrated .osim in a session."""
    model_dir = Path(session_dir) / "OpenSimData" / "Model"
    if not model_dir.is_dir():
        raise ScaffoldError(f"{session_dir} has no OpenSimData/Model directory.")
    models = [p for p in sorted(model_dir.glob("*.osim"))
              if not p.stem.endswith(_CALIBRATED_SUFFIX)]
    if len(models) != 1:
        raise ScaffoldError(
            f"expected exactly one source .osim in {model_dir}, found "
            f"{len(models)} ({[p.name for p in models]}). Calibrated models "
            f"(*{_CALIBRATED_SUFFIX}.osim) are excluded deliberately -- "
            "reusing one as a source would stack two IMU calibrations."
        )
    return models[0]


def find_trials(participant_dir):
    """The participant's .mvnx files, in natural order."""
    participant_dir = Path(participant_dir)
    trials = sorted(
        participant_dir.rglob("*.mvnx"),
        key=lambda p: [int(t) if t.isdigit() else t.lower()
                       for t in re.split(r"(\d+)", p.stem)],
    )
    if not trials:
        raise ScaffoldError(f"no .mvnx files found under {participant_dir}.")
    return trials


def build_scaffold(participant_code, participant_dir, opencap_session, out_root,
                   force=False):
    """Create one session directory ready for xsens_to_opensim --session-dir.

    Named by participant code alone. The OpenCap subjectID may be a real
    name and never reaches disk here.
    """
    model_source = find_source_model(opencap_session["path"])
    trials = find_trials(participant_dir)

    session_dir = Path(out_root) / f"XsensSession_{str(participant_code).upper()}"
    model_dest = session_dir / "OpenSimData" / "Model" / model_source.name
    if model_dest.exists() and not force:
        raise ScaffoldError(
            f"{model_dest} already exists. Refusing to overwrite a scaffold: "
            "if a conversion has already run against it, replacing the model "
            "would leave results that no longer match it. Pass force=True to "
            "replace it deliberately."
        )

    for subdir in SESSION_SUBDIRS:
        (session_dir / subdir).mkdir(parents=True, exist_ok=True)
    # Copied, not linked: this install uses file copies rather than symlinks,
    # and a session must stay valid if the OpenCap export is moved away.
    shutil.copy2(model_source, model_dest)

    return {
        "participant": str(participant_code).upper(),
        "session_dir": session_dir,
        "model": model_dest,
        "model_source": model_source,
        "n_trials": len(trials),
        "trials": trials,
    }


def build_all(participants_root, opencap_root, out_root, only=None, force=False):
    """A scaffold per participant folder. Never stops on one failure."""
    participants_root = Path(participants_root)
    sessions = discover_opencap_sessions(opencap_root)
    results, failures = [], []

    for participant_dir in sorted(p for p in participants_root.iterdir() if p.is_dir()):
        code = participant_dir.name.upper()
        if only and code not in {c.upper() for c in only}:
            continue
        try:
            session = match_session(code, sessions)
            results.append(build_scaffold(code, participant_dir, session,
                                          out_root, force=force))
        except ScaffoldError as exc:
            failures.append({"participant": code, "error": str(exc)})
    return results, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--participants", required=True,
                        help="Root holding one folder of .mvnx per participant.")
    parser.add_argument("--opencap", required=True,
                        help="Root holding the OpenCap sessions to take models from.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--participant", action="append", dest="only")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    results, failures = build_all(args.participants, args.opencap, args.out,
                                  only=args.only, force=args.force)
    for result in results:
        print(f"{result['participant']}: {result['n_trials']} trials -> "
              f"{result['session_dir']} (model {result['model'].name})")
    for failure in failures:
        print(f"{failure['participant']}: FAILED -- {failure['error']}")
    print(f"{len(results)} scaffold(s) built, {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
