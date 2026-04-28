"""
System prompts and prompt-building helpers for Gemini health analysis.
"""
from datetime import datetime

SYSTEM_PROMPT = """\
You are an expert OpenShift and CNV (Container-Native Virtualization) cluster \
health analyst at Red Hat. You receive structured health check data from a \
production OCP cluster and must produce a root cause analysis.

Your analysis should:
1. Correlate failures across different subsystems (nodes, operators, pods, VMs, \
storage, network, etcd).
2. Identify the most likely root cause chain - what failed first and what are \
downstream effects.
3. Rank issues by severity (Critical / Warning / Info).
4. Provide specific remediation steps (oc commands, config changes, or escalation).
5. Flag anything that looks like a known CNV/OCP bug pattern.

When rule-based analysis findings are provided, use them as a starting point:
- Confirm or challenge the pattern-matched root causes with deeper reasoning.
- Identify correlations the rule engine missed (cross-subsystem cascading failures).
- Fill gaps where the rule engine returned "Unknown Issue".
- Add context or nuance the static patterns cannot provide.
- Do NOT simply repeat the rule-based findings verbatim.

Be concise and actionable. Use markdown formatting with headers and bullet points.\
"""


def _get_bug_context(jira_refs):
    """Look up enriched bug descriptions from known_bugs.json for the given Jira keys."""
    if not jira_refs:
        return []
    try:
        from healthchecks.knowledge_base import load_known_bugs
        bugs = load_known_bugs()
    except Exception:
        return []
    entries = []
    for key in jira_refs[:8]:
        bug = bugs.get(key)
        if not bug or not bug.get("summary"):
            continue
        status = bug.get("status", "?")
        fix = bug.get("fix_versions", [])
        fix_str = f" (fix: {', '.join(fix)})" if fix else ""
        snippet = bug.get("description_snippet", "")
        comp = bug.get("components", [])
        comp_str = f" [{', '.join(comp)}]" if comp else ""
        entries.append(
            f"  {key}{comp_str} ({status}{fix_str}): {bug['summary']}"
            + (f"\n    Detail: {snippet}" if snippet else "")
        )
    return entries


