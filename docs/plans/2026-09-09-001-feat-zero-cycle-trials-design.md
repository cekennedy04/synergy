---
title: Zero-Cycle Trials - Design
type: feat
date: 2026-09-09
topic: zero-cycle-trials
status: revised-after-review-2026-09-09
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
after auto-trim rather than before.

**"Accept fewer cycles than requested" already happens.** The
`len(hsIps)-1 < n_gait_cycles` clamp reduces `n_gait_cycles` to `len(hsIps)-1` and prints
that it is proceeding with that number.

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
   case, where cycles existed but every one lost its contralateral events.

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
- **The report layer has an unavailability concept** — though not at the granularity this
  design first assumed. See "What review corrected" below.

**One real crash site, on the curve path.** `get_coordinates_normalized_time:1295` does
`np.mean(np.array(coordValuesNorm), axis=0)` over an empty list, which yields a scalar
`nan` (plus two RuntimeWarnings), and then `pd.DataFrame(data=nan, columns=colNames)`.
Verified 2026-09-09 on this machine's numpy/pandas:

```
ValueError: DataFrame constructor not properly called!
```

It is one place where "zero cycles flow through" is not merely degraded output but an
outright failure, so it needs a regression test rather than an assurance.

## What review corrected — read before implementing

The first draft of this design was reviewed on 2026-09-09 by a checklist pass, a testing
specialist, a maintainability specialist and an adversarial pass. Five of its claims were
wrong. Each was reproduced against the code, and the corrections are folded into the
sections below; they are recorded here rather than quietly edited away, because three of
them were the reasons the "let zero flow through" option looked cheap.

**1. Zero cycles corrupt session pooling, silently. This is the finding that matters.**
`gaitAnalysis-UCM.py` builds its curve matrix as
`np.zeros((len(JOINT_NAMES) * 101, n_cycles))`. At zero cycles that is `(3737, 0)`, and
`np.savetxt` writes **7474 bytes of blank lines** — not an empty file. Measured:

```
bytes written: 7474
loadtxt shape: (0, 1)
two zero-cycle trials byte-identical: True
```

`combine_curves.py` then fails on every ordering, with a message that misdiagnoses it:

```
one zero-cycle + one real trial:
  ValueError: T2_right.csv has 3737 rows but the earlier files have 0.
  These exports use different coordinate lists and cannot be pooled...

two zero-cycle trials + one real:
  ValueError: These files hold the same strides: T1_right.csv and T2_right.csv...
```

The second breaks `combine_curves.py`'s own stated premise, that "two genuinely different
trials will not be byte-identical, so this cannot fire on a normal session."

Then the tail: `clinician_gui.py:733` swallows that failure into a progress line, and
stage 7 scores `pooled_paths(session_dir)` — the **stale** matrix still on disk — under a
report line reading "Scored over all N strides pooled across this session so far". Every
trial processed after the zero-cycle one is invisible to the GDI, and the page asserts
otherwise.

That is the silent corruption this design was chosen over "skip but flag loudly" to
avoid. **A zero-cycle trial must therefore not write a curve matrix at all**, and
`combine_curves` must skip a zero-column contribution explicitly and record the omission
in its sidecar index. Neither file was named in the first draft.

**2. There is no per-metric `unavailable` concept to reuse.** The claim that this design
"reuses the report layer's existing concept" is false. There are two concepts, at two
granularities, and neither is per-metric: `report_export.py:169-185` reads
`summary.get("unavailable")` off the whole Summary-scores **section** and returns early;
`report_export.py:535-538` reads `available`/`reason` per **curve**. The metrics table has
neither — it goes through `_shape_scalar_entry` (`clinician_gui.py:1730`), which
recognises **only** `entry is None`:

```python
def _shape_scalar_entry(entry):
    if entry is None:
        return {"available": False, "status": "not available", ...}
    return {"available": True, "status": "ok", "value": entry.get("value"), ...}
```

A dict carrying `available: False` and a reason falls to the else branch, becomes
`available: True, status: "ok"` with `value` None, and the cell renders the literal string
**`"None"`**. The reason is dropped before it reaches the page.

**3. The seams are three, not two.** `compute_treadmill_speed` is called at
`gait_analysis_UCM_fixed.py:621`, in `__init__`, immediately after `self.nGaitCycles` is
set and before either dispatch seam is reachable. At zero cycles it means
`self.treadmillSpeed` is `nan` permanently — and because `nan < overground_speed_threshold`
is False, it is never normalised to 0, so `compute_gait_frame` takes the **treadmill**
heading branch on an overground trial. The first draft's test criterion, "no RuntimeWarning
raised, no `compute_*` method invoked", is unsatisfiable as written.

