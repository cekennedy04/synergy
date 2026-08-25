"""Tests for xtoo.py -- a Python port of the supervisor's XtoO.m.

XtoO takes a completely different route from our OpenSense pipeline: instead
of running inverse kinematics on segment orientations, it relabels Xsens's own
joint angles into OpenSim coordinate names and writes a .mot directly. That
gives real pelvis translation, working toe joints and unsaturated arms -- the
three things our IK path cannot supply.

Axis and sign constants were established empirically against real data (see
the module docstring), not read off the MATLAB. Two of them contradict a
literal reading of XtoO.m, so the tests pin the verified behaviour and a
separate test pins the legacy behaviour for reproducing the original output.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "xtoo.py"


@pytest.fixture(scope="module")
def xtoo():
    spec = importlib.util.spec_from_file_location("xtoo_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_identity_quaternion_gives_zero_euler_angles(xtoo):
    roll, pitch, yaw = xtoo.quaternion_to_euler(np.array([[1.0, 0.0, 0.0, 0.0]]))

    assert roll[0] == pytest.approx(0.0)
    assert pitch[0] == pytest.approx(0.0)
    assert yaw[0] == pytest.approx(0.0)


def test_euler_conversion_matches_the_matlab_formula(xtoo):
    """Ported from q_to_euler.m verbatim, including its use of atan rather
    than atan2. Checked against the formula evaluated by hand so a later
    'improvement' to atan2 is a deliberate change, not an accident."""
    q = np.array([[0.9, 0.2, 0.3, 0.1]])
    q0, q1, q2, q3 = 0.9, 0.2, 0.3, 0.1
    expected_roll = np.degrees(np.arctan((2*q2*q3 + 2*q0*q1) / (2*q0*q0 + 2*q3*q3 - 1)))
    expected_pitch = -np.degrees(np.arcsin(2*q1*q3 - 2*q0*q2))
    expected_yaw = np.degrees(np.arctan((2*q1*q2 + 2*q0*q3) / (2*q0*q0 + 2*q1*q1 - 1)))

    roll, pitch, yaw = xtoo.quaternion_to_euler(q)

    assert roll[0] == pytest.approx(expected_roll)
    assert pitch[0] == pytest.approx(expected_pitch)
    assert yaw[0] == pytest.approx(expected_yaw)


def _frames(n=5):
    """Synthetic per-frame inputs: quaternions, pelvis positions, joint angles."""
    quats = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))
    # Xsens global frame is X-forward, Y-left, Z-up.
    positions = np.column_stack([
        np.linspace(0.0, 3.0, n),      # X: forward travel
        np.linspace(0.0, 0.4, n),      # Y: lateral
        np.full(n, 0.97),              # Z: height
    ])
    joint_angles = np.zeros((n, 22, 3))
    return quats, positions, joint_angles


def test_pelvis_translation_maps_height_to_ty_not_tz(xtoo):
    """The bug this port fixes. XtoO.m assigns pelvis_ty from Xsens Y and
    pelvis_tz from Xsens Z, which puts the subject's ~1 m height into the
    lateral coordinate. OpenSim is Y-up and Xsens is Z-up, and the real data
    confirms it: Xsens Z sits at 0.95-0.98 m and matches OpenCap's pelvis_ty,
    while Xsens Y matches pelvis_tz at r = -0.994."""
    quats, positions, joint_angles = _frames()

    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)

    assert table["pelvis_ty"] == pytest.approx([0.97] * 5)          # height
    assert table["pelvis_tx"][-1] == pytest.approx(3.0)             # forward
    assert table["pelvis_tz"][-1] == pytest.approx(-0.4)            # lateral, negated


def test_pelvis_rotation_axes_follow_the_measured_mapping(xtoo):
    """Also contradicts a literal XtoO.m reading. Measured against our IK
    solution: tilt is -pitch (r -0.992), list is +roll (r +0.984), rotation is
    +yaw (r +0.989). XtoO.m assigns tilt from roll instead."""
    n = 4
    # a quaternion with a known non-zero pitch only
    quats = np.tile(np.array([0.9848, 0.0, 0.1736, 0.0]), (n, 1))   # ~20 deg about Y
    positions = np.zeros((n, 3))
    joint_angles = np.zeros((n, 22, 3))

    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)
    _roll, pitch, _yaw = xtoo.quaternion_to_euler(quats)

    assert table["pelvis_tilt"] == pytest.approx(list(-pitch))
    assert table["pelvis_list"] == pytest.approx([0.0] * n, abs=1e-6)


def test_joint_coordinates_take_the_right_dof_and_sign(xtoo):
    """DOF order in <jointAngle> is (abduction/adduction, internal/external
    rotation, flexion/extension) -- confirmed empirically: index 0 matched
    hip_adduction at r 0.937 and index 2 matched hip_flexion at r 0.988.
    XtoO.m negates adduction; that sign is preserved."""
    quats, positions, joint_angles = _frames(n=3)
    hip_r = xtoo.XSENS_JOINT_ORDER.index("jRightHip")
    joint_angles[:, hip_r, 0] = 10.0     # abduction/adduction
    joint_angles[:, hip_r, 2] = 25.0     # flexion/extension

    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)

    assert table["hip_flexion_r"] == pytest.approx([25.0] * 3)
    assert table["hip_adduction_r"] == pytest.approx([-10.0] * 3)   # negated


def test_toe_joint_is_populated_unlike_the_ik_pipeline(xtoo):
    """The reason this port matters for mtp: XtoO maps BallFoot flexion, so
    mtp_angle is a real coordinate here where our IK leaves it frozen."""
    quats, positions, joint_angles = _frames(n=3)
    ball_r = xtoo.XSENS_JOINT_ORDER.index("jRightBallFoot")
    joint_angles[:, ball_r, 2] = 7.5

    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)

    assert table["mtp_angle_r"] == pytest.approx([7.5] * 3)


def test_legacy_flag_reproduces_the_original_matlab_axes(xtoo):
    """So the supervisor's exact output can still be regenerated for
    comparison. Not the default, because it is measurably wrong."""
    quats, positions, joint_angles = _frames()

    table = xtoo.build_coordinate_table(
        quats, positions, joint_angles, frame_rate=60.0, legacy_axes=True
    )

    # XtoO.m: pelvis_ty = PelvisY * -1, pelvis_tz = PelvisZ
    assert table["pelvis_ty"][-1] == pytest.approx(-0.4)
    assert table["pelvis_tz"] == pytest.approx([0.97] * 5)


def test_time_column_is_derived_from_the_frame_rate(xtoo):
    quats, positions, joint_angles = _frames(n=4)

    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)

    assert table["time"] == pytest.approx([0.0, 1/60, 2/60, 3/60])


def test_mot_file_carries_the_opensim_header(xtoo, tmp_path):
    """utilsKinematics and every OpenSim tool parse to 'endheader' and read
    nRows/nColumns/inDegrees. A .mot missing those is silently unreadable."""
    quats, positions, joint_angles = _frames(n=5)
    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)
    out = tmp_path / "trial.mot"

    xtoo.write_mot(out, table)
    text = out.read_text()

    assert text.startswith("Coordinates")
    assert "version=1" in text
    assert "nRows=5" in text
    assert f"nColumns={len(xtoo.MOT_COLUMN_ORDER)}" in text
    assert "inDegrees=yes" in text
    assert "endheader" in text


def test_mot_columns_are_tab_separated_in_the_declared_order(xtoo, tmp_path):
    quats, positions, joint_angles = _frames(n=3)
    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)
    out = tmp_path / "trial.mot"

    xtoo.write_mot(out, table)
    lines = out.read_text().splitlines()
    header_index = lines.index("endheader") + 1

    assert lines[header_index].split("\t") == list(xtoo.MOT_COLUMN_ORDER)
    assert len(lines[header_index + 1].split("\t")) == len(xtoo.MOT_COLUMN_ORDER)


def test_written_mot_round_trips_through_the_same_reader_the_pipeline_uses(xtoo, tmp_path):
    """The point of writing a .mot at all is that downstream OpenSim code can
    read it. Parse it back the way every other reader in this repo does."""
    quats, positions, joint_angles = _frames(n=6)
    joint_angles[:, xtoo.XSENS_JOINT_ORDER.index("jRightKnee"), xtoo.FLEXION] = 30.0
    table = xtoo.build_coordinate_table(quats, positions, joint_angles, frame_rate=60.0)
    out = tmp_path / "trial.mot"
    xtoo.write_mot(out, table)

    lines = out.read_text().splitlines()
    start = lines.index("endheader") + 1
    columns = lines[start].split("\t")
    rows = [line.split("\t") for line in lines[start + 1:] if line.strip()]

    assert len(rows) == 6
    knee = columns.index("knee_angle_r")
    assert all(float(row[knee]) == pytest.approx(30.0) for row in rows)


_FIXTURE_MVNX = """<?xml version="1.0" encoding="UTF-8"?>
<mvnx xmlns="http://www.xsens.com/mvn/mvnx" version="4">
  <subject label="test" frameRate="60" segmentCount="23">
    <segments><segment id="1" label="Pelvis"/></segments>
    <frames>
      <frame type="identity" index="-2"><orientation>{ident}</orientation></frame>
      <frame type="tpose" index="-1"><orientation>{ident}</orientation></frame>
      <frame type="normal" index="0" time="0">
        <orientation>{ident}</orientation>
        <position>{pos0}</position>
        <jointAngle>{ja0}</jointAngle>
      </frame>
      <frame type="normal" index="1" time="17">
        <orientation>{ident}</orientation>
        <position>{pos1}</position>
        <jointAngle>{ja1}</jointAngle>
      </frame>
    </frames>
  </subject>