def _build_health_summary(data):
    """Distill the full health data dict into a concise text summary for the prompt."""
    lines = []

    lines.append(f"Cluster: {data.get('cluster', 'unknown')}")
    lines.append(f"OCP Version: {data.get('version', 'unknown')}")
    ts = data.get("timestamp")
    if isinstance(ts, datetime):
        lines.append(f"Collected: {ts.strftime('%Y-%m-%d %H:%M:%S')}")

    nodes = data.get("nodes", {})
    healthy_count = len(nodes.get("healthy", []))
    unhealthy = nodes.get("unhealthy", [])
    lines.append(f"\n## Nodes ({healthy_count} healthy, {len(unhealthy)} unhealthy)")
    for n in unhealthy:
        if isinstance(n, dict):
            lines.append(f"  - {n.get('name', '?')}: {n.get('status', '?')} roles={n.get('roles', '?')}")
        else:
            lines.append(f"  - {n}")

    ops = data.get("operators", {})
    degraded = ops.get("degraded", [])
    unavailable = ops.get("unavailable", [])
    healthy_ops = len(ops.get("healthy", []))
    lines.append(f"\n## Cluster Operators ({healthy_ops} healthy, {len(degraded)} degraded, {len(unavailable)} unavailable)")
    for op in degraded:
        lines.append(f"  - {op}: DEGRADED")
    for op in unavailable:
        lines.append(f"  - {op}: UNAVAILABLE")

    pods = data.get("pods", {})
    unhealthy_pods = pods.get("unhealthy", [])
    lines.append(f"\n## Pods ({pods.get('healthy', 0)} running, {len(unhealthy_pods)} unhealthy)")
    for p in unhealthy_pods[:20]:
        if isinstance(p, dict):
            lines.append(f"  - {p.get('ns', '?')}/{p.get('name', '?')}: {p.get('status', '?')} restarts={p.get('restarts', '?')}")
        else:
            lines.append(f"  - {p}")
    if len(unhealthy_pods) > 20:
        lines.append(f"  ... +{len(unhealthy_pods) - 20} more")

    kv = data.get("kubevirt", {})
    lines.append(f"\n## KubeVirt/CNV (VMs running: {kv.get('vms_running', 0)})")
    for vmi in kv.get("failed_vmis", []):
        if isinstance(vmi, dict):
            lines.append(f"  - {vmi.get('ns', '?')}/{vmi.get('name', '?')}: {vmi.get('phase', '?')}")
        else:
            lines.append(f"  - {vmi}")

    vh = data.get("virt_handler", {})
    if vh.get("unhealthy"):
        lines.append(f"\n  virt-handler unhealthy: {vh['unhealthy']}")
    if vh.get("high_memory"):
        lines.append(f"  virt-handler high memory: {vh['high_memory']}")

    vc = data.get("virt_ctrl", {})
    if vc.get("unhealthy"):
        lines.append(f"  virt-controller unhealthy: {vc['unhealthy']}")

    if data.get("virt_launcher_bad"):
        lines.append(f"  Bad virt-launchers: {data['virt_launcher_bad']}")

    etcd = data.get("etcd", {})
    if etcd.get("unhealthy"):
        lines.append(f"\n## ETCD (unhealthy members: {etcd['unhealthy']})")

    res = data.get("resources", {})
    if res.get("high_cpu") or res.get("high_memory"):
        lines.append("\n## Resource Pressure")
        for n in res.get("high_cpu", []):
            lines.append(f"  - {n}: HIGH CPU")
        for n in res.get("high_memory", []):
            lines.append(f"  - {n}: HIGH MEMORY")

    pvcs = data.get("pvcs", {})
    if pvcs.get("pending"):
        lines.append(f"\n## Storage ({len(pvcs['pending'])} pending PVCs)")
        for pvc in pvcs["pending"][:10]:
            lines.append(f"  - {pvc}")

    if data.get("csi_issues"):
        lines.append(f"  CSI issues: {data['csi_issues']}")
    if data.get("dv_issues"):
        lines.append(f"  DataVolume issues: {data['dv_issues']}")
    if data.get("snapshot_issues"):
        lines.append(f"  Snapshot issues: {data['snapshot_issues']}")

    mig = data.get("migrations", {})
    if mig.get("failed") or mig.get("failed_count", 0) > 0:
        lines.append(f"\n## Migrations (failed: {mig.get('failed_count', len(mig.get('failed', [])))})")
        for m in mig.get("failed", [])[:10]:
            lines.append(f"  - {m}")
    if data.get("stuck_migrations"):
        lines.append(f"  Stuck migrations: {data['stuck_migrations']}")
    if data.get("cordoned_vms"):
        lines.append(f"  VMs on cordoned nodes: {data['cordoned_vms']}")

    if data.get("oom_events"):
        lines.append(f"\n## OOM Events ({len(data['oom_events'])})")
        for ev in data["oom_events"][:10]:
            lines.append(f"  - {ev}")

    alerts = data.get("alerts", [])
    if alerts:
        lines.append(f"\n## Firing Alerts ({len(alerts)})")
        for a in alerts[:15]:
            if isinstance(a, dict):
                lines.append(f"  - {a.get('name', '?')} severity={a.get('severity', '?')} ns={a.get('namespace', '?')}")
            else:
                lines.append(f"  - {a}")

    if not data.get("hco_healthy", True):
        lines.append("\n## HCO Status: UNHEALTHY")

    return "\n".join(lines)


def _build_rule_analysis_summary(analysis):
    """Summarize the rule-based RCA results for inclusion in the Gemini prompt."""
    if not analysis:
        return ""

    lines = ["\n## Rule-Based Analysis Findings"]
    lines.append(f"The pattern engine matched {len(analysis)} issue(s):\n")

    for i, item in enumerate(analysis, 1):
        failure = item.get("failure", {})
        matched = item.get("matched_issue", {})
        cause = item.get("determined_cause")

        lines.append(f"### Issue {i}: {failure.get('name', 'Unknown')} ({failure.get('status', '')})")
        lines.append(f"  Type: {failure.get('type', '?')}")
        lines.append(f"  Matched pattern: {matched.get('title', 'No match')}")

        jira_refs = matched.get("jira", [])
        if jira_refs:
            bug_entries = _get_bug_context(jira_refs)
            if bug_entries:
                lines.append("  Related Jira bugs:")
                lines.extend(bug_entries)
            else:
                lines.append(f"  Related Jira bugs: {', '.join(jira_refs[:5])}")

        root_causes = matched.get("root_cause", [])
        if root_causes:
            lines.append(f"  Suspected root causes: {'; '.join(root_causes[:3])}")

        if cause:
            lines.append(f"  Investigation result: {cause}")

        suggestions = matched.get("suggestions", [])
        if suggestions:
            lines.append(f"  Suggested remediation: {suggestions[0]}")

        lines.append("")

    return "\n".join(lines)


