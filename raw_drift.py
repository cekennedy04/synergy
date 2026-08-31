"""Check a session's raw Xsens recordings for heading drift, before processing.

Built 2026-08-30. Companion to `session_drift.py`, which needs a processed
session; this needs only the `.mvnx`, so it can run before an hour of
conversion rather than after.

**What it measures.** Mean pelvis yaw per trial, and each foot's yaw relative
to the pelvis. Trial order is the axis for the same reason as in
`session_drift.py`: recordings are independent of each other, so a quantity
that moves monotonically with trial number is moving in the capture.

**Why the two are reported separately.** Measured across six participants:
four of six sessions drift 10 to 36 degrees in absolute pelvis heading, at
correlations of 0.95 to 0.99. Most of that never reaches a result, because a
heading error shared by every segment cancels out of joint angles, which are
relative. What does reach a result is a segment drifting *differently* from
its parent -- one participant's right foot moved 9.9 degrees against the
pelvis and took 18 GDI points with it. So absolute drift is context and
relative drift is the alarm, and collapsing them into one number loses the
distinction that matters.

**Angles are wrapped and averaged circularly, and that is not fussiness.** A
first version of this analysis differenced raw `atan2` outputs and reported a
296-degree drift for one participant -- a foot sitting either side of the
+/-180 seam reads as a full turn. Wrapped properly, that participant drifts
1.2 degrees. A wrap artefact of 30 degrees would not have looked absurd enough
to catch.

Usage:
    python raw_drift.py --mvnx-dir "context/Data for Alex/AN/HD Reprocessed"
"""
import argparse
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

# Segment indices in the MVNX orientation block (23 segments x 4 quaternion
# values). Read from the header on real files; these are the defaults for the
# FullBody configuration every recording here uses.
DEFAULT_SEGMENTS = {"pelvis": 0, "right_foot": 17, "left_foot": 21}

# Xsens computes its own joint angles alongside the segment orientations, as
# ZXY Euler triples per joint; index 2 of each triple is flexion. Checked as
# well as yaw because a yaw-only check misses a whole class of drift: one
# participant here has no foot yaw drift at all, yet its right hip flexion
# moves -6.2 degrees across the session at r = -0.951, and that is what takes
# its score down. Using Xsens's own numbers rather than our IK also means a
# finding here cannot be blamed on our conversion.
DEFAULT_JOINTS = {"right_hip": 14, "left_hip": 18}
FLEXION_COMPONENT = 2

# |r| at or above this, with a change worth caring about, is worth a human's
# attention. Matches session_drift.TREND_ALERT_R deliberately.
TREND_ALERT_R = 0.85
MIN_CHANGE_DEG = 3.0
MIN_TRIALS_FOR_TREND = 6


def wrap_degrees(delta):
    """A difference wrapped into (-180, 180]."""
    return (delta + 180.0) % 360.0 - 180.0


def circular_mean(angles):
    """Mean of angles in degrees, taken on the circle.

    An arithmetic mean of values straddling +/-180 lands near zero, which is
    the opposite side of the circle from where the data is.
    """
    radians = np.radians(np.asarray(angles, dtype=float))
    return math.degrees(math.atan2(np.sin(radians).mean(),
                                   np.cos(radians).mean()))


def yaw_from_quaternion(w, x, y, z):
    return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def segment_indices(mvnx_path):
    """Segment label -> index, from the file's own header."""
    labels = []
    for _event, element in ET.iterparse(str(mvnx_path), events=("end",)):
        tag = element.tag.split("}")[-1]
        if tag == "segment":
            labels.append(element.attrib.get("label"))
            element.clear()
        elif tag == "segments" and labels:
            break
    return {label: index for index, label in enumerate(labels)}


def trial_yaws(mvnx_path, segments=None, joints=None):
    """Per-trial mean pelvis yaw, each foot's yaw relative to it, and each
    hip's flexion from Xsens's own joint angles."""
    segments = segments or DEFAULT_SEGMENTS
    pelvis, right, left = (segments["pelvis"], segments["right_foot"],
                           segments["left_foot"])
    highest = max(pelvis, right, left)

    pelvis_yaw, right_rel, left_rel = [], [], []
    flexion = {name: [] for name in (joints or DEFAULT_JOINTS)}
    joints = joints or DEFAULT_JOINTS
    for _event, element in ET.iterparse(str(mvnx_path), events=("end",)):
        if element.tag.split("}")[-1] != "frame":
            continue
        # npose/tpose calibration frames are not walking and would bias the mean.
        if element.attrib.get("type") != "normal":
            element.clear()
            continue
        angles = next((child for child in element
                       if child.tag.split("}")[-1] == "jointAngle"), None)
        if angles is not None and angles.text:
            triples = [float(v) for v in angles.text.split()]
            for name, index in joints.items():
                if len(triples) >= (index + 1) * 3:
                    flexion[name].append(triples[index * 3 + FLEXION_COMPONENT])
        node = next((child for child in element
                     if child.tag.split("}")[-1] == "orientation"), None)
        if node is not None and node.text:
            values = [float(v) for v in node.text.split()]
            if len(values) >= (highest + 1) * 4:
                def yaw(index):
                    return yaw_from_quaternion(*values[index * 4:index * 4 + 4])
                base = yaw(pelvis)
                pelvis_yaw.append(base)
                # Wrapped per frame, BEFORE averaging: averaging first would
                # mix values from either side of the seam.
                right_rel.append(wrap_degrees(yaw(right) - base))
                left_rel.append(wrap_degrees(yaw(left) - base))
        element.clear()

    if not pelvis_yaw:
        raise ValueError(f"{mvnx_path} contains no normal frames with orientations.")
    result = {"pelvis": circular_mean(pelvis_yaw),
              "right_minus_pelvis": circular_mean(right_rel),
              "left_minus_pelvis": circular_mean(left_rel)}
    for name, values in flexion.items():
        # Flexion is a bounded sagittal angle, not a heading -- an ordinary
        # mean is right here and a circular one would be wrong.
        result[name + "_flexion"] = float(np.mean(values)) if values else float("nan")
    return result


