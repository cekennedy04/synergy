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


# -- MVNX v4 centerOfMass layout (2026-08-24) ----------------------------
# The real HD-reprocessed CK exports (MVN 2022.0.0, mvnx version="4") write
# <centerOfMass> as 9 values -- position, velocity, then acceleration --
# where the export shape this parser was first built against carried only
# the 3 position components. parse_mvnx rejected the real files outright
# ("frame has 9 <centerOfMass> values, expected 3") until this was fixed.


def test_center_of_mass_accepts_mvnx_v4_nine_value_layout(mod, tmp_path):
    """9 values parse, and the leading 3 (position) are what's kept --
    silently storing velocity or acceleration as position would be worse
    than the original hard failure."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(
        text,
        # position | velocity | acceleration. Synthetic values chosen to
        # mirror the SHAPE and order of magnitude of a real v4 export
        # (~1 m standing CoM height, ~0.01 m/s, ~0.01 m/s^2) without
        # copying any real recording's numbers into the repo.
        com_text="-4.0 0.35 0.99  -0.008 0.006 -0.0004  0.017 -0.028 0.008",
    ))

    parsed = mod.parse_mvnx(str(path))

    assert parsed["center_of_mass"][0] == pytest.approx((-4.0, 0.35, 0.99))


def test_center_of_mass_still_accepts_three_value_layout(mod, tmp_path):
    """The older 3-value shape must keep working -- the v4 fix widens the
    accepted set, it does not swap one layout for the other."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text, com_text="0.1 1.2 -0.05"))

    parsed = mod.parse_mvnx(str(path))

    assert parsed["center_of_mass"][0] == pytest.approx((0.1, 1.2, -0.05))


def test_center_of_mass_length_between_the_two_layouts_still_raises(mod, tmp_path):
    """Only 3 and 9 are real MVNX layouts. A 6-value frame is a file we do
    not understand, so it must fail loudly rather than get truncated to a
    plausible-looking position."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text, com_text="0.1 1.2 -0.05 0.0 0.0 0.0"))

    with pytest.raises(ValueError, match="centerOfMass"):
        mod.parse_mvnx(str(path))


# -- centerOfMass layout tripwire (2026-08-24) ---------------------------
# Truncating a 9-value row to its leading 3 is only safe while the layout is
# position|velocity|acceleration. These pin the structural checks that catch
# a future MVN revision emitting 9 values in some other arrangement, which
# would otherwise silently redefine the parsed center-of-mass.


def test_nine_value_row_with_position_like_tail_is_rejected(mod, tmp_path):
    """The failure mode this guard exists for: 9 values that are three
    POSITIONS (e.g. the same CoM in different reference frames) rather than
    position + derivatives. Truncating those to the leading 3 would be
    silently wrong, so it must raise."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(
        text,
        com_text="-4.0 0.35 0.99  -3.8 0.40 1.02  -3.6 0.45 1.05",
    ))

    with pytest.raises(ValueError, match="do not look like"):
        mod.parse_mvnx(str(path))


def test_implausible_com_height_in_a_nine_value_row_is_rejected(mod, tmp_path):
    """A vertical component nowhere near a human stature means the leading 3
    of a truncated row are not the position triple we think they are. Only
    9-value rows are checked -- a 3-value row is used as given, so there is
    no truncation assumption to defend."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(
        text, com_text="0.001 0.002 0.003  -0.008 0.006 -0.0004  0.017 -0.028 0.008"))

    with pytest.raises(ValueError, match="vertical component"):
        mod.parse_mvnx(str(path))


def test_three_value_row_is_not_subjected_to_the_truncation_tripwire(mod, tmp_path):
    """Regression: an earlier draft of the guard also policed 3-value rows and
    rejected legitimate fixtures whose CoM sat near the origin."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(text, com_text="0.001 0.002 0.003"))

    parsed = mod.parse_mvnx(str(path))

    assert parsed["center_of_mass"][0] == pytest.approx((0.001, 0.002, 0.003))


def test_realistic_nine_value_row_passes_the_tripwire(mod, tmp_path):
    """The guard must not fire on the layout it was written for -- a false
    positive here would reject every real v4 file."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    path.write_text(_fixture_mvnx(
        text,
        com_text="-4.0 0.35 0.99  -0.008 0.006 -0.0004  0.017 -0.028 0.008",
    ))

    parsed = mod.parse_mvnx(str(path))

    assert parsed["center_of_mass"][0] == pytest.approx((-4.0, 0.35, 0.99))


def test_frames_without_com_skip_validation_entirely(mod, tmp_path):
    """A file with no <centerOfMass> at all is valid (older export shape) and
    must not trip a guard about data it does not contain."""
    text = _joint_angle_values(mod, "jL5S1")
    path = tmp_path / "fixture.mvnx"
    src = _fixture_mvnx(text, com_text="0.1 1.2 -0.05")
    path.write_text(src.replace("<centerOfMass>0.1 1.2 -0.05</centerOfMass>", ""))

    parsed = mod.parse_mvnx(str(path))

    assert parsed["center_of_mass"] == [None]
