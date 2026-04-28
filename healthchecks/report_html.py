"""Grafana-style primary HTML dashboard; section builders live in report_html_sections and report_html_checks."""

from healthchecks import hybrid_flags
from healthchecks.data_collector import has_issues
from healthchecks.jira_integration import search_emails_for_issues
from healthchecks.report_generator import analyze_failures, run_deep_investigation
from healthchecks.report_rca_html import generate_rca_html
from healthchecks.report_html_checks import _render_health_checks_panel
from healthchecks.report_html_sections import (
    _build_issues_html,
    _build_resource_rows,
    _render_check_cards_script,
    _render_css,
    _render_dash_header,
    _render_footer,
    _render_navbar,
    _render_resources_and_issues_panels,
    _render_secondary_health_cards_row,
    _render_summary_gauges_row,
)
from healthchecks.ssh_client import ssh_command


def generate_html_report(data, include_rca=False, rca_level='none', ai_rca=False):
    """Generate Grafana-style HTML dashboard report

    rca_level can be:
    - 'none': No RCA, just health checks
    - 'bugs': Match failures to known bugs (no deep investigation)
    - 'full': Full RCA with deep investigation
    ai_rca: If True, run Gemini-powered AI analysis on the collected data
    """
    if include_rca and rca_level == 'none':
        rca_level = 'full'

    issues = has_issues(data)

    rca_html = ""
    email_rca_data = {}
    analysis = None
    need_patterns = (rca_level != 'none' or ai_rca) and issues

    if need_patterns:
        print(f"  🔬 Running pattern analysis...", flush=True)
        print(f"     → Matching failures to known issues database...", flush=True)
        analysis = analyze_failures(data)
        print(f"     → Found {len(analysis)} issue(s) to analyze", flush=True)

        if hybrid_flags.RCA_JIRA:
            print(f"     → Searching Jira for related bugs...", flush=True)

        if hybrid_flags.RCA_EMAIL:
            print(f"     → Searching emails for related discussions...", flush=True)
            email_rca_data = search_emails_for_issues(analysis)
            for item in analysis:
                if isinstance(item, dict):
                    item['email_searches'] = email_rca_data.get('keywords', [])

        if rca_level == 'full':
            print(f"     → Running deep investigation commands...", flush=True)
            analysis = run_deep_investigation(analysis, ssh_command)
            print(f"     → Deep investigation complete", flush=True)

        if rca_level != 'none':
            print(f"     → Generating RCA HTML section...", flush=True)
            rca_html = generate_rca_html(
                analysis, data.get("version", ""), show_investigation=(rca_level == 'full'), email_data=email_rca_data
            )
            print(f"  ✅ Rule-based RCA complete", flush=True)

    ai_rca_html = ""
    if ai_rca and issues:
        print(f"  🤖 Running Gemini AI analysis (building on {len(analysis or [])} pattern findings)...", flush=True)
        try:
            try:
                from healthchecks.ai_analysis import (
                    analyze_with_gemini,
                    generate_ai_rca_html,
                    suggest_new_patterns,
                    suggest_root_cause_rules,
                )
            except ImportError:
                from ai_analysis import (
                    analyze_with_gemini,
                    generate_ai_rca_html,
                    suggest_new_patterns,
                    suggest_root_cause_rules,
                )
            ai_markdown = analyze_with_gemini(data, rule_analysis=analysis)
            if ai_markdown:
                ai_rca_html = generate_ai_rca_html(ai_markdown)
                print(f"  ✅ AI analysis complete", flush=True)
                try:
                    new_patterns = suggest_new_patterns(data, ai_markdown, rule_analysis=analysis)
                    if new_patterns:
                        print(f"  🧠 Gemini suggested {len(new_patterns)} new pattern(s) for the knowledge base", flush=True)
                    new_rc_rules = suggest_root_cause_rules(data, ai_markdown, rule_analysis=analysis)
                    if new_rc_rules:
                        print(f"  🧠 Gemini suggested {len(new_rc_rules)} new root cause rule(s)", flush=True)
                except Exception as exc:
                    print(f"  ⚠️  Pattern suggestion step failed (non-fatal): {exc}", flush=True)
            else:
                print(f"  ⚠️  AI analysis skipped (no API key or API error)", flush=True)
        except Exception as e:
            print(f"  ⚠️  AI analysis failed: {e}", flush=True)

    status_color = "#FF9830" if issues else "#73BF69"
    status_text = "ATTENTION NEEDED" if issues else "ALL SYSTEMS HEALTHY"

    css = _render_css(issues, status_color)
    resource_rows = _build_resource_rows(data)
    issues_html = _build_issues_html(data)

    body_parts = [
        _render_navbar(status_text),
        '<div class="dashboard">',
        _render_dash_header(data),
        _render_summary_gauges_row(data),
        _render_secondary_health_cards_row(data),
        _render_resources_and_issues_panels(data, resource_rows, issues_html),
        _render_health_checks_panel(data),
        "",
        rca_html,
        "",
        ai_rca_html,
        _render_footer(status_text),
        "</div>",
        _render_check_cards_script(),
    ]
    body = "\n".join(body_parts)

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CNV HealthCrew AI - {data["cluster"]}</title>
<style>
{css}
</style>
</head>
<body>

{body}

</body>
</html>'''