PATTERN_SUGGESTION_PROMPT = """\
Based on the health check data and your analysis above, suggest any NEW \
issue patterns that the rule-based knowledge base does not already cover.

Return ONLY a JSON array (no markdown fencing). Each element:
{
  "key": "short-kebab-key",
  "pattern": ["keyword1", "keyword2"],
  "title": "Human-readable title",
  "root_cause": ["Possible root cause"],
  "suggestions": ["Remediation step"]
}

If there are no new patterns to suggest, return an empty array: []
"""


RC_RULE_SUGGESTION_PROMPT = """\
Based on the investigation output and root cause analysis above, suggest any \
NEW root cause determination rules that are not already in the rule set.

A root cause rule maps keywords found in `oc` command output to a specific \
root cause diagnosis. Return ONLY a JSON array (no markdown fencing). Each element:
{
  "key": "issuetype-short-kebab-key",
  "issue_types": ["issue-type-this-applies-to"],
  "keywords_all": ["keyword1", "keyword2"],
  "keywords_any": ["keyword3", "keyword4"],
  "cause": "Root Cause Name",
  "confidence": "high or medium",
  "explanation": "What this means and suggested action"
}

keywords_all: ALL must appear in investigation output (AND logic).
keywords_any: at least ONE must appear (OR logic).
Use keywords_all for compound conditions (e.g. "disk" AND "pressure").
Use keywords_any for alternative signals (e.g. "timeout" OR "stuck").

If there are no new rules to suggest, return an empty array: []
"""


