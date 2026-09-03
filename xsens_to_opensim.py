"""
xsens_to_opensim.py

Draft: a lighter-weight Xsens -> OpenSim conversion, replacing the existing
MATLAB-joint-mapping + marker-reconstruction pipeline (getMarkers.py +
whatever MATLAB step produces the .mot files it consumes) with OpenSim's own
purpose-built IMU-orientation pipeline, called "OpenSense". No MATLAB, no
marker synthesis, no re-running IK twice on synthetic markers.

WHY THIS IS LESS HEAVYWEIGHT THAN THE EXISTING PIPELINE
---------------------------------------------------------------------------
The existing repo pipeline (see VENDORING.md) is:
    Xsens .mvnx --[MATLAB, manual joint-name mapping]--> .mot
        --[getMarkers.py: forward-kinematics a model through that .mot,
           read back marker positions, write .trc]--> synthetic markers
        --[re-run OpenSim's marker-based InverseKinematicsTool]--> .mot again

That round-trip exists to work around one specific problem: OpenCap's
downstream analysis code expects marker-derived motion, and raw joint-angle
.mot files can't be imported back into an OpenCap session directly (see
README.md's "Known issues" section).

OpenSim ships its own answer to "I have an IMU suit, I want joint angles,
skip the markers": the OpenSense framework (IMUPlacer + IMUInverseKinematicsTool),
built specifically for this (Xsens is one of its two officially supported
input formats, alongside APDM). It goes straight from IMU orientations to a
.mot file:

    Xsens .mvnx --[this script, pure Python + stdlib xml]--> orientations.sto
        --[opensim.IMUPlacer, one static frame]--> calibrated .osim
        --[opensim.IMUInverseKinematicsTool]--> .mot directly, no markers

No MATLAB. No per-joint manual angle mapping. No forward-kinematics/marker
round-trip. Three stages, each a single OpenSim API call.

SOURCES THIS WAS BUILT FROM (2026-08-17 research)
---------------------------------------------------------------------------
- opensim-core source, read directly via `gh api` (not guessed):
  - OpenSim/Common/XsensDataReader.cpp -- confirms Xsens quaternion convention
    is scalar-first (q0=w, q1=x, q2=y, q3=z), matching SimTK::Quaternion's own
    constructor order, so no component reordering is needed anywhere below.
  - OpenSim/Simulation/OpenSense/IMUPlacer.h, OpenSim/Tools/IMUInverseKinematicsTool.h,
    OpenSim/Tools/InverseKinematicsToolBase.h -- the exact Python-settable
    property names used below (set_model_file, set_orientation_file_for_calibration,
    set_base_imu_label, set_base_heading_axis, set_sensor_to_opensim_rotations,
    set_orientations_file, set_time_range, set_results_directory, set_output_motion_file).
  - Applications/opensense/opensense.cpp -- the official reference CLI driver;
    confirms the 3-stage sequence and that these are meant to be scripted, not
    just run from the GUI.
  - Bindings/Java/Matlab/OpenSenseExample/{IMUDataConversion.m,
    OpenSense_CalibrateModel.m, OpenSense_OrientationTracking.m} -- the
    official worked example. MATLAB and Python share the same SWIG-generated
    property setters (org.opensim.modeling.* == opensim.*), so this script's
    API calls mirror that example almost line for line. This is also where
    the sensor_to_opensim_rotations = (-pi/2, 0, 0) constant comes from: it's
    the documented rotation from Xsens's Z-up world frame to OpenSim's Y-up
    ground frame, not something invented here.
  - Web search confirmed opensim.TimeSeriesTableQuaternion and
    opensim.STOFileAdapterQuaternion.write(table, path) are exposed in the
    Python bindings (SimTK forum thread on quaternion import in Python).
- MVNX schema. Originally read from a real open-source parser's element
  traversal (github.com/alexharston/mvnx, mvnx/models.py) -- a "full"
  document shaped like <mvnx><subject segmentCount=.. frameRate=..>
  <segments><segment id=.. label=..>...</segments><frames>...</frames>,
  with each <frame>'s first 3 entries assumed to be non-motion frames.
  **Then corrected against a real file** (0_Bed_to_ShowerChair_M.mvnx,
  provided 2026-08-17, inspected directly with `ET.parse` + byte-offset
  greps, not assumed): that file's root element IS <frames
  segmentCount="23" jointCount="22"> directly -- no <mvnx>/<subject>
  wrapper, no <segments> label list at all. It has exactly 2 non-motion
  leading frames (one type="npose", one type="tpose"), not 3 -- the
  original fixed `frames[3:]` slice would have silently dropped the first
  real motion frame. Frame selection is now done by each frame's own
  type="normal" attribute instead of a hardcoded count. Confirmed empirically
  against the real file: 2609 "normal" frames at ~60 Hz (16-17ms spacing),
  23 segments x 4 floats = 92 values in <orientation>, 17 sensors x 4 = 68
  values in <sensorOrientation>. The frame's `time` attribute genuinely is
  elapsed milliseconds (0, 16, 33, 50...) -- the separate `ms` attribute is
  the one holding a large Unix-epoch timestamp, not `time`.
- Standard 23-segment Xsens order (STANDARD_23_SEGMENT_ORDER below), needed
  as a fallback because the real file has no <segments> labels to read.
  Cross-checked against three independent sources: Xsens's own MVN User
  Manual, the original "Xsens MVN: Full 6DOF Human Motion Tracking" paper,
  and an arXiv paper on bridging Xsens MVN to ROS -- all agree on the same
  23-segment order.

STATUS (updated 2026-08-19 -- see VENDORING.md for the full history)
---------------------------------------------------------------------------
The OpenSim-dependent half (STOFileAdapterQuaternion, IMUPlacer,
IMUInverseKinematicsTool) HAS been run end to end, repeatedly, against real
clinical data -- not just the .mvnx-parsing half. Real bugs this surfaced and
fixed along the way: two Python-binding API mismatches (RowVectorQuaternion
has no __setitem__; Model.print() is Model.printToXML() in Python), a missing
mkdir before writing the .sto, and -- the big one -- a wrong default
`base_heading_axis` ('z', copied from OpenSim's Rajagopal reference example)
that produced a 95.8 degree heading-correction anomaly and effectively froze
knee flexion in the output. Fixed by switching the default to 'x' (confirmed
empirically: 5.8 degree correction vs. 84-174 degrees for every other axis
option). Full numbers and the diagnostic process are in VENDORING.md.

SECOND CALIBRATION BUG, FOUND AND FIXED 2026-09-02
---------------------------------------------------------------------------
The arm half of the "still open" gap below turned out to be the 2026-08-19
T-pose hypothesis, and it was right. IMUPlacer measures each body<->IMU
offset against the model's DEFAULT pose; the calibration frame written as
row 0 is the Xsens T-pose; the LaiUhlrich2022 default is arms-down. The 90
degrees of shoulder abduction between them went into the arm IMU offsets, IK
had to report a walking arm as ~90 degrees abducted, that is gimbal lock for
the shoulder Euler triplet, and arm_flex/arm_rot then wound up against the
model's own +/-572.96 deg (+/-10 rad) coordinate bounds. Fixed by posing the
model in the calibration frame's own pose before IMUPlacer runs -- see
CALIBRATION_POSES and calibrate_model. Upper-body IMU tracking error on
CK-001 drops from 4.5 to 2.0 deg RMS; the lower limb moves by under 0.4 deg,
which is the point: the legs hold the same pose in both, and were never wrong.

WHAT'S STILL OPEN (be honest about the gap)
---------------------------------------------------------------------------
- Some tracking error remains even with the corrected heading axis
  (femur_r and calcn_r/l specifically) -- not yet explained. See
  VENDORING.md's 2026-08-19 entries for the current numbers and the one
  untested hypothesis left over from them (alternate `base_imu`). The arm
  segments used to be on this list; that part is the calibration-pose bug
  above, now fixed.
- source="sensor" (raw per-sensor orientation, <sensorOrientation>) is
  still experimental, not a verified alternative to the default
  source="segment": the sensor-to-segment slot-order mapping is inferred
  from a parallel Excel export's structure, not independently proven for
  the .mvnx binary compact form. Treat source="segment" as the supported
  path.
- SEGMENT_TO_IMU_FRAME's Xsens-side keys are now real (STANDARD_23_SEGMENT_ORDER,
  confirmed above). Its OpenSim-side values are still a stand-in from
  OpenSim's official Rajagopal example -- they depend on which OpenSim model
  you calibrate against, which isn't chosen yet.
- Calibration pose: if the .mvnx has a dedicated tpose/npose frame (the real
  file does), that's used automatically -- see build_orientations_sto. If a
  future file doesn't have one, --list-segments will print a warning, and
  calibration falls back to the first motion frame, which may not be a
  clean static pose.

USAGE
---------------------------------------------------------------------------
    python xsens_to_opensim.py --list-segments capture.mvnx
        # prints segment id/label pairs -- use this to fill in
        # SEGMENT_TO_IMU_FRAME below for your subject/model.

    python xsens_to_opensim.py capture.mvnx generic_model.osim \
        --base-imu pelvis_imu --base-heading-axis x \
        --start-time 7.25 --end-time 15.0 \
        --results-dir IKResults

REQUIREMENTS
---------------------------------------------------------------------------
- Python's standard library only for the .mvnx parsing (xml.etree).
- The `opensim` package (conda: `conda install -c opensim-org opensim`) for
  everything from writing the .sto file onward. Nothing else.
"""

