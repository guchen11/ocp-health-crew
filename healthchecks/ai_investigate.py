"""Gemini-driven iterative investigation over SSH with command safety checks."""
import json
import logging
import re

from healthchecks.ai_gemini import _call_gemini_json
from healthchecks.ai_prompts import AI_ANALYZE_SYSTEM, AI_INVESTIGATE_SYSTEM, _get_bug_context

logger = logging.getLogger(__name__)

SAFE_CMD_PREFIXES = (
    "oc get", "oc describe", "oc logs", "oc adm top", "oc adm node-logs",
    "oc status", "oc whoami", "oc version", "oc api-resources",
    "oc explain", "oc events", "oc exec",
    "kubectl get", "kubectl describe", "kubectl logs", "kubectl top",
    "ping ", "ping6 ",
    "ssh ",
    "cat ", "head ", "tail ", "ls ", "df ", "du ", "free ",
    "ps ", "top ", "uptime", "uname", "hostname",
    "dmesg", "journalctl", "systemctl status", "systemctl is-active",
    "systemctl list-units", "systemctl show",
    "crictl ps", "crictl images", "crictl stats", "crictl info",
    "ip addr", "ip route", "ip link", "ss -", "netstat -",
)

BLOCKED_PATTERNS = (
    "delete", "remove", "rm ", "rm -", "rmdir",
    "apply", "create", "patch", "replace", "edit",
    "scale", "rollout", "drain", "cordon", "uncordon", "taint",
    "reboot", "shutdown", "poweroff", "halt", "init ",
    "systemctl restart", "systemctl stop", "systemctl start",
    "systemctl enable", "systemctl disable",
    "kill", "pkill", "killall",
    "mv ", "cp ", "chmod", "chown", "chgrp",
    "curl -X POST", "curl -X PUT", "curl -X DELETE", "curl -X PATCH",
    "oc debug",
    "mkfs", "fdisk", "mount", "umount",
    "yum ", "dnf ", "rpm ", "pip ",
    "export ", "unset ",
    "--force", "--grace-period=0",
    "> /", ">> /", "tee ",
)


def is_safe_command(cmd):
    """Check if a command is read-only and safe to auto-execute."""
    cmd_stripped = cmd.strip().lstrip("$ ")
    cmd_lower = cmd_stripped.lower()

    for blocked in BLOCKED_PATTERNS:
        if blocked in cmd_lower:
            return False

    if cmd_lower.startswith(SAFE_CMD_PREFIXES):
        return True

    if cmd_lower.startswith("ssh "):
        inner = cmd_lower.split("'", 1)[-1] if "'" in cmd_lower else cmd_lower.split('"', 1)[-1]
        for blocked in BLOCKED_PATTERNS:
            if blocked in inner:
                return False
        return True

    return False


def _get_relevant_rules(failure_type):
    """Load root_cause_rules.json and return rules matching the failure type."""
    try:
        from healthchecks.knowledge_base import load_root_cause_rules
        all_rules = load_root_cause_rules()
    except Exception:
        return []
    relevant = []
    for key, rule in all_rules.items():
        issue_types = rule.get("issue_types", [])
        if failure_type in issue_types or not issue_types:
            relevant.append({
                "key": key,
                "cause": rule.get("cause", ""),
                "is_symptom": rule.get("is_symptom", False),
                "explanation": rule.get("explanation", ""),
                "next_steps": rule.get("next_steps", []),
                "investigation_playbook": rule.get("investigation_playbook", []),
            })
    return relevant


_node_ip_cache = {}


