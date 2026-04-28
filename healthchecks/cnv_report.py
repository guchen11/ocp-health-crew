"""
CNV Scenarios Report Generator

Generates a beautiful dark-themed HTML report for CNV scenario runs,
matching the style of the health check report from hybrid_health_check.py.

HTML builders live in ``cnv_report_html`` and related modules; this file holds
parsers and re-exports for backward-compatible imports.
"""

import re


# ── Scenario metadata lookup ─────────────────────────────────────────────────
# Maps remote_name -> display info.  Imported lazily so the module stays
# self-contained when used outside the Flask app.
_SCENARIO_META = None


def _get_scenario_meta():
    global _SCENARIO_META
    if _SCENARIO_META is None:
        try:
            from config.cnv_scenarios import CNV_SCENARIOS
            _SCENARIO_META = {}
            for sid, sc in CNV_SCENARIOS.items():
                _SCENARIO_META[sc["remote_name"]] = {
                    "name": sc["name"],
                    "icon": sc["icon"],
                    "category": sc["category"],
                    "description": sc.get("description", ""),
                }
        except ImportError:
            _SCENARIO_META = {}
    return _SCENARIO_META


# ── Output parser ─────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(s):
    return _ANSI_RE.sub('', s)


def parse_cnv_results(raw_output):
    """Parse structured results from CNV scenario console output.

    Looks for:
      - The results summary table printed by cnv_scenarios.py
      - The PASSED: X | FAILED: Y | TOTAL: Z summary line
      - Individual test status lines

    Returns a dict:
        {
            "tests": [
                {"name": "cpu-limits", "status": "PASS", "validation": "OK", "duration_str": "2m 30s", "duration_secs": 150},
                ...
            ],
            "passed": int,
            "failed": int,
            "total": int,
        }
    """
    lines = raw_output.split('\n')
    tests = []
    passed = 0
    failed = 0
    total = 0

    # Regex to strip the [HH:MM:SS] timestamp prefix that cnv_scenarios.py adds
    _TS_RE = re.compile(r'^\[?\d{2}:\d{2}:\d{2}\]?\s*')

    def strip_ts(s):
        """Remove leading timestamp like '[14:30:00] '."""
        return _TS_RE.sub('', s)

    # Pattern 1: summary table rows like "  cpu-limits       PASS       OK          2m 30s"
    # Lines arrive as "[14:32:00]   cpu-limits    PASS    validated    2m 30s"
    in_summary_table = False
    for line in lines:
        clean = strip_ts(strip_ansi(line)).strip()

        # Detect start of summary table
        if 'Results Summary' in clean or ('Test' in clean and 'Status' in clean and 'Validation' in clean):
            in_summary_table = True
            continue

        if in_summary_table:
            # End of table
            if clean.startswith('===') or not clean:
                if clean.startswith('===') and tests:
                    in_summary_table = False
                continue
            if clean.startswith('---'):
                continue

            # Parse table row:  "  test-name    PASS    validated    3m 10s"
            parts = clean.split()
            if len(parts) >= 2:
                name = parts[0]
                status_val = parts[1].upper()
                if status_val not in ('PASS', 'FAIL'):
                    continue
                # Only accept names that look like test slugs (contain a hyphen or alphanumeric)
                if not re.match(r'^[a-zA-Z][\w-]+$', name):
                    continue
                validation = parts[2] if len(parts) >= 3 else 'N/A'
                dur_str = ' '.join(parts[3:]) if len(parts) >= 4 else 'N/A'

                # Parse duration to seconds
                dur_secs = 0
                m_match = re.search(r'(\d+)m', dur_str)
                s_match = re.search(r'(\d+)s', dur_str)
                if m_match:
                    dur_secs += int(m_match.group(1)) * 60
                if s_match:
                    dur_secs += int(s_match.group(1))

                tests.append({
                    "name": name,
                    "status": status_val,
                    "validation": validation,
                    "duration_str": dur_str,
                    "duration_secs": dur_secs,
                })

    # Pattern 2: "PASSED: X | FAILED: Y | TOTAL: Z"
    for line in lines:
        clean = strip_ansi(line)
        match = re.search(r'PASSED:\s*(\d+)\s*\|\s*FAILED:\s*(\d+)\s*\|\s*TOTAL:\s*(\d+)', clean)
        if match:
            passed = int(match.group(1))
            failed = int(match.group(2))
            total = int(match.group(3))

    # If we didn't find the summary table, try to extract individual PASS/FAIL lines
    if not tests:
        for line in lines:
            clean = strip_ts(strip_ansi(line)).strip()
            # Match lines containing a test-name slug followed by PASS or FAIL
            m = re.match(r'.*?\b([a-zA-Z][\w]*(?:-[\w]+)+)\s+.*?\b(PASS|FAIL)\b', clean)
            if m:
                name = m.group(1)
                status_val = m.group(2)
                # Avoid false positives
                if name.lower() in ('the', 'test', 'all', 'cnv', 'kube', 'run', 'kube-burner'):
                    continue
                if not any(t["name"] == name for t in tests):
                    tests.append({
                        "name": name,
                        "status": status_val,
                        "validation": "N/A",
                        "duration_str": "N/A",
                        "duration_secs": 0,
                    })

    # Fallback: derive passed/failed from tests list
    if total == 0 and tests:
        passed = sum(1 for t in tests if t["status"] == "PASS")
        failed = sum(1 for t in tests if t["status"] == "FAIL")
        total = len(tests)

    # Extract iteration data JSON block emitted by cnv_scenarios.py
    iteration_data = {}
    import json as _json
    start_marker = "__CNV_ITERATION_DATA_START__"
    end_marker = "__CNV_ITERATION_DATA_END__"
    start_idx = raw_output.find(start_marker)
    end_idx = raw_output.find(end_marker)
    if start_idx != -1 and end_idx != -1:
        json_block = raw_output[start_idx + len(start_marker):end_idx].strip()
        try:
            summaries_list = _json.loads(json_block)
            # Map test_name -> iteration_data
            for s in summaries_list:
                tname = s.get("test", "")
                idata = s.get("iteration_data", {})
                if tname and idata:
                    iteration_data[tname] = idata
        except _json.JSONDecodeError:
            pass

    return {
        "tests": tests,
        "passed": passed,
        "failed": failed,
        "total": total,
        "iteration_data": iteration_data,
    }


def parse_cluster_info(raw_output):
    """Extract __CNV_CLUSTER_INFO__ JSON block from raw console output.

    Returns a dict with cluster metadata, or empty dict if not found.
    """
    import json as _json
    start_marker = "__CNV_CLUSTER_INFO_START__"
    end_marker = "__CNV_CLUSTER_INFO_END__"
    start_idx = raw_output.find(start_marker)
    end_idx = raw_output.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return {}
    json_block = raw_output[start_idx + len(start_marker):end_idx].strip()
    try:
        return _json.loads(json_block)
    except _json.JSONDecodeError:
        return {}


from .cnv_report_combined import generate_combined_report_html  # noqa: E402
from .cnv_report_email import generate_cnv_email_html  # noqa: E402
from .cnv_report_html import generate_cnv_report_html  # noqa: E402

__all__ = [
    "generate_cnv_email_html",
    "generate_cnv_report_html",
    "generate_combined_report_html",
    "parse_cluster_info",
    "parse_cnv_results",
    "strip_ansi",
]
