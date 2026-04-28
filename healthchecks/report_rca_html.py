"""Root Cause Analysis HTML section: grouping, Jira checks, assembly of RCA panel."""

from healthchecks.rca_engine import check_jira_bugs
from healthchecks.report_rca_styles import (
    build_executive_summary_html,
    render_email_keywords_section,
    render_rca_grouped_issue_cards,
    render_rca_panel_header,
)


def generate_rca_html(analysis, cluster_version="", show_investigation=True, email_data=None):
    """Generate HTML for Root Cause Analysis section - grouped by issue type.

    show_investigation: If False, only show bug matching without deep investigation
    email_data: Dict containing email search results
    """
    if not analysis:
        return ""

    grouped = {}
    for item in analysis:
        title = item["matched_issue"]["title"]
        if title not in grouped:
            grouped[title] = {
                "issue": item["matched_issue"],
                "failures": [],
                "raw_outputs": [],
                "investigations": [],
                "determined_causes": [],
            }
        grouped[title]["failures"].append(item["failure"])
        raw = item["failure"].get("raw_output", "")
        if raw and raw not in grouped[title]["raw_outputs"]:
            grouped[title]["raw_outputs"].append(raw)
        if item.get("investigation"):
            grouped[title]["investigations"].append({
                "failure_name": item["failure"].get("name", ""),
                "results": item["investigation"],
            })
        if item.get("determined_cause"):
            grouped[title]["determined_causes"].append(item["determined_cause"])
        if item.get("drilldown"):
            grouped[title]["drilldown"] = item["drilldown"]
        if item.get("followup"):
            grouped[title]["followup"] = item["followup"]

    all_jira_keys = []
    for data in grouped.values():
        all_jira_keys.extend(data["issue"].get("jira", []))

    bug_status_info = check_jira_bugs(all_jira_keys, cluster_version)

    open_bugs = sum(1 for b in bug_status_info.values() if b.get("assessment") == "open")
    regression_bugs = sum(
        1 for b in bug_status_info.values() if b.get("assessment") == "regression"
    )
    fixed_bugs = sum(
        1
        for b in bug_status_info.values()
        if b.get("assessment") in ["fixed", "fixed_newer"]
    )

    html = render_rca_panel_header(
        len(grouped), open_bugs, regression_bugs, fixed_bugs
    )

    if email_data and email_data.get("keywords"):
        html += render_email_keywords_section(email_data.get("keywords", []))

    html += build_executive_summary_html(grouped)

    html += render_rca_grouped_issue_cards(
        grouped, bug_status_info, cluster_version, show_investigation
    )

    html += """
        </div>
    </div>
    """
    return html
