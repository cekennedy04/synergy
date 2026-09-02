"""Tests the OpenSim model pose IMUPlacer calibrates against.

The defect this pins (found 2026-09-02, present since the OpenSense route was
first written): IMUPlacer computes each body<->IMU offset from the model's
DEFAULT pose, but the calibration frame `build_orientations_sto` writes as row
0 is the Xsens **T-pose** -- arms stretched horizontally out to the sides. The
LaiUhlrich2022 default pose is arms-down, so 90 degrees of shoulder abduction
was being baked into the humerus/radius/hand IMU offsets. Downstream, IK then
had to report the walking arm as ~90 degrees abducted, which puts the shoulder
Euler triplet in gimbal lock and lets `arm_flex`/`arm_rot` wind up to the
model's +/-572.96 degree (+/-10 rad) coordinate bounds. Measured on the CK
session before the fix: arm_flex_l reached -566 deg, arm_rot_l +573 deg, with
across-stride SDs of ~157 deg against ~2 deg for the same coordinates from the
marker-based OpenCap pipeline.

Legs, pelvis and torso were never affected: they hold the same pose in the
Xsens T-pose and in the model default, so their offsets were already right.

opensim is stubbed here for the same two reasons as
test_xsens_to_opensim_source_selection.py: these tests must run in whatever
interpreter pytest was started from, and the fakes double as a written record
of the real API shape being relied on (Model.getCoordinateSet() ->
CoordinateSet.contains/get, Coordinate.getDefaultValue/setDefaultValue in
RADIANS, IMUPlacer.setModel, Model.printToXML).
"""
import importlib.util
import math
import os
import sys
import types

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'xsens_to_opensim.py')


class _FakeCoordinate:
    def __init__(self, name, default_value=0.0):
        self.name = name
        self._default = default_value
        self.default_history = []

    def getDefaultValue(self):
        return self._default

    def setDefaultValue(self, value):
        self._default = value
        self.default_history.append(value)


class _FakeCoordinateSet:
    def __init__(self, names):
        self._by_name = {name: _FakeCoordinate(name) for name in names}

    def contains(self, name):
        return name in self._by_name

    def get(self, name):
        return self._by_name[name]


# Every coordinate the real LaiUhlrich2022 model carries that this fix touches,
# plus two leg coordinates to prove the pose leaves the lower limb alone.
MODEL_COORDINATES = [
    "arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r", "pro_sup_r",
    "arm_flex_l", "arm_add_l", "arm_rot_l", "elbow_flex_l", "pro_sup_l",
    "hip_flexion_r", "knee_angle_r",
]


class _FakeModel:
    instances = []

    def __init__(self, path):
        self.path = path
        self.coordinates = _FakeCoordinateSet(MODEL_COORDINATES)
        self.printed_to = []
        _FakeModel.instances.append(self)

    def getCoordinateSet(self):
        return self.coordinates

    def initSystem(self):
        return object()

    def printToXML(self, path):
        # Record the defaults as they stood at the moment of writing, so a
        # test can tell "restored before printing" from "restored afterwards".
        self.printed_to.append(
            (path, {name: self.coordinates.get(name).getDefaultValue()
                    for name in MODEL_COORDINATES})
        )


class _FakeVec3:
    def __init__(self, *values):
        self.values = values


class _FakeIMUPlacer:
    instances = []

    def __init__(self):
        self.model = None
        self.model_file = None
        self.calls = []
        self.defaults_seen_at_run = None
        _FakeIMUPlacer.instances.append(self)

    def setModel(self, model):
        self.model = model

    def set_model_file(self, path):
        self.model_file = path

    def set_orientation_file_for_calibration(self, path):
        self.calls.append(("orientation_file", path))

    def set_sensor_to_opensim_rotations(self, vec3):
        self.calls.append(("rotations", vec3.values))

    def set_base_imu_label(self, label):
        self.calls.append(("base_imu", label))

    def set_base_heading_axis(self, axis):
        self.calls.append(("base_heading_axis", axis))

    def run(self, visualize):
        # The whole point of the fix: the model must already be posed by now.
        self.defaults_seen_at_run = {
            name: self.model.getCoordinateSet().get(name).getDefaultValue()
            for name in MODEL_COORDINATES
        }
        return True

    def getCalibratedModel(self):
        return self.model


def _install_stub_opensim(monkeypatch):
    fake = types.ModuleType('opensim')
    fake.Model = _FakeModel
    fake.IMUPlacer = _FakeIMUPlacer
    fake.Vec3 = _FakeVec3
    monkeypatch.setitem(sys.modules, 'opensim', fake)