import argparse
import math
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Standard Xsens full-body 23-segment order. Used as a fallback ONLY when a
# parsed .mvnx has no <segments> label list of its own -- which turned out to
# be the case for the real file this was tested against
# (0_Bed_to_ShowerChair_M.mvnx, 2026-08-17: root is a bare <frames
# segmentCount="23"> with no <mvnx>/<subject>/<segments> wrapper at all, so
# there's nowhere to read real labels from). Originally corroborated by three
# independent literature sources (Xsens's MVN User Manual, the original
# "Xsens MVN: Full 6DOF Human Motion Tracking" paper, an arXiv paper on
# bridging Xsens MVN to ROS); **now also directly confirmed against a real,
# fully-labeled export** -- context/S01-001.xlsx (a parallel Excel export
# for the same suit/subject, provided 2026-08-17), whose "Segment
# Orientation - Quat" sheet has literal column headers "Pelvis q0, Pelvis
# q1, ..., L5 q0, ...", in exactly this order. If your actual segment order
# differs (custom configuration, different Xsens software version), this
# will be wrong; re-export a full .mvnx with the <segments> list included,
# or check against your own Excel export, rather than trusting this blindly.
STANDARD_23_SEGMENT_ORDER = [
    "Pelvis", "L5", "L3", "T12", "T8", "Neck", "Head",
    "RightShoulder", "RightUpperArm", "RightForeArm", "RightHand",
    "LeftShoulder", "LeftUpperArm", "LeftForeArm", "LeftHand",
    "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToe",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToe",
]

# Which of the 23 standard segments actually carry a physical IMU on a
# full-body Xsens Awinda/Link suit, in STANDARD_23_SEGMENT_ORDER order.
# Confirmed directly, not assumed: context/S01-001.xlsx's "Sensor
# Orientation - Quat" sheet uses the same 23-segment column layout as
# "Segment Orientation - Quat", but with (0,0,0,0) for segments that have no
# physical sensor -- Xsens interpolates/constrains those from its
# biomechanical model instead of measuring them directly. Checked every
# column: exactly these 17 have real (non-zero) data; L5, L3, T12, Neck,
# RightToe, LeftToe do not. This is the set to use if you switch to raw
# sensor orientation instead of segment orientation (see the module
# docstring's accuracy discussion) -- assumes the same 17-sensor
# configuration holds across sessions/trials for this subject/suit setup,
# which wasn't independently re-confirmed for 0_Bed_to_ShowerChair_M.mvnx
# specifically (different trial than the Excel file this was checked
# against).
# Standard Xsens full-body 22-joint order for the <jointAngle> element (66
# values/frame = 22 joints x 3 DOF). Used as a fallback ONLY when a parsed
# .mvnx has no joint label list of its own -- true for every real file seen
# so far (same "frames-only" export shape with no <segments> list either;
# see STANDARD_23_SEGMENT_ORDER above).
#
# Not guessed: 23 segments in a tree rooted at Pelvis means exactly 22
# parent-child edges, i.e. one joint per non-root segment -- so this is
# STANDARD_23_SEGMENT_ORDER's own traversal order with the root dropped,
# each entry renamed to Xsens's "j<Parent><Child>"-style joint-naming
# convention. Confirmed directly, not just structurally inferred: this exact
# order (and the per-DOF order below) was read out of
# context/S01-001.xlsx's "Joint Angles ZXY" sheet -- a real parallel export
# for this same subject/suit -- via its literal column headers ("L5S1
# Lateral Bending", "L5S1 Axial Bending", "L5S1 Flexion/Extension", "L4L3
# ...", ..., "hip_add_r", "hip_rot_r", "hip_flex_r", ..., "ballfoot_flex_l"),
# 2026-08-19. All 22 joints, in this order, confirmed present with exactly
# 3 columns each.
STANDARD_22_JOINT_ORDER = [
    "jL5S1", "jL4L3", "jL1T12", "jT9T8", "jT1C7", "jC1Head",
    "jRightC7Shoulder", "jRightShoulder", "jRightElbow", "jRightWrist",
    "jLeftC7Shoulder", "jLeftShoulder", "jLeftElbow", "jLeftWrist",
    "jRightHip", "jRightKnee", "jRightAnkle", "jRightBallFoot",
    "jLeftHip", "jLeftKnee", "jLeftAnkle", "jLeftBallFoot",
]

# The 3 values per joint in <jointAngle>, in order. Also confirmed against
# context/S01-001.xlsx's real column headers (2026-08-19), not assumed --
# notably flexion/extension is the THIRD value, not the first, for every
# joint checked (e.g. "hip_add_r, hip_rot_r, hip_flex_r"; "Right Shoulder
# Abduction/Adduction, ...Internal/External Rotation, ...Flexion/Extension").
# Some joints use synonymous naming in the raw export (elbow/wrist/ankle use
# "dev"/"pro" instead of "add"/"rot") but the same 3-axis order throughout.
JOINT_ANGLE_DOF_NAMES = (
    "abduction_adduction", "internal_external_rotation", "flexion_extension",
)

SENSOR_EQUIPPED_SEGMENTS = [
    "Pelvis", "T8", "Head",
    "RightShoulder", "RightUpperArm", "RightForeArm", "RightHand",
    "LeftShoulder", "LeftUpperArm", "LeftForeArm", "LeftHand",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
]

# Map Xsens segment label -> OpenSim model IMU frame name.
#
# IMPORTANT, confirmed by reading IMUPlacer.cpp directly (not guessed): the
# "IMU frame name" isn't an arbitrary label. IMUPlacer takes each orientation
# column name, strips a literal trailing "_imu", and looks for an EXISTING
# Body/PhysicalFrame in the model with exactly that remaining name --
# `imuName.rfind("_imu")` then `model->findComponent<PhysicalFrame>(bodyName)`.
# If no body matches, that column is silently skipped (logged, not an error).
# So these values must be "<real body name in your model>_imu", nothing else
# -- the model does NOT need pre-existing IMU frames; IMUPlacer creates them.
#
# The mapping below is now grounded in two real files, not placeholders:
#   - Left side: SENSOR_EQUIPPED_SEGMENTS (confirmed real sensors, above).
#   - Right side: actual Body names read directly out of
#     context/LaiUhlrich2022_scaled.osim (the real scaled model from your
#     OpenCap session, extracted from the OpenCap data zip and grepped for
#     `<Body name="...">`), not a generic example model.
# Segments dropped from the Rajagopal-example version some have no matching
# body in this model at all (Head, RightShoulder, LeftShoulder -- this model
# has no separate head/shoulder bodies; T8 stands in for the whole torso).
SEGMENT_TO_IMU_FRAME = {
    "Pelvis": "pelvis_imu",
    "T8": "torso_imu",
    "RightUpperArm": "humerus_r_imu",
    "RightForeArm": "radius_r_imu",
    "RightHand": "hand_r_imu",
    "LeftUpperArm": "humerus_l_imu",
    "LeftForeArm": "radius_l_imu",
    "LeftHand": "hand_l_imu",
    "RightUpperLeg": "femur_r_imu",
    "RightLowerLeg": "tibia_r_imu",
    "RightFoot": "calcn_r_imu",
    "LeftUpperLeg": "femur_l_imu",
    "LeftLowerLeg": "tibia_l_imu",
    "LeftFoot": "calcn_l_imu",
}

# Xsens world frame (Z-up) -> OpenSim ground frame (Y-up), space-fixed XYZ
# Euler angles. This exact constant is used, unmodified, in OpenSim's own
# Rajagopal OpenSense example scripts -- not something derived here.
SENSOR_TO_OPENSIM_ROTATIONS = (-math.pi / 2, 0.0, 0.0)

