"""Deep investigation, drill-down, and AI follow-up HTML for RCA cards."""

import re

from healthchecks.report_rca_common import confidence_color, escape_html_basic


def render_rca_investigation_section(
    investigations: list,
    determined_causes: list,
    data: dict,
) -> str:
    if not determined_causes:
        return ""

    best_cause = determined_causes[0]
    confidence_color_val = confidence_color(best_cause["confidence"])
    inv_id = best_cause.get("investigation_id", "inv")

    html = f'''
                <div style="margin-top:15px;padding:16px;background:linear-gradient(135deg, #1a2332 0%, #0d1117 100%);border:1px solid #30363d;border-radius:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                        <div style="color:#B877D9;font-weight:600;font-size:13px;">🔬 INVESTIGATED ROOT CAUSE</div>
                        <span style="background:{confidence_color_val}22;color:{confidence_color_val};padding:3px 10px;border-radius:10px;font-size:10px;font-weight:600;text-transform:uppercase;">{best_cause["confidence"]} confidence</span>
                    </div>
                    <div style="background:#161b22;border-left:3px solid {confidence_color_val};padding:12px 16px;border-radius:4px;margin-bottom:12px;">
                        <div style="color:#fff;font-size:15px;font-weight:600;margin-bottom:4px;">🎯 {best_cause["cause"]}</div>
                        <div style="color:#8b949e;font-size:12px;">{best_cause["explanation"]}</div>
                    </div>
                    <details style="margin-top:10px;">
                        <summary style="cursor:pointer;color:#58a6ff;font-size:13px;font-weight:600;padding:8px 0;">
                            📋 Detailed Investigation ({len(investigations)} diagnostic commands executed)
                        </summary>
                        <div id="inv-{inv_id}" style="margin-top:12px;max-height:800px;overflow-y:auto;">
            '''

    for inv in investigations:
        failure_name = inv.get("failure_name", "")
        results = inv.get("results", [])
        html += f'''
                            <div style="margin-bottom:16px;background:#0d1117;border-radius:6px;padding:12px;">
                                <div style="color:#8b949e;font-size:11px;margin-bottom:10px;border-bottom:1px solid #21262d;padding-bottom:8px;">
                                    Investigation for: <span style="color:#c9d1d9;font-family:monospace;">{failure_name}</span>
                                </div>
                '''
        for r in results:
            desc = r.get("description", "")
            cmd = r.get("command", "")
            output = r.get("output", "")
            output_escaped = escape_html_basic(output, 1500)
            if output_escaped.strip() in ("(no output)", "(error: )", ""):
                continue
            html += f'''
                                <div style="margin-bottom:12px;">
                                    <div style="color:#58a6ff;font-size:12px;font-weight:600;margin-bottom:4px;">📌 {desc}</div>
                                    <code style="display:block;background:#161b22;padding:6px 10px;border-radius:4px;font-size:11px;color:#8b949e;margin-bottom:4px;word-break:break-all;">$ {cmd}</code>
                                    <pre style="background:#0a0e14;padding:10px 12px;border-radius:4px;font-size:11px;color:#e6edf3;margin:0;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;line-height:1.5;">{output_escaped}</pre>
                                </div>
                    '''
        html += """
                            </div>
                """

    html += """
                        </div>
                    </details>
            """

    drilldown = data.get("drilldown")
    if drilldown and drilldown.get("results"):
        dd_results = drilldown["results"]
        dd_conclusion = drilldown.get("conclusion")
        html += f'''
                    <details style="margin-top:12px;">
                        <summary style="cursor:pointer;color:#B877D9;font-size:13px;font-weight:600;padding:8px 0;">
                            🔬 Deep Drill-Down ({len(dd_results)} additional diagnostic commands)
                        </summary>
                        <div style="margin-top:12px;max-height:800px;overflow-y:auto;">
                '''
        if dd_conclusion:
            cc = confidence_color(dd_conclusion["confidence"])
            html += f'''
                            <div style="background:#0a1a0a;border:1px solid {cc};border-radius:6px;padding:14px;margin-bottom:14px;">
                                <div style="color:{cc};font-weight:700;font-size:14px;margin-bottom:6px;">✅ Root Cause Identified</div>
                                <div style="color:#e6edf3;font-size:13px;margin-bottom:8px;">{dd_conclusion["conclusion"]}</div>
                    '''
            if dd_conclusion.get("fix"):
                fix_escaped = escape_html_basic(dd_conclusion["fix"])
                html += f'''
                                <div style="color:#58a6ff;font-size:12px;margin-bottom:4px;">🔧 <strong>How to fix:</strong></div>
                                <div style="color:#c9d1d9;font-size:12px;padding:8px 12px;background:#161b22;border-radius:4px;">{fix_escaped}</div>
                        '''
            if dd_conclusion.get("doc"):
                html += f'''
                                <div style="margin-top:8px;">
                                    <a href="{dd_conclusion["doc"]}" target="_blank" style="color:#58a6ff;font-size:11px;">📖 Red Hat Documentation →</a>
                                </div>
                        '''
            html += '''
                            </div>
                    '''
        for r in dd_results:
            desc = r.get("description", "")
            cmd = r.get("command", "")
            output = r.get("output", "")
            output_escaped = escape_html_basic(output, 2000)
            if output_escaped.strip() in ("(no output)", "(error: )", ""):
                continue
            html += f'''
                            <div style="margin-bottom:12px;">
                                <div style="color:#B877D9;font-size:12px;font-weight:600;margin-bottom:4px;">📌 {desc}</div>
                                <code style="display:block;background:#161b22;padding:6px 10px;border-radius:4px;font-size:11px;color:#8b949e;margin-bottom:4px;word-break:break-all;">$ {cmd}</code>
                                <pre style="background:#0a0e14;padding:10px 12px;border-radius:4px;font-size:11px;color:#e6edf3;margin:0;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;line-height:1.5;">{output_escaped}</pre>
                            </div>
                    '''
        html += """
                        </div>
                    </details>
                """

    followup = data.get("followup")
    if followup and followup.get("results"):
        fu_results = followup["results"]
        fu_conclusion = followup.get("conclusion")
        html += f'''
                    <details style="margin-top:12px;">
                        <summary style="cursor:pointer;color:#39D353;font-size:13px;font-weight:600;padding:8px 0;">
                            🤖 AI Deep Investigation ({len(fu_results)} diagnostic checks auto-executed)
                        </summary>
                        <div style="margin-top:12px;max-height:800px;overflow-y:auto;">
                '''
        if fu_conclusion:
            fcc = confidence_color(fu_conclusion["confidence"])
            html += f'''
                            <div style="background:#0a1a0a;border:1px solid {fcc};border-radius:6px;padding:14px;margin-bottom:14px;">
                                <div style="color:{fcc};font-weight:700;font-size:14px;margin-bottom:6px;">🔒 AI-Verified Root Cause</div>
                                <div style="color:#e6edf3;font-size:13px;margin-bottom:8px;">{fu_conclusion["conclusion"]}</div>
                    '''
            if fu_conclusion.get("fix"):
                fix_esc = escape_html_basic(fu_conclusion["fix"])
                html += f'''
                                <div style="color:#58a6ff;font-size:12px;margin-bottom:4px;">🔧 <strong>How to fix:</strong></div>
                                <div style="color:#c9d1d9;font-size:12px;padding:8px 12px;background:#161b22;border-radius:4px;">{fix_esc}</div>
                        '''
            if fu_conclusion.get("needs_manual"):
                manual_esc = escape_html_basic(fu_conclusion["needs_manual"])
                html += f'''
                                <div style="margin-top:8px;color:#FF9830;font-size:12px;">
                                    ⚠️ <strong>Manual steps needed:</strong> {manual_esc}
                                </div>
                        '''
            if fu_conclusion.get("doc"):
                html += f'''
                                <div style="margin-top:8px;">
                                    <a href="{fu_conclusion["doc"]}" target="_blank" style="color:#58a6ff;font-size:11px;">📖 Red Hat Documentation →</a>
                                </div>
                        '''
            html += '''
                            </div>
                    '''
        for r in fu_results:
            desc = r.get("description", "")
            cmd = r.get("command", "")
            output = r.get("output", "")
            output_escaped = escape_html_basic(output, 3000)
            if output_escaped.strip() in ("(no output)", "(error: )", ""):
                continue
            html += f'''
                            <div style="margin-bottom:12px;">
                                <div style="color:#39D353;font-size:12px;font-weight:600;margin-bottom:4px;">🤖 {desc}</div>
                                <code style="display:block;background:#161b22;padding:6px 10px;border-radius:4px;font-size:11px;color:#8b949e;margin-bottom:4px;word-break:break-all;">$ {cmd}</code>
                                <pre style="background:#0a0e14;padding:10px 12px;border-radius:4px;font-size:11px;color:#e6edf3;margin:0;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;line-height:1.5;">{output_escaped}</pre>
                            </div>
                    '''
        html += """
                        </div>
                    </details>
                """

    next_steps = best_cause.get("next_steps", [])
    doc_url = best_cause.get("doc_url", "")
    if next_steps or doc_url:
        html += """
                    <div style="margin-top:14px;padding:14px;background:linear-gradient(135deg, #1a1a0a 0%, #0d1117 100%);border:1px solid #FF9830;border-radius:8px;">
                        <div style="color:#FF9830;font-weight:700;font-size:13px;margin-bottom:10px;">🧪 Recommended Next Steps (if cause still unclear)</div>
                        <ol style="color:#c9d1d9;font-size:12px;margin-left:18px;line-height:1.8;">
                """
        for step in next_steps:
            step_escaped = escape_html_basic(step)
            if "http" in step:
                step_escaped = re.sub(
                    r"(https?://[^\s,)]+)",
                    r'<a href="\1" target="_blank" style="color:#58a6ff;">\1</a>',
                    step_escaped,
                )
            html += f"<li>{step_escaped}</li>"
        html += """
                        </ol>
                """
        if doc_url:
            html += f'''
                        <div style="margin-top:8px;">
                            <a href="{doc_url}" target="_blank" style="color:#58a6ff;font-size:12px;">📖 Red Hat Knowledge Base Article →</a>
                        </div>
                    '''
        html += """
                    </div>
                """

    html += """
                </div>
            """
    return html
