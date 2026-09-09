---
title: Zero-Cycle Trials - Design
type: feat
date: 2026-09-09
topic: zero-cycle-trials
status: approved-for-planning
source: brainstorm dialogue, 2026-09-09
---

# Zero-Cycle Trials — Design

## Goal

A trial that cannot yield a gait cycle should report **zero cycles recovered, with the
reason**, instead of raising and disappearing from the run.

The user's statement of the pathway, verbatim:

> the pathway goes fail to find gait cycle then auto trim then picker then accept the
> quality that is provided

## What already works

Two thirds of that pathway is already the code's shape, and this design must not
disturb it.

**"Not enough cycles routes to the picker" already happens.** The handover condition is
`_gait_cycle_possible` (`gait_analysis_UCM_fixed.py:419`), which is `len(hsIps) >= 2` for
an explicit leg. So 0 *or* 1 heel strikes already reaches the picker, and reaches it
after auto-trim rather than before (`:1709`).

**"Accept fewer cycles than requested" already happens.** `:1881` clamps `n_gait_cycles`
down to `len(hsIps)-1` and prints that it is proceeding with that number.

So the gap is narrower than the request implies. A trial only fails when **zero cycles
are computable**, which means fewer than two ipsilateral heel strikes survived. That is a
geometric floor — a cycle is heel strike to the next heel strike on the same leg — not a
policy threshold, and no amount of accepting lower quality creates a cycle out of one
heel strike.

## Decision

**Zero cycles flow through.** `segment_walking` returns a well-formed result with zero
rows rather than raising, and the trial appears in the results carrying its count and the
reason it is zero.

Chosen over the two alternatives considered:

- *Skip but flag loudly* — smaller, and keeps the `>= 1 cycle` postcondition, but the
  trial still vanishes from the results into a log line.
- *Reopen the picker until it yields two* — keeps the postcondition, but traps an
  operator in a window over a trial that may genuinely not contain a walkable cycle.

Rejected because both leave the trial out of the record, and this project's standing rule
is that code flags data quality and never drops (2026-08-27).

### Approved with this decision

1. A zero-cycle trial **appears** in cohort figures and per-trial reports as a flagged
   row. It is not filtered out of aggregates.
2. `nGaitCycles == 0` is the trigger, so this also covers the `'No good steps for X leg'`
   case at `:1938`, where cycles existed but every one lost its contralateral events.

## Why this is affordable

`segment_walking`'s postcondition today is "at least one cycle, or an exception", and 58
sites read `self.gaitEvents` / `self.nGaitCycles` on that assumption. Letting zero
through changes an interface all of them depend on, which is why this is a design and not
a patch. The blast radius was measured rather than assumed:

- **Per-cycle loops are already safe.** They are `for i in range(self.nGaitCycles)`, which
  no-ops at zero.
- **No `IndexError` risk in the compute path.** No hard `[0]` / `[-1]` indexing into
  `gaitEvents` exists there.
- **28 aggregations degrade rather than crash.** `np.mean` of an empty array returns
  `nan` with a RuntimeWarning.
- **The report layer already speaks this language.** `report_export.py:22` documents that
  a results object with an unavailable section "still produces a page/row with a clear
  'not available' note", and `:493` that it never raises on one.

**One real crash site, on the curve path.** `get_coordinates_normalized_time:1295` does
`np.mean(np.array(coordValuesNorm), axis=0)` over an empty list, which yields a scalar
`nan` (plus two RuntimeWarnings), and then `pd.DataFrame(data=nan, columns=colNames)`.
Verified 2026-09-09 on this machine's numpy/pandas:

```
ValueError: DataFrame constructor not properly called!
```

This is why the design has two guarded seams rather than one. It is also the one place
where "zero cycles flow through" is not merely degraded output but an outright failure, so
it needs a regression test rather than an assurance.

## Design

Guard at the two dispatch seams. No `compute_*` method and no curve consumer ever sees an
empty array, so NaN never leaks into a report looking like a measurement.

### Seam 1 — scalars

`compute_scalars` (`:663`) dispatches every metric dynamically via
`getattr(self, 'compute_' + name)`. When `self.nGaitCycles == 0` it short-circuits: each
requested scalar comes back marked unavailable, carrying the reason, without calling the
underlying method.

### Seam 2 — curves

`get_coordinates_normalized_time` (`:1282`) returns its documented shape with no cycles in
it — `mean` and `sd` absent rather than malformed, `indiv` empty — instead of constructing
a DataFrame from a scalar `nan`.

### Provenance, not a bare flag

The reason travels with the result, so a report can say *why* there are no cycles rather
than only that there are none. It carries the leg, the heel-strike counts at the point
segmentation gave up, and whether manual entry ran.

Intended reader-facing effect:

> 0 cycles recovered — 1 right heel strike after manual entry. A cycle needs two.

rather than a bare "not available".

This reuses the report layer's existing `unavailable` concept rather than introducing a
competing one.

### Sites that stop raising

| Site | Today | After |
| --- | --- | --- |
| `:1868` | 0 HS, manual entry ran — raises naming leg and counts | zero cycles, same text as the reason |
| `:1894` | `n_gait_cycles < 1` — bare `'Not enough gait cycles found.'` | zero cycles, with leg and counts |
| `:1938` | all steps lost contralateral events — `'No good steps for X leg.'` | zero cycles, with the count dropped |

## What does not change

**The unattended path still raises.** With `allow_manual_entry=False` and fewer than two
heel strikes, `:1758` raises before any of the sites above are reached — no picker ran, so
there is no operator-accepted quality to record. `clinician_gui.run_batch` and
`process_participants.py` depend on that raise (`:1753-1758`), and this design does not
touch it.

**One exception to that**, which needs calling out because it changes unattended runs: the
`'No good steps'` case at `:1938` is reachable with `>= 2` heel strikes, so an unattended
batch that hits it will now record a zero-cycle trial where it previously raised
`GaitAnalysisFailedError` and skipped. This is the intended direction — the trial enters
the record instead of vanishing — but it means batch summaries gain zero-cycle rows that
did not exist before.

**The picker is unchanged.** No new prompts, no reopening, no change to seeding, Cancel,
or the fallback chain's shape.

## Testing

- `nGaitCycles == 0` produces a complete scalar dict, every entry unavailable, no
  RuntimeWarning raised, no `compute_*` method invoked.
- `get_coordinates_normalized_time` at zero cycles returns its shape without raising —
  the current `pd.DataFrame(data=nan, ...)` crash pinned as a regression test.
- Each of the three sites in the table returns zero cycles instead of raising, with the
  reason carrying leg and counts.
- The unattended `<2` heel-strike path still raises, unchanged.
- A zero-cycle result survives report export end to end and renders as a flagged row.
- End-to-end on a real trial in the opencap tier, since `SYNERGY_FORCE_MANUAL_EVENTS`
  plus a picker that declines to pick two heel strikes reproduces this exactly.

Both tiers must pass. The e2e tier is the only one that exercises `gait_analysis`, and CI
cannot see it.

## Open items

- The **exact report wording** for a zero-cycle row is not settled here; it should be
  chosen against a rendered page, per this repo's render-and-look rule.
- Whether cohort aggregates should show zero-cycle trials as a **separate count**
  ("N trials, 3 with no recoverable cycle") or only as flagged rows is deferred to
  implementation, where the figures can be looked at.