# The OpenSim model pose that corresponds to each Xsens calibration frame, as
# {coordinate name: value in DEGREES}. Anything not listed keeps the model's
# own default value.
#
# WHY THIS EXISTS (defect found and fixed 2026-09-02). IMUPlacer does not
# infer the subject's pose from the data: it computes each body<->IMU offset
# by comparing the calibration frame's measured orientation against the
# orientation that body has in the model's DEFAULT pose (IMUPlacer.cpp calls
# initSystem() and reads the working state; it never solves for a pose). So
# the model must be standing in the same physical pose the subject held when
# that frame was recorded, or the difference is silently absorbed into the
# offsets and reappears as a constant error in every joint angle downstream.
#
# build_orientations_sto writes the Xsens T-pose as row 0 (every real .mvnx in
# this study has one: 90/90 trials carry 'tpose', none carry 'npose'). The
# LaiUhlrich2022 default pose is arms-DOWN. That 90 degrees of shoulder
# abduction was going into the humerus/radius/hand offsets, and IK then had to
# report a walking arm as ~90 degrees abducted -- which is gimbal lock for the
# shoulder's Euler triplet, so arm_flex and arm_rot became free to trade off
# against each other and wound up to the model's own +/-572.96 deg (+/-10 rad)
# coordinate bounds. Measured on CK before the fix: arm_flex_l -566 deg,
# arm_rot_l +573 deg, across-stride SD ~157 deg. After: SD ~2 deg, and the
# upper-body IMU tracking error drops from 4.5 to 2.0 deg RMS. The lower limb
# is unchanged to within 0.4 deg, because the legs hold the same pose in both.
#
# The values below were read off the real scaled model, not assumed:
#   arm_add = -90 abducts on BOTH sides (at arm_add_r = -90 the humerus_r
#     frame's proximal axis points left, i.e. the right arm points right; the
#     same value mirrors correctly on the left).
#   pro_sup = +90 is forearm-neutral on this model (range 0..119.75 deg, 0 =
#     full supination). The Xsens T-pose is palms-down with the arm abducted,
#     which is the same forearm rotation as relaxed standing -- adducting the
#     arm to the side takes palm-down to palm-medial with no forearm rotation.
#     Confirmed against the marker-based OpenCap solution on the same subject:
#     with pro_sup posed at 90 the IMU route reports 95-101 deg where OpenCap
#     reports 89-94; left at 0 it reported 5-11 deg.
#   arm_flex, arm_rot and elbow_flex are 0 in a T-pose, i.e. already default.
CALIBRATION_POSES = {
    "tpose": {
        "arm_add_r": -90.0,
        "arm_add_l": -90.0,
        "pro_sup_r": 90.0,
        "pro_sup_l": 90.0,
    },
    # Relaxed standing, arms at the sides -- already the model's default pose,
    # so nothing to set. Present as an explicit entry rather than a missing
    # key so "we know this pose needs no adjustment" reads differently from
    # "we don't know what this pose is".
    "npose": {},
}


def resolve_calibration_pose(calibration_pose):
    """Normalise calibrate_model's `calibration_pose` argument to a
    {coordinate: degrees} dict.

    Accepts a CALIBRATION_POSES key, an explicit dict, or None (meaning "do
    not pose the model" -- the right answer when the .mvnx had no static
    calibration frame at all and row 0 is just whatever the recording started
    on, since then there is no known pose to match).

    An unrecognised name raises rather than falling back to "leave it alone":
    a silently unposed model is the exact failure this whole mechanism exists
    to prevent, and it produces plausible-looking numbers rather than an error.
    """
    if calibration_pose is None:
        return {}
    if isinstance(calibration_pose, dict):
        return dict(calibration_pose)
    if calibration_pose in CALIBRATION_POSES:
        return dict(CALIBRATION_POSES[calibration_pose])
    raise ValueError(
        f"Unknown calibration pose {calibration_pose!r}. Known poses: "
        f"{sorted(CALIBRATION_POSES)}. Pass an explicit "
        "{coordinate: degrees} dict for anything else, or None to leave the "
        "model in its default pose."
    )


