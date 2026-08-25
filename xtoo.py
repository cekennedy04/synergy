"""Python port of XtoO.m -- Xsens joint angles straight to an OpenSim .mot.

A second, independent conversion route alongside the OpenSense pipeline in
xsens_to_opensim.py. Instead of running inverse kinematics on segment
orientations, this relabels Xsens's OWN joint angles into OpenSim coordinate
names and writes the .mot directly. No IMUPlacer, no IK, no model.

That matters because it supplies the three things the IK path cannot:

  * real pelvis translation (IK leaves the root pinned, which is why gait
    speed and stride length there are stance-foot proxies),
  * a live mtp/toe joint (nothing maps RightToe in SEGMENT_TO_IMU_FRAME),
  * unsaturated arms (no T-pose calibration step to go wrong).

Measured on CK-001: pelvis_tx spans 6.998 m against 0.000 m from IK and
6.275 m from OpenCap; mtp_angle_r spans 57.4 deg against 1.21; arm_flex_l
spans 45.2 deg against IK's saturated 419.8. Where both paths are valid they
agree closely -- knee r 0.990, hip 0.988, ankle 0.985, pelvis 0.984-0.992.

Reads .mvnx directly. XtoO.m reads .xlsx exports, but <jointAngle>,
<orientation> and <position> already carry everything it uses, so the
spreadsheet step and its column-naming drift are avoided.

**Two axis assignments differ from XtoO.m, deliberately.** Both were
established empirically rather than read off the MATLAB, and both are wrong in
the original:

  * Pelvis rotations. XtoO.m assigns tilt from roll, list from -yaw and
    rotation from -pitch. Measured against our IK solution, tilt is -pitch
    (r -0.992), list is +roll (r +0.984), rotation is +yaw (r +0.989). The
    xlsx 'Pelvis x/y/z' columns really are roll/pitch/yaw (verified r = 1.000
    against the quaternion sheet), so this is not a column-naming confusion.
  * Pelvis translation. XtoO.m assigns pelvis_ty from Xsens Y and pelvis_tz
    from Xsens Z. Xsens is Z-up and OpenSim is Y-up: Xsens Z sits at
    0.95-0.98 m (stature) and matches OpenCap's pelvis_ty, while Xsens Y
    matches pelvis_tz at r -0.994. XtoO.m's version routes the subject's
    height into the lateral coordinate.

legacy_axes=True reproduces XtoO.m's original assignment, so its exact output
can still be regenerated for comparison.

A caveat worth carrying: this output IS Xsens's joint angles under OpenSim
names. No model solves anything, so it inherits Xsens's biomechanical model
wholesale -- a different scientific claim from IK, and one a write-up should
state explicitly.
"""
import numpy as np


def quaternion_to_euler(quaternions, use_atan2=True):
    """Quaternion to (roll, pitch, yaw) in degrees.

    q_to_euler.m uses `atan`, which caps roll and yaw at +/-90 degrees and
    throws away the quadrant: a 120 degree yaw comes back as -60. Measured
    consequence on real data -- one 175.3 degree discontinuity in CK-004's
    pelvis_rotation across the 15 CK trials. Rare, but it silently corrupts
    that trial, and pelvis_rotation is one of the 26 coordinates the
    comparison uses.

    `use_atan2=True` (the default) uses the same numerators and denominators
    but resolves the quadrant properly. Inside +/-90 the two are identical, so
    this only changes cases atan could not represent at all.
    `use_atan2=False` reproduces the MATLAB exactly.
    """
    q = np.atleast_2d(np.asarray(quaternions, dtype=float))
    q0, q1, q2, q3 = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    roll_num, roll_den = 2*q2*q3 + 2*q0*q1, 2*q0*q0 + 2*q3*q3 - 1
    yaw_num, yaw_den = 2*q1*q2 + 2*q0*q3, 2*q0*q0 + 2*q1*q1 - 1
    if use_atan2:
        roll = np.degrees(np.arctan2(roll_num, roll_den))
        yaw = np.degrees(np.arctan2(yaw_num, yaw_den))
    else:
        roll = np.degrees(np.arctan(roll_num / roll_den))
        yaw = np.degrees(np.arctan(yaw_num / yaw_den))
    pitch = -np.degrees(np.arcsin(2*q1*q3 - 2*q0*q2))
    return roll, pitch, yaw