def _build_investigation_context(issue_title, issue_desc, failure, investigation_results,
                                  drilldown_results=None, drilldown_conclusion=None,
                                  previous_followup=None,
                                  matched_inv_commands=None,
                                  jira_refs=None):
    """Build a concise context string for the AI investigation prompt."""
    lines = []
    lines.append(f"Issue: {issue_title}")
    lines.append(f"Description: {issue_desc}")

    if _node_ip_cache:
        lines.append("\nNode name -> IP mapping (use IPs for SSH, never hostnames):")
        for name, ip in _node_ip_cache.items():
            lines.append(f"  {name} = {ip}")

    f_type = failure.get("type", "")
    f_name = failure.get("name", "")
    f_status = failure.get("status", "")
    details = failure.get("details", {})
    lines.append(f"Failure: type={f_type} name={f_name} status={f_status}")
    if details:
        if isinstance(details, dict):
            lines.append(f"Details: {json.dumps(details, default=str)[:500]}")
        elif isinstance(details, list):
            lines.append(f"Details ({len(details)} items): {json.dumps(details[:3], default=str)[:500]}")

    rules = _get_relevant_rules(f_type)
    if rules:
        lines.append("\n--- Known Root Cause Rules for this issue type ---")
        lines.append("These are patterns the system already recognizes. Use them as starting")
        lines.append("hypotheses, but dig DEEPER than the rule's conclusion:")
        for r in rules:
            sym = " [SYMPTOM - dig deeper]" if r["is_symptom"] else ""
            lines.append(f"  - {r['cause']}{sym}: {r['explanation']}")
            for step in r.get("next_steps", [])[:3]:
                lines.append(f"    hint: {step}")

        playbooks = [r for r in rules if r.get("investigation_playbook")]
        if playbooks:
            pb = playbooks[0]
            lines.append(f"\n--- Investigation Playbook: {pb['cause']} ---")
            lines.append("Follow these stages in order. Each stage builds on the previous one.")
            lines.append("Use the commands as starting points; adapt based on what you find:")
            for stage in pb["investigation_playbook"]:
                lines.append(f"  Stage '{stage['stage']}': {stage['goal']}")
                for cmd in stage.get("commands", [])[:3]:
                    lines.append(f"    $ {cmd}")

    bug_entries = _get_bug_context(jira_refs)
    if bug_entries:
        lines.append("\n--- Related Known Jira Bugs ---")
        lines.append("These are real Jira bugs filed for similar symptoms. Compare the")
        lines.append("descriptions against what you observe. If symptoms match, reference")
        lines.append("the bug in your conclusion:")
        lines.extend(bug_entries)

    if matched_inv_commands:
        lines.append("\n--- Pattern-Matched Investigation Commands ---")
        lines.append("These commands were identified for this specific issue pattern:")
        for ic in matched_inv_commands[:8]:
            lines.append(f"  $ {ic.get('cmd', '')}  # {ic.get('desc', '')}")

    if investigation_results:
        lines.append("\n--- Investigation Commands Output ---")
        for r in investigation_results[:6]:
            out = r.get("output", "")[:600]
            if out.strip() in ("(no output)", "(error: )", ""):
                continue
            lines.append(f"[{r.get('description', '')}]")
            lines.append(f"$ {r.get('command', '')}")
            lines.append(out)

    if drilldown_results:
        lines.append("\n--- Drill-Down Commands Output ---")
        for r in drilldown_results[:6]:
            out = r.get("output", "")[:600]
            if out.strip() in ("(no output)", "(error: )", ""):
                continue
            lines.append(f"[{r.get('description', '')}]")
            lines.append(f"$ {r.get('command', '')}")
            lines.append(out)

    if drilldown_conclusion:
        lines.append(f"\nDrill-down conclusion: {drilldown_conclusion.get('conclusion', '')}")
        lines.append(f"Confidence: {drilldown_conclusion.get('confidence', '')}")
        if drilldown_conclusion.get("fix"):
            lines.append(f"Suggested fix: {drilldown_conclusion['fix']}")

    if previous_followup:
        lines.append("\n--- Previous AI Investigation Output ---")
        for r in previous_followup[:10]:
            out = r.get("output", "")[:800]
            if out.strip() in ("(no output)", "(error: )", ""):
                continue
            lines.append(f"[{r.get('description', '')}]")
            lines.append(f"$ {r.get('command', '')}")
            lines.append(out)

    return "\n".join(lines)


