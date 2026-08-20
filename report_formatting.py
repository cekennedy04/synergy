"""
report_formatting.py

Shared, pure text-formatting for a shaped gait-metric/symmetry entry (as
produced by clinician_gui.py's shape_gait_metrics_for_display). Used by both
ClinicianGUI's on-screen metrics grid (U4) and report_export.py's PDF
metrics table (U5) so there is exactly one place that decides how a metric
or symmetry entry renders as text -- previously each module had its own
copy of this logic with subtly different None-handling.

No tkinter, no matplotlib, no file I/O -- pure functions over plain dicts.
"""


def format_metric_value(entry):
    """Formats one leg's (r or l) shaped metric entry, e.g.
    {"available": True, "value": 1.234, "units": "m/s"} -> "1.23 m/s", or
    the entry's own "not available"/status text when unavailable."""
    if not entry or not entry.get("available"):
        return (entry or {}).get("status") or "not available"
    value = entry.get("value")
    units = entry.get("units") or ""
    if isinstance(value, (int, float)):
        return f"{value:.2f} {units}".strip()
    return f"{value} {units}".strip()


def format_symmetry_value(entry):
    """Formats a shaped symmetry entry, e.g.
    {"available": True, "value": 98.7, "units": "% (R/L)"} -> "98.7 % (R/L)",
    or the entry's own reason text when unavailable."""
    if not entry or not entry.get("available"):
        return (entry or {}).get("reason") or "not available"
    value = entry.get("value")
    units = entry.get("units") or ""
    if isinstance(value, (int, float)):
        return f"{value:.1f} {units}".strip()
    return f"{value} {units}".strip()
