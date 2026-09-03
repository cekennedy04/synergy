"""Pick gait events by hand when automatic detection cannot.

Built 2026-08-30. Phase 2.2, on top of `motion_scrubber.py`. This is the third
rung of `segment_walking`'s fallback chain: prominence escalation
(0.3 -> 0.25 -> 0.2), then the auto-trim retry loop, then a human.

**What it must reproduce exactly.** `segment_walking` unpacks
`rHS, lHS, rTO, lTO` from whatever supplies its events. Edit #13 exists
because `trimend` returned those four in a different order for months,
putting left heel-strikes in the right toe-off slot and silently corrupting
every metric downstream. `as_segment_walking_events` returns that same
four-tuple in that same order, and a test pins it against
`detect_gait_peaks`. Do not add a fifth return value or reorder these.

**Events are stored as row indices, never as times.** `.mot` sample times are
not uniform -- a real file from this pipeline runs 0.016667, 0.017, 0.016,
0.017 -- so a time chosen in the UI and converted back would not land on the
frame the operator saw. `segment_walking` works in indices into
`markerDict['time']` anyway, so the index is both the natural storage and the
natural output; time is derived for display only.

**Ordering is checked but never enforced.** The picker reports whether the
picked set satisfies the same cyclic order `detect_correct_order` requires, so
the operator gets the pipeline's own verdict while picking rather than a
rejection afterwards. It does not refuse to save an out-of-order set: a
pathological gait may genuinely violate the expected order, and the guardrail
removal on 2026-08-27 established that this project reports rather than
blocks.
"""
from pathlib import Path

# The cycle segment_walking's detect_correct_order requires. Duplicated from
# that nested function deliberately -- it is not importable, being defined
# inside segment_walking -- and pinned by a test that reads the source, so the
# two cannot drift silently.
EXPECTED_ORDER = {
    "rHS": "lTO",
    "lTO": "lHS",
    "lHS": "rTO",
    "rTO": "rHS",
}

EVENT_TYPES = ("rHS", "rTO", "lHS", "lTO")


def _chain_from(start, names):
    """`names` read as consecutive cycle steps beginning at `start`.

    Returns (ordered, run) where `run` is how many of them actually chained;
    anything the cycle could not reach is appended alphabetically so nothing
    is ever dropped. A pathological set that no order rescues therefore keeps
    all its events and still fails the ordering verdict, which is the
    behaviour this project wants: report, do not refuse.
    """
    pool = [name for name in names if name != start]
    ordered = [start]
    current = start
    while EXPECTED_ORDER[current] in pool:
        current = EXPECTED_ORDER[current]
        pool.remove(current)
        ordered.append(current)
    return ordered + sorted(pool), len(ordered)


def _order_within_frame(names, previous):
    """Order the events sharing one frame so they read as the cycle does.

    Double support puts one foot's toe-off and the other's heel-strike within
    a few frames of each other, and at the 60Hz these trials are captured at
    they land on the same frame often enough to matter.

    The start is whichever event chains the most of the group; ties go to the
    one `previous` expects next, then alphabetically -- so the result depends
    only on the picked set, never on the order the operator clicked.
    """
    candidates = sorted(names)
    if len(candidates) < 2:
        return candidates
    expected = EXPECTED_ORDER.get(previous) if previous else None
    ranked = min(
        candidates,
        key=lambda start: (-_chain_from(start, candidates)[1],
                           0 if start == expected else 1,
                           start))
    return _chain_from(ranked, candidates)[0]


