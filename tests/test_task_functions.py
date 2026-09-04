"""Tests for task_functions.py -- the task variables x = f(q) feeding
ucm.analyse_cycle's jacobian_fn.

The model is injected, so these run without OpenSim (which lives in the
opencap-processing env and has no pytest). A fake model with an analytically
known centre of mass pins the behaviour that matters; the real OpenSim adapter
is a thin wrapper over the same protocol.

The units conversion is the dangerous one: the curve exports are in degrees,
OpenSim coordinates are radians. Getting it wrong scales the whole Jacobian by
57.3 with no visible symptom -- every Delta-V would still look plausible.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "task_functions.py"


@pytest.fixture(scope="module")
def tasks():
    spec = importlib.util.spec_from_file_location("task_functions_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeModel:
    """Records what it was asked to set, and reports a COM that is a known
    function of the coordinates so the Jacobian is hand-computable."""

    def __init__(self):
        self.values = {}

    def set_coordinate(self, name, value_radians):
        self.values[name] = value_radians

    def center_of_mass(self):
        # COM_x depends linearly on the first coordinate; y, z constant.
        return np.array([self.values.get("knee_angle_r", 0.0), 0.5, 1.0])


def test_coordinate_values_are_converted_from_degrees_to_radians(tasks):
    """Curve exports are in degrees; OpenSim wants radians. A missing
    conversion scales every Jacobian entry by 57.3 and is otherwise silent."""
    model = FakeModel()
    task = tasks.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([180.0]))

    assert model.values["knee_angle_r"] == pytest.approx(np.pi)


def test_pelvis_translation_is_zeroed_so_com_is_pelvis_relative(tasks):
    """The task variable is COM RELATIVE to the pelvis, matching what the
    curve export computes (com minus the pelvis translation). Leaving the
    pelvis translated would make the task variable global COM -- which the IMU
    pipeline cannot supply at all, since its root is pinned."""
    model = FakeModel()
    task = tasks.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([10.0]))

    for axis in ("pelvis_tx", "pelvis_ty", "pelvis_tz"):
        assert model.values[axis] == pytest.approx(0.0)


def test_jacobian_has_one_column_per_joint_and_three_task_rows(tasks):
    model = FakeModel()
    names = ["knee_angle_r", "hip_flexion_r", "ankle_angle_r"]
    task = tasks.PelvisRelativeComTask(model, names)

    jacobian = task.jacobian(np.zeros(len(names)))

    assert jacobian.shape == (3, 3)


def test_jacobian_matches_the_fake_models_known_derivative(tasks):
    """FakeModel's COM_x is exactly the (radian) value of knee_angle_r, so
    d(COM_x)/d(knee_angle_r in degrees) is pi/180. Any missing or doubled
    conversion shows up here as a factor of 57.3."""
    model = FakeModel()
    task = tasks.PelvisRelativeComTask(model, ["knee_angle_r", "hip_flexion_r"])

    jacobian = task.jacobian(np.array([0.0, 0.0]))

    assert jacobian[0, 0] == pytest.approx(np.pi / 180.0, rel=1e-6)
    assert jacobian[0, 1] == pytest.approx(0.0, abs=1e-9)   # COM_x ignores hip
    assert np.allclose(jacobian[1:, :], 0.0, atol=1e-9)     # y, z are constant


def test_unnamed_coordinates_are_left_alone(tasks):
    """Only the DOFs in q are perturbed. A coordinate absent from q must keep
    whatever the model already holds, not be reset to zero."""
    model = FakeModel()
    model.set_coordinate("lumbar_bending", 0.75)
    task = tasks.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([5.0]))

    assert model.values["lumbar_bending"] == pytest.approx(0.75)


def test_length_mismatch_between_q_and_coordinate_names_is_rejected(tasks):
    """Silently zipping a short vector against the name list would set only
    the leading coordinates and leave the rest stale -- a wrong pose that
    still produces a plausible COM."""
    task = tasks.PelvisRelativeComTask(FakeModel(), ["a", "b", "c"])

    with pytest.raises(ValueError, match="3 coordinate"):
        task.evaluate(np.array([1.0, 2.0]))


class FakeBodyModel(FakeModel):
    """Adds body-position lookup, with the foot's position depending on the
    ankle so the Jacobian's distal sensitivity is hand-checkable."""

    def body_position(self, body_name):
        ankle = self.values.get("ankle_angle_r", 0.0)
        knee = self.values.get("knee_angle_r", 0.0)
        return np.array([ankle + 0.5 * knee, 0.0, 0.2])


