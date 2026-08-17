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

WHAT THIS SCRIPT DOES NOT DO YET (be honest about the gap)
---------------------------------------------------------------------------
- The OpenSim-dependent half (writing the real .sto via
  STOFileAdapterQuaternion, IMUPlacer, IMUInverseKinematicsTool) has still
  never been run -- OpenSim isn't installed on this machine yet. Only the
  .mvnx-parsing half is tested (synthetic fixture + the structural facts
  above, confirmed against the real file). This is source-grounded, not
  guessed, but "grounded" isn't the same as "verified end to end."
- It assumes Xsens's per-SEGMENT orientation (already sensor-fused and
  biomechanically constrained by Xsens's own MVN engine) is the right input
  to OpenSense, rather than the raw per-sensor orientation
  (<sensorOrientation>, confirmed present in the real file too: 17 sensors,
  separate from the 23 segments). Whether that's actually the more accurate
  choice for a full-body suit is a real open question -- see the
  conversation this script came out of for the reasoning; short version is
  segment orientation is ready to use now (order is well-sourced), while
  sensor orientation would be architecturally cleaner but needs the
  sensor-to-segment mapping confirmed from a non-stripped .mvnx export or
  your MVN Analyze hardware configuration, which this file doesn't contain.
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
        --base-imu pelvis_imu --base-heading-axis z \
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
    calibration_orientation = None
    calibration_sensor_orientation_raw = None
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
                break

    times = []
    orientations = []
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

        time_attr = frame.attrib.get("time")
        if time_attr is not None:
            times.append(float(time_attr) / 1000.0)  # ms -> s, confirmed against
            # real frame timestamps (0, 16, 33, 50... ms at ~60 Hz) -- this
            # attribute genuinely is elapsed time, not an epoch stamp (that's
            # what the separate 'ms' attribute is, confirmed by inspecting
            # the real file: 'ms' holds a huge Unix-epoch-millisecond value).
        else:
            times.append(len(times) / frame_rate if frame_rate else float(len(times)))

    if frame_rate is None and len(times) > 1:
        # Not present as an attribute in the frames-only export shape --
        # derive it from the actual frame timing instead of leaving it unset.
        frame_rate = round(1.0 / ((times[-1] - times[0]) / (len(times) - 1)))

    return {
        "segments": segments,
        "frame_rate": frame_rate,
        "times": times,
        "orientations": orientations,
        "sensor_orientations_raw": sensor_orientations_raw,
        "calibration_orientation": calibration_orientation,
        "calibration_sensor_orientation_raw": calibration_sensor_orientation_raw,
    }


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


def build_orientations_sto(mvnx_path, sto_path, segment_to_imu_frame, source="segment"):
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

    Requires the `opensim` package -- imported lazily so --list-segments
    works without it installed.
    """
    import opensim as osim

    if source not in ("segment", "sensor"):
        raise ValueError(f"source must be 'segment' or 'sensor', got {source!r}")

    parsed = parse_mvnx(mvnx_path)
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

    osim.STOFileAdapterQuaternion.write(table, str(sto_path))
    return sto_path


def calibrate_model(model_file, orientations_sto, base_imu_label, base_heading_axis,
                     output_model_file=None):
    """opensim.IMUPlacer: register IMU frames on the model using the FIRST
    frame of orientations_sto as the calibration pose. Mirrors
    OpenSense_CalibrateModel.m exactly."""
    import opensim as osim

    output_model_file = output_model_file or str(
        Path(model_file).with_name(Path(model_file).stem + "_calibrated.osim")
    )

    imu_placer = osim.IMUPlacer()
    imu_placer.set_model_file(str(model_file))
    imu_placer.set_orientation_file_for_calibration(str(orientations_sto))
    imu_placer.set_sensor_to_opensim_rotations(osim.Vec3(*SENSOR_TO_OPENSIM_ROTATIONS))
    if base_imu_label:
        imu_placer.set_base_imu_label(base_imu_label)
    if base_heading_axis:
        imu_placer.set_base_heading_axis(base_heading_axis)

    imu_placer.run(False)
    calibrated_model = imu_placer.getCalibratedModel()
    # The MATLAB/C++ API calls this print(); the Python bindings rename it to
    # printToXML() (confirmed by actually running this, 2026-08-17 -- `print`
    # collides with the Python builtin, so SWIG must rename it there but not
    # in MATLAB).
    calibrated_model.printToXML(output_model_file)
    return output_model_file


def run_imu_ik(calibrated_model_file, orientations_sto, start_time, end_time,
               results_dir):
    """opensim.IMUInverseKinematicsTool: joint angles directly from IMU
    orientations, no markers. Mirrors OpenSense_OrientationTracking.m exactly."""
    import opensim as osim

    Path(results_dir).mkdir(parents=True, exist_ok=True)

    imu_ik = osim.IMUInverseKinematicsTool()
    imu_ik.set_model_file(str(calibrated_model_file))
    imu_ik.set_orientations_file(str(orientations_sto))
    imu_ik.set_sensor_to_opensim_rotations(osim.Vec3(*SENSOR_TO_OPENSIM_ROTATIONS))
    if start_time is not None and end_time is not None:
        imu_ik.set_time_range(0, start_time)
        imu_ik.set_time_range(1, end_time)
    imu_ik.set_results_directory(str(results_dir))

    imu_ik.run(False)
    return results_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("USAGE", 1)[0])
    parser.add_argument("mvnx_file", help="Path to the Xsens .mvnx export")
    parser.add_argument("model_file", nargs="?", help="Path to a generic .osim model")
    parser.add_argument("--list-segments", action="store_true",
                         help="Print segment id/label pairs and exit (no opensim needed)")
    parser.add_argument("--base-imu", default="pelvis_imu",
                         help="IMU frame name to use for heading correction (default: pelvis_imu)")
    parser.add_argument("--base-heading-axis", default="z",
                         help="Heading axis of the base IMU: x, -x, y, -y, z, -z (default: z)")
    parser.add_argument("--start-time", type=float, default=None)
    parser.add_argument("--end-time", type=float, default=None)
    parser.add_argument("--results-dir", default="IKResults")
    parser.add_argument("--sto-path", default=None,
                         help="Where to write the intermediate orientations .sto "
                              "(default: <mvnx_file stem>_orientations.sto)")
    parser.add_argument("--source", choices=["segment", "sensor"], default="segment",
                         help="'segment' (default): Xsens's biomechanically-solved "
                              "per-segment orientation. 'sensor': raw per-sensor "
                              "orientation -- only for segments in "
                              "SENSOR_EQUIPPED_SEGMENTS. See build_orientations_sto's "
                              "docstring for the accuracy tradeoff.")
    args = parser.parse_args()

    if args.list_segments:
        list_segments(args.mvnx_file)
        return

    if not args.model_file:
        parser.error("model_file is required unless --list-segments is given")

    sto_path = args.sto_path or (Path(args.mvnx_file).stem + "_orientations.sto")

    print(f"[1/3] Parsing {args.mvnx_file} -> {sto_path} (source={args.source})")
    build_orientations_sto(args.mvnx_file, sto_path, SEGMENT_TO_IMU_FRAME, source=args.source)

    print(f"[2/3] Calibrating {args.model_file} against frame 0 of {sto_path}")
    calibrated_model = calibrate_model(
        args.model_file, sto_path, args.base_imu, args.base_heading_axis
    )
    print(f"       -> {calibrated_model}")

    print(f"[3/3] Running IMU inverse kinematics -> {args.results_dir}/")
    run_imu_ik(calibrated_model, sto_path, args.start_time, args.end_time,
               args.results_dir)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
