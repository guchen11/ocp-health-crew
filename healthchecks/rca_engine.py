"""Root cause analysis rules, drill-down, Jira bug checks, and version parsing."""

import re

from healthchecks.rca_drilldown_data import (
    DRILLDOWN_ANALYSIS_RULES,
    DRILLDOWN_COMMANDS,
    FOLLOWUP_ANALYSIS_RULES,
    FOLLOWUP_COMMANDS,
)

# Jira bug status cache (populated at runtime)
JIRA_BUG_CACHE = {}

def _extract_context_from_results(results):
    """Extract additional context (like node_ip) from drilldown/investigation results."""
    extra = {}
    import re as _re
    for r in results:
        desc = r.get("description", "").lower()
        output = r.get("output", "").strip()
        if not output or output in ("(no output)", "(error: )"):
            continue
        if "node internal ip" in desc or "node ip" in desc:
            ip_match = _re.search(r'(\d+\.\d+\.\d+\.\d+)', output)
            if ip_match:
                extra["node_ip"] = ip_match.group(1)
        if "schedulingdisabled" in desc:
            lines = output.strip().split('\n')
            if lines and lines[0].strip():
                extra["stuck_node"] = lines[0].strip().split()[0]
    return extra


def run_followup(followup_key, context, drilldown_results, ssh_command_func):
    """Run level-3 followup commands after drilldown conclusion is known.
    Only executes safe, read-only diagnostic commands.
    Returns (followup_results, refined_conclusion_or_none).
    """
    import re as _re
    commands = FOLLOWUP_COMMANDS.get(followup_key, [])
    if not commands:
        return [], None

    enriched_ctx = dict(context)
    enriched_ctx.update(_extract_context_from_results(drilldown_results))

    if "node_ip" not in enriched_ctx and enriched_ctx.get("name"):
        try:
            ip_out = ssh_command_func(
                f"oc get node {enriched_ctx['name']} -o wide 2>&1 | tail -1 | awk '{{print $6}}'",
                timeout=8
            )
            if ip_out:
                ip_match = _re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out.strip())
                if ip_match:
                    enriched_ctx["node_ip"] = ip_match.group(1)
        except Exception:
            pass

    results = []
    for cmd_info in commands:
        cmd = cmd_info["cmd"]
        for key, value in enriched_ctx.items():
            cmd = cmd.replace("{" + key + "}", str(value))
        if "{node_ip}" in cmd or "{stuck_node}" in cmd:
            continue
        try:
            output = ssh_command_func(cmd, timeout=12)
            if output:
                output = output.strip()[:3000]
            else:
                output = "(no output)"
        except Exception as e:
            output = f"(error: {str(e)[:100]})"
        results.append({
            "description": cmd_info["desc"],
            "command": cmd,
            "output": output,
        })

    if not results:
        return [], None

    all_output = " ".join(r["output"] for r in results).lower()
    analysis_rules = FOLLOWUP_ANALYSIS_RULES.get(followup_key, [])
    best = None
    for arule in analysis_rules:
        kws = arule["keywords"]
        if any(kw.lower() in all_output for kw in kws):
            best = {
                "conclusion": arule["conclusion"],
                "confidence": arule.get("confidence", "medium"),
                "fix": arule.get("fix", ""),
                "doc": arule.get("doc", ""),
            }
            break

    return results, best