class GaitEventPicker:
    """Accumulates hand-picked gait events for one trial.

    Holds no GUI state. The scrubber window drives it; the tests drive it
    directly, which is the only reason the picking logic is verifiable at all
    without a display and an OpenSim install.
    """

    def __init__(self, motion):
        self.motion = motion
        self._events = {name: [] for name in EVENT_TYPES}

    # -- picking ----------------------------------------------------------

    def mark(self, event_type, row):
        """Record one event at a row. Idempotent per (type, row)."""
        if event_type not in self._events:
            raise ValueError(
                f"unknown event type {event_type!r}; expected one of "
                f"{list(EVENT_TYPES)}.")
        if not 0 <= row < self.motion.n_rows:
            raise IndexError(
                f"row {row} is outside this motion's {self.motion.n_rows} "
                "frames, so it cannot name a gait event.")
        if row not in self._events[event_type]:
            self._events[event_type].append(row)
            self._events[event_type].sort()
        return row

    def unmark(self, event_type, row):
        """Remove one event. Silent when it was not marked -- the operator
        clicking delete twice is not an error."""
        if event_type in self._events and row in self._events[event_type]:
            self._events[event_type].remove(row)

    def clear(self, event_type=None):
        for name in ([event_type] if event_type else EVENT_TYPES):
            self._events[name] = []

    def rows(self, event_type):
        return list(self._events[event_type])

    # -- what the operator sees -------------------------------------------

    def timeline(self):
        """Every picked event in time order: (row, time, event_type).

        Frames decide the order. Two events on ONE frame are decided by the
        gait cycle instead -- see `_order_within_frame`. A plain sort broke
        here: it fell back to sorting by name, and 'lTO' < 'rHS' is the
        reverse of the cycle's rHS -> lTO, so a correctly-picked trial with a
        double-support collision was reported as out of order.
        """
        by_frame = {}
        for name, rows in self._events.items():
            for row in rows:
                by_frame.setdefault(row, []).append(name)

        entries = []
        previous = None
        for row in sorted(by_frame):
            for name in _order_within_frame(by_frame[row], previous):
                entries.append((row, self.motion.time_at(row), name))
                previous = name
        return entries

    def counts(self):
        return {name: len(rows) for name, rows in self._events.items()}

    def ordering_report(self):
        """The pipeline's own verdict on the picked set, while picking.

        Mirrors detect_correct_order: walk the four sequences in time order
        and require each event to be followed by the one EXPECTED_ORDER names.
        Returns (ok, message) rather than raising -- see the module docstring
        on reporting versus blocking.
        """
        entries = self.timeline()
        if not entries:
            return False, "No events picked yet."

        missing = [name for name, rows in self._events.items() if not rows]
        for index in range(len(entries) - 1):
            _row, _time, current = entries[index]
            _next_row, next_time, following = entries[index + 1]
            if following != EXPECTED_ORDER[current]:
                return False, (
                    f"{current} at {entries[index][1]:.3f}s is followed by "
                    f"{following} at {next_time:.3f}s; gait ordering expects "
                    f"{EXPECTED_ORDER[current]}. Either an event is missing "
                    "between them or one is on the wrong foot."
                )
        if missing:
            return False, (
                f"Ordering is consistent so far, but nothing is picked for "
                f"{missing}. A gait cycle needs all four."
            )
        return True, f"{len(entries)} events in correct gait order."

    # -- handing back to the pipeline -------------------------------------

    def as_segment_walking_events(self):
        """(rHS, lHS, rTO, lTO) -- segment_walking's unpacking order.

        This ordering is the contract edit #13 was about. It is deliberately
        NOT alphabetical and NOT the order of EVENT_TYPES.
        """
        return (self.rows("rHS"), self.rows("lHS"),
                self.rows("rTO"), self.rows("lTO"))

    def to_dict(self):
        """A saveable record. Times are included for a human reading the file
        and are never read back -- rows are the source of truth."""
        return {
            "motion": self.motion.name,
            "n_rows": self.motion.n_rows,
            "events": {
                name: [{"row": row, "time": self.motion.time_at(row)}
                       for row in rows]
                for name, rows in self._events.items()
            },
        }

    @classmethod
    def from_dict(cls, motion, record):
        """Restore a saved set onto a motion, checking it is the same one.

        A picked set silently applied to a different trial would place events
        at frames nobody chose, which is exactly the class of silent wrongness
        this project keeps finding.
        """
        if record.get("n_rows") != motion.n_rows:
            raise ValueError(
                f"saved events describe a motion of {record.get('n_rows')} "
                f"frames but this one has {motion.n_rows}. Rows are frame "
                "indices, so they do not transfer between trials."
            )
        picker = cls(motion)
        for name, entries in record.get("events", {}).items():
            for entry in entries:
                picker.mark(name, entry["row"])
        return picker
