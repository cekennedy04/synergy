---
title: Unsegmentable Trials - Design
type: feat
date: 2026-09-11
topic: unsegmentable-trials
status: CLOSED - no work required, goal already met
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

That list is the whole behaviour. The section below explains why nothing needs adding
to it.

## There is no gap. Close this design.

The first draft of this document (2026-09-11, same day) claimed one remaining item: that
"an unsegmentable trial produces no per-trial PDF page". Verified the same day, that claim
is wrong in a way that removes the work entirely.

**No trial produces an automatic PDF page.** Export runs off `self.last_shaped` and
`self._current_figures` — an Export button acting on whichever trial the clinician
currently has loaded. There is no per-trial report artifact for an unsegmentable trial to
be missing from.

**An unsegmentable trial opened interactively already explains itself.** `map_error_to_message`
has a purpose-written branch for it that tells the clinician detection failed, that no
events were picked when the picker opened, what conditions cause it (very short recording,
non-walking motion, noisy tracking), what to do (re-run and pick rather than closing the
window), and gives a `rescue_trial.py` command that recovers the trial without redoing the
conversion.

**In a batch it is named with its reason** in the completion dialog's `Skipped:` block.

So an unsegmentable trial is already visible in both paths a clinician uses, with a reason
in both, and the remedy in one. The goal this design and its predecessor set out to reach
was reached before either was written.

**Recommendation: close this design unimplemented.** Build nothing. If a future need
appears — a session-level report page listing unsegmentable trials, say — it should be
specified from that need, not from this document's assumption that something is missing.

## Why this is the safer shape

The superseded design's first draft had five wrong load-bearing claims, found by review.
Each of its three seams was new surface in a pipeline whose contract 58 sites rely on, and
its own evidence showed that surface was where the hazards lived — the `nan` treadmill
speed, the `"None"` metrics cell, the `KeyError` on an absent `mean`, the `'auto'` leg
resolving silently to left.

The shape that won is the one that adds nothing. It cannot corrupt a pooled matrix,
cannot put `nan` on a report, and cannot change what any existing trial produces, because
it does not touch them.

## Testing

No new tests, because no new behaviour. What must keep holding is already pinned:

- The failure messages keep naming the leg and quoting the counts. Pinned by
  `test_a_never_opened_window_over_a_seed_still_fails_loudly`,
  `test_one_picked_heel_strike_still_names_the_leg_and_the_counts`, and the CI-visible
  source pin `test_one_picked_heel_strike_is_not_reported_as_a_bare_cycle_shortage`.
  **These tests stay**, where the superseded design would have deleted all three.
- Both tiers pass. The end-to-end tier is the only one that exercises `gait_analysis` and
  CI cannot see it, so anything that must hold on the runner needs a source pin in
  `tests/test_gait_analysis_manual_entry.py`.

## Open items

Only one, and it is not implementation work.

- **The "never drop" rule** (2026-08-27) exists in this repo only in these two design
  documents. It is a standing user instruction, not a repo artifact. Worth writing down
  properly somewhere durable if it is to keep deciding questions like this one.

## Status

**Closed 2026-09-11, unimplemented, because the work turned out not to exist.**

Two designs were written for this goal. The first proposed changing `segment_walking`'s
postcondition across 58 references; review found five wrong load-bearing claims in it. The
second proposed one report page; verification found that page was neither missing nor
automatic anywhere.

The behaviour both were chasing — an unsegmentable trial is visible, with its reason, and
corrupts nothing — was already shipped. What was actually needed was the one-line fix that
landed in `63762dd`, which made the one-heel-strike failure name the leg and quote the
counts instead of saying 'Not enough gait cycles found.'