def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_mvnx(mvnx_path, skip_leading_frames=3):
    """Parse an Xsens .mvnx file with the standard library only.

    Returns a dict:
        segments: {id (str): label (str)}, in document order
        frame_rate: float (Hz)
        times: list[float], seconds, one per motion frame
        orientations: list[ list[(w, x, y, z), ...] ]
            outer list is one entry per motion frame,
            inner list is one quaternion per segment, in `segments` order.
        sensor_orientations_raw: list[ list[float] | None ], one entry per
            motion frame, each a FLAT (not yet reshaped) list of floats from
            that frame's <sensorOrientation> element, or None if absent.
            Not validated/reshaped here -- this file alone doesn't tell you
            reliably which compact slot is which segment (no <sensors>
            label list either), so that mapping lives in
            SENSOR_EQUIPPED_SEGMENTS + build_orientations_sto instead of
            being guessed at parse time.
        calibration_orientation: list[(w, x, y, z), ...] | None -- a static
            tpose/npose frame's segment orientations, if the file has one.
        calibration_frame_type: "tpose" | "npose" | None -- WHICH static frame
            the entry above came from. Reported rather than left implicit
            because the two are different physical poses and the OpenSim
            model has to be put into the matching one before IMUPlacer runs
            (see CALIBRATION_POSES / calibrate_model). None means the file had
            neither and calibration falls back to the first motion frame.

    Handles two shapes of .mvnx, confirmed by inspecting a real file
    (0_Bed_to_ShowerChair_M.mvnx, 2026-08-17) rather than assumed:

    1. A "full" document: <mvnx><mvn/><subject frameRate=.. segmentCount=..>
       <segments><segment id=.. label=..>...</segments><frames>...
       This is what the reference open-source parser (alexharston/mvnx) this
       was originally built against expects, and what OpenSim's own
       documentation describes.
    2. A "frames-only" export: the document root IS <frames segmentCount=..
       jointCount=..> directly -- no <mvnx>/<mvn>/<subject> wrapper, and
       critically, NO <segments> label list. This is what the real file
       turned out to be. Since there's no label list, segment names fall
       back to STANDARD_23_SEGMENT_ORDER (see module-level constant) --
       correct only if segmentCount == 23 (a standard full-body suit); for
       any other count this raises rather than guessing.

    `skip_leading_frames` is IGNORED for frame selection now -- an earlier
    version sliced off a fixed number of leading frames (3, matching the
    reference parser), but the real file has only 2 non-motion leading
    frames (one 'npose', one 'tpose'), which would have silently dropped
    the first real motion frame. Frames are now selected by their own
    type="normal" attribute instead, which is robust to however many
    calibration frames precede the real data.
    """
    tree = ET.parse(mvnx_path)
    root = tree.getroot()
    ns = _strip_ns(root.tag) and (
        root.tag[: root.tag.index("}") + 1] if "}" in root.tag else ""
    )
    root_tag = _strip_ns(root.tag)

    if root_tag == "mvnx":
        subject = root.find(ns + "subject")
        if subject is None:
            raise ValueError(f"{mvnx_path}: no <subject> element under <mvnx>.")
        frame_rate = float(subject.attrib.get("frameRate", 0)) or None
        segments_el = subject.find(ns + "segments")
        frames_el = subject.find(ns + "frames")
        if frames_el is None:
            raise ValueError(f"{mvnx_path}: no <frames> element under <subject>.")
    elif root_tag == "frames":
        # Frames-only export (root IS <frames>) -- no <mvn>/<subject> wrapper,
        # and typically no <segments> label list either.
        frame_rate = None
        segments_el = None
        frames_el = root
    else:
        raise ValueError(
            f"{mvnx_path}: root element is <{root_tag}>, expected <mvnx> or "
            "<frames> -- is this really an .mvnx export?"
        )

    declared_segment_count = frames_el.attrib.get("segmentCount")

    if segments_el is not None:
        segments = {s.attrib["id"]: s.attrib["label"] for s in segments_el}
    else:
        # No <segments> label list in this file (the "frames-only" export
        # shape). Fall back to the standard Xsens full-body segment order --
        # only trustworthy if the frame's declared count matches 23.
        if declared_segment_count is not None and int(declared_segment_count) != len(
            STANDARD_23_SEGMENT_ORDER
        ):
            raise ValueError(
                f"{mvnx_path}: this file has no <segments> label list, and "
                f"segmentCount={declared_segment_count} doesn't match the "
                f"standard 23-segment full-body order this script falls "
                "back to. Can't safely guess segment names for a non-standard "
                "segment count -- re-export a full .mvnx with the <segments> "
                "list included, or supply segment names explicitly."
            )
        segments = {str(i + 1): name for i, name in enumerate(STANDARD_23_SEGMENT_ORDER)}

    n_segments = len(segments)

    # Unlike n_segments (validated upfront, since every real file so far has
    # had <orientation> data for every frame), joint_names is only actually
    # exercised if a frame turns out to have <jointAngle> data -- validated
    # lazily in the per-frame loop below instead of raising here, so files
    # with a non-standard segmentCount used only for segment-orientation
    # testing (no jointAngle data at all) aren't rejected over a joint count
    # that's irrelevant to what they're actually being parsed for.
    joint_names = list(STANDARD_22_JOINT_ORDER)
    n_joints = len(joint_names)

    def _frame_child_values(frame, tag_name):
        for child in frame:
            if _strip_ns(child.tag) == tag_name and child.text:
                return [float(v) for v in child.text.split()]
        return None

    def _frame_orientation(frame):
        return _frame_child_values(frame, "orientation")

    all_frames = list(frames_el)
    motion_frames = [f for f in all_frames if f.attrib.get("type") == "normal"]
    if not motion_frames:
        # Fall back to the old fixed-skip behavior if no frame has a 'type'
        # attribute at all (older/different mvnx variant).
        motion_frames = all_frames[skip_leading_frames:]

    # A dedicated static pose to calibrate against, IF this file has one.
    # Matters because the first 'normal' frame is just wherever the recording
    # happened to start -- for a trial like "Bed to ShowerChair" that's very
    # likely NOT a clean static pose (could be lying down, mid-transfer,
    # etc.), and IMUPlacer calibrates off whatever frame ends up first in the
    # orientations file. Prefer 'tpose' (arms out, a clean reference pose)
    # over 'npose' (relaxed standing, arms at sides -- still static, but a
    # worse IMU-alignment reference) if both are present.
    #
    # Which of the two was taken is REPORTED, not just used: they are
    # different physical poses, and IMUPlacer calibrates against whatever
    # pose the OpenSim model is in. A T-pose needs the model's shoulders
    # abducted first (see CALIBRATION_POSES); an N-pose does not. Leaving the
    # caller to assume one is exactly how the arm defect fixed on 2026-09-02
    # survived -- see calibrate_model.
    calibration_orientation = None
    calibration_sensor_orientation_raw = None
    calibration_frame_type = None
    for frame_type in ("tpose", "npose"):
        candidate = next((f for f in all_frames if f.attrib.get("type") == frame_type), None)
        if candidate is not None:
            values = _frame_orientation(candidate)
            if values and len(values) == n_segments * 4:
                calibration_orientation = [
                    tuple(values[i : i + 4]) for i in range(0, len(values), 4)
                ]
                calibration_sensor_orientation_raw = _frame_child_values(
                    candidate, "sensorOrientation"
                )
                calibration_frame_type = frame_type
                break

    times = []
    orientations = []
    joint_angles = []  # list (per frame) of lists (per joint) of (add/abd,
    # int/ext rotation, flex/ext) tuples in STANDARD_22_JOINT_ORDER order --
    # None for a frame with no <jointAngle> element.
    center_of_mass = []  # list (per frame) of (x, y, z) tuples, or None.
    center_of_mass_raw = []  # same frames, untruncated -- kept only so the
    # 9-value layout can be structurally validated after the loop (below).
    sensor_orientations_raw = []  # flat float lists, not yet reshaped/labeled --
    # see build_orientations_sto's sensor path for validation against
    # SENSOR_EQUIPPED_SEGMENTS. Kept separate from `orientations` validation
    # above since we don't have a per-file-confirmed sensor count the way we
    # do for the (always-present) full segment set.
    for frame in motion_frames:
        values = _frame_orientation(frame)
        if values is None:
            # Some frame types (e.g. a trailing empty frame) may lack data.
            continue
        expected = n_segments * 4
        if len(values) != expected:
            raise ValueError(
                f"{mvnx_path}: frame has {len(values)} orientation values, "
                f"expected {expected} ({n_segments} segments x 4). The "
                "segment count may not match this frame's <orientation> "
                "data -- double check this is a full-body recording."
            )

        quats = [tuple(values[i : i + 4]) for i in range(0, len(values), 4)]
        orientations.append(quats)

        sensor_values = _frame_child_values(frame, "sensorOrientation")
        sensor_orientations_raw.append(sensor_values)

        # Xsens's own joint-angle computation (see STANDARD_22_JOINT_ORDER
        # and JOINT_ANGLE_DOF_NAMES above) -- an independent source of joint
        # kinematics that doesn't go through this script's IMUPlacer/
        # IMUInverseKinematicsTool conversion at all. Not every .mvnx
        # necessarily has this element, so treat absence as "no data" rather
        # than an error.
        joint_angle_values = _frame_child_values(frame, "jointAngle")
        if joint_angle_values is not None:
            expected_joint = n_joints * 3
            if len(joint_angle_values) != expected_joint:
                raise ValueError(
                    f"{mvnx_path}: frame has {len(joint_angle_values)} "
                    f"<jointAngle> values, expected {expected_joint} "
                    f"({n_joints} joints x 3 DOF)."
                )
            joint_angles.append(
                [tuple(joint_angle_values[i : i + 3]) for i in range(0, len(joint_angle_values), 3)]
            )
        else:
            joint_angles.append(None)

        com_values = _frame_child_values(frame, "centerOfMass")
        if com_values is not None and len(com_values) not in (3, 9):
            raise ValueError(
                f"{mvnx_path}: frame has {len(com_values)} <centerOfMass> values, "
                "expected 3 (position) or 9 (position, velocity, acceleration)."
            )
        # MVNX v4 (MVN 2022+) writes centerOfMass as 9 values -- position,
        # then velocity, then acceleration -- where the older export shape
        # this parser was first built against carried only the 3 position
        # components. Confirmed empirically against a real v4 file rather
        # than taken from the schema: columns 0-2 hold a plausible standing
        # CoM height (~1 m, matching the recorded subject) that drifts slowly,
        # columns 3-5 hold ~0.01 m/s velocities, and columns 6-8 hold noisy
        # near-zero accelerations. Only position is used downstream, so keep
        # the leading 3 and drop the rest rather than rejecting the file.
        center_of_mass.append(tuple(com_values[:3]) if com_values else None)
        center_of_mass_raw.append(tuple(com_values) if com_values else None)

        time_attr = frame.attrib.get("time")
        if time_attr is not None:
            times.append(float(time_attr) / 1000.0)  # ms -> s, confirmed against
            # real frame timestamps (0, 16, 33, 50... ms at ~60 Hz) -- this
            # attribute genuinely is elapsed time, not an epoch stamp (that's
            # what the separate 'ms' attribute is, confirmed by inspecting
            # the real file: 'ms' holds a huge Unix-epoch-millisecond value).
        else:
            times.append(len(times) / frame_rate if frame_rate else float(len(times)))

    _validate_center_of_mass_layout(mvnx_path, center_of_mass_raw)

    if frame_rate is None and len(times) > 1:
        # Not present as an attribute in the frames-only export shape --
        # derive it from the actual frame timing instead of leaving it unset.
        frame_rate = round(1.0 / ((times[-1] - times[0]) / (len(times) - 1)))

    return {
        "segments": segments,
        "joint_names": joint_names,
        "frame_rate": frame_rate,
        "times": times,
        "orientations": orientations,
        "joint_angles": joint_angles,
        "center_of_mass": center_of_mass,
        "sensor_orientations_raw": sensor_orientations_raw,
        "calibration_orientation": calibration_orientation,
        "calibration_sensor_orientation_raw": calibration_sensor_orientation_raw,
        "calibration_frame_type": calibration_frame_type,
    }


# Index of the vertical component in an Xsens global-frame position triple.
# MVNX's global frame is Z-up (confirmed against a real export: a standing
# subject's centerOfMass reads ~(-4.0, 0.35, 0.99) -- the third component is
# the stature-like one, the first two are floor-plane coordinates). Note this
# differs from OpenSim, which is Y-up; the conversion happens downstream in
# build_orientations_sto, not here.
VERTICAL_AXIS_INDEX = 2


