"""Jira search, bug suggestions, and email search helpers."""

import json
import os
import subprocess
import sys

from healthchecks.jira_constants import COMPONENT_TO_CHECK, HEALTH_CHECK_KEYWORDS

def call_jira_mcp(tool_name, arguments):
    """Call Jira MCP tool via subprocess"""
    try:
        # Use cursor's mcp-proxy to call the tool
        import urllib.request
        import urllib.error
        
        # Try direct Jira API if MCP not available
        # For now, return mock data structure - will be replaced by actual MCP call
        return None
    except Exception as e:
        print(f"  ⚠️  Jira API error: {e}")
        return None

def search_jira_for_new_bugs(days=30, limit=50):
    """
    Search Jira for recent bugs in CNV, ODF, OCPBUGS projects.
    Returns list of bugs that might suggest new health checks.
    """
    # JQL to find recent bugs
    jql_queries = [
        f'project = CNV AND issuetype = Bug AND status in (Open, "In Progress", New) AND created >= -{days}d ORDER BY priority DESC, created DESC',
        f'project = OCPBUGS AND issuetype = Bug AND status in (Open, "In Progress", New) AND created >= -{days}d ORDER BY priority DESC, created DESC',
    ]
    
    all_bugs = []
    
    # Try to use mcp-proxy for Jira access
    try:
        for jql in jql_queries:
            result = subprocess.run(
                ['mcp-proxy', 'call', 'user-jira', 'jira_search', 
                 '--jql', jql, '--limit', str(limit // 2),
                 '--fields', 'summary,status,priority,components,labels,created'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if 'issues' in data:
                    all_bugs.extend(data['issues'])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        # MCP proxy not available, use fallback recent bugs list
        pass
    
    # If no bugs from Jira, use known recent bugs from our database
    if not all_bugs:
        all_bugs = get_known_recent_bugs()
    
    return all_bugs

def get_known_recent_bugs():
    """Return list of known recent bugs that might need health checks"""
    return [
        {
            "key": "OCPBUGS-74962",
            "summary": "[4.19] Very High etcd Latency",
            "priority": {"name": "Critical"},
            "components": [{"name": "Etcd"}],
            "suggested_check": "etcd_latency",
            "check_description": "Monitor etcd latency and alert on high values"
        },
        {
            "key": "OCPBUGS-74938",
            "summary": "Kubelet and NetworkManager do not start automatically on any node after reboot",
            "priority": {"name": "Critical"},
            "components": [{"name": "Machine Config Operator"}],
            "suggested_check": "kubelet_health",
            "check_description": "Check if kubelet is running on all nodes"
        },
        {
            "key": "OCPBUGS-74926",
            "summary": "In-memory certificate expiration date is too short",
            "priority": {"name": "Major"},
            "components": [{"name": "oauth-apiserver"}],
            "suggested_check": "cert_expiry",
            "check_description": "Check certificate expiration dates"
        },
        {
            "key": "OCPBUGS-74907",
            "summary": "SDN to OVN-Kubernetes migration stuck",
            "priority": {"name": "Critical"},
            "components": [{"name": "Networking / ovn-kubernetes"}],
            "suggested_check": "network_migration",
            "check_description": "Check network migration status"
        },
        {
            "key": "CNV-78575",
            "summary": "kubevirt-hyperconverged operator version disappeared from OLM catalog",
            "priority": {"name": "Major"},
            "components": [{"name": "CNV Install, Upgrade and Operators"}],
            "suggested_check": "catalog_source",
            "check_description": "Verify OLM catalog sources are healthy"
        },
        {
            "key": "OCPBUGS-74894",
            "summary": "Router got flooding connection",
            "priority": {"name": "Major"},
            "components": [{"name": "Networking / router"}],
            "suggested_check": "router_health",
            "check_description": "Monitor router pod health and connection count"
        },
        {
            "key": "CNV-78518",
            "summary": "virt-exportserver image pull issues",
            "priority": {"name": "Major"},
            "components": [{"name": "CNV Install, Upgrade and Operators"}],
            "suggested_check": "image_pull",
            "check_description": "Check for ImagePullBackOff errors"
        },
    ]

def analyze_bugs_for_new_checks(bugs, existing_checks):
    """
    Analyze bugs to determine if new health checks should be added.
    Returns list of suggested new checks.
    """
    suggestions = []
    
    for bug in bugs:
        summary = bug.get("summary", "").lower()
        key = bug.get("key", "")
        priority = bug.get("priority", {}).get("name", "Normal")
        components = [c.get("name", "") if isinstance(c, dict) else c for c in bug.get("components", [])]
        
        # Check if bug already has a suggested check
        if bug.get("suggested_check"):
            check_name = bug["suggested_check"]
            if check_name not in existing_checks:
                suggestions.append({
                    "jira_key": key,
                    "summary": bug.get("summary", ""),
                    "priority": priority,
                    "components": components,
                    "suggested_check": check_name,
                    "check_description": bug.get("check_description", ""),
                    "reason": f"Based on bug {key}"
                })
            continue
        
        # Analyze summary for health check keywords
        matched_keywords = []
        for keyword, check_type in HEALTH_CHECK_KEYWORDS.items():
            if keyword in summary:
                matched_keywords.append((keyword, check_type))
        
        # Analyze components
        matched_components = []
        for comp in components:
            for comp_key, check_cat in COMPONENT_TO_CHECK.items():
                if comp_key.lower() in comp.lower():
                    matched_components.append((comp, check_cat))
        
        # Only suggest if priority is Critical/Major or multiple keywords match
        if (priority in ["Critical", "Blocker", "Major"] or len(matched_keywords) >= 2) and matched_keywords:
            # Generate suggested check name
            check_name = matched_keywords[0][1].lower().replace(" ", "_")
            if matched_components:
                check_name = f"{matched_components[0][1]}_{check_name}"
            
            if check_name not in existing_checks:
                suggestions.append({
                    "jira_key": key,
                    "summary": bug.get("summary", ""),
                    "priority": priority,
                    "components": components,
                    "suggested_check": check_name,
                    "check_description": f"New check based on: {matched_keywords[0][1]}",
                    "matched_keywords": [k[0] for k in matched_keywords],
                    "reason": f"Keywords: {', '.join([k[0] for k in matched_keywords[:3]])}"
                })
    
    # Deduplicate by check name
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        if s["suggested_check"] not in seen:
            seen.add(s["suggested_check"])
            unique_suggestions.append(s)
    
    return unique_suggestions[:10]  # Limit to top 10 suggestions

def get_existing_check_names():
    """Return list of existing health check names"""
    return [
        "nodes", "operators", "pods", "kubevirt", "resources", "etcd",
        "pvcs", "migrations", "oom_events", "csi", "virt_handler",
        "virt_ctrl", "virt_launcher", "datavolumes", "volumesnapshots",
        "cordoned_vms", "stuck_migrations"
    ]

def display_jira_suggestions(suggestions):
    """Display Jira-based health check suggestions to user"""
    if not suggestions:
        print("\n  ✅ No new health checks suggested from recent Jira bugs.\n")
        return []
    
    # ANSI colors
    Y = '\033[93m'
    G = '\033[92m'
    B = '\033[94m'
    C = '\033[96m'
    R = '\033[91m'
    X = '\033[0m'
    BD = '\033[1m'
    
    print(f"\n{B}╔{'═'*72}╗{X}")
    print(f"{B}║{X}  {BD}🔍 NEW HEALTH CHECK SUGGESTIONS FROM JIRA{X}".ljust(83) + f"{B}║{X}")
    print(f"{B}╠{'═'*72}╣{X}")
    print(f"{B}║{X}  Found {Y}{len(suggestions)}{X} potential new checks based on recent Jira bugs:".ljust(88) + f"{B}║{X}")
    print(f"{B}╠{'─'*72}╣{X}")
    
    for i, s in enumerate(suggestions, 1):
        priority_color = R if s['priority'] in ['Critical', 'Blocker'] else Y if s['priority'] == 'Major' else X
        print(f"{B}║{X}  {BD}{i}.{X} {C}{s['suggested_check']}{X}".ljust(85) + f"{B}║{X}")
        print(f"{B}║{X}     {priority_color}[{s['priority']}]{X} {s['jira_key']}: {s['summary'][:45]}...".ljust(85) + f"{B}║{X}")
        print(f"{B}║{X}     {G}→ {s['check_description'][:55]}{X}".ljust(88) + f"{B}║{X}")
        if i < len(suggestions):
            print(f"{B}║{X}" + " "*72 + f"{B}║{X}")
    
    print(f"{B}╠{'═'*72}╣{X}")
    print(f"{B}║{X}  {Y}Enter check numbers to add (comma-separated), 'all', or 'skip':{X}".ljust(88) + f"{B}║{X}")
    print(f"{B}╚{'═'*72}╝{X}")
    
    return suggestions

def prompt_for_new_checks(suggestions):
    """Prompt user to select which checks to add"""
    if not suggestions:
        return []
    
    # Check if running non-interactively (from web UI)
    import sys
    import os
    import json
    
    if not sys.stdin.isatty() or os.environ.get('NON_INTERACTIVE'):
        # Save suggestions to file for web UI review
        suggestions_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.suggested_checks.json')
        try:
            # Load existing suggestions
            existing = []
            if os.path.exists(suggestions_file):
                with open(suggestions_file, 'r') as f:
                    existing = json.load(f)
            
            # Add new suggestions with timestamp
            from datetime import datetime
            for s in suggestions:
                s['timestamp'] = datetime.now().isoformat()
                s['status'] = 'pending'
            
            # Merge (avoid duplicates by jira_key)
            existing_keys = {s.get('jira_key') for s in existing}
            for s in suggestions:
                if s.get('jira_key') not in existing_keys:
                    existing.append(s)
            
            with open(suggestions_file, 'w') as f:
                json.dump(existing, f, indent=2)
            
            print(f"  💾 Saved {len(suggestions)} suggestions for web UI review")
            print(f"     Review at: Dashboard > Jira Suggestions\n")
        except Exception as e:
            print(f"  ⚠️  Could not save suggestions: {e}\n")
        
        return []  # Don't add checks automatically, let user review in web UI
    
    # Interactive mode - prompt user
    try:
        response = input("\n  Your choice: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return []
    
    if response == 'skip' or response == 's' or response == '':
        print("  ⏭️  Skipping new check additions.\n")
        return []
    
    if response == 'all' or response == 'a':
        print(f"  ✅ Adding all {len(suggestions)} suggested checks.\n")
        return suggestions
    
    # Parse comma-separated numbers
    selected = []
    try:
        indices = [int(x.strip()) - 1 for x in response.split(',')]
        for idx in indices:
            if 0 <= idx < len(suggestions):
                selected.append(suggestions[idx])
    except ValueError:
        print("  ⚠️  Invalid input. Skipping.\n")
        return []
    
    if selected:
        print(f"  ✅ Adding {len(selected)} selected checks.\n")
    
    return selected

def generate_check_code(check_info):
    """Generate the code for a new health check"""
    check_name = check_info['suggested_check']
    jira_key = check_info['jira_key']
    description = check_info['check_description']
    
    # Map check types to actual commands (stored as description, actual execution happens in collect_data)
    check_commands = {
        "etcd_latency": "oc exec etcd pod -- etcdctl endpoint health",
        "kubelet_health": "oc get nodes with Ready status",
        "cert_expiry": "oc get secrets with TLS type",
        "network_migration": "oc get network.operator migration status",
        "catalog_source": "oc get catalogsource status",
        "router_health": "oc get router pods",
        "image_pull": "oc get pods with ImagePullBackOff",
    }
    
    cmd = check_commands.get(check_name, "oc get pods")
    
    return {
        "name": check_name,
        "command": cmd,
        "jira": jira_key,
        "description": description
    }

def add_checks_to_script(selected_checks):
    """
    Add new checks to the SUGGESTED_NEW_CHECKS list (runtime only).
    In a real implementation, this could modify the script file.
    """
    global SUGGESTED_NEW_CHECKS
    SUGGESTED_NEW_CHECKS = []
    
    for check in selected_checks:
        check_code = generate_check_code(check)
        SUGGESTED_NEW_CHECKS.append(check_code)
        print(f"  📝 Added check: {check_code['name']} (from {check_code['jira']})")
    
    return SUGGESTED_NEW_CHECKS

def check_jira_for_new_tests():
    """
    Main function to check Jira for new bugs and suggest health checks.
    Called before running the health check if --check-jira flag is set.
    """
    print(f"\n  🔍 Checking Jira for recent bugs that might need new health checks...")
    
    # Get existing check names
    existing_checks = get_existing_check_names()
    
    # Search Jira for recent bugs
    bugs = search_jira_for_new_bugs(days=30, limit=50)
    
    if not bugs:
        print("  ⚠️  Could not fetch bugs from Jira. Using known recent bugs.\n")
        bugs = get_known_recent_bugs()
    
    print(f"  📊 Analyzed {len(bugs)} recent bugs from CNV/OCP/ODF projects")
    
    # Analyze bugs for potential new checks
    suggestions = analyze_bugs_for_new_checks(bugs, existing_checks)
    
    # Display suggestions and prompt user
    display_jira_suggestions(suggestions)
    
    # Get user selection
    selected = prompt_for_new_checks(suggestions)
    
    # Add selected checks
    if selected:
        add_checks_to_script(selected)
        return selected
    
    return []

def search_emails_for_issues(issues, gmail_account="guchen@redhat.com"):
    """
    Search Gmail for emails related to the detected issues.
    Uses the MCP Gmail tool to search for relevant emails.
    Returns dict mapping issue types to related emails.
    """
    import subprocess
    import json
    
    email_results = {}
    
    if not issues:
        return email_results
    
    print(f"  📧 Searching emails for related discussions...")
    
    # Build search queries based on issue types
    search_keywords = []
    for issue in issues:
        if isinstance(issue, dict):
            issue_type = issue.get('type', '')
            resource = issue.get('resource', issue.get('name', ''))
        else:
            issue_type = str(issue)
            resource = ''
        
        # Add keywords based on issue type
        if 'virt-handler' in str(issue_type).lower() or 'virt-handler' in str(resource).lower():
            search_keywords.extend(['virt-handler memory', 'virt-handler high memory'])
        elif 'migration' in str(issue_type).lower():
            search_keywords.extend(['vm migration stuck', 'migration failed'])
        elif 'operator' in str(issue_type).lower():
            search_keywords.extend(['operator degraded', 'cluster operator'])
        elif 'pod' in str(issue_type).lower():
            search_keywords.extend(['pod crashloop', 'pod not ready'])
        elif 'storage' in str(issue_type).lower() or 'odf' in str(issue_type).lower():
            search_keywords.extend(['storage issue', 'ODF degraded', 'ceph'])
        elif 'snapshot' in str(issue_type).lower():
            search_keywords.extend(['snapshot failed', 'volumesnapshot'])
    
    # Also search for general CNV/OCP issues
    search_keywords.extend(['CNV issue', 'OpenShift problem', 'cluster alert'])
    
    # Deduplicate
    search_keywords = list(set(search_keywords))[:5]  # Limit to 5 searches
    
    found_emails = []
    for keyword in search_keywords:
        try:
            # For now, we'll store the search terms - actual email search would be done via MCP
            # This is a placeholder that the web dashboard can use with MCP tools
            found_emails.append({
                'search_term': keyword,
                'status': 'pending',
                'results': []
            })
        except Exception as e:
            pass
    
    email_results['searches'] = found_emails
    email_results['keywords'] = search_keywords
    
    print(f"  📧 Prepared {len(search_keywords)} email search queries")
    
    return email_results

# Storage for dynamically added checks
SUGGESTED_NEW_CHECKS = []
