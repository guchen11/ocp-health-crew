#!/usr/bin/env python3
"""
CrewAI-based multi-agent health check system.

Uses AI agents (Infrastructure SRE, Virtualization Specialist, Performance Auditor)
to run oc commands via SSH and produce a Markdown health report.

Usage:
    python healthchecks/crewai_agents.py
"""

import os
import sys
from datetime import datetime

# Ensure project root is in path (for `tools` package)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import Agent, Task, Crew, Process, LLM
from tools.ssh_tool import RemoteOCPTool

# Initialize the Tool
ocp_tool = RemoteOCPTool()

# Initialize Ollama LLM (local - 3B model, balance of speed and capability)
ollama_llm = LLM(
    model="ollama/llama3.2:3b",
    base_url="http://localhost:11434"
)

# --- 1. DEFINE THE AGENTS ---

infra_agent = Agent(
    role='Infrastructure SRE',
    goal='Ensure OpenShift nodes and ClusterOperators are healthy.',
    backstory='You are a strict SRE. You verify node status and check if any operator is degraded.',
    tools=[ocp_tool],
    verbose=True,
    memory=True,
    llm=ollama_llm
)

cnv_agent = Agent(
    role='Virtualization Specialist',
    goal='Audit the CNV/KubeVirt subsystem health.',
    backstory='You specialize in OpenShift Virtualization. You check for failed VirtualMachineInstances (VMIs) and the kubevirt operator.',
    tools=[ocp_tool],
    verbose=True,
    memory=True,
    llm=ollama_llm
)

perf_agent = Agent(
    role='Performance Auditor',
    goal='Identify resource bottlenecks in the cluster.',
    backstory='You analyze `oc adm top` data to find overloaded nodes (CPU/RAM > 85%).',
    tools=[ocp_tool],
    verbose=True,
    memory=True,
    llm=ollama_llm
)

# --- 2. DEFINE THE TASKS ---

task_infra = Task(
    description=(
        "1. Execute 'oc get nodes'. List any node NOT in 'Ready' state.\n"
        "2. Execute 'oc get co'. List any operator that is 'Degraded' or not 'Available'."
    ),
    expected_output="A summary of unhealthy nodes/operators, or confirmation that the cluster is healthy.",
    agent=infra_agent
)

task_cnv = Task(
    description=(
        "1. Run 'oc get kubevirt -A' to check the operator status.\n"
        "2. Run 'oc get vmi -A' to list VMIs. Identify any in 'Failed' or 'Error' state."
    ),
    expected_output="Status of the KubeVirt operator and any failed VMs.",
    agent=cnv_agent
)

task_perf = Task(
    description=(
        "Run 'oc adm top nodes'. Identify and list any node using >85% CPU or Memory."
    ),
    expected_output="A list of resource-heavy nodes or 'No high load detected'.",
    agent=perf_agent
)

# --- 3. RUN THE CREW ---

crew = Crew(
    agents=[infra_agent, cnv_agent, perf_agent],
    tasks=[task_infra, task_cnv, task_perf],
    process=Process.sequential
)

print("\n🚀 Connecting to Red Hat Scale Lab (guchen@fedora)...")
result = crew.kickoff()

# --- 4. SAVE TO FILE ---

# Create a timestamped filename (e.g., report_2024-10-12_14-30.md)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
filename = f"ocp_report_{timestamp}.md"

# Write the result to the file
with open(filename, "w") as file:
    file.write(str(result))

print("\n\n########################")
print(f"## REPORT SAVED: {filename} ##")
print("########################\n")