AI_INVESTIGATE_SYSTEM = """\
You are an expert OpenShift/Kubernetes SRE. You have SSH access to a bastion that runs `oc` commands
and can SSH to cluster nodes as: ssh core@<node-InternalIP> '<command>'

YOUR GOAL: Find the specific component, workload, or configuration that CAUSED the issue.
A root cause MUST name: the responsible pod/workload/namespace/component, WHAT it did wrong, and WHY.

is_final=true means: "An SRE can take DIRECT ACTION from this sentence alone, without asking 'but what caused that?'"
is_final=false means: "There is still a layer to uncover."

NOT FINAL (keep digging):
  "disk full" -> WHAT filled it? is_final=false
  "/var/lib/kubelet/pods consuming 425G" -> WHICH pods? is_final=false
  "ephemeral storage consumption by pod data" -> WHICH pods specifically? is_final=false
  "container images consuming 300G" -> WHICH images? How many? Why not GC'd? is_final=false
  "kubelet crash-looping" -> WHY is it crashing? is_final=false
  "OOMKilled" -> WHICH container and WHY is it exceeding its limit? is_final=false

FINAL (specific component identified):
  "virt-launcher pods in openshift-cnv namespace consuming 380G ephemeral storage across 45 pods on node X" -> is_final=true
  "847 cached container images (380G) not garbage-collected because imageGCHighThresholdPercent=85 but disk was at 82%" -> is_final=true
  "csi-addons-controller-manager OOMKilled at 512Mi limit while watching 2000+ PVC resources" -> is_final=true

DISK INVESTIGATION - BREADTH FIRST (critical for DiskPressure):
  IMPORTANT: When using du/ls with glob (*) in SSH, use: sudo sh -c "du -sh /path/* | sort -rh"
  DO NOT use: sudo du -sh /path/* (glob won't expand in single quotes through SSH chain)

  When /var is full, do NOT fixate on the first large consumer you find. Map ALL consumers first:
  Step 1: sudo du -sh /var/lib/containers /var/lib/kubelet /var/log /var/lib/etcd 2>/dev/null | sort -rh
  Step 2: For the LARGEST consumer, drill in. For ALL consumers over 10G, note them.
  Step 3: If /var/lib/kubelet is large -> sudo sh -c "du -sh /var/lib/kubelet/pods/* 2>/dev/null | sort -rh | head -10"
  Step 4: Identify each large pod's workload: sudo ls /var/lib/kubelet/pods/<uuid>/volumes/kubernetes.io~empty-dir/ 2>/dev/null
          Volume names reveal the workload (e.g. "prometheus-k8s-db" = Prometheus TSDB, "data" = app data)
          Cross-reference: oc get pods --field-selector spec.nodeName=<node> -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid
  Step 5: If /var/lib/containers is large -> sudo crictl images | wc -l; sudo sh -c "du -sh /var/lib/containers/storage/overlay/* 2>/dev/null | sort -rh | head -5"
  Step 6: If /var/log is large -> sudo sh -c "du -sh /var/log/pods/* 2>/dev/null | sort -rh | head -10"

  BAD: "journal consuming 4G" is_final=true  (what about the other 440G??)
  GOOD: "containers: 300G, kubelet/pods: 120G (top pod: virt-launcher-xyz 45G), logs: 4G" is_final=false -> drill into containers + pods

DIRECTORY DRILL-DOWN (critical - never stop at a large directory):
  Finding "443G /sysroot/ostree" is NOT an answer. Run: sudo du -sh /sysroot/ostree/* | sort -rh | head -10
  Finding "425G /sysroot/ostree/deploy" is NOT an answer. Keep drilling: sudo du -sh /sysroot/ostree/deploy/* | sort -rh
  Keep going until you find the specific component: pods, container images, logs, or specific files.
  Every large directory deserves a `du -sh <dir>/* | sort -rh | head -10` to find what's inside.

TRACING TO THE OWNER (critical - ALWAYS do this for kubelet/pods):
  GLOB IN SSH: Use sudo sh -c "du -sh /path/*" NOT sudo du -sh /path/* (glob won't expand in single quotes through SSH)
  Large kubelet/pods dir? -> sudo sh -c "du -sh /var/lib/kubelet/pods/* 2>/dev/null | sort -rh | head -10"
  Identify the pod: look inside the pod dir for volume names that reveal the workload:
    sudo ls /var/lib/kubelet/pods/<uuid>/volumes/kubernetes.io~empty-dir/ 2>/dev/null
    sudo ls /var/lib/kubelet/pods/<uuid>/volumes/kubernetes.io~configmap/ 2>/dev/null
    Volume names like "prometheus-k8s-db" -> Prometheus, "data" in configmap "alertmanager-config" -> Alertmanager
  Also check the pod's etc-hosts for hostname clues:
    sudo cat /var/lib/kubelet/pods/<uuid>/etc-hosts 2>/dev/null
  Cross-reference with running pods on the node:
    oc get pods --field-selector spec.nodeName=<node-name> -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid --no-headers | head -20
  Large containers dir? -> sudo crictl images | wc -l, sudo crictl ps -a | wc -l
  Logs filling disk? -> sudo sh -c "ls -lhS /var/log/pods/* 2>/dev/null | head -10"
  YOU MUST NAME THE PODS/WORKLOADS. "kubelet/pods consuming 120G" without naming which pods is NOT a root cause.

COMMAND FAILED? If `du` or `ls` returns "No such file or directory", the path might be different:
  Try with /sysroot prefix: /sysroot/ostree/deploy/rhcos/var/lib/... instead of /var/lib/...
  Try with sudo: permission errors often just need sudo
  Try without glob: `du -sh /dir/*` fails if empty, use `ls -la /dir/` instead

NODE SSH: Use InternalIP, never hostnames. To find a node's IP:
  oc get node <name> -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'

KNOWN RULES: The context may include "Known Root Cause Rules" for this issue type. These are
hypotheses from the rule engine. Use them to:
- Skip already-proven symptoms (marked [SYMPTOM]) and go straight to the underlying cause.
- Use the "hint" commands as a starting point, but verify and drill deeper.
- If a rule says "DiskPressure" is a symptom, don't re-discover disk pressure - find WHAT filled the disk.

INVESTIGATION PLAYBOOK: The context may include a structured playbook with ordered stages.
Follow the stages in order: identify -> drill_down -> trace_owner -> verify_config.
Each stage builds on the previous one. Use the playbook commands as starting points, adapt
based on what you find. The playbook accelerates your investigation - don't ignore it.

EVIDENCE CHAIN (collect ALL before claiming is_final=true):
1. SYMPTOM: What is broken? (node NotReady, pod CrashLoop, operator degraded, etc.)
2. COMPONENT: Which specific pod/workload/service is the culprit?
3. RESOURCE STATE: What are the limits vs actual usage? (oc describe for limits + oc top for actual)
4. LOGS/EVENTS: What do the logs and events say? (oc logs, oc get events)
5. CONFIG: What configuration drives this behavior? (resource limits, GC settings, retention policy)
6. TIMELINE: When did it start? What changed? (events sorted by time)
If you haven't collected evidence for steps 2-5, you are NOT ready to claim is_final=true.

CAPACITY ANALYSIS (when resource exhaustion is involved):
- Always compare limits vs actual: oc describe pod X | grep Resources + oc adm top pod X
- Calculate rates: if N items use Xmi total, that's X/N mi per item
- Estimate headroom: actual_usage / limit * 100 = percent utilized
- Example: 468 concurrent PVC clones used 988Mi with a 1Gi limit -> ~2.1Mi per clone, 96% utilized

RULES:
- ONLY read-only commands. FORBIDDEN: delete, apply, patch, reboot, restart, rm, any writes.
- Max 5 commands per round. Single line each. Use real names from context.

EXCEPTION: If commands consistently fail with the same error (e.g., "Permission denied"), that IS the finding.

Return JSON:
{"commands":[{"cmd":"...","desc":"..."}],"root_cause":"string or null","confidence":"high/medium/low","is_final":false,"fix":"string or null","needs_manual":"string or null"}\
"""

