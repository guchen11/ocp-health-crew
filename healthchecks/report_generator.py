"""Failure analysis and pattern matching for RCA."""

def format_raw_output(details, failure_type):
    """Format raw details into readable output like oc command result"""
    if isinstance(details, list):
        if not details:
            return "(no data)"
        lines = []
        for item in details[:8]:  # Limit to 8 items
            if isinstance(item, dict):
                if "ns" in item and "name" in item:
                    lines.append(f"{item.get('ns', '-'):<30} {item.get('name', '-'):<45} {item.get('status', '-')}")
                elif "name" in item:
                    lines.append(f"{item.get('name', '-'):<45} {item.get('status', item.get('memory', '-'))}")
                else:
                    lines.append(str(item))
            else:
                lines.append(str(item))
        if len(details) > 8:
            lines.append(f"... +{len(details) - 8} more")
        return "\n".join(lines)
    elif isinstance(details, dict):
        return "\n".join([f"{k}: {v}" for k, v in list(details.items())[:5]])
    else:
        return str(details)

def analyze_failures(data):
    """Analyze failures and match to known issues from Jira"""
    analysis = []
    
    # Check each failure type against known issues
    failures = []
    
    # Collect all failures with raw output
    
    # Degraded / unavailable cluster operators
    if data.get("operators", {}).get("degraded"):
        raw_lines = ["NAME" + " " * 40 + "STATUS"]
        for op in data["operators"]["degraded"]:
            raw_lines.append(f"{op:<44} Degraded")
        failures.append({
            "type": "operator-degraded",
            "name": "Cluster Operators",
            "status": f"{len(data['operators']['degraded'])} degraded",
            "details": data["operators"]["degraded"],
            "raw_output": "\n".join(raw_lines)
        })
    
    if data.get("operators", {}).get("unavailable"):
        raw_lines = ["NAME" + " " * 40 + "STATUS"]
        for op in data["operators"]["unavailable"]:
            raw_lines.append(f"{op:<44} Unavailable")
        failures.append({
            "type": "operator-unavailable",
            "name": "Cluster Operators",
            "status": f"{len(data['operators']['unavailable'])} unavailable",
            "details": data["operators"]["unavailable"],
            "raw_output": "\n".join(raw_lines)
        })
    
    # Unhealthy nodes
    if data.get("nodes", {}).get("unhealthy"):
        raw_lines = ["NAME" + " " * 30 + "STATUS" + " " * 10 + "ROLES"]
        for node in data["nodes"]["unhealthy"]:
            if isinstance(node, dict):
                raw_lines.append(f"{node.get('name', '-'):<34} {node.get('status', '-'):<16} {node.get('roles', '-')}")
            else:
                raw_lines.append(str(node))
        failures.append({
            "type": "node",
            "name": "Nodes",
            "status": f"{len(data['nodes']['unhealthy'])} not ready",
            "details": data["nodes"]["unhealthy"],
            "raw_output": "\n".join(raw_lines)
        })
    
    # Firing alerts
    if data.get("alerts"):
        raw_lines = ["ALERT" + " " * 35 + "SEVERITY" + " " * 5 + "NAMESPACE"]
        for alert in data["alerts"][:15]:
            if isinstance(alert, dict):
                raw_lines.append(f"{alert.get('name', '-'):<40} {alert.get('severity', '-'):<13} {alert.get('namespace', '-')}")
            else:
                raw_lines.append(str(alert))
        if len(data["alerts"]) > 15:
            raw_lines.append(f"... +{len(data['alerts']) - 15} more alerts")
        failures.append({
            "type": "alert",
            "name": "Firing Alerts",
            "status": f"{len(data['alerts'])} firing",
            "details": data["alerts"],
            "raw_output": "\n".join(raw_lines)
        })
    
    if data["pods"]["unhealthy"]:
        # Format pod output like oc get pods
        raw_lines = ["NAMESPACE" + " "*22 + "NAME" + " "*41 + "STATUS"]
        for pod in data["pods"]["unhealthy"][:10]:
            raw_lines.append(f"{pod['ns']:<30} {pod['name']:<45} {pod['status']}")
        if len(data["pods"]["unhealthy"]) > 10:
            raw_lines.append(f"... +{len(data['pods']['unhealthy']) - 10} more pods")
        
        for pod in data["pods"]["unhealthy"]:
            failures.append({
                "type": "pod",
                "name": f"{pod['ns']}/{pod['name']}",
                "status": pod["status"],
                "details": pod,
                "raw_output": "\n".join(raw_lines)
            })
    
    if data["virt_handler"]["unhealthy"]:
        raw_out = format_raw_output(data["virt_handler"]["unhealthy"], "virt-handler")
        failures.append({
            "type": "virt-handler",
            "name": "virt-handler pods",
            "status": "unhealthy",
            "details": data["virt_handler"]["unhealthy"],
            "raw_output": raw_out
        })
    
    if data["virt_handler"]["high_memory"]:
        # Format like oc adm top pods output
        raw_lines = ["NAME" + " "*36 + "CPU" + " "*5 + "MEMORY"]
        for pod in data["virt_handler"]["high_memory"][:8]:
            raw_lines.append(f"{pod.get('name', '-'):<40} {pod.get('cpu', '-'):<8} {pod.get('memory', '-')}")
        if len(data["virt_handler"]["high_memory"]) > 8:
            raw_lines.append(f"... +{len(data['virt_handler']['high_memory']) - 8} more")
        
        failures.append({
            "type": "virt-handler-memory",
            "name": "virt-handler memory",
            "status": f"{len(data['virt_handler']['high_memory'])} pods high memory",
            "details": data["virt_handler"]["high_memory"],
            "raw_output": "\n".join(raw_lines)
        })
    
    if data["snapshot_issues"]:
        raw_out = format_raw_output(data["snapshot_issues"], "snapshot")
        failures.append({
            "type": "volumesnapshot",
            "name": "VolumeSnapshots",
            "status": f"{len(data['snapshot_issues'])} not ready",
            "details": data["snapshot_issues"],
            "raw_output": raw_out
        })
    
    if data["dv_issues"]:
        raw_out = format_raw_output(data["dv_issues"], "dv")
        failures.append({
            "type": "datavolume",
            "name": "DataVolumes",
            "status": f"{len(data['dv_issues'])} stuck",
            "details": data["dv_issues"],
            "raw_output": raw_out
        })
    
    if data["migrations"]["failed"] or data["migrations"]["failed_count"] > 0:
        raw_out = format_raw_output(data["migrations"]["failed"], "migration")
        failures.append({
            "type": "migration-failed",
            "name": "VM Migrations",
            "status": "failed",
            "details": data["migrations"]["failed"],
            "raw_output": raw_out
        })
    
    if data["stuck_migrations"]:
        raw_out = format_raw_output(data["stuck_migrations"], "migration")
        failures.append({
            "type": "stuck-migration",
            "name": "Stuck Migrations",
            "status": f"{len(data['stuck_migrations'])} stuck",
            "details": data["stuck_migrations"],
            "raw_output": raw_out
        })
    
    if data["cordoned_vms"]:
        raw_out = format_raw_output(data["cordoned_vms"], "vmi")
        failures.append({
            "type": "cordoned-vms",
            "name": "VMs on cordoned nodes",
            "status": f"{len(data['cordoned_vms'])} at risk",
            "details": data["cordoned_vms"],
            "raw_output": raw_out
        })
    
    if data["etcd"]["unhealthy"]:
        raw_out = format_raw_output(data["etcd"]["unhealthy"], "etcd")
        failures.append({
            "type": "etcd",
            "name": "etcd",
            "status": "unhealthy",
            "details": data["etcd"]["unhealthy"],
            "raw_output": raw_out
        })
    
    if data["oom_events"]:
        raw_out = format_raw_output(data["oom_events"], "events")
        failures.append({
            "type": "oom",
            "name": "OOM Events",
            "status": f"{len(data['oom_events'])} events",
            "details": data["oom_events"],
            "raw_output": raw_out
        })
    
    if data["csi_issues"]:
        raw_out = format_raw_output(data["csi_issues"], "csi")
        failures.append({
            "type": "csi",
            "name": "CSI Drivers",
            "status": f"{len(data['csi_issues'])} issues",
            "details": data["csi_issues"],
            "raw_output": raw_out
        })
    
    # Load patterns from the dynamic knowledge base (falls back to hardcoded on first run)
    try:
        from healthchecks.knowledge_base import load_known_issues, update_last_matched
    except ImportError:
        from knowledge_base import load_known_issues, update_last_matched
    known_issues = load_known_issues()

    # Match failures to known issues (prefer specific matches over generic)
    for failure in failures:
        matched_issues = []
        failure_text = f"{failure['type']} {failure['name']} {failure['status']} {str(failure['details'])}".lower()
        
        for issue_key, issue in known_issues.items():
            match_count = 0
            for pattern in issue["pattern"]:
                if pattern.lower() in failure_text:
                    match_count += 1
            if match_count > 0:
                matched_issues.append((match_count, len(issue.get("jira", [])), issue_key, issue))
        
        if matched_issues:
            # Sort: most pattern matches first, then most Jira refs (=most specific)
            matched_issues.sort(key=lambda x: (-x[0], -x[1]))
            best_key = matched_issues[0][2]
            best_match = matched_issues[0][3]
            all_matches = [m[3] for m in matched_issues]
            try:
                update_last_matched(best_key)
            except Exception:
                pass
            analysis.append({
                "failure": failure,
                "matched_issue": best_match,
                "all_matches": all_matches,
                "investigation": None,
                "determined_cause": None
            })
        else:
            # Generic analysis for unmatched failures
            analysis.append({
                "failure": failure,
                "matched_issue": {
                    "title": f"Unknown Issue: {failure['name']}",
                    "jira": [],
                    "description": f"Issue detected: {failure['status']}",
                    "root_cause": ["Unable to determine root cause from known issues database"],
                    "suggestions": [
                        f"Check pod/resource logs: oc logs <pod> -n <namespace>",
                        f"Describe the resource: oc describe <resource>",
                        "Search Jira for similar issues",
                        "Contact support if issue persists"
                    ]
                },
                "all_matches": [],
                "investigation": None,
                "determined_cause": None
            })
    
    return analysis


def escape_html(text):
    """Escape HTML special characters"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


from healthchecks.report_deep_investigation import run_deep_investigation  # noqa: E402