**4. `mean` must be `None`, not absent.** The first draft said absent.
`Examples/example_gait_analysis.py:104-105` and `Examples/gaitAnalysis-UCM.py:527`
hard-index `['mean']`, so absent raises `KeyError`. The function's own precedent
sets `sd = None` when `nGaitCycles <= 2`. `None` costs nothing and breaks nothing.

**5. `leg='auto'` has no answer here.** The first draft's table omitted the `leg='auto'`
guard and the non-manual branch. If zero cycles are produced under `leg='auto'`, `leg` is
never reassigned and `'ipsilateralLeg'` is stored as the string `'auto'`, which
`compute_gait_frame`'s `if ... == 'r'` silently resolves to **left**, and which the
`leg + '_ankle_study'` lookup turns into
`KeyError: 'auto_ankle_study'`. A zero-cycle result must name a real leg or must not be
produced under `auto` at all.

## Design

Guard at **three** seams, and write **no** curve file. Anchored to symbols rather than
line numbers, because implementation renumbers the file this design is read against.

### Seam 1 — treadmill speed, in the constructor

`compute_treadmill_speed`, called from `gait_analysis.__init__` right after
`self.nGaitCycles` is set. At zero cycles it returns `0` for an overground trial rather
than `nan`, so `self.treadmillSpeed` is never `nan` on the instance and
`compute_gait_frame`'s `== 0` test still means what it says. This seam is first because it
runs before either of the others is reachable.

### Seam 2 — scalars

`compute_scalars` dispatches every metric dynamically via `getattr(self, 'compute_' + name)`.
At zero cycles it short-circuits and returns **`{name: None}` for every requested scalar**,
without calling the underlying method.

`None` specifically, not a dict with a flag: `_shape_scalar_entry` recognises only `None`,
and already turns it into `{"available": False, "status": "not available"}`, which
`report_formatting.format_metric_value` already renders. Zero downstream edits, correct
page.

### Seam 3 — curves

`get_coordinates_normalized_time` returns its documented shape with no cycles in it:
`mean = None`, `sd = None` (as it already is below three cycles), `indiv = []`. Not
absent — consumers hard-index `['mean']`.

### Carrying the reason

Rendering "not available" is free (Seam 2 above). Carrying *why* is not, and it is a
second, separable step:

- **Metrics table:** `_shape_scalar_entry` must additionally honour an explicit
  `available: False` + `reason`, and `format_metric_value` must prefer `reason` over
  `status`. Two edits.
- **Curve pages:** `clinician_gui`'s curve builder hardcodes its reason to "'X' is not
  present in this trial's gait-cycle curves", which for a zero-cycle trial tells a
  clinician the coordinate is missing from the model. It must branch on the zero-cycle
  reason instead.

Intended reader-facing effect:

> 0 cycles recovered — 1 right heel strike after manual entry. A cycle needs two.

**Ship the `None` path first and the reason second.** The `None` path is correct and small;
the reason path touches display code and can land behind it without blocking.

### No curve file is written