@pytest.fixture
def xsens_module(monkeypatch):
    _FakeModel.instances.clear()
    _FakeIMUPlacer.instances.clear()
    _install_stub_opensim(monkeypatch)
    spec = importlib.util.spec_from_file_location('x2o_calibration_pose', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- the pose itself ------------------------------------------------------

def test_tpose_pose_abducts_both_shoulders_ninety_degrees(xsens_module):
    """The Xsens T-pose is arms horizontal to the sides. In this model
    abduction is NEGATIVE arm_add on both sides (verified against the real
    LaiUhlrich2022_scaled model: at arm_add_r = -90 the humerus_r frame's
    proximal axis points left, i.e. the right arm points right; the same
    value mirrors correctly on the left)."""
    pose = xsens_module.CALIBRATION_POSES["tpose"]
    assert pose["arm_add_r"] == -90.0
    assert pose["arm_add_l"] == -90.0


def test_tpose_pose_puts_the_forearms_in_neutral_rotation(xsens_module):
    """Palms-down with the arm abducted is forearm-neutral, which is ~90 deg
    on this model's pro_sup (range 0..119.75, 0 = full supination). Leaving
    it at 0 shifted every reported pro_sup down by 90 deg -- the IMU route
    read ~5-11 deg where the marker-based OpenCap route read ~89-94 deg on
    the same subject."""
    pose = xsens_module.CALIBRATION_POSES["tpose"]
    assert pose["pro_sup_r"] == 90.0
    assert pose["pro_sup_l"] == 90.0


def test_tpose_pose_leaves_the_lower_limb_alone(xsens_module):
    """The legs, pelvis and torso are in the same configuration in the Xsens
    T-pose and in the model's default pose, so posing them would introduce an
    error where there wasn't one."""
    posed = set(xsens_module.CALIBRATION_POSES["tpose"])
    assert not any(
        name.startswith(("hip_", "knee_", "ankle_", "subtalar_", "mtp_",
                         "pelvis_", "lumbar_"))
        for name in posed
    )


def test_npose_needs_no_posing(xsens_module):
    """An N-pose calibration frame is relaxed standing, arms at the sides --
    already the model's default pose."""
    assert xsens_module.CALIBRATION_POSES["npose"] == {}


def test_resolve_calibration_pose_accepts_names_dicts_and_none(xsens_module):
    assert xsens_module.resolve_calibration_pose("tpose") == xsens_module.CALIBRATION_POSES["tpose"]
    assert xsens_module.resolve_calibration_pose(None) == {}
    assert xsens_module.resolve_calibration_pose({"arm_add_r": -45.0}) == {"arm_add_r": -45.0}


def test_resolve_calibration_pose_rejects_an_unknown_name(xsens_module):
    with pytest.raises(ValueError) as excinfo:
        xsens_module.resolve_calibration_pose("apose")
    assert "apose" in str(excinfo.value)


# -- calibrate_model applies it -------------------------------------------

def test_calibrate_model_poses_the_model_before_imu_placer_runs(xsens_module, tmp_path):
    xsens_module.calibrate_model(
        str(tmp_path / "model.osim"), str(tmp_path / "orientations.sto"),
        "pelvis_imu", "x", str(tmp_path / "out.osim"),
    )
    placer = _FakeIMUPlacer.instances[-1]
    seen = placer.defaults_seen_at_run
    assert seen is not None, "IMUPlacer.run was never called"
    assert seen["arm_add_r"] == pytest.approx(math.radians(-90.0))
    assert seen["arm_add_l"] == pytest.approx(math.radians(-90.0))
    assert seen["pro_sup_r"] == pytest.approx(math.radians(90.0))
    assert seen["pro_sup_l"] == pytest.approx(math.radians(90.0))
    assert seen["hip_flexion_r"] == 0.0
    assert seen["knee_angle_r"] == 0.0


def test_calibrate_model_restores_the_original_defaults_before_writing(xsens_module, tmp_path):
    """The calibration pose is scaffolding for IMUPlacer, not a property of
    the calibrated model. Everything downstream (IK's initial guess, the
    forward-kinematics marker stage, task_functions) reads this file, so it
    must come out of here with the same default pose it went in with -- the
    only difference being the IMU offset frames IMUPlacer added."""
    out = str(tmp_path / "out.osim")
    xsens_module.calibrate_model(
        str(tmp_path / "model.osim"), str(tmp_path / "orientations.sto"),
        "pelvis_imu", "x", out,
    )
    model = _FakeIMUPlacer.instances[-1].getCalibratedModel()
    path, defaults_at_write = model.printed_to[-1]
    assert path == out
    assert defaults_at_write["arm_add_r"] == 0.0
    assert defaults_at_write["arm_add_l"] == 0.0
    assert defaults_at_write["pro_sup_r"] == 0.0
    assert defaults_at_write["pro_sup_l"] == 0.0


def test_calibrate_model_can_be_told_not_to_pose_the_model(xsens_module, tmp_path):
    xsens_module.calibrate_model(
        str(tmp_path / "model.osim"), str(tmp_path / "orientations.sto"),
        "pelvis_imu", "x", str(tmp_path / "out.osim"), calibration_pose=None,
    )
    seen = _FakeIMUPlacer.instances[-1].defaults_seen_at_run
    assert seen["arm_add_r"] == 0.0
    assert seen["pro_sup_r"] == 0.0


def test_calibrate_model_ignores_coordinates_the_model_does_not_have(xsens_module, tmp_path):
    """An armless or otherwise reduced model must calibrate, not crash."""
    xsens_module.calibrate_model(
        str(tmp_path / "model.osim"), str(tmp_path / "orientations.sto"),
        "pelvis_imu", "x", str(tmp_path / "out.osim"),
        calibration_pose=dict(xsens_module.CALIBRATION_POSES["tpose"], wrist_flex_r=15.0),
    )
    seen = _FakeIMUPlacer.instances[-1].defaults_seen_at_run
    assert seen["arm_add_r"] == pytest.approx(math.radians(-90.0))


# -- the frame type the pose has to follow --------------------------------

FIXTURE_MVNX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<frames segmentCount="3" jointCount="2">
{calibration}  <frame type="normal" index="0" time="0">
    <orientation>0.9 0.1 0 0  0.8 0.2 0 0  0.7 0.3 0 0</orientation>
  </frame>
  <frame type="normal" index="1" time="17">
    <orientation>0.85 0.15 0 0  0.75 0.25 0 0  0.65 0.35 0 0</orientation>
  </frame>
</frames>
"""

_STATIC_FRAME = """  <frame type="{ftype}" index="-2" time="0">
    <orientation>1 0 0 0  1 0 0 0  1 0 0 0</orientation>
  </frame>
"""


def _write_fixture(tmp_path, calibration_type):
    calibration = (
        "" if calibration_type is None
        else _STATIC_FRAME.format(ftype=calibration_type)
    )
    path = tmp_path / f"fixture_{calibration_type}.mvnx"
    path.write_text(FIXTURE_MVNX_TEMPLATE.format(calibration=calibration))
    return str(path)


@pytest.mark.parametrize("frame_type", ["tpose", "npose", None])
def test_parse_mvnx_reports_which_calibration_frame_it_selected(
        xsens_module, monkeypatch, tmp_path, frame_type):
    """`calibrate_model`'s pose has to match the frame that actually became row
    0 of the .sto -- a T-pose needs the shoulders abducted, an N-pose does not,
    and no static frame at all must not be posed as either. Guessing it is
    exactly how this defect survived, so the parser reports it and the drivers
    pass it through instead of assuming."""
    monkeypatch.setattr(xsens_module, 'STANDARD_23_SEGMENT_ORDER', ['Pelvis', 'L5', 'T8'])
    parsed = xsens_module.parse_mvnx(_write_fixture(tmp_path, frame_type))
    assert parsed["calibration_frame_type"] == frame_type
    if frame_type is None:
        assert parsed["calibration_orientation"] is None
    else:
        assert parsed["calibration_orientation"] is not None


def test_a_tpose_is_preferred_over_an_npose_and_reported_as_such(
        xsens_module, monkeypatch, tmp_path):
    """build_orientations_sto writes whichever static frame parse_mvnx picked,
    and it prefers tpose. The reported type must be the one actually used, or
    the pose that follows it is wrong."""
    monkeypatch.setattr(xsens_module, 'STANDARD_23_SEGMENT_ORDER', ['Pelvis', 'L5', 'T8'])
    both = (_STATIC_FRAME.format(ftype="npose") + _STATIC_FRAME.format(ftype="tpose"))
    path = tmp_path / "both.mvnx"
    path.write_text(FIXTURE_MVNX_TEMPLATE.format(calibration=both))
    assert xsens_module.parse_mvnx(str(path))["calibration_frame_type"] == "tpose"