# Xsens's 22-joint order, as <jointAngle> lays them out (3 values each).
XSENS_JOINT_ORDER = (
    "jL5S1", "jL4L3", "jL1T12", "jT9T8", "jT1C7", "jC1Head",
    "jRightC7Shoulder", "jRightShoulder", "jRightElbow", "jRightWrist",
    "jLeftC7Shoulder", "jLeftShoulder", "jLeftElbow", "jLeftWrist",
    "jRightHip", "jRightKnee", "jRightAnkle", "jRightBallFoot",
    "jLeftHip", "jLeftKnee", "jLeftAnkle", "jLeftBallFoot",
)

# DOF index within each joint's triplet. Confirmed empirically against our IK
# solution on real data: index 0 matched hip_adduction at r 0.937, index 2
# matched hip_flexion at r 0.988.
ABDUCTION, ROTATION, FLEXION = 0, 1, 2

# OpenSim coordinate -> (Xsens joint, DOF index, sign). Signs are XtoO.m's.
JOINT_COORDINATE_MAP = {
    "hip_flexion_r": ("jRightHip", FLEXION, 1.0),
    "hip_adduction_r": ("jRightHip", ABDUCTION, -1.0),
    "hip_rotation_r": ("jRightHip", ROTATION, 1.0),
    "knee_angle_r": ("jRightKnee", FLEXION, 1.0),
    "ankle_angle_r": ("jRightAnkle", FLEXION, 1.0),
    "subtalar_angle_r": ("jRightAnkle", ROTATION, 1.0),
    "mtp_angle_r": ("jRightBallFoot", FLEXION, 1.0),
    "hip_flexion_l": ("jLeftHip", FLEXION, 1.0),
    "hip_adduction_l": ("jLeftHip", ABDUCTION, -1.0),
    "hip_rotation_l": ("jLeftHip", ROTATION, 1.0),
    "knee_angle_l": ("jLeftKnee", FLEXION, 1.0),
    "ankle_angle_l": ("jLeftAnkle", FLEXION, 1.0),
    "subtalar_angle_l": ("jLeftAnkle", ROTATION, 1.0),
    "mtp_angle_l": ("jLeftBallFoot", FLEXION, 1.0),
    "lumbar_extension": ("jL5S1", FLEXION, -1.0),
    "lumbar_bending": ("jL5S1", ABDUCTION, 1.0),
    "lumbar_rotation": ("jL5S1", ROTATION, 1.0),
    "arm_flex_r": ("jRightShoulder", FLEXION, 1.0),
    "arm_add_r": ("jRightShoulder", ABDUCTION, -1.0),
    "arm_rot_r": ("jRightShoulder", ROTATION, 1.0),
    "elbow_flex_r": ("jRightElbow", FLEXION, 1.0),
    "pro_sup_r": ("jRightElbow", ROTATION, 1.0),
    "arm_flex_l": ("jLeftShoulder", FLEXION, 1.0),
    "arm_add_l": ("jLeftShoulder", ABDUCTION, -1.0),
    "arm_rot_l": ("jLeftShoulder", ROTATION, 1.0),
    "elbow_flex_l": ("jLeftElbow", FLEXION, 1.0),
    "pro_sup_l": ("jLeftElbow", ROTATION, 1.0),
}

# Pelvis rotation: (euler channel, sign). MEASURED, not taken from XtoO.m --
# against our IK solution on CK-001, tilt is -pitch (r -0.992), list is +roll
# (r +0.984), rotation is +yaw (r +0.989). XtoO.m assigns tilt from roll.
PELVIS_ROTATION_MAP = {
    "pelvis_tilt": ("pitch", -1.0),
    "pelvis_list": ("roll", 1.0),
    "pelvis_rotation": ("yaw", 1.0),
}