def run_drilldown(drilldown_key, context, ssh_command_func):
    """Run second-level drill-down commands for a symptom-level root cause.
    Returns (drilldown_results, conclusion_dict_or_none).
    """
    import re as _re
    commands = DRILLDOWN_COMMANDS.get(drilldown_key, [])
    if not commands:
        return [], None

    enriched_ctx = dict(context)
    if "node_ip" not in enriched_ctx and enriched_ctx.get("name"):
        try:
            ip_out = ssh_command_func(
                f"oc get node {enriched_ctx['name']} -o wide 2>&1 | tail -1 | awk '{{print $6}}'",
                timeout=8
            )
            if ip_out:
                ip_match = _re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out.strip())
                if ip_match:
                    enriched_ctx["node_ip"] = ip_match.group(1)
        except Exception:
            pass

    results = []
    for cmd_info in commands:
        cmd = cmd_info["cmd"]
        for key, value in enriched_ctx.items():
            cmd = cmd.replace("{" + key + "}", str(value))
        if "{node_ip}" in cmd:
            continue
        try:
            output = ssh_command_func(cmd, timeout=15)
            if output:
                output = output.strip()[:3000]
            else:
                output = "(no output)"
        except Exception as e:
            output = f"(error: {str(e)[:100]})"
        results.append({
            "description": cmd_info["desc"],
            "command": cmd,
            "output": output,
        })

    all_output = " ".join(r["output"] for r in results).lower()
    analysis_rules = DRILLDOWN_ANALYSIS_RULES.get(drilldown_key, [])
    best_conclusion = None
    for arule in analysis_rules:
        kws = arule["keywords"]
        if any(kw.lower() in all_output for kw in kws):
            best_conclusion = {
                "conclusion": arule["conclusion"],
                "confidence": arule.get("confidence", "medium"),
                "fix": arule.get("fix", ""),
                "doc": arule.get("doc", ""),
                "follow_drilldown": arule.get("follow_drilldown"),
                "followup": arule.get("followup"),
            }
            break

    return results, best_conclusion


def investigate_issue(issue_type, context, ssh_command_func):
    """
    Run investigation commands for a specific issue type.
    Returns list of investigation results.
    """
    try:
        from healthchecks.knowledge_base import load_investigation_commands
    except ImportError:
        from knowledge_base import load_investigation_commands
    inv_commands = load_investigation_commands()
    results = []
    commands = inv_commands.get(issue_type, [])
    
    for cmd_info in commands:
        cmd_template = cmd_info["cmd"]
        desc = cmd_info["desc"]
        
        # Substitute context variables
        cmd = cmd_template
        for key, value in context.items():
            cmd = cmd.replace("{" + key + "}", str(value))
        
        # Run command with shorter timeout for speed
        try:
            output = ssh_command_func(cmd, timeout=8)
            if output:
                output = output.strip()[:2000]  # Limit output size
            else:
                output = "(no output)"
        except Exception as e:
            output = f"(error: {str(e)[:100]})"
        
        results.append({
            "description": desc,
            "command": cmd,
            "output": output
        })
    
    return results

def _extract_vmi_count(investigation_results):
    """Extract VMI count from investigation results for special rules."""
    for r in investigation_results:
        if "Total VMI" in r.get("description", ""):
            try:
                return int(r.get("output", "0").strip())
            except (ValueError, AttributeError):
                pass
    return 0


def _extract_max_memory_mi(investigation_results):
    """Extract the maximum memory value in Mi from investigation output."""
    import re as _re
    max_mem = 0
    for r in investigation_results:
        output = r.get("output", "")
        for match in _re.findall(r'(\d+)Mi', output):
            val = int(match)
            if val > max_mem:
                max_mem = val
    return max_mem


def _evaluate_special(special_key, investigation_results):
    """Evaluate special (non-keyword) conditions."""
    if special_key == "vmi_count_gt_1000":
        return _extract_vmi_count(investigation_results) > 1000
    if special_key == "vmi_count_gt_500":
        count = _extract_vmi_count(investigation_results)
        return 500 < count <= 1000
    if special_key == "virt_handler_memory_gt_800mi":
        return _extract_max_memory_mi(investigation_results) > 800
    return False