</mvnx>
"""


def _write_fixture(path, knee_r=(11.0, 12.0)):
    ident = " ".join(["1 0 0 0"] * 23)
    pos0 = " ".join(["0.0 0.0 0.97"] + ["0 0 0"] * 22)
    pos1 = " ".join(["1.5 0.4 0.97"] + ["0 0 0"] * 22)
    knee_index = 15          # jRightKnee in XSENS_JOINT_ORDER
    def ja(value):
        vals = [0.0] * 66
        vals[knee_index * 3 + 2] = value      # flexion/extension
        return " ".join(str(v) for v in vals)
    path.write_text(_FIXTURE_MVNX.format(
        ident=ident, pos0=pos0, pos1=pos1, ja0=ja(knee_r[0]), ja1=ja(knee_r[1])))


def test_conversion_reads_a_real_mvnx_structure_end_to_end(xtoo, tmp_path):
    """No .xlsx round-trip: XtoO.m reads spreadsheets, but everything it needs
    is already in the .mvnx (<jointAngle>, <orientation>, <position>)."""
    mvnx = tmp_path / "trial.mvnx"
    _write_fixture(mvnx)
    out = tmp_path / "trial.mot"

    xtoo.convert_mvnx_to_mot(mvnx, out)

    lines = out.read_text().splitlines()
    start = lines.index("endheader") + 1
    columns = lines[start].split("\t")
    rows = [line.split("\t") for line in lines[start + 1:] if line.strip()]

    assert len(rows) == 2, "calibration frames must not become motion rows"
    knee = columns.index("knee_angle_r")
    assert float(rows[0][knee]) == pytest.approx(11.0)
    assert float(rows[1][knee]) == pytest.approx(12.0)


def test_conversion_carries_real_pelvis_translation(xtoo, tmp_path):
    """The headline reason for this path: our IK output has pelvis_tx pinned
    at zero, and this does not."""
    mvnx = tmp_path / "trial.mvnx"
    _write_fixture(mvnx)
    out = tmp_path / "trial.mot"

    xtoo.convert_mvnx_to_mot(mvnx, out)

    lines = out.read_text().splitlines()
    start = lines.index("endheader") + 1
    columns = lines[start].split("\t")
    rows = [line.split("\t") for line in lines[start + 1:] if line.strip()]
    tx = [float(r[columns.index("pelvis_tx")]) for r in rows]
    ty = [float(r[columns.index("pelvis_ty")]) for r in rows]

    assert tx[1] == pytest.approx(1.5)
    assert tx[1] != tx[0], "translation must actually vary"
    assert ty == pytest.approx([0.97, 0.97])


def test_calibration_frames_are_excluded(xtoo, tmp_path):
    """identity/tpose frames carry no motion and no <position>; including them
    would prepend garbage rows."""
    mvnx = tmp_path / "trial.mvnx"
    _write_fixture(mvnx)

    frames = xtoo.read_mvnx_frames(mvnx)

    assert frames["n_frames"] == 2
    assert frames["frame_rate"] == pytest.approx(60.0)
