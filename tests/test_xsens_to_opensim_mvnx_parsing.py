"""
Smoke-tests xsens_to_opensim.py's .mvnx parsing against a synthetic fixture built
to match the real MVNX schema (element names/nesting/frame-skipping confirmed
against github.com/alexharston/mvnx's actual parser, not guessed -- see the
module docstring in xsens_to_opensim.py for the full source list).

Does NOT test build_orientations_sto/calibrate_model/run_imu_ik -- those need
the `opensim` package, which isn't installed on this machine (see VENDORING.md).
This only covers the pure-stdlib XML parsing, which is the one part of the new
script that's actually verifiable right now.
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


# Two segments (Pelvis, T8), 3 leading non-motion frames (identity/tpose/calibration,
# skipped per the real parser's frames[3:] convention) + 2 real motion frames.
# Quaternion order is w,x,y,z (scalar-first) per XsensDataReader.cpp's Quat_q0..q3.
FIXTURE_MVNX = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <mvnx version="4">
      <mvn version="2026.0" build="1"/>
      <comment>synthetic test fixture</comment>
      <subject label="test" frameRate="60" segmentCount="2" recDate="2026-08-17">
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
            <orientation>0.7071 0.7071 0 0 0.9239 0.3827 0 0</orientation>
          </frame>
          <frame type="normal" index="1" time="17">
            <orientation>0.6 0.8 0 0 0.9 0.436 0 0</orientation>
          </frame>
        </frames>
      </subject>
      <securityCode code="none"/>
    </mvnx>
    """)


@pytest.fixture
def fixture_mvnx_path(tmp_path):
    path = tmp_path / "fixture.mvnx"
    path.write_text(FIXTURE_MVNX)
    return str(path)


def test_parse_mvnx_segments_and_frame_skipping(fixture_mvnx_path):
    module = _load_module()
    parsed = module.parse_mvnx(fixture_mvnx_path)

    assert parsed["segments"] == {"1": "Pelvis", "2": "T8"}
    assert parsed["frame_rate"] == 60.0
    # 5 total <frame> elements, first 3 are non-motion -> 2 real motion frames.
    assert len(parsed["times"]) == 2
    assert len(parsed["orientations"]) == 2


def test_parse_mvnx_orientation_values_and_order(fixture_mvnx_path):
    module = _load_module()
    parsed = module.parse_mvnx(fixture_mvnx_path)

    # First motion frame: Pelvis quat (0.7071, 0.7071, 0, 0), T8 quat (0.9239, 0.3827, 0, 0).
    pelvis_quat, t8_quat = parsed["orientations"][0]
    assert pelvis_quat == pytest.approx((0.7071, 0.7071, 0.0, 0.0))
    assert t8_quat == pytest.approx((0.9239, 0.3827, 0.0, 0.0))

    # time attribute is in milliseconds in real MVNX files -> converted to seconds.
    assert parsed["times"][0] == pytest.approx(0.0)
    assert parsed["times"][1] == pytest.approx(0.017)


def test_parse_mvnx_rejects_mismatched_segment_count(tmp_path):
    module = _load_module()
    bad = FIXTURE_MVNX.replace(
        "<orientation>0.7071 0.7071 0 0 0.9239 0.3827 0 0</orientation>",
        "<orientation>0.7071 0.7071 0 0</orientation>",  # only 1 segment's worth of data
    )
    path = tmp_path / "bad.mvnx"
    path.write_text(bad)

    with pytest.raises(ValueError, match="orientation values"):
        module.parse_mvnx(str(path))


def test_list_segments_runs_without_opensim(fixture_mvnx_path, capsys):
    """--list-segments must work without the opensim package installed --
    that's the whole point of importing opensim lazily inside
    build_orientations_sto rather than at module level."""
    module = _load_module()
    module.list_segments(fixture_mvnx_path)
    out = capsys.readouterr().out
    assert "Pelvis" in out
    assert "T8" in out
    assert "2 motion frames" in out