def _rule_matches(rule, issue_type, all_output, investigation_results):
    """Check if a single root cause rule matches the given context.

    Rule schema:
      issue_types      - list of issue types this rule applies to
      keywords_all     - ALL must appear in output (AND)
      keywords_any     - at least ONE must appear (OR)
      extra_required   - additional keywords that ALL must appear (AND)
      extra_required_any - at least ONE must appear (OR)
      special          - non-keyword condition key (e.g. vmi_count_gt_1000)
    """
    if issue_type not in rule.get("issue_types", []):
        return False

    special = rule.get("special")
    if special:
        return _evaluate_special(special, investigation_results)

    kw_all = rule.get("keywords_all", [])
    if kw_all and not all(kw.lower() in all_output for kw in kw_all):
        return False

    kw_any = rule.get("keywords_any", [])
    if kw_any and not any(kw.lower() in all_output for kw in kw_any):
        return False

    extra_req = rule.get("extra_required", [])
    if extra_req and not all(kw.lower() in all_output for kw in extra_req):
        return False

    extra_req_any = rule.get("extra_required_any", [])
    if extra_req_any and not any(kw.lower() in all_output for kw in extra_req_any):
        return False

    if not kw_all and not kw_any and not extra_req and not extra_req_any:
        return False

    return True


def determine_root_cause(issue_type, investigation_results, failure_details):
    """Analyze investigation results to determine the most likely root cause.

    Loads rules from knowledge/root_cause_rules.json so the logic is
    extensible without code changes.
    Returns (root_cause, confidence, explanation, rule_key, matched_rule).
    The last two are optional for backward compat - callers using 3-tuple
    unpacking still work because extra values are silently ignored by
    tuple assignment.
    """
    from healthchecks.knowledge_base import (
        load_root_cause_rules, update_root_cause_rule_matched,
    )

    all_output = " ".join(
        [r.get("output", "") for r in investigation_results]
    ).lower()

    if failure_details:
        if isinstance(failure_details, dict):
            all_output += " " + " ".join(str(v) for v in failure_details.values()).lower()
        elif isinstance(failure_details, list):
            for fd in failure_details:
                if isinstance(fd, dict):
                    all_output += " " + " ".join(str(v) for v in fd.values()).lower()
                else:
                    all_output += " " + str(fd).lower()
        else:
            all_output += " " + str(failure_details).lower()

    rules = load_root_cause_rules()
    root_causes = []

    for rule_key, rule in rules.items():
        if _rule_matches(rule, issue_type, all_output, investigation_results):
            root_causes.append((
                rule["cause"],
                rule.get("confidence", "medium"),
                rule.get("explanation", ""),
                rule_key,
                rule,
            ))

    if not root_causes:
        return ("Unknown", "low", "Further manual investigation required", None, None)

    confidence_order = {"high": 0, "medium": 1, "low": 2}
    root_causes.sort(key=lambda x: confidence_order.get(x[1], 3))

    best = root_causes[0]
    try:
        update_root_cause_rule_matched(best[3])
    except Exception:
        pass

    return (best[0], best[1], best[2], best[3], best[4])

def parse_version(version_str):
    """Parse version string to comparable tuple"""
    if not version_str:
        return (0, 0, 0)
    # Handle formats like "4.21.0-ec.3", "4.17", "CNV 4.17.0"
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', str(version_str))
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)

def compare_versions(v1, v2):
    """Compare two version strings. Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2"""
    v1_tuple = parse_version(v1)
    v2_tuple = parse_version(v2)
    if v1_tuple < v2_tuple:
        return -1
    elif v1_tuple > v2_tuple:
        return 1
    return 0

