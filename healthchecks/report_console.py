"""ANSI console summary report."""

from healthchecks.data_collector import has_issues

def print_console_report(data):
    """Print beautiful console report"""
    # ANSI colors
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow
    R = '\033[91m'  # Red
    B = '\033[94m'  # Blue
    C = '\033[96m'  # Cyan
    W = '\033[97m'  # White
    D = '\033[2m'   # Dim
    BD = '\033[1m'  # Bold
    X = '\033[0m'   # Reset
    
    issues = has_issues(data)
    w = 72
    
    print()
    print(f"{B}╔{'═'*w}╗{X}")
    print(f"{B}║{X}  {BD}{W}🏥 CNV HEALTHCREW AI - CLUSTER HEALTH REPORT{X}".ljust(w+20) + f"{B}║{X}")
    print(f"{B}╠{'═'*w}╣{X}")
    print(f"{B}║{X}  {D}Cluster:{X} {C}{data['cluster']}{X}".ljust(w+25) + f"{B}║{X}")
    print(f"{B}║{X}  {D}Version:{X} {data['version']}   {D}Time:{X} {data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}".ljust(w+15) + f"{B}║{X}")
    print(f"{B}╠{'═'*w}╣{X}")
    
    # Summary line function
    def summary_line(icon, label, ok, value):
        status = f"{G}✓{X}" if ok else f"{R}✗{X}"
        color = G if ok else Y
        print(f"{B}║{X}  {status}  {BD}{label.ljust(22)}{X} {color}{value}{X}".ljust(w+30) + f"{B}║{X}")
    
    # Nodes
    n_ok = len(data["nodes"]["unhealthy"]) == 0
    n_total = len(data["nodes"]["healthy"]) + len(data["nodes"]["unhealthy"])
    summary_line("🖥️", "Nodes", n_ok, f"{len(data['nodes']['healthy'])}/{n_total} Ready")
    
    # Operators
    o_bad = len(data["operators"]["degraded"]) + len(data["operators"]["unavailable"])
    o_total = len(data["operators"]["healthy"]) + o_bad
    summary_line("⚙️", "Cluster Operators", o_bad == 0, f"{len(data['operators']['healthy'])}/{o_total} Available")
    
    # Pods
    p_bad = len(data["pods"]["unhealthy"])
    p_total = data["pods"]["healthy"] + p_bad
    summary_line("📦", "Pods", p_bad == 0, f"{data['pods']['healthy']}/{p_total} Running" + (f" ({R}{p_bad} unhealthy{X})" if p_bad else ""))
    
    # KubeVirt
    if data["kubevirt"]["installed"]:
        kv_ok = data["kubevirt"]["status"] == "Deployed" and len(data["kubevirt"]["failed_vmis"]) == 0
        summary_line("💻", "KubeVirt", kv_ok, f"{data['kubevirt']['status']} ({data['kubevirt']['vms_running']} VMs)")
    
    # Resources
    r_bad = len(data["resources"]["high_cpu"]) + len(data["resources"]["high_memory"])
    summary_line("📊", "Resources", r_bad == 0, "Normal" if r_bad == 0 else f"{r_bad} nodes high usage")
    
    # etcd
    etcd_ok = len(data["etcd"]["unhealthy"]) == 0
    summary_line("🗄️", "etcd", etcd_ok, f"{data['etcd']['healthy']} members healthy" if etcd_ok else f"{len(data['etcd']['unhealthy'])} unhealthy")
    
    # PVCs
    pvc_bad = len(data["pvcs"]["pending"])
    summary_line("💾", "PVCs", pvc_bad == 0, "All Bound" if pvc_bad == 0 else f"{pvc_bad} Pending")
    
    # VM Migrations
    mig_bad = len(data["migrations"]["failed"]) + data["migrations"]["failed_count"]
    mig_run = data["migrations"]["running"]
    summary_line("🔄", "VM Migrations", mig_bad == 0, f"{mig_run} running" if mig_bad == 0 else f"{mig_bad} failed")
    
    # OOM Events
    oom_count = len(data["oom_events"])
    summary_line("💥", "OOM Events", oom_count == 0, "None" if oom_count == 0 else f"{oom_count} recent")
    
    # CSI Drivers
    csi_bad = len(data["csi_issues"])
    summary_line("🔌", "CSI Drivers", csi_bad == 0, "Healthy" if csi_bad == 0 else f"{csi_bad} issues")
    
    # CNV-specific checks
    if data["kubevirt"]["installed"]:
        print(f"{B}╠{'─'*w}╣{X}")
        print(f"{B}║{X}  {BD}{C}CNV/KubeVirt Checks:{X}".ljust(w+25) + f"{B}║{X}")
        
        # virt-handler
        vh_bad = len(data["virt_handler"]["unhealthy"]) + len(data["virt_handler"]["high_memory"])
        summary_line("🔧", "virt-handler", vh_bad == 0, f"{data['virt_handler']['healthy']} healthy" if vh_bad == 0 else f"{vh_bad} issues")
        
        # virt-controller/api
        vc_bad = len(data["virt_ctrl"]["unhealthy"])
        summary_line("🎛️", "virt-controller/api", vc_bad == 0, f"{data['virt_ctrl']['healthy']} healthy" if vc_bad == 0 else f"{vc_bad} unhealthy")
        
        # virt-launcher
        vl_bad = len(data["virt_launcher_bad"])
        summary_line("🚀", "virt-launcher pods", vl_bad == 0, "All healthy" if vl_bad == 0 else f"{vl_bad} issues")
        
        # DataVolumes
        dv_bad = len(data["dv_issues"])
        summary_line("💿", "DataVolumes", dv_bad == 0, "All ready" if dv_bad == 0 else f"{dv_bad} stuck")
        
        # Snapshots
        snap_bad = len(data["snapshot_issues"])
        summary_line("📸", "VolumeSnapshots", snap_bad == 0, "All ready" if snap_bad == 0 else f"{snap_bad} not ready")
        
        # Cordoned nodes with VMs
        cord_bad = len(data["cordoned_vms"])
        summary_line("🚧", "VMs on cordoned nodes", cord_bad == 0, "None" if cord_bad == 0 else f"{cord_bad} VMs at risk")
        
        # Stuck migrations
        stuck_bad = len(data["stuck_migrations"])
        summary_line("⏳", "Stuck migrations", stuck_bad == 0, "None" if stuck_bad == 0 else f"{stuck_bad} stuck")
    
    # Dynamic checks from Jira (if any)
    if data.get("dynamic_checks"):
        print(f"{B}╠{'─'*w}╣{X}")
        print(f"{B}║{X}  {BD}{C}🆕 Jira-Suggested Checks:{X}".ljust(w+28) + f"{B}║{X}")
        for check_name, check_data in data["dynamic_checks"].items():
            check_has_issues = bool(check_data.get("issues"))
            jira = check_data.get("jira", "")
            desc = check_data.get("description", check_name)[:30]
            summary_line("🔍", f"{check_name} ({jira})", not check_has_issues, "OK" if not check_has_issues else "Issues found")
    
    print(f"{B}╠{'═'*w}╣{X}")
    
    # Issues detail
    if issues:
        print(f"{B}║{X}  {Y}{BD}⚠️  ISSUES DETECTED:{X}".ljust(w+25) + f"{B}║{X}")
        print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
        
        # Unhealthy pods grouped
        if data["pods"]["unhealthy"]:
            by_ns = {}
            for p in data["pods"]["unhealthy"]:
                by_ns.setdefault(p["ns"], []).append(p)
            
            count = 0
            for ns in sorted(by_ns.keys()):
                if count >= 4:
                    remaining = len(data["pods"]["unhealthy"]) - sum(len(by_ns[n]) for n in list(by_ns.keys())[:4])
                    print(f"{B}║{X}    {D}...and {remaining} more unhealthy pods{X}".ljust(w+15) + f"{B}║{X}")
                    break
                print(f"{B}║{X}    {C}{ns}/{X}".ljust(w+20) + f"{B}║{X}")
                for pod in by_ns[ns][:2]:
                    print(f"{B}║{X}      {D}•{X} {pod['name'][:35]} {R}{pod['status']}{X}".ljust(w+25) + f"{B}║{X}")
                if len(by_ns[ns]) > 2:
                    print(f"{B}║{X}      {D}...+{len(by_ns[ns])-2} more{X}".ljust(w+15) + f"{B}║{X}")
                count += 1
        
        # Pending PVCs
        if data["pvcs"]["pending"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Pending PVCs:{X}".ljust(w+20) + f"{B}║{X}")
            for pvc in data["pvcs"]["pending"][:3]:
                print(f"{B}║{X}      {D}•{X} {pvc['ns']}/{pvc['name']}".ljust(w+15) + f"{B}║{X}")
            if len(data["pvcs"]["pending"]) > 3:
                print(f"{B}║{X}      {D}...+{len(data['pvcs']['pending'])-3} more{X}".ljust(w+15) + f"{B}║{X}")
        
        # Failed Migrations
        if data["migrations"]["failed"] or data["migrations"]["failed_count"] > 0:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Failed VM Migrations:{X}".ljust(w+20) + f"{B}║{X}")
            for mig in data["migrations"]["failed"][:3]:
                print(f"{B}║{X}      {D}•{X} {mig['ns']}/{mig['name']}: {R}{mig['phase']}{X}".ljust(w+25) + f"{B}║{X}")
        
        # OOM Events
        if data["oom_events"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Recent OOM Events:{X}".ljust(w+20) + f"{B}║{X}")
            for oom in data["oom_events"][:3]:
                print(f"{B}║{X}      {D}•{X} {oom['ns']}/{oom['object']}".ljust(w+15) + f"{B}║{X}")
        
        # CSI Issues
        if data["csi_issues"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}CSI Driver Issues:{X}".ljust(w+20) + f"{B}║{X}")
            for csi in data["csi_issues"][:3]:
                print(f"{B}║{X}      {D}•{X} {csi['pod']}: {R}{csi['status']}{X}".ljust(w+25) + f"{B}║{X}")
        
        print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
    
    # Footer
    print(f"{B}╠{'═'*w}╣{X}")
    if issues:
        print(f"{B}║{X}  {Y}{BD}STATUS: ATTENTION NEEDED{X}".ljust(w+25) + f"{B}║{X}")
    else:
        print(f"{B}║{X}  {G}{BD}STATUS: CLUSTER HEALTHY ✨{X}".ljust(w+25) + f"{B}║{X}")
    print(f"{B}╚{'═'*w}╝{X}")
    print()
