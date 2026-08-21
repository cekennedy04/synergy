# Residual Review Findings

Branch: `feat/clinician-trial-report-gui`
Commit at filing time: `de8bbfb0d213e6bf892e8b23334d371bcd5d720e`
Source: LFG step 4 (`ce-code-review mode:agent`), step 5 apply pass, step 6 residual handoff.

`ce-code-review` returned 6 actionable findings. 4 were mechanical, low-risk,
and consistent with the established per-stage exception + centralized-mapper
pattern, so LFG applied them directly in step 5 (commit `de8bbfb`). The 2
below needed a design decision or touched vendored/read-only code, so they
were filed as tracker tickets instead (no named tracker documented in this
repo; fell back to GitHub Issues via `gh`, per the tracker-defer fallback
chain — `any_sink_available: true`, `named_sink_available: false`).

## Residual Review Findings

- **P2** — `clinician_gui.py:1043` — Main-thread Figure rendering understates KTD4's disclosed UI-freeze risk.
  [github.com/cekennedy04/synergy/issues/1](https://github.com/cekennedy04/synergy/issues/1)
- **P3 (unconfirmed)** — `Examples/gaitAnalysis-UCM.py:259` — Possible AnalyzeTool output-path collision across sessions in one GUI process.
  [github.com/cekennedy04/synergy/issues/2](https://github.com/cekennedy04/synergy/issues/2)

## Applied (not residual — recorded here for traceability only)

- `clinician_gui.py:305` — `calibrate_model`/`run_imu_ik` had no dedicated exception wrapping → `ImuKinematicsError` (commit `de8bbfb`).
- `clinician_gui.py:829` — `shape_results_for_display`'s own `parse_mvnx` call was unwrapped → wrapped into `MvnxParsingError` (commit `de8bbfb`).
- `report_export.py:216` — PDF export had no specific Windows `PermissionError` handling → `ReportExportError` (commit `de8bbfb`).
- `module_loading.py:20` — docstring claimed `sys.modules` registration the implementation never performs → docstring corrected (commit `de8bbfb`).
