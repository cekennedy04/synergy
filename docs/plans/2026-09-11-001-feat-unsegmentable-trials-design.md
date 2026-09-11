---
title: Unsegmentable Trials - Design
type: feat
date: 2026-09-11
topic: unsegmentable-trials
status: mostly-already-built
supersedes: 2026-09-09-001-feat-zero-cycle-trials-design.md
source: ce-pov reversal, 2026-09-11
---

# Unsegmentable Trials — Design

## Goal

A trial that cannot yield a gait cycle should be **visible, with its reason**, and must
not silently corrupt anything.

Unchanged from the superseded design. What changed is the mechanism, because the goal
turned out to be nearly met already.

## The decision, and why it reversed

The superseded design chose "let zero cycles flow through the pipeline" over "skip but
flag loudly". That ranking does not survive contact with the code.

**The rejected option was rejected on a property it does not have.** The reason recorded
for dismissing skip-and-flag was that the trial "still vanishes from the results into a
log line". It does not. `run_batch` appends a structured per-trial record —

```python
trials.append({"trial": trial_name, "ok": False,
               "error": f"{type(exc).__name__}: {exc}", "result": None})
```

— under a comment that says what it is (`# noqa: BLE001 -- recorded, not swallowed`), and
the completion dialog prints a per-trial `Skipped:` block naming each trial and its full
reason. That is flagged-and-recorded, not dropped.

**Flow-through's pooling advantage was zero.** Its own hazard — a zero-column curve matrix
serialising to 7474 bytes of blank lines, poisoning `combine_curves` for the whole session
— forced the rule that a zero-cycle trial writes no curve file. But `discover_trial_files`
globs, so an absent trial is simply absent and benign. With no curve file, a zero-cycle
trial contributes nothing to the pooled GDI: exactly what skipping does.

So the two options differ in one respect only — whether an unsegmentable trial appears as
a *row reading zero cycles* or as a *record reading "failed, here is why"*. That is a
presentation difference. It does not justify changing `segment_walking`'s postcondition,
which 58 `self.gaitEvents` references and 28 `self.nGaitCycles` references depend on, nor
the three seams, the `leg='auto'` carve-out, and the two display edits that came with it.

## What is already built

Verified 2026-09-11. Most of this design is the current state of the code, which is why
it is short.

| Behaviour | Where | State |
| --- | --- | --- |
| No heel strikes, manual entry ran — names leg and counts | `segment_walking`, `len(hsIps) == 0` branch | shipped |
| One heel strike, manual entry ran — names leg and counts | `segment_walking`, `n_gait_cycles < 1` branch | shipped 2026-09-09 (`63762dd`) |
| Heel strikes for one leg only under `leg='auto'` | `segment_walking`, auto guard | shipped |
| Decline (Cancel) fails with auto-trim's reason, not a blame message | `segment_walking`, empty-set branch | shipped |
| Failing trial recorded structurally, not logged | `run_batch` | shipped |
| Operator sees each skipped trial and its reason | completion dialog `Skipped:` block | shipped |
| Batch continues past a failing trial | `run_batch` | shipped |

The remaining gap is narrow, and it is the only work this design proposes.

## The gap, and the design

**An unsegmentable trial produces no per-trial PDF page.** Its reason reaches the operator
in the batch summary and nowhere else. A clinician reading a session's reports later sees
a trial that is simply not there, with no page saying why.

Build the page, at the report layer, against the record that already exists. The report
layer is already designed for this: it renders an `unavailable` section without raising
and prints a per-curve `reason` verbatim. A trial-level equivalent is the same idea one
level up.

Explicitly **not** in scope, and this is the point of the reversal:

- No change to `segment_walking`'s postcondition. It still guarantees at least one cycle
  or an exception.
- No guard in `compute_scalars`, `get_coordinates_normalized_time`, or
  `compute_treadmill_speed`. Nothing downstream needs to learn about zero cycles.
- No `leg='auto'` carve-out, because no zero-cycle result is ever produced.
- No change to `combine_curves`. A failing trial writes no curve file today, which is
  already the safe behaviour the superseded design had to legislate.

## Why this is the safer shape

The superseded design's first draft had five wrong load-bearing claims, found by review.
Each of its three seams was new surface in a pipeline whose contract 58 sites rely on, and
its own evidence showed that surface was where the hazards lived — the `nan` treadmill
speed, the `"None"` metrics cell, the `KeyError` on an absent `mean`, the `'auto'` leg
resolving silently to left.

This design adds one page to a layer built to render missing things. It cannot corrupt a
pooled matrix, cannot put `nan` on a report, and cannot change what any existing trial
produces.

## Testing

- An unsegmentable trial produces a report page naming the trial and the reason
  segmentation failed, and the surrounding session's other trials export unchanged.
- A session containing an unsegmentable trial still pools: the combined matrix contains
  exactly the segmentable trials' strides, and the GDI is scored over those.
- The existing failure messages keep naming the leg and quoting the counts. Pinned by
  `test_a_never_opened_window_over_a_seed_still_fails_loudly`,
  `test_one_picked_heel_strike_still_names_the_leg_and_the_counts`, and the CI-visible
  source pin `test_one_picked_heel_strike_is_not_reported_as_a_bare_cycle_shortage`.
  **These tests stay**, where the superseded design would have deleted all three.
- Both tiers pass. The end-to-end tier is the only one that exercises `gait_analysis` and
  CI cannot see it, so anything that must hold on the runner needs a source pin in
  `tests/test_gait_analysis_manual_entry.py`.

## Open items

- **Report wording** for the unsegmentable-trial page is not settled here. Choose it
  against a rendered page per this repo's render-and-look rule, not in prose.
- **Whether cohort figures should count unsegmentable trials separately** ("N trials, 3
  unsegmentable") is deferred to implementation, where the figures can be looked at.
- **The "never drop" rule** (2026-08-27) exists in this repo only in these two design
  documents. It is a standing user instruction, not a repo artifact. Worth writing down
  properly somewhere durable if it is to keep deciding questions like this one.

## Status

Not started, and mostly not needed. The behaviour this design set out to guarantee is
shipped except for the per-trial page. Confirm the page is wanted before building it — if
the batch summary is where operators actually look, this design is already complete and
should be closed rather than implemented.
