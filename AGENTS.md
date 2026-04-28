# Project Instructions

## Project Overview

OCP Health Crew is a Flask-based web application that runs health checks against OpenShift Container Platform (OCP) clusters. It connects to clusters via SSH, executes `oc` / `kubectl` / `virtctl` commands, and presents results through a web dashboard. It includes specialized checks for CNV (Container-Native Virtualization), storage (ODF/Ceph), networking, and general cluster health.

## Tech Stack

- **Language:** Python 3
- **Framework:** Flask (with Jinja2 templates)
- **Dependencies:** managed via `requirements.txt` (pip)
- **Remote access:** SSH to bastion/cluster nodes
- **CLI tools:** `oc`, `kubectl`, `virtctl` (executed remotely)

## Development Conventions

- Follow rules in `.cursor/rules/` (code-quality, error-handling, git-safety, KISS, security-ssh, etc.)
- Max 500 lines per file, 50 lines per function, 3 levels of nesting
- No secrets in code or config files
- Shell commands use subprocess with list args (never string interpolation)
- No inline scripts via SSH - use separate script files
- Error messages include: what happened, where, why, how to fix

## Agent Configuration

Shared agent configuration is located in `.agents/`:

- `.agents/CYNEFIN.md` - Problem classification framework
- `.agents/PERSONALITY.md` - Shared agent values and behavioral commitments
- `.agents/LESSONS.md` - Lessons learned from past sessions (index)
- `.agents/lessons/` - Themed lesson files (architecture, code-quality, communication, implementation, process, security)
- `.agents/REQUIREMENTS.md` - Non-negotiable project requirements (index)
- `.agents/SECURITY_REVIEW_CHECKLIST.md` - Security review process for external context files
- `.agents/pipelines/` - Pipeline process definitions (SDLC, Jira, Skill Generation)
- `.agents/requirements/` - Individual requirement definitions (REQ-001 through REQ-009)
- `.agents/roles/` - Role-specific instructions for each SDLC gate

Platform-specific configuration:

- `.claude/` - Claude Code skills and settings
- `.cursor/rules/` - Cursor IDE rules (project-scoped SDLC rules + global quality rules)
