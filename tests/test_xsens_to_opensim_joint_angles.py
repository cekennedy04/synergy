"""
Tests parse_mvnx's <jointAngle>/<centerOfMass> extraction (added 2026-08-19) --
Xsens's own joint-kinematics computation, independent of this script's
IMUPlacer/IMUInverseKinematicsTool conversion. See STANDARD_22_JOINT_ORDER's
and JOINT_ANGLE_DOF_NAMES's docstrings in xsens_to_opensim.py for how the
22-joint order and per-joint [abd/add, rotation, flexion] axis order were
confirmed against context/S01-001.xlsx's real column headers, not guessed.
"""
import importlib.util
import os
import textwrap

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'xsens_to_opensim.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('xsens_to_opensim_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


def _joint_angle_values(mod, target_joint, target_values=(11.0, 22.0, 33.0)):
    """66 floats (22 joints x 3 DOF): all zero except target_joint's 3
    values, so a test can assert exactly those land at the right index."""
    idx = mod.STANDARD_22_JOINT_ORDER.index(target_joint)
    values = [0.0] * 66
    values[idx * 3 : idx * 3 + 3] = target_values
    return " ".join(str(v) for v in values)


def _fixture_mvnx(joint_angle_text, com_text="0.1 1.2 -0.05"):
    # Same minimal 2-segment shape the mvnx-parsing tests use -- jointAngle
    # parsing doesn't depend on segmentCount (see the "lazily validated"
    # comment on joint_names in parse_mvnx).
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <mvnx version="4">
          <mvn version="2026.0" build="1"/>
          <subject label="test" frameRate="60" segmentCount="2">
            <segments>
              <segment id="1" label="Pelvis"/>
              <segment id="2" label="T8"/>
            </segments>
            <frames>
              <frame type="identity" index="-3">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="tpose" index="-2">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="tpose-isb" index="-1">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="normal" index="0" time="0">
                <orientation>1 0 0 0 1 0 0 0</orientation>
                <jointAngle>{joint_angle_text}</jointAngle>
                <centerOfMass>{com_text}</centerOfMass>
              </frame>
            </frames>
          </subject>
        </mvnx>
        """)


def test_joint_angle_lands_at_correct_joint_and_dof_order(mod, tmp_path):
    text = _joint_angle_values(mod, "jRightKnee", (5.0, -10.0, 45.0))
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text))

    parsed = mod.parse_mvnx(str(path))
    assert parsed["joint_names"] == mod.STANDARD_22_JOINT_ORDER

    knee_idx = mod.STANDARD_22_JOINT_ORDER.index("jRightKnee")
    knee_angles = parsed["joint_angles"][0][knee_idx]
    assert knee_angles == pytest.approx((5.0, -10.0, 45.0))
    # Per JOINT_ANGLE_DOF_NAMES: (abduction_adduction, int/ext rotation,
    # flexion_extension) -- flexion is the THIRD value, confirmed against
    # real column headers, not the first.
    assert mod.JOINT_ANGLE_DOF_NAMES[2] == "flexion_extension"
    flexion = knee_angles[2]
    assert flexion == pytest.approx(45.0)

    # Every other joint should be all-zero -- confirms indexing didn't bleed
    # into a neighboring joint.
    hip_idx = mod.STANDARD_22_JOINT_ORDER.index("jRightHip")
    assert parsed["joint_angles"][0][hip_idx] == pytest.approx((0.0, 0.0, 0.0))


def test_center_of_mass_parsed(mod, tmp_path):
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text, com_text="0.1 1.2 -0.05"))

    parsed = mod.parse_mvnx(str(path))
    assert parsed["center_of_mass"][0] == pytest.approx((0.1, 1.2, -0.05))


def test_missing_joint_angle_element_yields_none_not_error(mod, tmp_path):
    # A frame with no <jointAngle>/<centerOfMass> at all (older/different
    # .mvnx variant) should parse as None for that frame, not raise --
    # mirrors how sensor_orientations_raw already handles absent data.
    fixture = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <mvnx version="4">
          <subject label="test" frameRate="60" segmentCount="2">
            <segments>
              <segment id="1" label="Pelvis"/>
              <segment id="2" label="T8"/>
            </segments>
            <frames>
              <frame type="identity" index="-3">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="tpose" index="-2">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="tpose-isb" index="-1">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
              <frame type="normal" index="0" time="0">
                <orientation>1 0 0 0 1 0 0 0</orientation>
              </frame>
            </frames>
          </subject>
        </mvnx>
        """)
    path = tmp_path / "fixture.mvnx"
    path.write_text(fixture)

    parsed = mod.parse_mvnx(str(path))
    assert parsed["joint_angles"] == [None]
    assert parsed["center_of_mass"] == [None]


def test_wrong_joint_angle_length_raises(mod, tmp_path):
    path = tmp_path / "fixture.mvnx"
    # 3 values instead of the expected 66 (22 joints x 3).
    path.write_text(_fixture_mvnx("1 2 3"))

    with pytest.raises(ValueError, match="jointAngle"):
        mod.parse_mvnx(str(path))


def test_wrong_center_of_mass_length_raises(mod, tmp_path):
    # Codex review (2026-08-19): centerOfMass was accepted at any nonempty
    # length instead of validated as exactly 3 (x, y, z).
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text, com_text="0.1 1.2"))  # only 2 values

    with pytest.raises(ValueError, match="centerOfMass"):
        mod.parse_mvnx(str(path))