# Pelvis translation: (Xsens position axis index, sign). Also measured. Xsens
# is Z-up and OpenSim is Y-up, so height (Xsens Z, ~0.97 m) belongs in
# pelvis_ty. Verified against OpenCap on the same motion: X->tx r +1.000,
# Z->ty r +0.664, Y->tz r -0.994.
PELVIS_TRANSLATION_MAP = {
    "pelvis_tx": (0, 1.0),
    "pelvis_ty": (2, 1.0),
    "pelvis_tz": (1, -1.0),
}

# XtoO.m's literal assignment, kept so the original output can be reproduced
# for comparison. Measurably wrong -- it routes height into the lateral
# coordinate and scrambles the three rotation axes among themselves.
LEGACY_PELVIS_ROTATION_MAP = {
    "pelvis_tilt": ("roll", 1.0),
    "pelvis_list": ("yaw", -1.0),
    "pelvis_rotation": ("pitch", -1.0),
}
LEGACY_PELVIS_TRANSLATION_MAP = {
    "pelvis_tx": (0, 1.0),
    "pelvis_ty": (1, -1.0),
    "pelvis_tz": (2, 1.0),
}

# Column order of the written .mot, matching XtoO.m's table exactly.
MOT_COLUMN_ORDER = (
    "time",
    "pelvis_tilt", "pelvis_list", "pelvis_rotation",
    "pelvis_tx", "pelvis_ty", "pelvis_tz",
    "hip_flexion_r", "hip_adduction_r", "hip_rotation_r",
    "knee_angle_r", "ankle_angle_r", "subtalar_angle_r", "mtp_angle_r",
    "hip_flexion_l", "hip_adduction_l", "hip_rotation_l",
    "knee_angle_l", "ankle_angle_l", "subtalar_angle_l", "mtp_angle_l",
    "lumbar_extension", "lumbar_bending", "lumbar_rotation",
    "arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r", "pro_sup_r",
    "arm_flex_l", "arm_add_l", "arm_rot_l", "elbow_flex_l", "pro_sup_l",
)


def build_coordinate_table(pelvis_quaternions, pelvis_positions, joint_angles,
                           frame_rate, legacy_axes=False):
    """Map Xsens per-frame data onto OpenSim coordinates.

    `joint_angles` is (n_frames, 22, 3) in XSENS_JOINT_ORDER. Returns a dict of
    column name -> list of values, in MOT_COLUMN_ORDER.
    """
    quaternions = np.atleast_2d(np.asarray(pelvis_quaternions, dtype=float))
    positions = np.atleast_2d(np.asarray(pelvis_positions, dtype=float))
    angles = np.asarray(joint_angles, dtype=float)
    n_frames = quaternions.shape[0]
    if not frame_rate:
        raise ValueError("frame_rate is required to build the time column")

    # legacy_axes reproduces XtoO.m, which means reproducing all of it --
    # including the truncated atan convention, not just the axis assignment.
    roll, pitch, yaw = quaternion_to_euler(quaternions, use_atan2=not legacy_axes)
    channels = {"roll": roll, "pitch": pitch, "yaw": yaw}

    rotation_map = LEGACY_PELVIS_ROTATION_MAP if legacy_axes else PELVIS_ROTATION_MAP
    translation_map = LEGACY_PELVIS_TRANSLATION_MAP if legacy_axes else PELVIS_TRANSLATION_MAP

    table = {"time": list(np.arange(n_frames) / float(frame_rate))}
    for name, (channel, sign) in rotation_map.items():
        table[name] = list(sign * channels[channel])
    for name, (axis, sign) in translation_map.items():
        table[name] = list(sign * positions[:, axis])
    for name, (joint, dof, sign) in JOINT_COORDINATE_MAP.items():
        table[name] = list(sign * angles[:, XSENS_JOINT_ORDER.index(joint), dof])
    return {name: table[name] for name in MOT_COLUMN_ORDER}