def _resolve_node_name_to_ip(hostname, ssh_command_func):
    """Resolve an OCP node name to its InternalIP, with caching."""
    if hostname in _node_ip_cache:
        return _node_ip_cache[hostname]
    try:
        import shlex as _shlex
        out = ssh_command_func(
            f"oc get node {_shlex.quote(hostname)} -o jsonpath='{{.status.addresses[?(@.type==\"InternalIP\")].address}}'",
            timeout=10,
        )
        ip = (out or "").strip().strip("'")
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
            _node_ip_cache[hostname] = ip
            return ip
    except Exception:
        pass
    return None


def _fix_unbounded_commands(cmd, ssh_command_func=None):
    """Add bounds/timeouts to commands that could run forever or hang.
    Resolves node hostnames to IPs in SSH commands when ssh_command_func is provided."""
    stripped = cmd.strip()

    if stripped.startswith("ping ") and " -c " not in stripped:
        target = stripped.split()[-1]
        return f"ping -c 3 -W 3 {target}"
    if stripped.startswith("ping6 ") and " -c " not in stripped:
        target = stripped.split()[-1]
        return f"ping6 -c 3 -W 3 {target}"

    if stripped.startswith("ssh ") and "-o ConnectTimeout" not in stripped:
        stripped = stripped.replace("ssh ", "ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no ", 1)

    if "ssh " in stripped:
        node_ips = set(_node_ip_cache.values())
        if node_ips and "@" not in stripped.split("'")[0] and "@" not in stripped.split('"')[0]:
            for ip in node_ips:
                if ip in stripped:
                    stripped = stripped.replace(ip, f"core@{ip}", 1)
                    break

        if ssh_command_func and "core@" in stripped:
            host_match = re.search(r'core@([a-zA-Z][a-zA-Z0-9._-]+)', stripped)
            if host_match:
                hostname = host_match.group(1)
                if not re.match(r'^\d+\.\d+\.\d+\.\d+$', hostname):
                    ip = _resolve_node_name_to_ip(hostname, ssh_command_func)
                    if ip:
                        stripped = stripped.replace(f"core@{hostname}", f"core@{ip}")

    return stripped


def _shell_quote(s):
    """Quote a string for safe use as a single shell argument."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _ssh_with_stderr(ssh_command_func, cmd, timeout=15, max_retries=2):
    """Wrapper that captures stderr too, so SSH errors are visible to the AI.
    Appends 2>&1 to the command and wraps with timeout to prevent hanging.
    Retries transient SSH failures with exponential backoff."""
    import time as _time

    cmd = _fix_unbounded_commands(cmd, ssh_command_func=ssh_command_func)
    merged_cmd = f"timeout {timeout} sh -c {_shell_quote(cmd + ' 2>&1')}"
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            output = ssh_command_func(merged_cmd, timeout=timeout + 5)
            if output and output.strip():
                return output.strip()
            return "(no output)"
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            is_transient = any(k in err_str for k in (
                "timeout", "timed out", "connection reset",
                "broken pipe", "connection refused", "no route",
            ))
            if is_transient and attempt < max_retries:
                delay = 2 * (2 ** attempt)
                _time.sleep(delay)
                continue
            return f"(error: {str(e)[:300]})"
    return f"(error: {str(last_error)[:300]})" if last_error else "(no output)"


def _is_vague_disk_conclusion(conclusion):
    """Return True if the conclusion mentions disk/full/pressure but doesn't name specific pods or workloads."""
    cl = conclusion.lower()
    disk_keywords = ("disk", "full", "pressure", "/var", "filesystem", "partition", "100%", "99%", "98%")
    if not any(kw in cl for kw in disk_keywords):
        return False
    specific_markers = (
        "virt-launcher", "virt-handler", "prometheus", "alertmanager",
        "csi-", "noobaa", "odf-", "ceph", "etcd", "elasticsearch",
        "fluentd", "kibana", "registry", "image-registry",
        "openshift-", "namespace", " ns:", " ns ",
        "crictl", "images not garbage", "imageGC",
    )
    if any(m in cl for m in specific_markers):
        return False
    if re.search(r'pod[s]?\s+\S+', cl) and "kubelet/pods" not in cl:
        return False
    return True


