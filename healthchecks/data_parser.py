"""Parse oc/SSH command output into structured dicts for cluster health data."""


def parse_shell_kv_output(text: str) -> dict:
    """Parse lines like KEY=value into a dict (first '=' wins per line)."""
    result = {}
    for line in text.split("\n"):
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def parse_nodes(nodes_out: str) -> dict:
    nodes = {"healthy": [], "unhealthy": []}
    for line in nodes_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, status, roles = parts[0], parts[1], parts[2]
                node_info = {"name": name, "status": status, "roles": roles}
                if status == "Ready":
                    nodes["healthy"].append(node_info)
                else:
                    nodes["unhealthy"].append(node_info)
    return nodes


def parse_operators(operators_out: str) -> dict:
    operators = {"healthy": [], "degraded": [], "unavailable": []}
    for line in operators_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 5:
                name, available, degraded = parts[0], parts[2], parts[4]
                if available == "False":
                    operators["unavailable"].append(name)
                elif degraded == "True":
                    operators["degraded"].append(name)
                else:
                    operators["healthy"].append(name)
    return operators


def parse_pods(pods_out: str, pod_count: str) -> dict:
    pods = {"healthy": 0, "unhealthy": []}
    try:
        total = int(pod_count.strip()) if pod_count.strip().isdigit() else 0
    except (ValueError, TypeError, AttributeError):
        total = 0

    for line in pods_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                ns, name, ready, status = parts[0], parts[1], parts[2], parts[3]
                restarts = parts[4] if len(parts) > 4 else "0"
                if status not in ["Completed", "Succeeded"]:
                    pods["unhealthy"].append({
                        "ns": ns, "name": name, "ready": ready,
                        "status": status, "restarts": restarts,
                    })
    pods["healthy"] = total - len(pods["unhealthy"])
    return pods


def parse_kubevirt(kubevirt_out: str, vmi_out: str) -> dict:
    kubevirt = {"installed": False, "status": None, "vms_running": 0, "failed_vmis": []}
    if kubevirt_out and "No resources" not in kubevirt_out:
        kubevirt["installed"] = True
        parts = kubevirt_out.split()
        kubevirt["status"] = parts[-1] if parts else "Unknown"

    for line in vmi_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                if parts[3] in ["Failed", "Error"]:
                    kubevirt["failed_vmis"].append(
                        {"ns": parts[0], "name": parts[1], "status": parts[3]}
                    )
                elif parts[3] == "Running":
                    kubevirt["vms_running"] += 1
    return kubevirt


def parse_resources(top_out: str) -> dict:
    resources = {"nodes": [], "high_cpu": [], "high_memory": []}
    for line in top_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 5:
                name = parts[0]
                try:
                    cpu_cores = parts[1]
                    cpu_pct = int(parts[2].replace("%", ""))
                    mem_bytes = parts[3]
                    mem_pct = int(parts[4].replace("%", ""))
                    resources["nodes"].append({
                        "name": name, "cpu": cpu_pct, "memory": mem_pct,
                        "cpu_cores": cpu_cores, "mem_bytes": mem_bytes,
                    })
                    if cpu_pct > 85:
                        resources["high_cpu"].append(f"{name}: {cpu_pct}%")
                    if mem_pct > 85:
                        resources["high_memory"].append(f"{name}: {mem_pct}%")
                except (ValueError, TypeError, IndexError):
                    pass
    return resources


def parse_version(version_out: str) -> str:
    return version_out.split(":")[-1].strip() if version_out else "Unknown"


def parse_etcd(etcd_out: str, etcd_leader: str) -> dict:
    etcd = {
        "healthy": 0,
        "unhealthy": [],
        "leader_info": etcd_leader.strip() if etcd_leader else "",
    }
    for line in etcd_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                if status == "Running" and ready.split("/")[0] == ready.split("/")[1]:
                    etcd["healthy"] += 1
                else:
                    etcd["unhealthy"].append({"name": name, "status": status})
    return etcd


def parse_pvcs(pvc_out: str) -> dict:
    pvcs = {"pending": []}
    for line in pvc_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                pvcs["pending"].append({"ns": parts[0], "name": parts[1], "status": parts[2]})
    return pvcs


