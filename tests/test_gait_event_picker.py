"""Tests for gait_event_picker.py.

No GUI and no OpenSim: the picking logic is deliberately separable from the
window that drives it, which is the only reason it is verifiable here.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load("gait_event_picker_under_test", "gait_event_picker.py")


@pytest.fixture(scope="module")
def scrubber():
    return _load("motion_scrubber_for_picker_tests", "motion_scrubber.py")


@pytest.fixture
def motion(scrubber):
    """A 40-frame motion with deliberately non-uniform sample times."""
    times = [round(-0.01667 + i * 0.0167, 5) for i in range(40)]
    rows = [[float(i)] for i in range(40)]
    return scrubber.MotionSource(["knee_angle_r"], times, rows, name="T1")


def _one_cycle(picker):
    """rHS -> lTO -> lHS -> rTO -> rHS, the order detect_correct_order wants."""
    for event, row in (("rHS", 0), ("lTO", 3), ("lHS", 8), ("rTO", 12),
                       ("rHS", 20)):
        picker.mark(event, row)
    return picker


# -- the contract that edit #13 was about ----------------------------------


def test_events_come_back_in_segment_walkings_unpacking_order(mod, motion):
    """segment_walking unpacks rHS, lHS, rTO, lTO. trimend returned those four
    in a different order for months, putting left heel-strikes in the right
    toe-off slot and silently corrupting every downstream metric."""
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 1)
    picker.mark("lHS", 2)
    picker.mark("rTO", 3)
    picker.mark("lTO", 4)

    rHS, lHS, rTO, lTO = picker.as_segment_walking_events()

    assert rHS == [1]
    assert lHS == [2]
    assert rTO == [3]
    assert lTO == [4]


def test_the_return_order_matches_detect_gait_peaks_in_the_pipeline(mod):
    """Pinned against the real source, so the two cannot drift. Both
    detect_gait_peaks and trimend return this order; the picker is a third
    supplier of the same tuple."""
    source = (REPO_ROOT / "gait_analysis_UCM_fixed.py").read_text(
        encoding="utf-8", errors="ignore")

    assert re.search(r"return\s+rHS\s*,\s*lHS\s*,\s*rTO\s*,\s*lTO", source)


def test_the_expected_order_matches_the_pipelines_own_table(mod):
    """EXPECTED_ORDER duplicates detect_correct_order's table, which cannot be
    imported because it is nested inside segment_walking. Pinned against the
    source so a change there is caught here."""
    source = (REPO_ROOT / "gait_analysis_UCM_fixed.py").read_text(
        encoding="utf-8", errors="ignore")
    block = re.search(r"expectedOrder = \{(.*?)\}", source, re.S).group(1)
    pairs = dict(re.findall(r"'(\w+)'\s*:\s*'(\w+)'", block))

    assert pairs == mod.EXPECTED_ORDER


# -- picking ---------------------------------------------------------------


def test_marking_the_same_frame_twice_does_not_duplicate_it(mod, motion):
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 5)
    picker.mark("rHS", 5)

    assert picker.rows("rHS") == [5]


def test_events_stay_sorted_however_they_were_picked(mod, motion):
    """The operator may scrub backwards; the pipeline expects ordered events."""
    picker = mod.GaitEventPicker(motion)
    for row in (12, 3, 20):
        picker.mark("rHS", row)

    assert picker.rows("rHS") == [3, 12, 20]


def test_a_frame_outside_the_motion_is_refused(mod, motion):
    picker = mod.GaitEventPicker(motion)

    with pytest.raises(IndexError):
        picker.mark("rHS", motion.n_rows)


def test_an_unknown_event_type_is_refused(mod, motion):
    picker = mod.GaitEventPicker(motion)

    with pytest.raises(ValueError, match="unknown event type"):
        picker.mark("rHeelStrike", 1)


def test_unmarking_something_never_marked_is_not_an_error(mod, motion):
    """The operator clicking delete twice is not a failure."""
    picker = mod.GaitEventPicker(motion)
    picker.unmark("rHS", 7)

    assert picker.rows("rHS") == []


# -- rows, not times -------------------------------------------------------


def test_the_timeline_reads_times_from_the_file(mod, motion):
    """.mot sample times are not uniform, so a time chosen in the UI and
    converted back would not land on the frame the operator saw."""
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 4)

    row, time, name = picker.timeline()[0]

    assert row == 4
    assert time == motion.time_at(4)
    assert name == "rHS"


def test_the_timeline_is_in_time_order_across_event_types(mod, motion):
    picker = _one_cycle(mod.GaitEventPicker(motion))

    rows = [row for row, _time, _name in picker.timeline()]

    assert rows == sorted(rows)


# -- the ordering verdict --------------------------------------------------


def test_a_correct_cycle_reports_ok(mod, motion):
    ok, message = _one_cycle(mod.GaitEventPicker(motion)).ordering_report()

    assert ok is True
    assert "correct gait order" in message


def test_a_wrong_foot_is_named_with_both_events(mod, motion):
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 0)
    picker.mark("rTO", 3)   # expects lTO after rHS

    ok, message = picker.ordering_report()

    assert ok is False
    assert "rHS" in message and "rTO" in message and "expects lTO" in message


def test_a_partially_picked_set_says_what_is_missing(mod, motion):
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 0)
    picker.mark("lTO", 3)

    ok, message = picker.ordering_report()

    assert ok is False
    assert "lHS" in message and "rTO" in message


def test_an_out_of_order_set_is_reported_but_still_saveable(mod, motion):
    """Reporting, not blocking: a pathological gait may genuinely violate the
    expected order, and this project stopped hard-refusing trials on
    2026-08-27."""
    picker = mod.GaitEventPicker(motion)
    picker.mark("rHS", 0)
    picker.mark("rTO", 3)

    assert picker.ordering_report()[0] is False
    assert picker.as_segment_walking_events()[0] == [0]   # still hands them back


def test_nothing_picked_is_not_reported_as_correct(mod, motion):
    ok, message = mod.GaitEventPicker(motion).ordering_report()

    assert ok is False
    assert "No events" in message


# -- saving and restoring --------------------------------------------------


def test_a_saved_set_round_trips(mod, motion):
    original = _one_cycle(mod.GaitEventPicker(motion))

    restored = mod.GaitEventPicker.from_dict(motion, original.to_dict())

    assert restored.as_segment_walking_events() == \
        original.as_segment_walking_events()


def test_a_set_from_a_different_trial_is_refused(mod, motion, scrubber):
    """Rows are frame indices. Applied to another trial they would place
    events at frames nobody chose."""
    record = _one_cycle(mod.GaitEventPicker(motion)).to_dict()
    other = scrubber.MotionSource(["knee_angle_r"], [0.0, 0.1],
                                  [[1.0], [2.0]], name="T2")

    with pytest.raises(ValueError, match="do not transfer between trials"):
        mod.GaitEventPicker.from_dict(other, record)


def test_the_saved_record_carries_times_for_a_human_reader(mod, motion):
    record = _one_cycle(mod.GaitEventPicker(motion)).to_dict()

    entry = record["events"]["rHS"][0]

    assert entry["row"] == 0
    assert entry["time"] == motion.time_at(0)