def _suggest_disk_drilldown_commands(all_results):
    """Generate follow-up commands when the AI's disk conclusion is too vague."""
    all_output = " ".join(r.get("output", "") for r in all_results)
    cmds = []
    if "kubelet/pods" in all_output.lower() or "kubelet" in all_output.lower():
        uuids = re.findall(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', all_output)
        seen = set()
        for uid in uuids:
            if uid in seen:
                continue
            seen.add(uid)
            cmds.append({"cmd": f"ssh core@<node-ip> 'sudo ls /var/lib/kubelet/pods/{uid}/volumes/kubernetes.io~empty-dir/ 2>/dev/null; sudo ls /var/lib/kubelet/pods/{uid}/volumes/kubernetes.io~configmap/ 2>/dev/null'",
                         "desc": f"Identify workload for pod UUID {uid[:8]}... via volume names"})
            if len(cmds) >= 3:
                break
    if not cmds:
        ips = set(_node_ip_cache.values())
        if ips:
            ip = next(iter(ips))
            cmds.append({"cmd": f"ssh core@{ip} 'sudo sh -c \"du -sh /var/lib/kubelet/pods/* 2>/dev/null | sort -rh | head -5\"'",
                          "desc": "Find largest pod directories under kubelet"})
    return cmds


def ai_investigate(issue_title, issue_desc, failure, investigation_results,
                   drilldown_results, drilldown_conclusion, ssh_command_func,
                   max_rounds=5, matched_inv_commands=None, jira_refs=None):
    """AI-driven recursive investigation loop. The AI self-evaluates via is_final
    and keeps digging until the root cause identifies the responsible component,
    or max_rounds is exhausted.

    Returns (all_followup_results, final_conclusion_dict_or_none).
    """
    if not _node_ip_cache:
        try:
            wide = ssh_command_func("oc get nodes -o wide --no-headers 2>/dev/null", timeout=10)
            for line in (wide or "").strip().splitlines():
                parts = line.split()
                if len(parts) >= 6 and re.match(r'\d+\.\d+\.\d+\.\d+', parts[5]):
                    _node_ip_cache[parts[0]] = parts[5]
        except Exception:
            pass

    all_results = []
    previous_followup = None
    min_rounds = 3

    for round_num in range(max_rounds):
        print(f"              AI round {round_num+1}/{max_rounds}...", flush=True)
        context = _build_investigation_context(
            issue_title, issue_desc, failure, investigation_results,
            drilldown_results, drilldown_conclusion,
            previous_followup=previous_followup,
            matched_inv_commands=matched_inv_commands,
            jira_refs=jira_refs,
        )

        if round_num == 0:
            prompt = (
                "Investigate the issue below. Suggest diagnostic commands to find the root cause. "
                "Do NOT claim is_final=true yet - gather evidence first.\n\n" + context
            )
            ai_response = _call_gemini_json(AI_INVESTIGATE_SYSTEM, prompt)
        else:
            depth_hint = ""
            if round_num < min_rounds - 1:
                depth_hint = (
                    "You MUST suggest more commands - it is too early to claim is_final=true. "
                    "If you found a large directory or resource hog, trace it to the specific "
                    "pod/workload/namespace responsible. "
                    "For disk issues: if you identified ONE consumer (e.g. journal 4G) but the disk "
                    "is much fuller (e.g. 440G), you've only found a small piece - check OTHER "
                    "directories too. Map ALL major consumers before concluding. "
                    "For kubelet/pods: you MUST identify the workload by checking volume names "
                    "inside the pod UUID dir (ls /var/lib/kubelet/pods/<uuid>/volumes/kubernetes.io~empty-dir/) "
                    "and cross-referencing with oc get pods on the node. "
                )
            prompt = (
                "Round %d. Analyze the new command output. %s"
                "Identify the specific component/workload responsible.\n\n"
                % (round_num + 1, depth_hint) + context
            )
            ai_response = _call_gemini_json(AI_ANALYZE_SYSTEM, prompt)

        if not ai_response:
            print("              AI: no response, stopping", flush=True)
            break

        rc = ai_response.get("root_cause")
        conf = ai_response.get("confidence", "low")
        is_final = ai_response.get("is_final", False)
        commands = ai_response.get("commands") or ai_response.get("needs_more_commands") or []

        if rc:
            label = "FINAL" if is_final else "INTERIM"
            print(f"              AI says ({conf}, {label}): {rc[:80]}", flush=True)

        if rc and is_final and conf in ("high", "medium") and round_num >= min_rounds - 1:
            if _is_vague_disk_conclusion(rc) and round_num < max_rounds - 1:
                print("              Depth check: DIG DEEPER - disk conclusion lacks specific pod/workload names", flush=True)
                is_final = False
                commands = commands or _suggest_disk_drilldown_commands(all_results)
            else:
                return all_results, {
                    "conclusion": rc,
                    "confidence": conf,
                    "fix": ai_response.get("fix", ""),
                    "needs_manual": ai_response.get("needs_manual", ""),
                }
        elif rc and is_final and round_num < min_rounds - 1:
            print(f"              Overriding is_final (round {round_num+1} < {min_rounds}), digging deeper", flush=True)

        if not commands:
            if rc:
                return all_results, {
                    "conclusion": rc,
                    "confidence": conf,
                    "fix": ai_response.get("fix", ""),
                    "needs_manual": ai_response.get("needs_manual", ""),
                }
            break

        round_results = []
        executed = 0
        print(f"              Running {len(commands[:5])} commands...", flush=True)
        for cmd_info in commands[:5]:
            cmd = cmd_info.get("cmd", "")
            if not cmd:
                continue
            cmd = _fix_unbounded_commands(cmd, ssh_command_func=ssh_command_func)
            if not is_safe_command(cmd):
                logger.info("Skipping unsafe AI command: %s", cmd[:80])
                continue
            desc = cmd_info.get("desc", "diagnostic")[:50]
            print(f"              $ {cmd[:70]} ({desc})", flush=True)
            output = _ssh_with_stderr(ssh_command_func, cmd, timeout=20)
            output = output[:4000]
            round_results.append({
                "description": cmd_info.get("desc", "AI-suggested diagnostic"),
                "command": cmd,
                "output": output,
            })
            executed += 1

        all_results.extend(round_results)
        previous_followup = all_results

        if executed == 0:
            break

    if all_results:
        context = _build_investigation_context(
            issue_title, issue_desc, failure, investigation_results,
            drilldown_results, drilldown_conclusion,
            previous_followup=all_results,
            jira_refs=jira_refs,
        )
        final_prompt = (
            "Based on ALL diagnostic data collected, provide your FINAL root cause. "
            "You MUST identify the specific component/workload/pod responsible. "
            "Include concrete evidence (paths, sizes, log lines, pod names, namespaces). "
            "If symptoms match a known Jira bug, reference it. "
            "Set is_final=true.\n\n" + context
        )
        final = _call_gemini_json(AI_ANALYZE_SYSTEM, final_prompt, max_tokens=4096)
        if final and final.get("root_cause"):
            return all_results, {
                "conclusion": final["root_cause"],
                "confidence": final.get("confidence", "medium"),
                "fix": final.get("fix", ""),
                "needs_manual": final.get("needs_manual", ""),
            }

    return all_results, None
