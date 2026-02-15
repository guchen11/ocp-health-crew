"""
Health Check Engines

This package contains the core health check and scenario implementations:

  - hybrid_health_check: Full-featured SSH-based health check with reports, email,
        Jira RCA, AI deep analysis, auto oc-login, and connection validation
  - cnv_scenarios:       CNV scenario runner — SSH to jump host, runs kube-burner
        workloads via cnv-scenarios/run-workloads.sh
  - cnv_report:          CNV report generator — parses scenario output and builds
        HTML reports (single-task and combined)
  - simple_health_check: Minimal SSH health check (no AI, no web dependencies)
  - crewai_agents:       CrewAI-based multi-agent health check system (experimental)
"""