A zero-cycle trial writes **no** `*_right.csv` / `*_left.csv`, because a zero-column
matrix serialises to 7474 bytes of blank lines and poisons the session (see "What review
corrected", item 1). `combine_curves` additionally skips any zero-column contribution
explicitly and records the omission in its sidecar index, so a trial that contributed
nothing is auditable rather than merely absent.

### Sites that stop raising

Anchored by condition, not line number. Every row also needs its **test** updated —
the `len(hsIps) == 0` raise is pinned by
`test_a_never_opened_window_over_a_seed_still_fails_loudly` and the `n_gait_cycles < 1`
one by `test_one_picked_heel_strike_still_names_the_leg_and_the_counts`, both of
which shipped 2026-09-09 and both of which this design deletes.

| Condition | Today | After |
| --- | --- | --- |
| `len(hsIps) == 0`, manual entry ran | raises naming leg and counts | zero cycles, same text as the reason |
| `n_gait_cycles < 1`, manual entry ran | raises naming leg and counts (fixed 2026-09-09) | zero cycles, same text as the reason |
| all steps lost contralateral events | `'No good steps for X leg.'` | zero cycles, with the count dropped |

**The last two must change in one edit.** `all([])` is `True`, so removing the
`n_gait_cycles < 1` raise while leaving the `'No good steps'` guard makes a zero-cycle
trial fall straight into it and raise a different message for a different cause.

### `leg='auto'` is out of scope

A zero-cycle result under `leg='auto'` has no leg to name, and `'auto'` stored as
`ipsilateralLeg` silently resolves to left downstream. Until that is designed, `leg='auto'`
keeps raising. This is a deliberate narrowing, not an oversight.

## What does not change

**The unattended path still raises.** With `allow_manual_entry=False` and fewer than two
heel strikes, the unattended branch raises before any of the sites above is reached — no picker ran, so
there is no operator-accepted quality to record. `clinician_gui.run_batch` and
`process_participants.py` depend on that raise, and this design does not
touch it.

**One exception to that**, which needs calling out because it changes unattended runs: the
`'No good steps'` case is reachable with `>= 2` heel strikes, so an unattended
batch that hits it will now record a zero-cycle trial where it previously raised
`GaitAnalysisFailedError` and skipped. This is the intended direction — the trial enters
the record instead of vanishing — but it means batch summaries gain zero-cycle rows that
did not exist before.

**The picker is unchanged.** No new prompts, no reopening, no change to seeding, Cancel,
or the fallback chain's shape.

## Testing

- `nGaitCycles == 0` produces a complete scalar dict of `None` values, with no
  `compute_*` method invoked. **Not** "no RuntimeWarning raised" — the first draft's
  criterion was unsatisfiable, because `compute_treadmill_speed` runs in `__init__`
  before `compute_scalars` exists. Seam 1 is what makes it satisfiable; test that
  `self.treadmillSpeed` is `0`, not `nan`.
- `get_coordinates_normalized_time` at zero cycles returns `mean=None`, `sd=None`,
  `indiv=[]` without raising — the `pd.DataFrame(data=nan, ...)` crash pinned as a
  regression test.
- **A zero-cycle trial writes no curve file, and a session containing one still pools.**
  This is the highest-value test in the list: build a session of one zero-cycle trial and
  two real ones, run the combine stage, and assert the pooled matrix contains exactly the
  real trials' strides and the sidecar index records the omission. It is also the
  cheapest to get wrong silently, because `clinician_gui` swallows combine failures into
  a progress line.
- Each condition in the table returns zero cycles instead of raising, with the reason
  carrying leg and counts.
- The unattended `<2` heel-strike path still raises, unchanged. So does `leg='auto'`.
- A zero-cycle result survives report export end to end and renders as a flagged row
  whose reason names the cycle shortage, not a missing coordinate.
- `Examples/example_gait_analysis.py` still runs: it does `round(value['value'], 2)` and
  hard-indexes `['mean']`, so both seams are exercised by it whether or not it is in the
  suite.

**Tests this design deletes, which must be replaced rather than removed.** Both landed
2026-09-09 and both pin a raise this design converts:
`test_a_never_opened_window_over_a_seed_still_fails_loudly` and
`test_one_picked_heel_strike_still_names_the_leg_and_the_counts`, plus the CI-visible
source pin `test_one_picked_heel_strike_is_not_reported_as_a_bare_cycle_shortage`. Their
guarantee — that a picker-involved failure names the leg and quotes the counts — must
survive as an assertion on the zero-cycle *reason*, or a never-opened window becomes
indistinguishable from an operator who legitimately could not pick.

Both tiers must pass. The e2e tier is the only one that exercises `gait_analysis`, and CI
cannot see it, so anything that must hold on the runner needs a source pin in
`tests/test_gait_analysis_manual_entry.py` as well.

## Open items

- The **exact report wording** for a zero-cycle row is not settled here; it should be
  chosen against a rendered page, per this repo's render-and-look rule.
- Whether cohort aggregates should show zero-cycle trials as a **separate count**
  ("N trials, 3 with no recoverable cycle") or only as flagged rows is deferred to
  implementation, where the figures can be looked at.
- **`leg='auto'` is unresolved and deliberately excluded** (see the Design section). It
  needs its own decision: either resolve a leg before producing a zero-cycle result, or
  keep raising under `auto` permanently.
- **`ActivityAnalyses/gait_analysis.py` is a second copy of this class** with the same
  postcondition, imported by `Examples/example_gait_analysis.py`. This design changes only
  `gait_analysis_UCM_fixed.py`, which leaves two classes with contradictory contracts.
  Decide whether the second one follows, or is documented as deliberately unchanged.

## Status

Revised 2026-09-09 after review. The decision (zero cycles flow through) stands; the
mechanism changed materially — three seams instead of two, `None` instead of a flag dict,
no curve file written, `leg='auto'` excluded. **Not yet implementation-ready:** the
pooling rule and the `leg='auto'` exclusion are new since approval and have not been
signed off.