def trend(order, values, circular=True):
    """(r, change) for a per-trial angle series."""
    values = np.asarray(values, dtype=float)
    if circular:
        values = np.degrees(np.unwrap(np.radians(values)))
    order = np.asarray(order, dtype=float)
    if values.size < 2 or np.ptp(values) == 0 or np.ptp(order) == 0:
        return 0.0, 0.0
    return (float(np.corrcoef(order, values)[0, 1]),
            float(values[-3:].mean() - values[:3].mean()))


def session_report(mvnx_dir, segments=None):
    paths = sorted(Path(mvnx_dir).glob("*.mvnx"),
                   key=lambda p: [int(t) if t.isdigit() else t.lower()
                                  for t in re.split(r"(\d+)", p.stem)])
    if not paths:
        raise FileNotFoundError(f"no .mvnx files in {mvnx_dir}")
    if segments is None:
        labels = segment_indices(paths[0])
        segments = {"pelvis": labels.get("Pelvis", 0),
                    "right_foot": labels.get("RightFoot", 17),
                    "left_foot": labels.get("LeftFoot", 21)}

    order, series = [], {"pelvis": [], "right_minus_pelvis": [],
                         "left_minus_pelvis": [],
                         "right_hip_flexion": [], "left_hip_flexion": []}
    for path in paths:
        match = re.search(r"(\d+)", path.stem)
        order.append(int(match.group(1)) if match else len(order) + 1)
        for key, value in trial_yaws(path, segments).items():
            series[key].append(value)

    report = {"session": Path(mvnx_dir).parent.name, "n_trials": len(paths),
              "measures": {}}
    if len(paths) < MIN_TRIALS_FOR_TREND:
        report["note"] = (f"{len(paths)} trials is too few for a trend; "
                          f"{MIN_TRIALS_FOR_TREND} are needed.")
        return report

    for key, values in series.items():
        # Only the yaw series live on a circle; unwrapping a flexion series
        # would invent 360-degree jumps in a quantity that has none.
        r, change = trend(order, values, circular=key not in
                          ("right_hip_flexion", "left_hip_flexion"))
        report["measures"][key] = {
            "r": r, "change": change,
            "alert": abs(r) >= TREND_ALERT_R and abs(change) >= MIN_CHANGE_DEG,
        }
    return report


def format_report(report):
    lines = [f"{report['session']}  ({report['n_trials']} trials, raw MVNX)"]
    if "note" in report:
        lines.append(f"  {report['note']}")
        return "\n".join(lines)
    for key in ("pelvis", "right_minus_pelvis", "left_minus_pelvis",
                "right_hip_flexion", "left_hip_flexion"):
        m = report["measures"][key]
        lines.append(f"  {key:<20} r={m['r']:+.3f}  {m['change']:+7.2f} deg"
                     + ("  <-- ALERT" if m["alert"] else ""))
    relative = [k for k in ("right_minus_pelvis", "left_minus_pelvis",
                            "right_hip_flexion", "left_hip_flexion")
                if report["measures"][k]["alert"]]
    if relative:
        lines.append("  Drifting: " + ", ".join(relative) + ". These are "
                     "relative quantities -- unlike absolute heading drift they "
                     "do NOT cancel out of joint angles, and they will reach "
                     "the results. A trend shows a problem, not its cause.")
    elif report["measures"]["pelvis"]["alert"]:
        lines.append("  Absolute heading drift only. This is common and mostly "
                     "cancels out of joint angles, which are relative -- but it "
                     "is worth knowing the session has it.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mvnx-dir", required=True, action="append",
                        dest="dirs")
    args = parser.parse_args(argv)
    worst = 0
    for directory in args.dirs:
        report = session_report(directory)
        print(format_report(report))
        print()
        if any(m["alert"] for m in report.get("measures", {}).values()):
            worst = 2
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