def test_foot_placement_reads_the_named_body_not_the_centre_of_mass(tasks):
    """The whole point of this task variable is that it tracks a distal
    end-effector, so it must query the body, not the COM."""
    model = FakeBodyModel()
    task = tasks.FootPlacementTask(model, ["ankle_angle_r"], body_name="calcn_r")

    value = task.evaluate(np.array([10.0]))

    assert value == pytest.approx(np.array([np.deg2rad(10.0), 0.0, 0.2]))


def test_foot_placement_also_zeroes_the_pelvis(tasks):
    """Foot position RELATIVE to the pelvis, for the same reason COM is:
    global position is unavailable to the pinned-root IMU pipeline."""
    model = FakeBodyModel()
    task = tasks.FootPlacementTask(model, ["ankle_angle_r"], body_name="calcn_r")

    task.evaluate(np.array([10.0]))

    for axis in ("pelvis_tx", "pelvis_ty", "pelvis_tz"):
        assert model.values[axis] == pytest.approx(0.0)


def test_foot_placement_is_sensitive_to_the_distal_joint(tasks):
    """The property that makes this task variable worth testing: unlike
    pelvis-relative COM, it must actually respond to the ankle -- otherwise
    distal noise still lands in the manifold and nothing is gained."""
    model = FakeBodyModel()
    task = tasks.FootPlacementTask(model, ["ankle_angle_r", "knee_angle_r"],
                                   body_name="calcn_r")

    jacobian = task.jacobian(np.zeros(2))

    ankle_sensitivity = np.linalg.norm(jacobian[:, 0])
    assert ankle_sensitivity == pytest.approx(np.pi / 180.0, rel=1e-6)
    assert ankle_sensitivity > 0.0


# -- the task must be pelvis-FRAME, not merely pelvis-origin (2026-09-03) ---
#
# `evaluate` zeroed pelvis_tx/ty/tz and then read the GLOBAL centre of mass, so
# translation was removed and rotation was not. The task variable was therefore
# ground-frame COM, and rotating the root moved it: sweeping pelvis_rotation
# from 0 to 180 degrees on the real model, with every relative joint held
# fixed, moved x by 0.166 m and gave pelvis_rotation the 4th-largest Jacobian
# column of 18. For a pelvis-relative task that column must be exactly zero.
#
# Downstream, absolute lab-frame heading became a real input to the task
# variable, so between-trial heading differences contaminated every pooled
# synergy index -- see VENDORING.md, "The synergy index was measuring where the
# subject was pointed".


class RotatingFakeModel(FakeModel):
    """A model whose global COM rotates with the root, as a real one does.

    The pelvis frame is a yaw rotation by `pelvis_rotation` about the vertical,
    and the COM sits at a fixed offset expressed in that frame. So the GLOBAL
    COM depends on the root angle while the PELVIS-FRAME COM cannot.
    """

    OFFSET = np.array([0.2, 0.5, 0.0])   # in the pelvis frame

    def _yaw(self):
        return self.values.get("pelvis_rotation", 0.0)

    def pelvis_rotation_matrix(self):
        c, s = np.cos(self._yaw()), np.sin(self._yaw())
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])

    def pelvis_origin(self):
        return np.zeros(3)

    def center_of_mass(self):
        return self.pelvis_rotation_matrix() @ self.OFFSET


def test_the_task_is_invariant_to_root_yaw(tasks):
    """Rotating the whole body must not move a pelvis-relative task variable.
    This is an exact invariance, not an approximation: it has to hold at every
    configuration, not just near a mean."""
    model = RotatingFakeModel()
    names = ["pelvis_rotation", "knee_angle_r"]
    task = tasks.PelvisRelativeComTask(model, names)

    reference = task.evaluate([0.0, 0.0])
    for yaw_degrees in (10.0, 45.0, 90.0, 180.0):
        moved = task.evaluate([yaw_degrees, 0.0])
        assert np.allclose(moved, reference, atol=1e-12), (
            f"root yaw of {yaw_degrees} deg moved the task variable by "
            f"{np.linalg.norm(moved - reference):.4f} -- the task is being read "
            "in the ground frame, not the pelvis frame")


def test_root_orientation_has_no_jacobian_column(tasks):
    """The consequence that matters for UCM: a coordinate the task cannot
    depend on must contribute an exactly zero column, so it lands wholly in
    the nullspace rather than steering the decomposition."""
    model = RotatingFakeModel()
    names = ["pelvis_rotation", "knee_angle_r"]
    task = tasks.PelvisRelativeComTask(model, names)

    jacobian = task.jacobian([30.0, 20.0])

    assert np.linalg.norm(jacobian[:, 0]) < 1e-9, (
        "pelvis_rotation must have a zero Jacobian column for a pelvis-relative "
        f"task; got norm {np.linalg.norm(jacobian[:, 0]):.3e}")
