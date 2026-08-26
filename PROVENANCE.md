# Provenance — who wrote what

Every file in this repo comes from one of three places. This document is the authoritative map.
It exists because git authorship cannot answer the question: all 44 commits are authored by the
repo owner, including the one that vendors 57 files of third-party upstream code.

Regenerate the underlying facts with:

```
git ls-tree -r cfcf7ad --name-only          # tier A: the vendored upstream baseline
git log --diff-filter=A --reverse -- <file> # which commit first introduced any file
```

**Ground rule followed throughout:** neither upstream files nor supervisor-supplied files are
edited in place. Fixes are added as separate, suffixed files alongside the original, so the
as-supplied version stays diffable forever. There is exactly one deliberate exception, flagged
in tier B.

---

## Tier A — Upstream `opencap-processing` (57 files) — NOT ours, NOT the supervisor's

Vendored from [opencap-org/opencap-processing](https://github.com/opencap-org/opencap-processing)
@ `72b5416` (2026-04-24), fetched 2026-08-14, in commit `cfcf7ad`. Third-party code under its own
licence (`LICENSE.md`, `README.opencap-processing.md`).

**Changes made: none. All 57 files are byte-identical to the vendored baseline.** Verified:

```
for f in $(git ls-tree -r cfcf7ad --name-only); do
  git diff --quiet cfcf7ad origin/master -- "$f" || echo "MODIFIED: $f"
done
# → no output
```

Covers `ActivityAnalyses/`, `OpenSimPipeline/`, `Moco/`, `UtilsDynamicSimulations/`, `Resources/`,
`Examples/` (except `gaitAnalysis-UCM.py`, tier B), and the root `utils.py`, `utilsKinematics.py`,
`utilsAPI.py`, `utilsAuthentication.py`, `utilsPlotting.py`, `utilsProcessing.py`, `utilsTRC.py`,
`marker_name_mapping.py`, `batchDownload.py`, `example.py`, `example_kinetics.py`.

---

## Tier B — Supervisor-supplied

Source material arrived as `utilsKinematics.zip` (2026-08-14), a later `gait_analysis_UCM.py`, and
the MATLAB in `context/` (gitignored — it also holds real patient data and must stay untracked).

### Still in the repo, as supplied

| File | Lines | Changes we made |
|---|---|---|
| `gait_analysis_UCM.py` | 1124 | **None — untouched, exactly as supplied.** Added in `67a4b2f` and never modified since. All of our fixes live in `gait_analysis_UCM_fixed.py` (tier C) so the original stays a clean reference. |

### Supervisor original that we DID edit in place — the one exception

| File | Changes we made |
|---|---|
| `Examples/gaitAnalysis-UCM.py` | Supplied at 1345 lines, now 687 — a full rewrite, not a patch (`+644 / −1302` since the as-supplied version). Two commits: `1114506` removed dead code and fixed real bugs; `67a4b2f` repointed the import to `gait_analysis_UCM_fixed`, wired the foot-progression-angle metric into `SCALAR_NAMES`/`JOINT_NAMES`, and threaded `allow_manual_entry` through `run_gait_analysis`/`process_trial` for batch mode. Earlier fixes replaced a hardcoded `\fs2.ric.org\...` network path with a repo-relative `os.chdir()`. Covered by `tests/test_gaitAnalysis_UCM_chdir.py` and `tests/test_gaitAnalysis_UCM_rewrite.py`. |

Diff it against the original at any time: `git diff 3a568fb origin/master -- Examples/gaitAnalysis-UCM.py`

### Supervisor files that were deleted

Removed in `67a4b2f` after being confirmed dead. They remain in git history at `3a568fb`.

| File | Why removed |
|---|---|
| `getMarkers.py` | Fully superseded by `xsens_to_opensim.py`'s marker export. Also carried a hardcoded `X:\Alex\...` drive path and a hardcoded `range(10)` trial count. |
| `utilsKinematics_UCM.py` | Never imported by anything. Callers do `from utilsKinematics import kinematics` — the plain name — so this file was inert. Based on an older upstream commit, missing `get_body_orientation` and the marker-name remapping. |
| `utils_UCM.py` | Never imported, and byte-identical to the stock upstream `utils.py` apart from line endings. No functional content to lose. |

### Supervisor MATLAB in `context/` — ported, never modified

The `.m` files are read-only source material. Each port was built test-first against the original:

| MATLAB source | Our port | Note |
|---|---|---|
| `context/XtoO.m` | `xtoo.py` | Port **corrects two wrong axis assignments** present in the MATLAB. |
| `context/jointcheck/jointcheck.m`, `stdshade.m` | `jointcheck.py` | Extended from a 2-way to a 3-way comparison; `stdshade` band-width defaults pinned to match MATLAB so figures stay comparable to the supervisor's existing ones. |
| `context/jointcheck/matrix_general.m` | `combine_curves.py` | Built to the supervisor's stated request; matches the positional row/column layout `matrix_general.m` hard-codes. |

---

## Tier C — Ours (created from scratch)

No supervisor or upstream ancestor. Every one is covered by tests in `tests/`.

### Conversion pipeline

| File | Lines | What it is |
|---|---|---|
| `xsens_to_opensim.py` | 1208 | Primary Xsens→OpenSim route via OpenSense IMU orientation. Written to replace the `getMarkers.py` + MATLAB round-trip. Later gained per-stage timing, a leg-tracking accuracy fix, marker/`.trc` export, and session-path handling. |
| `xtoo.py` | 294 | Second conversion route, no inverse kinematics. Port of `XtoO.m` (see tier B). |
| `module_loading.py` | 41 | Dynamic module loading support for the GUI. |

### Clinician GUI

| File | Lines | What it is |
|---|---|---|
| `clinician_gui.py` | 2124 | The GUI. Built across U1–U5: shell and session/trial input, background pipeline execution with error mapping, per-segment confidence, results review display, one-action PDF export. Later gained a scrollable results panel, raw `.mot`/`.trc` surfacing, curve-matrix export, and whole-session batch processing (`run_batch()`). |
| `report_export.py` | 248 | PDF report generation. |
| `report_formatting.py` | 38 | Report formatting helpers. |
| `joint_confidence.py` | 361 | Per-segment confidence: compares pipeline `.mot` joint angles against the Xsens suit's own. |

### Analysis and metrics

| File | Lines | What it is |
|---|---|---|
| `gait_analysis_UCM_fixed.py` | 1526 | A **copy** of the supervisor's `gait_analysis_UCM.py`, not an in-place edit, carrying 8 bug fixes found by independent review and testing: `input()` calls that hung batch runs (now behind `allow_manual_entry`), an `IndexError` on short trials in auto-trim, a no-op termination check that could run past the array end, an `IndexError` when zero heel-strikes are found, `compute_correlations()` raising `ZeroDivisionError` on its own defaults plus a stale-variable reuse, centre of mass computed with two disagreeing filter settings, a missing `@staticmethod`, and `modelName` not being forwarded to `kinematics.__init__`. Also adds `compute_foot_progression_angle()`. |
| `ucm.py` | 214 | UCM variance decomposition. Built test-first; nothing of this kind existed in the repo or its history. |
| `gdi.py` | 231 | Gait Deviation Index. |
| `task_functions.py` | 154 | Foot-placement task variable for the synergy analysis. |
| `methodology_comparison.py` | 289 | Multi-trial methodology comparison. |
| `combine_curves.py` | 207 | Pools a participant's session into one gait-cycle curve matrix. |
| `jointcheck.py` | 92 | 3-way comparison ribbon figure. |
| `make_comparison_figures.py` | 127 | Figure generation. |

### Tests and docs

All 22 files in `tests/` are ours. So are `README.md`, `VENDORING.md`, `CLAUDE.md`, `DESIGN.md`,
`CHANGELOG.md`, `.gitignore`, `docs/plans/`, and `docs/residual-review-findings/`.

Note that `tests/test_gaitAnalysis_UCM_chdir.py` and `tests/test_gaitAnalysis_UCM_rewrite.py` are
ours even though their subject is a supervisor file.