def write_mot(path, table):
    """Write an OpenSim .mot. Header format is XtoO.m's, which is OpenSim's own.

    Every reader in this repo (and utilsKinematics) parses forward to
    'endheader' and then reads a tab-separated column row, so those two pieces
    are what make the file usable rather than merely well-formed.
    """
    columns = list(MOT_COLUMN_ORDER)
    n_rows = len(table[columns[0]])
    lines = [
        "Coordinates",
        "version=1",
        f"nRows={n_rows}",
        f"nColumns={len(columns)}",
        "inDegrees=yes",
        "Units are S.I. units (second, meters, Newtons, ...)",
        "If the header above contains a line with 'inDegrees', this indicates "
        "whether rotational values are in degrees (yes) or radians (no).",
        "endheader",
        "\t".join(columns),
    ]
    for row_index in range(n_rows):
        lines.append("\t".join(f"{table[name][row_index]:.6f}" for name in columns))
    from pathlib import Path as _Path
    _Path(path).parent.mkdir(parents=True, exist_ok=True)
    _Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def read_mvnx_frames(mvnx_path):
    """Pull the three things XtoO needs straight out of the .mvnx.

    XtoO.m reads .xlsx exports, but every field it uses is already present in
    the .mvnx -- <jointAngle> (22 joints x 3), <orientation> (23 segments x 4)
    and <position> (23 segments x 3). Skipping the spreadsheet removes an
    export step and a whole class of column-naming drift.

    Only `type="normal"` frames are returned: identity/tpose frames are
    calibration poses that carry no <position> at all.
    """
    import xml.etree.ElementTree as ET

    namespace = {"m": "http://www.xsens.com/mvn/mvnx"}
    quaternions, positions, joint_angles = [], [], []
    frame_rate = None

    for _event, element in ET.iterparse(str(mvnx_path), events=("end",)):
        tag = element.tag.split("}")[-1]
        if tag == "subject":
            frame_rate = float(element.attrib.get("frameRate") or 0.0) or frame_rate
        if tag != "frame":
            continue
        if element.attrib.get("type") == "normal":
            orientation = element.find("m:orientation", namespace)
            position = element.find("m:position", namespace)
            angles = element.find("m:jointAngle", namespace)
            if orientation is None or position is None or angles is None:
                element.clear()
                continue
            quaternions.append([float(v) for v in orientation.text.split()][0:4])
            positions.append([float(v) for v in position.text.split()][0:3])
            flat = [float(v) for v in angles.text.split()]
            expected = len(XSENS_JOINT_ORDER) * 3
            if len(flat) != expected:
                raise ValueError(
                    f"{mvnx_path}: frame has {len(flat)} <jointAngle> values, "
                    f"expected {expected} ({len(XSENS_JOINT_ORDER)} joints x 3)."
                )
            joint_angles.append(np.array(flat).reshape(len(XSENS_JOINT_ORDER), 3))
        element.clear()

    if not quaternions:
        raise ValueError(f"{mvnx_path}: no motion frames with orientation, position "
                         "and jointAngle were found.")
    return {
        "pelvis_quaternions": np.array(quaternions),
        "pelvis_positions": np.array(positions),
        "joint_angles": np.array(joint_angles),
        "frame_rate": frame_rate,
        "n_frames": len(quaternions),
    }


def convert_mvnx_to_mot(mvnx_path, mot_path, legacy_axes=False):
    """.mvnx -> OpenSim .mot, bypassing inverse kinematics entirely."""
    frames = read_mvnx_frames(mvnx_path)
    table = build_coordinate_table(
        frames["pelvis_quaternions"], frames["pelvis_positions"],
        frames["joint_angles"], frames["frame_rate"], legacy_axes=legacy_axes,
    )
    return write_mot(mot_path, table)