def _validate_center_of_mass_layout(mvnx_path, com_rows):
    """Tripwire for the assumption that a 9-value <centerOfMass> row is laid
    out [px,py,pz, vx,vy,vz, ax,ay,az] and can be truncated to its leading 3.

    That layout was confirmed empirically against a real MVNX v4 export, but
    truncation is only safe while it holds. A future MVN revision emitting 9
    values in some other arrangement -- the same CoM in two reference frames,
    say -- would pass the length check and silently redefine what
    "center of mass" means in the parsed output. This raises instead.

    Scope is deliberately narrow: **only 9-value rows are checked**, because
    only they get truncated. A 3-value row is used exactly as given, so there
    is no slicing assumption to defend, and validating it here would only add
    false rejections (an earlier draft of this guard broke on legitimate
    fixtures whose CoM sat near the origin).

    The discriminator is the vertical component, not magnitude. Magnitude
    cannot separate a position triple (~4 m) from a velocity triple (~1-2 m/s
    walking) -- the numbers overlap. But in Xsens's Z-up global frame the
    vertical component of a POSITION is stature-like and always well above
    zero, whereas the vertical component of a velocity or acceleration
    averages to ~0 over a trial. Three stacked positions therefore fail; a
    genuine position|velocity|acceleration row passes.

    This cannot prove the layout is [p|v|a]. It rejects the arrangements that
    would actually mislead us, and fails loudly instead of silently.

    Nothing downstream currently consumes center_of_mass (it is parsed,
    returned, and reported by --list-segments only), so a bad slice would be
    latent rather than immediately visible -- which is exactly why it is worth
    catching at parse time rather than at first use.
    """
    nine = [r for r in com_rows if r and len(r) == 9]
    if not nine:
        return

    def _median_of(index):
        vals = sorted(r[index] for r in nine)
        return vals[len(vals) // 2]

    pos_v = _median_of(VERTICAL_AXIS_INDEX)
    vel_v = _median_of(3 + VERTICAL_AXIS_INDEX)
    acc_v = _median_of(6 + VERTICAL_AXIS_INDEX)

    # Loose enough for a seated or supine subject, tight enough that a
    # non-position leading triple cannot pass.
    if not 0.15 <= pos_v <= 2.5:
        raise ValueError(
            f"{mvnx_path}: median <centerOfMass> vertical component is "
            f"{pos_v:.3f} m, outside the plausible 0.15-2.5 m range. The "
            "9-value layout is assumed to be position|velocity|acceleration "
            "and truncated to the leading 3 -- that assumption looks wrong "
            "for this file. Inspect a frame's raw values before trusting any "
            "center-of-mass output."
        )

    # A velocity or acceleration triple has a near-zero median vertical
    # component; a position triple does not.
    if abs(vel_v) > 0.15 or abs(acc_v) > 0.5:
        raise ValueError(
            f"{mvnx_path}: 9-value <centerOfMass> rows have median vertical "
            f"components (pos={pos_v:.3f}, second={vel_v:.3f}, "
            f"third={acc_v:.3f}) that do not look like "
            "position|velocity|acceleration -- the trailing triples read as "
            "positions, not derivatives. This parser truncates such rows to "
            "their leading 3 values on that assumption, so the center-of-mass "
            "output would be wrong. Inspect the file's raw values."
        )


def list_segments(mvnx_path):
    """Print segment id/label pairs -- use this to fill in SEGMENT_TO_IMU_FRAME."""
    parsed = parse_mvnx(mvnx_path)
    print(f"{len(parsed['segments'])} segments in {mvnx_path}:")
    for seg_id, label in parsed["segments"].items():
        print(f"  id={seg_id:>3}  label={label}")
    print(f"\n{len(parsed['times'])} motion frames at {parsed['frame_rate']} Hz.")
    if parsed["calibration_orientation"] is not None:
        print("A dedicated static calibration pose (tpose/npose) was found and "
              "will be used to calibrate the model -- not the first motion frame.")
    else:
        print("WARNING: no tpose/npose frame found in this file. Calibration will "
              "fall back to the first motion frame, which may not be a clean "
              "static pose -- check this before trusting the result.")

    has_joint_angles = any(ja is not None for ja in parsed["joint_angles"])
    has_com = any(com is not None for com in parsed["center_of_mass"])
    if has_joint_angles:
        print(f"\nThis file also has Xsens's own <jointAngle> data for all "
              f"{len(parsed['joint_names'])} joints -- an independent source of "
              "joint kinematics that doesn't need the IMUPlacer/IK conversion at all.")
    if has_com:
        print("This file also has Xsens's own <centerOfMass> per frame.")


def build_orientations_sto(mvnx_path, sto_path, segment_to_imu_frame, source="segment",
                           calibration_info=None):
    """Parse the .mvnx and write an OpenSim orientations .sto file, using only
    the segments named in `segment_to_imu_frame`. Column labels in the .sto
    file are the OpenSim IMU frame names (the dict's values), matching the
    convention OpenSim's own XsensDataReader uses (see IMUDataConversion.m).

    `source`:
      - "segment" (default): Xsens's own biomechanically-solved per-segment
        orientation (the <orientation> element). Ready to use now -- segment
        order/labels are confirmed (see STANDARD_23_SEGMENT_ORDER).
      - "sensor": raw per-sensor orientation (<sensorOrientation>), before
        Xsens's skeletal engine touches it. Architecturally closer to what
        OpenSense's IMU pipeline was designed around (one virtual IMU per
        physical sensor, constrained only by OpenSim's own model) -- but
        every key in `segment_to_imu_frame` MUST be in
        SENSOR_EQUIPPED_SEGMENTS, and the compact-slot-order assumption
        documented on SENSOR_EQUIPPED_SEGMENTS applies (inferred from a
        parallel Excel export's zero-padded layout, not independently
        proven for this exact .mvnx's compact <sensorOrientation> encoding
        -- worth spot-checking once you can run this for real).

    If the .mvnx has a dedicated static pose (tpose preferred, npose as
    fallback), it's written as the FIRST row, ahead of all motion frames --
    IMUPlacer always calibrates off the first row of whatever file it's
    given, so this makes sure that's a real static reference pose rather
    than whatever the recording happened to start on (see parse_mvnx's
    docstring for why that matters for a trial like this one).

    Pass a dict as `calibration_info` to find out WHICH static frame ended up
    as row 0: it gets a "frame_type" key ("tpose", "npose", or None if the
    file had neither). That value is what calibrate_model's `calibration_pose`
    argument wants -- the OpenSim model has to be posed to match, and a caller
    re-parsing the .mvnx just to find out would double the cost of the
    slowest stage in this pipeline. An out-parameter rather than a changed
    return value, so every existing caller keeps working unchanged.

    Requires the `opensim` package -- imported lazily so --list-segments
    works without it installed.
    """
    import opensim as osim

    if source not in ("segment", "sensor"):
        raise ValueError(f"source must be 'segment' or 'sensor', got {source!r}")

    parsed = parse_mvnx(mvnx_path)
    if calibration_info is not None:
        calibration_info["frame_type"] = parsed["calibration_frame_type"]
    segments = parsed["segments"]
    label_to_id = {label: seg_id for seg_id, label in segments.items()}
    seg_ids_in_order = list(segments.keys())

    if source == "segment":
        missing = [seg for seg in segment_to_imu_frame if seg not in label_to_id]
        if missing:
            raise ValueError(
                f"Segment(s) {missing} in segment_to_imu_frame not found in "
                f"{mvnx_path}. Available segments: {sorted(segments.values())}. "
                "Run with --list-segments to see them."
            )
        selected_indices = [
            seg_ids_in_order.index(label_to_id[seg]) for seg in segment_to_imu_frame
        ]
        motion_source_frames = parsed["orientations"]
        calibration_frame = parsed["calibration_orientation"]

        def _get_quat(frame_data, idx):
            return frame_data[idx]

    else:  # source == "sensor"
        not_sensor_equipped = [
            seg for seg in segment_to_imu_frame if seg not in SENSOR_EQUIPPED_SEGMENTS
        ]
        if not_sensor_equipped:
            raise ValueError(
                f"Segment(s) {not_sensor_equipped} in segment_to_imu_frame have no "
                f"physical sensor per SENSOR_EQUIPPED_SEGMENTS -- can't use "
                "source='sensor' for them. Use source='segment' instead, or drop "
                "them from segment_to_imu_frame."
            )
        expected_n_sensors = len(SENSOR_EQUIPPED_SEGMENTS)
        selected_indices = [
            SENSOR_EQUIPPED_SEGMENTS.index(seg) for seg in segment_to_imu_frame
        ]

        def _reshape_sensor(raw):
            if raw is None:
                return None
            if len(raw) != expected_n_sensors * 4:
                raise ValueError(
                    f"{mvnx_path}: frame has {len(raw)} <sensorOrientation> values, "
                    f"expected {expected_n_sensors * 4} ({expected_n_sensors} sensors "
                    "x 4, per SENSOR_EQUIPPED_SEGMENTS). This file's sensor "
                    "configuration doesn't match what SENSOR_EQUIPPED_SEGMENTS "
                    "assumes -- don't use source='sensor' until that's resolved."
                )
            return [tuple(raw[i : i + 4]) for i in range(0, len(raw), 4)]

        motion_source_frames = [_reshape_sensor(r) for r in parsed["sensor_orientations_raw"]]
        calibration_frame = _reshape_sensor(parsed["calibration_sensor_orientation_raw"])

        def _get_quat(frame_data, idx):
            return frame_data[idx]

    imu_frame_names = list(segment_to_imu_frame.values())

    table = osim.TimeSeriesTableQuaternion()
    table.setColumnLabels(imu_frame_names)

    def _append(t, frame_data):
        row = osim.RowVectorQuaternion(len(selected_indices))
        for col, idx in enumerate(selected_indices):
            w, x, y, z = _get_quat(frame_data, idx)
            # RowVectorQuaternion has no __setitem__/.set(col, quat) -- confirmed
            # by actually running this against real OpenSim 4.5 (2026-08-17),
            # not assumed. updElt(0, col) returns a *reference* into the row
            # (verified: mutating it via Quaternion.set(component_index, value)
            # propagates back into the row), so that's the only way to
            # populate a row in place. Quaternion.set(i, value) sets ONE of
            # the 4 components -- it's inherited from Vec4, not a
            # set-all-4-at-once call, hence 4 separate calls below.
            elt = row.updElt(0, col)
            elt.set(0, w)
            elt.set(1, x)
            elt.set(2, y)
            elt.set(3, z)
        table.appendRow(t, row)

    if calibration_frame is not None:
        first_motion_time = parsed["times"][0] if parsed["times"] else 0.0
        dt = (1.0 / parsed["frame_rate"]) if parsed["frame_rate"] else 1.0
        _append(first_motion_time - dt, calibration_frame)
    elif source == "sensor":
        # Confirmed against the real file (0_Bed_to_ShowerChair_M.mvnx,
        # 2026-08-17): its tpose/npose frames carry <orientation> and
        # <position> only -- no <sensorOrientation> at all -- even though
        # 'segment' mode's calibration_orientation IS available from the
        # same frames. Silently falling through here would mean
        # source='sensor' calibrates off the first real motion frame with
        # no warning, the exact bad-calibration-pose problem this script
        # already goes out of its way to avoid for source='segment'. Fail
        # loudly instead of guessing.
        raise ValueError(
            f"{mvnx_path}: no <sensorOrientation> data in the tpose/npose "
            "calibration frame, so source='sensor' has no static pose to "
            "calibrate against. Use source='segment' (has a valid "
            "calibration frame in this file), or find/record a trial with "
            "sensor data in its calibration frame."
        )

    for t, frame_data in zip(parsed["times"], motion_source_frames):
        if frame_data is None:
            continue  # a motion frame with no sensorOrientation data (source='sensor' only)
        _append(t, frame_data)

    Path(sto_path).parent.mkdir(parents=True, exist_ok=True)
    osim.STOFileAdapterQuaternion.write(table, str(sto_path))
    return sto_path


def calibrate_model(model_file, orientations_sto, base_imu_label, base_heading_axis,
                     output_model_file=None, calibration_pose="tpose"):
    """opensim.IMUPlacer: register IMU frames on the model using the FIRST
    frame of orientations_sto as the calibration pose. Mirrors
    OpenSense_CalibrateModel.m, with one addition it does not have.

    `calibration_pose` names the physical pose the subject held in that first
    frame -- a CALIBRATION_POSES key ("tpose", "npose"), an explicit
    {coordinate: degrees} dict, or None for "leave the model as it is". The
    model is put into that pose before IMUPlacer runs and restored afterwards,
    because IMUPlacer measures each body<->IMU offset against the model's
    default pose and has no way to discover the subject's. See
    CALIBRATION_POSES for the full reasoning and the numbers; the short
    version is that calibrating a T-pose frame against an arms-down model
    default buried 90 degrees of shoulder abduction in the arm IMU offsets.

    The default is "tpose" because that is what build_orientations_sto writes
    as row 0 for every real .mvnx seen (all 90 trials in this study carry a
    tpose frame and none carry an npose). Drivers should still pass the value
    parse_mvnx reported rather than rely on the default.
    """
    import opensim as osim

    output_model_file = output_model_file or str(
        Path(model_file).with_name(Path(model_file).stem + "_calibrated.osim")
    )

    # Posed in memory rather than by writing a second .osim: IMUPlacer.setModel
    # takes precedence over set_model_file (IMUPlacer::run only loads the file
    # when no model has been set), so this leaves no stray posed model on disk
    # to be mistaken for a real input later.
    model = osim.Model(str(model_file))
    pose = resolve_calibration_pose(calibration_pose)
    coordinates = model.getCoordinateSet()
    original_defaults = {}
    for name, degrees in pose.items():
        # A model without that coordinate is skipped, not an error: the pose
        # describes a human, and a reduced model (no arms, say) is still a
        # legitimate thing to calibrate.
        if not coordinates.contains(name):
            continue
        coordinate = coordinates.get(name)
        original_defaults[name] = coordinate.getDefaultValue()
        coordinate.setDefaultValue(math.radians(degrees))
    model.initSystem()

    imu_placer = osim.IMUPlacer()
    imu_placer.setModel(model)
    imu_placer.set_model_file(str(model_file))
    imu_placer.set_orientation_file_for_calibration(str(orientations_sto))
    imu_placer.set_sensor_to_opensim_rotations(osim.Vec3(*SENSOR_TO_OPENSIM_ROTATIONS))
    if base_imu_label:
        imu_placer.set_base_imu_label(base_imu_label)
    if base_heading_axis:
        imu_placer.set_base_heading_axis(base_heading_axis)

    imu_placer.run(False)
    calibrated_model = imu_placer.getCalibratedModel()

    # The calibration pose was scaffolding for IMUPlacer, not a property of
    # the calibrated model: the IMU offsets are baked into the offset frames
    # it just added, and everything downstream reads this file (IK's initial
    # guess, the forward-kinematics marker stage, task_functions). Hand it
    # back with the default pose it arrived with so the only difference from
    # the input model is the IMU frames.
    calibrated_coordinates = calibrated_model.getCoordinateSet()
    for name, radians in original_defaults.items():
        if calibrated_coordinates.contains(name):
            calibrated_coordinates.get(name).setDefaultValue(radians)

    # The MATLAB/C++ API calls this print(); the Python bindings rename it to
    # printToXML() (confirmed by actually running this, 2026-08-17 -- `print`
    # collides with the Python builtin, so SWIG must rename it there but not
    # in MATLAB).
    calibrated_model.printToXML(output_model_file)
    return output_model_file


def run_imu_ik(calibrated_model_file, orientations_sto, start_time, end_time,
               results_dir, output_motion_filename=None):
    """opensim.IMUInverseKinematicsTool: joint angles directly from IMU
    orientations, no markers. Mirrors OpenSense_OrientationTracking.m exactly.

    Returns the output .mot file's full path (not just results_dir) so
    callers -- e.g. main()'s optional marker/.trc stage -- can chain off it
    without having to guess IMUInverseKinematicsTool's default naming
    convention or list the results directory afterward.

    output_motion_filename overrides the default "ik_<sto stem>.mot" naming
    -- needed when writing directly into an existing OpenCap session's
    OpenSimData/Kinematics/ folder, where utilsKinematics.py's `kinematics`
    class (see resolve_session_output_paths) expects the file to be named
    exactly "<trialName>.mot", no prefix.
    """
    import opensim as osim

    Path(results_dir).mkdir(parents=True, exist_ok=True)
    output_motion_file = output_motion_filename or ("ik_" + Path(orientations_sto).stem + ".mot")

    imu_ik = osim.IMUInverseKinematicsTool()
    imu_ik.set_model_file(str(calibrated_model_file))
    imu_ik.set_orientations_file(str(orientations_sto))
    imu_ik.set_sensor_to_opensim_rotations(osim.Vec3(*SENSOR_TO_OPENSIM_ROTATIONS))
    if start_time is not None and end_time is not None:
        imu_ik.set_time_range(0, start_time)
        imu_ik.set_time_range(1, end_time)
    imu_ik.set_results_directory(str(results_dir))
    imu_ik.set_output_motion_file(output_motion_file)

    imu_ik.run(False)
    return str(Path(results_dir) / output_motion_file)


def _trc_header(trc_path, frame_rate, n_frames, n_markers, marker_names):
    """Build the standard 5-line TRC header as a list of lines (no trailing
    newlines) -- factored out from the writer so its exact format is
    independently checkable without needing OpenSim or real marker data."""
    lines = [
        "PathFileType\t4\t(X/Y/Z)\t" + Path(trc_path).name,
        "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
        f"{frame_rate}\t{frame_rate}\t{n_frames}\t{n_markers}\tm\t{frame_rate}\t1\t{n_frames}",
    ]
    label_row = "Frame#\tTime"
    sublabel_row = "\t"
    for i, name in enumerate(marker_names):
        label_row += f"\t{name}\t\t"
        sublabel_row += f"\tX{i + 1}\tY{i + 1}\tZ{i + 1}"
    lines.append(label_row)
    lines.append(sublabel_row)
    return lines


def write_trc(trc_path, times, marker_names, positions, frame_rate):
    """Write a TRC (marker trajectory) file.

    `positions` is a list (one entry per frame, same length as `times`) of
    lists of (x, y, z) tuples, one per marker, in `marker_names` order --
    i.e. the pure-Python file-writing half of get_marker_trajectory, kept
    separate so it's testable without OpenSim or a real model.
    """
    if len(times) != len(positions):
        raise ValueError(
            f"write_trc: {len(times)} times but {len(positions)} position frames -- "
            "these must match 1:1. zip() would otherwise silently truncate to the "
            "shorter one and the .trc header's NumFrames would disagree with the "
            "actual row count."
        )
    lines = _trc_header(trc_path, frame_rate, len(times), len(marker_names), marker_names)
    for frame_idx, (t, frame_positions) in enumerate(zip(times, positions), start=1):
        row = [str(frame_idx), f"{t:.6f}"]
        for x, y, z in frame_positions:
            row += [f"{x:.6f}", f"{y:.6f}", f"{z:.6f}"]
        lines.append("\t".join(row))
    Path(trc_path).write_text("\n".join(lines) + "\n")
    return trc_path


def get_marker_trajectory(model_file, mot_file):
    """Drive `model_file` through `mot_file`'s joint angles (frame by frame,
    forward kinematics only -- no dynamics, no muscle equilibrium) and read
    back each Marker's global position at every frame.

    This is the OpenSim-dependent half of "write a .trc from our IK output"
    -- the piece OpenCap's own downstream code needs (its gait-event
    detection reads marker trajectories, not raw joint angles; see
    getMarkers.py and README.md's "No direct motion-file import" issue).
    Deliberately NOT a port of getMarkers.py's version of this: that script
    applies np.radians() to every column indiscriminately, including the
    translational pelvis_tx/ty/tz columns (meters, not degrees), then papers
    over it with an ad hoc "+= pelvis_tx/ty" correction on the marker
    position that only covers two of the three translational coordinates.
    This version instead reads each coordinate's actual MotionType
    (Rotational vs Translational) from the model and only converts degrees
    to radians where that's actually correct, and sets each coordinate by
    name (matched against the .mot's own column labels) rather than by
    positional index -- avoiding the manual "rowSkip" bookkeeping
    getMarkers.py needs to keep index-based alignment working around
    constrained (e.g. patella '_beta') coordinates.

    Returns (times, marker_names, positions) -- positions is a list (one
    per frame) of lists of (x, y, z) tuples, one per marker, in
    marker_names order. Matches write_trc's expected input directly.
    """
    import opensim as osim

    model = osim.Model(str(model_file))
    state = model.initSystem()

    marker_set = model.getMarkerSet()
    markers = [marker_set.get(i) for i in range(marker_set.getSize())]
    marker_names = [m.getName() for m in markers]
    if not markers:
        raise ValueError(f"{model_file}: model has no markers -- can't write a .trc.")

    table = osim.TimeSeriesTable(str(mot_file))
    times = list(table.getIndependentColumn())
    column_labels = list(table.getColumnLabels())

    in_degrees = True
    if table.hasTableMetaDataKey("inDegrees"):
        in_degrees = str(table.getTableMetaDataString("inDegrees")).strip().lower() == "yes"

    coordinate_set = model.updCoordinateSet()
    # (coordinate, column_index, needs_degrees_to_radians) for every .mot
    # column that names an independent (non-constrained) model coordinate.
    # Skips columns with no matching coordinate and coordinates the model
    # itself says are dependent (e.g. patella '_beta' coordinates driven by
    # a CoordinateCouplerConstraint on knee flexion) -- setting those
    # directly is meaningless; the constraint recomputes them on realize.
    drivable = []
    for col_idx, label in enumerate(column_labels):
        if not coordinate_set.contains(label):
            continue
        coordinate = coordinate_set.get(label)
        if coordinate.isDependent(state):
            continue
        # Confirmed against the real Python bindings (2026-08-19, opensim 4.5):
        # the enum members are osim.Coordinate.Rotational / .Translational,
        # not MotionType_Rotational as the C++ enum name might suggest.
        is_rotational = coordinate.getMotionType() == osim.Coordinate.Rotational
        drivable.append((coordinate, col_idx, is_rotational and in_degrees))

    positions = []
    for row_idx in range(len(times)):
        row = table.getRowAtIndex(row_idx)
        for coordinate, col_idx, needs_conversion in drivable:
            value = row[col_idx]
            if needs_conversion:
                value = math.radians(value)
            coordinate.setValue(state, value, False)
        model.realizePosition(state)
        positions.append([tuple(m.getLocationInGround(state).to_numpy()) for m in markers])

    return times, marker_names, positions


def write_markers_trc(model_file, mot_file, trc_path):
    """get_marker_trajectory + write_trc, for use as pipeline stage 4."""
    times, marker_names, positions = get_marker_trajectory(model_file, mot_file)
    frame_rate = round(1.0 / (times[1] - times[0])) if len(times) > 1 else 0.0
    return write_trc(trc_path, times, marker_names, positions, frame_rate)


def resolve_session_output_paths(session_dir, trial_name, model_file=None):
    """Compute output paths matching an OpenCap session's layout, so this
    script's output is directly consumable by the existing OpenCap-derived
    analysis code (utilsKinematics.py's `kinematics` class, which
    gait_analysis_UCM.py subclasses) without renaming anything by hand.

    Read directly out of utilsKinematics.py's `kinematics.__init__` (model +
    motion path construction) and `get_marker_dict` (marker path
    construction), 2026-08-19, not guessed:

        model:   <session_dir>/OpenSimData/Model/<name>.osim
        motion:  <session_dir>/OpenSimData/Kinematics/<trial_name>.mot
        markers: <session_dir>/MarkerData/<trial_name>.trc

    Does NOT replicate utilsKinematics.py's "mono session" handling (models
    stored in a per-trial subfolder of OpenSimData/Model/) or its
    metadata-file-based model name lookup -- if a session uses either of
    those, pass model_file explicitly rather than relying on auto-discovery
    here. Auto-discovery only handles the plain case: exactly one .osim
    directly inside OpenSimData/Model/.

    Returns a dict: model_file, results_dir, output_motion_filename,
    trc_path, sto_path. sto_path isn't part of utilsKinematics.py's own
    layout -- nothing downstream reads the intermediate orientations file --
    it's placed alongside the .mot in Kinematics/ purely so a session's
    Xsens-derived files stay together, not because anything requires that
    location.
    """
    session_dir = Path(session_dir)
    kinematics_dir = session_dir / "OpenSimData" / "Kinematics"
    marker_dir = session_dir / "MarkerData"

    if model_file is None:
        model_dir = session_dir / "OpenSimData" / "Model"
        osim_files = sorted(model_dir.glob("*.osim")) if model_dir.exists() else []
        # calibrate_model() writes "<stem>_calibrated.osim" into this very
        # directory, so once a session has been processed a single time, a
        # naive "*.osim" glob sees two models and auto-discovery fails
        # forever ("found 2") -- the app breaking its own next run, and every
        # subsequent trial in the same session. Calibrated models are this
        # pipeline's OUTPUT, never a source model to be calibrated again, so
        # they're excluded here rather than counted. Excluding (instead of
        # writing the calibrated model elsewhere) is deliberate: it also
        # repairs sessions already polluted by an earlier run, which a
        # change of output location alone would leave permanently broken.
        source_models = [f for f in osim_files if not f.stem.endswith("_calibrated")]
        if len(source_models) != 1:
            derived = [f.name for f in osim_files if f.stem.endswith("_calibrated")]
            hint = (
                "Pass model_file explicitly instead (e.g. for a 'mono' session "
                "with per-trial model subfolders, which this auto-discovery "
                "doesn't handle)."
            )
            if not source_models and derived:
                hint = (
                    f"Only previously-calibrated model(s) {derived} were found, "
                    "with no source model alongside them. Restore the original "
                    "scaled .osim for this session, or pass model_file explicitly."
                )
            raise ValueError(
                f"{model_dir}: expected exactly one source .osim file for model "
                f"auto-discovery, found {len(source_models)} "
                f"({[f.name for f in source_models]}). {hint}"
            )
        model_file = str(source_models[0])

    return {
        "model_file": model_file,
        "results_dir": str(kinematics_dir),
        "output_motion_filename": f"{trial_name}.mot",
        "trc_path": str(marker_dir / f"{trial_name}.trc"),
        "sto_path": str(kinematics_dir / f"{trial_name}_orientations.sto"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("USAGE", 1)[0])
    parser.add_argument("mvnx_file", help="Path to the Xsens .mvnx export")
    parser.add_argument("model_file", nargs="?", help="Path to a generic .osim model")
    parser.add_argument("--list-segments", action="store_true",
                         help="Print segment id/label pairs and exit (no opensim needed)")
    parser.add_argument("--base-imu", default="pelvis_imu",
                         help="IMU frame name to use for heading correction (default: pelvis_imu)")
    parser.add_argument("--base-heading-axis", default="x",
                         help="Heading axis of the base IMU: x, -x, y, -y, z, -z (default: x -- "
                              "confirmed empirically 2026-08-19 against real data: 'z', the "
                              "OpenSense reference example's value and this script's old default, "
                              "produces a 95.8 degree heading correction for this file/model, "
                              "while 'x' produces 5.8 degrees; every other option produces 84-174 "
                              "degrees. A large heading correction here is a red flag, not just a "
                              "number -- it fixed the knee flatness bug reported earlier, see "
                              "VENDORING.md. For a negative axis, use '=' (e.g. "
                              "--base-heading-axis=-x) -- a space-separated '-x' is parsed as an "
                              "unrecognized option by argparse, not a value.)")
    parser.add_argument("--start-time", type=float, default=None)
    parser.add_argument("--end-time", type=float, default=None)
    parser.add_argument("--session-dir", default=None,
                         help="An existing OpenCap session folder. Combined with --trial-name, "
                              "output paths (model, .mot, .trc) are auto-resolved to match that "
                              "session's own layout (see resolve_session_output_paths) so the "
                              "result is directly usable by the existing OpenCap-derived analysis "
                              "code, not just this script. Explicit --results-dir/--sto-path/"
                              "--trc-path/model_file still override individual paths if given.")
    parser.add_argument("--trial-name", default=None,
                         help="Trial name to use for output filenames when --session-dir is "
                              "given (produces <session-dir>/OpenSimData/Kinematics/"
                              "<trial-name>.mot and <session-dir>/MarkerData/<trial-name>.trc).")
    parser.add_argument("--results-dir", default=None,
                         help="Where IMUInverseKinematicsTool writes its output "
                              "(default: 'IKResults', or <session-dir>/OpenSimData/Kinematics "
                              "if --session-dir/--trial-name are given).")
    parser.add_argument("--sto-path", default=None,
                         help="Where to write the intermediate orientations .sto "
                              "(default: <mvnx_file stem>_orientations.sto, or alongside the "
                              ".mot if --session-dir/--trial-name are given).")
    parser.add_argument("--source", choices=["segment", "sensor"], default="segment",
                         help="'segment' (default): Xsens's biomechanically-solved "
                              "per-segment orientation. 'sensor': raw per-sensor "
                              "orientation -- only for segments in "
                              "SENSOR_EQUIPPED_SEGMENTS. See build_orientations_sto's "
                              "docstring for the accuracy tradeoff.")
    parser.add_argument("--trc-path", default=None,
                         help="Where to write marker positions (stage 4, runs automatically -- "
                              "drives the calibrated model through the IK output and writes a "
                              ".trc, which is what lets OpenCap's own downstream gait-event-"
                              "detection code, which reads marker trajectories rather than raw "
                              "joint angles, consume Xsens-derived motion; see "
                              "get_marker_trajectory's docstring). Default: "
                              "<results-dir>/<mvnx_file stem>_markers.trc.")
    parser.add_argument("--no-trc", action="store_true",
                         help="Skip stage 4 (marker/.trc export) and only produce the .mot.")
    args = parser.parse_args()

    if args.list_segments:
        list_segments(args.mvnx_file)
        return

    session_mode = bool(args.session_dir and args.trial_name)
    if bool(args.session_dir) != bool(args.trial_name):
        parser.error("--session-dir and --trial-name must be given together")

    session_paths = None
    if session_mode:
        session_paths = resolve_session_output_paths(
            args.session_dir, args.trial_name, model_file=args.model_file
        )
    elif not args.model_file:
        parser.error(
            "model_file is required unless --list-segments is given, or "
            "--session-dir/--trial-name are given for model auto-discovery"
        )

    model_file = args.model_file or (session_paths["model_file"] if session_paths else None)
    results_dir = args.results_dir or (
        session_paths["results_dir"] if session_paths else "IKResults"
    )
    output_motion_filename = session_paths["output_motion_filename"] if session_paths else None
    sto_path = args.sto_path or (
        session_paths["sto_path"] if session_paths
        else Path(args.mvnx_file).stem + "_orientations.sto"
    )
    run_trc_stage = not args.no_trc
    trc_path = args.trc_path or (
        session_paths["trc_path"] if session_paths
        else str(Path(results_dir) / (Path(args.mvnx_file).stem + "_markers.trc"))
    )

    # Wall-clock timing per stage. Nothing about how long this pipeline takes
    # was recorded anywhere until 2026-08-18 -- the only evidence of the first
    # real end-to-end run's ~5-minute duration was reconstructed after the
    # fact from output-file timestamps. Recording it directly here means that
    # never has to happen again.
    timings = {}
    run_start = time.perf_counter()
    n_stages = 4 if run_trc_stage else 3

    print(f"[1/{n_stages}] Parsing {args.mvnx_file} -> {sto_path} (source={args.source})")
    t = time.perf_counter()
    calibration_info = {}
    build_orientations_sto(args.mvnx_file, sto_path, SEGMENT_TO_IMU_FRAME,
                           source=args.source, calibration_info=calibration_info)
    timings["parse_and_write_sto_s"] = time.perf_counter() - t
    print(f"       done in {timings['parse_and_write_sto_s']:.1f}s")

    calibration_frame_type = calibration_info.get("frame_type")
    print(f"[2/{n_stages}] Calibrating {model_file} against frame 0 of {sto_path} "
          f"(pose: {calibration_frame_type or 'none -- first motion frame, model left at default'})")
    t = time.perf_counter()
    calibrated_model = calibrate_model(
        model_file, sto_path, args.base_imu, args.base_heading_axis,
        calibration_pose=calibration_frame_type,
    )
    timings["calibrate_model_s"] = time.perf_counter() - t
    print(f"       -> {calibrated_model} ({timings['calibrate_model_s']:.1f}s)")

    print(f"[3/{n_stages}] Running IMU inverse kinematics -> {results_dir}/")
    t = time.perf_counter()
    mot_path = run_imu_ik(calibrated_model, sto_path, args.start_time, args.end_time,
                           results_dir, output_motion_filename=output_motion_filename)
    timings["run_imu_ik_s"] = time.perf_counter() - t
    print(f"       -> {mot_path} ({timings['run_imu_ik_s']:.1f}s)")

    if run_trc_stage:
        print(f"[4/{n_stages}] Writing marker positions -> {trc_path}")
        t = time.perf_counter()
        Path(trc_path).parent.mkdir(parents=True, exist_ok=True)
        write_markers_trc(calibrated_model, mot_path, trc_path)
        timings["write_markers_trc_s"] = time.perf_counter() - t
        print(f"       done in {timings['write_markers_trc_s']:.1f}s")

    timings["total_s"] = time.perf_counter() - run_start
    summary = (
        f"parse+write {timings['parse_and_write_sto_s']:.1f}s, "
        f"calibrate {timings['calibrate_model_s']:.1f}s, "
        f"IK {timings['run_imu_ik_s']:.1f}s"
    )
    if run_trc_stage:
        summary += f", markers {timings['write_markers_trc_s']:.1f}s"
    print(f"Done in {timings['total_s']:.1f}s total ({summary}).")

    timing_log = Path(results_dir) / "timing.txt"
    timing_log.parent.mkdir(parents=True, exist_ok=True)
    with open(timing_log, "w") as f:
        f.write(f"mvnx_file: {args.mvnx_file}\n")
        f.write(f"model_file: {model_file}\n")
        f.write(f"source: {args.source}\n")
        f.write(f"start_time: {args.start_time}\n")
        f.write(f"end_time: {args.end_time}\n")
        f.write(f"session_dir: {args.session_dir}\n")
        f.write(f"trial_name: {args.trial_name}\n")
        f.write(f"trc_path: {trc_path if run_trc_stage else None}\n")
        for key, seconds in timings.items():
            f.write(f"{key}: {seconds:.3f}\n")
    print(f"Timing recorded to {timing_log}")


if __name__ == "__main__":
    sys.exit(main())