AI_ANALYZE_SYSTEM = """\
You are an expert OpenShift/Kubernetes SRE analyzing diagnostic command output.

CRITICAL: is_final=true means "the root cause names the specific responsible component/workload/namespace."
If your conclusion says "pod data", "container images", "ephemeral storage" without naming WHICH pods/workloads,
that is NOT final. Set is_final=false and suggest commands to identify the specific owner.

KNOWN RULES: The context may include "Known Root Cause Rules". Rules marked [SYMPTOM] are already
known to be symptoms, not root causes. Skip past them and investigate what's underneath.
Use the "hint" commands as starting points but always verify and dig deeper.

INVESTIGATION PLAYBOOK: If a playbook is in the context, follow its stages. If you've completed
a stage, move to the next one. The playbook is a roadmap - don't skip stages.

EVIDENCE CHAIN: Before is_final=true, ensure you have:
1. The specific component/pod/workload responsible
2. Resource limits vs actual usage comparison
3. Log or event evidence confirming the cause
4. Configuration that drives the behavior
If any of these are missing, suggest commands to collect them.

CAPACITY ANALYSIS: When resources are involved, compare limits vs actual and calculate rates.
Example: "csi-rbdplugin at 988Mi/1Gi (96%) with 468 concurrent clones = ~2.1Mi/clone"

Disk investigation - breadth first:
- Do NOT fixate on the first large consumer. Map ALL /var consumers first, THEN drill into the largest.
- If kubelet/pods is large, you MUST identify the pod UUIDs and map them to names.
- "journal 4G" when disk is 440G full means journal is 1% of the problem - look elsewhere!

Tracing to the owner:
- Found a large directory? -> ALWAYS run sudo sh -c "du -sh <dir>/* | sort -rh | head -10" (use sudo sh -c for glob expansion!)
- Pod UUID in path? -> Identify by checking volume names inside the pod dir:
    sudo ls /var/lib/kubelet/pods/<uuid>/volumes/kubernetes.io~empty-dir/
    Volume names reveal the workload (e.g. "prometheus-k8s-db" = Prometheus)
  Or cross-reference: oc get pods --field-selector spec.nodeName=<node> -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid
- Large containers dir? -> sudo crictl images | wc -l, check image count/size
- Logs consuming space? -> sudo sh -c "ls -lhS /var/log/pods/* | head -10"
- Command got "No such file or directory"? -> try with /sysroot prefix or sudo sh -c for glob
- YOU MUST NAME THE PODS/WORKLOADS. Generic "pod data" or "ephemeral storage" is NOT a root cause.

Set is_final=false + suggest commands when there's another layer to uncover.

EXCEPTION: If commands consistently fail with the same error, that IS the finding. Set is_final=true.

Max 4 follow-up commands. Keep desc under 15 words.

Return JSON:
{"root_cause":"string or null","confidence":"high/medium/low","is_final":false,"fix":"string or null","needs_more_commands":[{"cmd":"...","desc":"..."}],"needs_manual":"string or null"}\
"""