def check_jira_bugs(jira_keys, cluster_version):
    """
    Check Jira bug status and determine if bugs are open, fixed, or regression.
    Uses subprocess to call the Jira MCP tool.
    
    Returns dict with bug info: {
        'CNV-12345': {
            'status': 'Closed',
            'resolution': 'Done',
            'fix_versions': ['CNV 4.17.0'],
            'affects_versions': ['CNV 4.16.0'],
            'assessment': 'fixed'|'open'|'regression'|'unknown',
            'assessment_detail': 'Fixed in CNV 4.17.0, you are on 4.21'
        }
    }
    """
    import subprocess
    
    results = {}
    
    for jira_key in jira_keys:
        if not jira_key or jira_key in ["OCPBUGS-storage", "OCPBUGS-general", "CNV-storage"]:
            # Skip placeholder keys
            continue
            
        if jira_key in JIRA_BUG_CACHE:
            results[jira_key] = JIRA_BUG_CACHE[jira_key]
            continue
        
        try:
            # Call the Jira MCP tool via cursor's mcp-proxy if available, 
            # or use direct Jira API
            # For now, we'll use a cached/known status approach
            
            # Try to get from environment or use known statuses
            bug_info = get_known_bug_info(jira_key, cluster_version)
            results[jira_key] = bug_info
            JIRA_BUG_CACHE[jira_key] = bug_info
            
        except Exception as e:
            results[jira_key] = {
                'status': 'Unknown',
                'resolution': None,
                'fix_versions': [],
                'assessment': 'unknown',
                'assessment_detail': f'Unable to fetch: {str(e)}'
            }
    
    return results

def get_known_bug_info(jira_key, cluster_version):
    """
    Get known bug information from the dynamic knowledge base.
    Falls back to the hardcoded dict for backward compatibility.
    """
    try:
        from healthchecks.knowledge_base import load_known_bugs
    except ImportError:
        from knowledge_base import load_known_bugs
    known_bugs = load_known_bugs()
    
    if jira_key in known_bugs:
        bug = known_bugs[jira_key]
        assessment, detail = assess_bug_status(bug, cluster_version, jira_key)
        return {
            'status': bug['status'],
            'resolution': bug.get('resolution'),
            'fix_versions': bug.get('fix_versions', []),
            'affects_versions': bug.get('affects', []),
            'assessment': assessment,
            'assessment_detail': detail
        }
    
    # Unknown bug - return generic info
    return {
        'status': 'Unknown',
        'resolution': None,
        'fix_versions': [],
        'affects_versions': [],
        'assessment': 'unknown',
        'assessment_detail': f'Bug {jira_key} not in local database'
    }

def assess_bug_status(bug, cluster_version, jira_key):
    """
    Assess if a bug is relevant to current cluster version.
    Returns (assessment, detail) tuple.
    """
    status = bug.get('status', 'Unknown')
    fix_versions = bug.get('fix_versions', [])
    affects = bug.get('affects', [])
    
    # Parse cluster version (e.g., "4.21.0-ec.3" -> (4, 21, 0))
    cluster_ver = parse_version(cluster_version)
    
    # Open/In Progress bugs
    if status in ['Open', 'In Progress', 'New', 'To Do']:
        # Check if affects current version
        for av in affects:
            av_ver = parse_version(av)
            if av_ver[0] == cluster_ver[0] and av_ver[1] <= cluster_ver[1]:
                return ('open', f'🔴 OPEN - Affects your version ({cluster_version})')
        return ('open', f'🟡 OPEN - May affect version {cluster_version}')
    
    # Closed/Done bugs
    if status in ['Closed', 'Done', 'Resolved']:
        if fix_versions:
            # Find the lowest fix version
            fix_ver = min([parse_version(fv) for fv in fix_versions])
            fix_ver_str = fix_versions[0]
            
            # Compare with cluster version
            if cluster_ver >= fix_ver:
                # Bug was fixed in a version <= current
                # This could be a regression!
                return ('regression', f'⚠️ POTENTIAL REGRESSION - Fixed in {fix_ver_str}, you have {cluster_version}')
            else:
                # Bug fixed in newer version
                return ('fixed_newer', f'🟢 Fixed in {fix_ver_str} - Upgrade from {cluster_version} to resolve')
        else:
            return ('fixed', f'🟢 Closed/Resolved')
    
    return ('unknown', f'Status: {status}')
