"""Tests that the picker opens on detection's answer rather than empty.

Auto-trim hands over when it cannot produce a *usable* gait cycle, which is
not the same as finding nothing: the handover condition is two ipsilateral
heel strikes, so a trial yielding one heel strike and three toe-offs still
arrives here. It used to arrive at an empty window, and the operator re-picked
from scratch events the detector had already found correctly -- slower, and
worse, because every re-picked event is a fresh chance to click the wrong peak
on a trial where the detector was mostly right.

Loads gait_analysis_UCM_fixed by path, stubbing the OpenCap login import chain
(see tests/test_force_manual_events.py for why, and for the teardown rule).
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope="module")
def gf():
    import sys
    import types

    os.environ.setdefault("API_TOKEN", "test-placeholder-token")
    added = []
    if "decouple" not in sys.modules:
        decouple = types.ModuleType("decouple")
        decouple.config = lambda key, *a, **k: os.environ[key]
        sys.modules["decouple"] = decouple
        added.append("decouple")
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    module = None
    try:
        for _ in range(20):
            try:
                spec = importlib.util.spec_from_file_location(
                    "gait_fixed_for_seeding_test",
                    os.path.join(REPO_ROOT, "gait_analysis_UCM_fixed.py"))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                break
            except ModuleNotFoundError as exc:
                if not exc.name or exc.name in sys.modules:
                    raise
                sys.modules[exc.name] = types.ModuleType(exc.name)
                added.append(exc.name)
        if module is None:
            raise RuntimeError("import chain changed shape")
        yield module
    finally:
        # Stubs removed again -- a leak makes other suites stop skipping and
        # start failing against fakes.
        for name in added:
            sys.modules.pop(name, None)


class _Analysis:
    """The little of an analysis that build_manual_picker actually reads."""

    def __init__(self, n_rows=200, name="AN-001"):
        self.markerDict = {'time': [i / 60.0 for i in range(n_rows)]}
        self.trial_name = name
        self.eventDetectionSignals = {
            'r_calc': [0.0] * n_rows, 'r_toe': [0.0] * n_rows,
            'l_calc': [0.0] * n_rows, 'l_toe': [0.0] * n_rows,
        }


def test_an_unseeded_picker_is_still_empty(gf):
    """The callers with no detection result to offer must be unaffected."""
    picker = gf.build_manual_picker(_Analysis())
    assert not any(picker.counts().values())


def test_detections_events_arrive_already_marked(gf):
    """The window opens on the machine's answer, for the operator to correct."""
    detected = ([10, 70], [40], [55, 115], [25])       # rHS, lHS, rTO, lTO
    picker = gf.build_manual_picker(_Analysis(), detected)

    assert picker.rows('rHS') == [10, 70]
    assert picker.rows('lHS') == [40]
    assert picker.rows('rTO') == [55, 115]
    assert picker.rows('lTO') == [25]


def test_the_seed_order_matches_what_segment_walking_unpacks(gf):
    """segment_walking passes (rHS, lHS, rTO, lTO) positionally. Getting this
    order wrong would put right-foot events on the left foot silently -- the
    same class of defect as the earlier alphabetical-order bug."""
    assert gf.SEEDED_EVENT_ORDER == ('rHS', 'lHS', 'rTO', 'lTO')

    picker = gf.build_manual_picker(_Analysis(), ([1], [2], [3], [4]))
    assert (picker.rows('rHS'), picker.rows('lHS'),
            picker.rows('rTO'), picker.rows('lTO')) == ([1], [2], [3], [4])


def test_the_partial_detection_that_actually_triggers_the_handover(gf):
    """One heel strike is not a cycle, which is exactly the case that reaches
    the picker -- and exactly the case worth not throwing away."""
    picker = gf.build_manual_picker(_Analysis(), ([30], [], [45, 90], []))
    assert picker.rows('rHS') == [30]
    assert picker.rows('rTO') == [45, 90]
    assert sum(picker.counts().values()) == 3


def test_frames_outside_the_index_space_are_dropped_not_raised(gf):
    """Trimming rebuilds the index space. A seed pointing outside it is a
    caller bug an operator cannot act on -- losing the marker still leaves a
    usable window; an exception leaves them nothing."""
    picker = gf.build_manual_picker(_Analysis(n_rows=100),
                                    ([10, 500, -3], [], [], []))
    assert picker.rows('rHS') == [10]


def test_empty_and_none_seeds_are_both_accepted(gf):
    assert not any(gf.build_manual_picker(_Analysis(), None).counts().values())
    assert not any(gf.build_manual_picker(_Analysis(), ([], [], [], [])).counts().values())
    # A None in one slot must not take the others down with it.
    picker = gf.build_manual_picker(_Analysis(), ([7], None, None, None))
    assert picker.rows('rHS') == [7]


def test_collect_manual_events_hands_the_seeded_picker_to_the_provider(gf):
    """The provider must receive the seeded picker, not a fresh empty one --
    otherwise the seeding never reaches the window."""
    seen = {}

    def provider(picker):
        seen['rHS'] = list(picker.rows('rHS'))
        return None

    analysis = _Analysis()
    analysis.manual_event_provider = provider
    gf.collect_manual_events(analysis, ([12, 60], [], [], []))

    assert seen['rHS'] == [12, 60]


def test_the_operator_can_still_clear_the_seed_entirely(gf):
    """Cancel empties the picker, and segment_walking reads empty as a
    decline. Seeding must not make declining impossible."""
    picker = gf.build_manual_picker(_Analysis(), ([10, 70], [40], [55], [25]))
    picker.clear()
    assert not any(picker.counts().values())
