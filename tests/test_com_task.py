"""Tests for com_task.py -- the pelvis-relative COM task function feeding
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

MODULE_PATH = Path(__file__).resolve().parent.parent / "com_task.py"


@pytest.fixture(scope="module")
def com_task():
    spec = importlib.util.spec_from_file_location("com_task_under_test", MODULE_PATH)
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


def test_coordinate_values_are_converted_from_degrees_to_radians(com_task):
    """Curve exports are in degrees; OpenSim wants radians. A missing
    conversion scales every Jacobian entry by 57.3 and is otherwise silent."""
    model = FakeModel()
    task = com_task.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([180.0]))

    assert model.values["knee_angle_r"] == pytest.approx(np.pi)


def test_pelvis_translation_is_zeroed_so_com_is_pelvis_relative(com_task):
    """The task variable is COM RELATIVE to the pelvis, matching what the
    curve export computes (com minus the pelvis translation). Leaving the
    pelvis translated would make the task variable global COM -- which the IMU
    pipeline cannot supply at all, since its root is pinned."""
    model = FakeModel()
    task = com_task.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([10.0]))

    for axis in ("pelvis_tx", "pelvis_ty", "pelvis_tz"):
        assert model.values[axis] == pytest.approx(0.0)


def test_jacobian_has_one_column_per_joint_and_three_task_rows(com_task):
    model = FakeModel()
    names = ["knee_angle_r", "hip_flexion_r", "ankle_angle_r"]
    task = com_task.PelvisRelativeComTask(model, names)

    jacobian = task.jacobian(np.zeros(len(names)))

    assert jacobian.shape == (3, 3)


def test_jacobian_matches_the_fake_models_known_derivative(com_task):
    """FakeModel's COM_x is exactly the (radian) value of knee_angle_r, so
    d(COM_x)/d(knee_angle_r in degrees) is pi/180. Any missing or doubled
    conversion shows up here as a factor of 57.3."""
    model = FakeModel()
    task = com_task.PelvisRelativeComTask(model, ["knee_angle_r", "hip_flexion_r"])

    jacobian = task.jacobian(np.array([0.0, 0.0]))

    assert jacobian[0, 0] == pytest.approx(np.pi / 180.0, rel=1e-6)
    assert jacobian[0, 1] == pytest.approx(0.0, abs=1e-9)   # COM_x ignores hip
    assert np.allclose(jacobian[1:, :], 0.0, atol=1e-9)     # y, z are constant


def test_unnamed_coordinates_are_left_alone(com_task):
    """Only the DOFs in q are perturbed. A coordinate absent from q must keep
    whatever the model already holds, not be reset to zero."""
    model = FakeModel()
    model.set_coordinate("lumbar_bending", 0.75)
    task = com_task.PelvisRelativeComTask(model, ["knee_angle_r"])

    task.evaluate(np.array([5.0]))

    assert model.values["lumbar_bending"] == pytest.approx(0.75)


def test_length_mismatch_between_q_and_coordinate_names_is_rejected(com_task):
    """Silently zipping a short vector against the name list would set only
    the leading coordinates and leave the rest stale -- a wrong pose that
    still produces a plausible COM."""
    task = com_task.PelvisRelativeComTask(FakeModel(), ["a", "b", "c"])

    with pytest.raises(ValueError, match="3 coordinate"):
        task.evaluate(np.array([1.0, 2.0]))