def parse_migrations(migrations_out: str, failed_migrations: str) -> dict:
    migrations = {"failed": [], "running": 0}
    try:
        migrations["failed_count"] = (
            int(failed_migrations.strip()) if failed_migrations.strip().isdigit() else 0
        )
    except (ValueError, TypeError, AttributeError):
        migrations["failed_count"] = 0
    for line in migrations_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                phase = parts[3] if len(parts) > 3 else "Unknown"
                if phase == "Running":
                    migrations["running"] += 1
                elif phase not in ["Succeeded", "Running"]:
                    migrations["failed"].append({"ns": parts[0], "name": parts[1], "phase": phase})
    return migrations


def parse_oom_events(oom_out: str) -> list:
    oom_events = []
    for line in oom_out.split("\n"):
        if line and "OOMKilled" in line:
            parts = line.split()
            if len(parts) >= 5:
                oom_events.append({"ns": parts[0], "object": parts[4] if len(parts) > 4 else "unknown"})
    return oom_events


def parse_csi_issues(csi_out: str) -> list:
    csi_issues = []
    for line in csi_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                csi_issues.append({"ns": parts[0], "pod": parts[1], "status": parts[3]})
    return csi_issues


def parse_virt_handler(virt_handler_out: str, virt_handler_mem: str) -> dict:
    virt_handler = {"healthy": 0, "unhealthy": [], "high_memory": []}
    for line in virt_handler_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                restarts = parts[3] if len(parts) > 3 else "0"
                if status == "Running" and ready.split("/")[0] == ready.split("/")[1]:
                    virt_handler["healthy"] += 1
                else:
                    virt_handler["unhealthy"].append({"name": name, "status": status, "restarts": restarts})
    for line in virt_handler_mem.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, _cpu, mem = parts[0], parts[1], parts[2]
                mem_mi = int(mem.replace("Mi", "").replace("Gi", "000")) if "Mi" in mem or "Gi" in mem else 0
                if mem_mi > 500:
                    virt_handler["high_memory"].append({"name": name, "memory": mem})
    return virt_handler


def parse_virt_launcher_bad(virt_launcher_issues: str) -> list:
    virt_launcher_bad = []
    for line in virt_launcher_issues.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                virt_launcher_bad.append({"ns": parts[0], "pod": parts[1], "status": parts[3]})
    return virt_launcher_bad


def parse_virt_ctrl(virt_ctrl_out: str) -> dict:
    virt_ctrl = {"healthy": 0, "unhealthy": []}
    for line in virt_ctrl_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                if status == "Running":
                    virt_ctrl["healthy"] += 1
                else:
                    virt_ctrl["unhealthy"].append({"name": name, "status": status})
    return virt_ctrl


def parse_dv_issues(dv_stuck: str) -> list:
    dv_issues = []
    for line in dv_stuck.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                dv_issues.append({
                    "ns": parts[0], "name": parts[1],
                    "phase": parts[3] if len(parts) > 3 else "Unknown",
                })
    return dv_issues


def parse_snapshot_issues(snapshots_out: str) -> list:
    snapshot_issues = []
    for line in snapshots_out.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                snapshot_issues.append({"ns": parts[0], "name": parts[1]})
    return snapshot_issues


def parse_cordoned_vms(vms_on_cordoned: str) -> list:
    cordoned_vms = []
    if vms_on_cordoned:
        for line in vms_on_cordoned.split("\n"):
            if line:
                parts = line.split()
                if len(parts) >= 4:
                    cordoned_vms.append({
                        "ns": parts[0], "vm": parts[1],
                        "node": parts[4] if len(parts) > 4 else "unknown",
                    })
    return cordoned_vms


def parse_stuck_migrations(stuck_migrations: str) -> list:
    stuck_migs = []
    for line in stuck_migrations.split("\n"):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                stuck_migs.append({"ns": parts[0], "name": parts[1]})
    return stuck_migs


def parse_hco_healthy(hco_status: str) -> bool:
    return "Available" in hco_status if hco_status else False


def parse_dynamic_check_issues(result: str) -> list:
    if not result:
        return []
    lower = result.lower()
    if "error" in lower or "fail" in lower or "false" in lower:
        return [{"raw": result[:200]}]
    return []
