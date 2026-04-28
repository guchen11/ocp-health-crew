"""Parallel deep investigation for RCA (extracted to keep report_generator smaller)."""

import concurrent.futures
import hashlib
import time as _time

from healthchecks.rca_engine import (
    determine_root_cause,
    investigate_issue,
    run_drilldown,
)


def run_deep_investigation(analysis, ssh_command_func, max_unique_types=10):
    """
    Run deep investigation for issues in the analysis.
    OPTIMIZATION: Clusters issues by symptom/type and only investigates ONE
    representative issue per cluster, then applies results to all similar issues.
    """
    # Helper function to get investigation type and context for an item
    def get_inv_info(item):
        failure = item["failure"]
        failure_type = failure.get("type", "")
        details = failure.get("details", {})

        # Determine investigation type based on failure
        if failure_type == "pod":
            status = failure.get("status", "").lower()
            if "crashloop" in status or "error" in status or "init:" in status:
                inv_type = "pod-crashloop"
            elif "unknown" in status or "pending" in status:
                inv_type = "pod-unknown"
            else:
                inv_type = "pod-unknown"

            # Check for specific pod types
            name = failure.get("name", "").lower()
            if "noobaa" in name:
                inv_type = "noobaa"
            elif "metal3" in name:
                inv_type = "metal3"

            # Build context
            if isinstance(details, dict):
                context = {
                    "pod": details.get("name", ""),
                    "ns": details.get("ns", ""),
                    "name": details.get("name", ""),
                }
            else:
                parts = failure.get("name", "").split("/")
                context = {
                    "pod": parts[1] if len(parts) > 1 else parts[0],
                    "ns": parts[0] if len(parts) > 1 else "default",
                    "name": parts[1] if len(parts) > 1 else parts[0],
                }

        elif failure_type == "virt-handler-memory":
            inv_type = "virt-handler-memory"
            context = {}

        elif failure_type == "volumesnapshot":
            inv_type = "volumesnapshot"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"name": first.get("name", ""), "ns": first.get("ns", "")}
            else:
                context = {"name": "", "ns": ""}

        elif failure_type == "etcd":
            inv_type = "etcd"
            context = {}

        elif failure_type in ["migration-failed", "stuck-migration"]:
            inv_type = "migration"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"name": first.get("name", ""), "ns": first.get("ns", ""), "vm": first.get("vm", "")}
            else:
                context = {"name": "", "ns": "", "vm": ""}

        elif failure_type == "csi":
            inv_type = "csi"
            if isinstance(details, dict):
                context = {"pod": details.get("pod", details.get("name", "")), "ns": details.get("ns", "")}
            elif isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"pod": first.get("pod", first.get("name", "")), "ns": first.get("ns", "")}
            else:
                context = {"pod": "", "ns": ""}

        elif failure_type == "oom":
            inv_type = "oom"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"pod": first.get("name", ""), "ns": first.get("ns", "")}
            else:
                context = {"pod": "", "ns": ""}

        elif failure_type in ["operator-degraded", "operator-unavailable"]:
            inv_type = failure_type
            if isinstance(details, list) and details:
                context = {"name": details[0] if isinstance(details[0], str) else str(details[0])}
            else:
                context = {"name": ""}

        elif failure_type == "node":
            inv_type = "node"
            if isinstance(details, list) and details:
                first = details[0]
                if isinstance(first, dict):
                    context = {"name": first.get("name", "")}
                else:
                    context = {"name": str(first)}
            else:
                context = {"name": ""}

        elif failure_type == "alert":
            inv_type = "alert"
            context = {}

        else:
            inv_type = "pod-unknown"
            context = {"pod": "", "ns": "", "name": ""}

        return inv_type, context, failure_type, details

    # Step 1: Group issues by their matched issue title (symptom)
    symptom_groups = {}
    for item in analysis:
        # Use matched issue title as the grouping key
        symptom_key = item.get("matched_issue", {}).get("title", "unknown")
        if symptom_key not in symptom_groups:
            symptom_groups[symptom_key] = []
        symptom_groups[symptom_key].append(item)

    unique_symptoms = len(symptom_groups)
    total_issues = len(analysis)

    print(f"        Found {unique_symptoms} unique issue types across {total_issues} issues", flush=True)
    print(f"        Investigating ONE representative per type (saves {total_issues - unique_symptoms} duplicate investigations)", flush=True)

    # Step 2: Investigate all symptom groups in parallel
    try:
        from healthchecks.ai_analysis import ai_investigate
    except ImportError:
        from ai_analysis import ai_investigate

    groups_to_investigate = list(symptom_groups.items())[:max_unique_types]

    def _investigate_one(idx, symptom_key, items):
        """Investigate a single symptom group. Returns (symptom_key, items) with results attached."""
        tag = f"[{idx+1}/{len(groups_to_investigate)}]"
        representative = items[0]
        inv_type, context, failure_type, details = get_inv_info(representative)

        print(f"        {tag} Investigating: {symptom_key[:50]}... ({len(items)} similar)", flush=True)

        investigation_results = investigate_issue(inv_type, context, ssh_command_func)
        if not investigation_results:
            return symptom_key, items

        rc_tuple = determine_root_cause(inv_type, investigation_results, details)
        root_cause, confidence, explanation = rc_tuple[0], rc_tuple[1], rc_tuple[2]
        matched_rule = rc_tuple[4] if len(rc_tuple) > 4 else None

        inv_id = hashlib.md5(f"{symptom_key}".encode()).hexdigest()[:8]
        drilldown_results = []
        drilldown_conclusion = None
        followup_results = []
        followup_conclusion = None
        next_steps = []

        if matched_rule and matched_rule.get("is_symptom") and matched_rule.get("drilldown"):
            drilldown_key = matched_rule["drilldown"]
            print(f"        {tag} ↳ Symptom, drilling down: {drilldown_key}", flush=True)

            dd_results, dd_conclusion = run_drilldown(drilldown_key, context, ssh_command_func)
            drilldown_results = dd_results

            if dd_conclusion:
                drilldown_conclusion = dd_conclusion
                root_cause = dd_conclusion["conclusion"]
                confidence = dd_conclusion["confidence"]
                explanation = dd_conclusion.get("fix", explanation)
                print(f"        {tag} ✓ Drilldown: {root_cause[:60]}", flush=True)

                follow = dd_conclusion.get("follow_drilldown")
                if follow and follow != drilldown_key:
                    dd2_results, dd2_conclusion = run_drilldown(follow, context, ssh_command_func)
                    drilldown_results.extend(dd2_results)
                    if dd2_conclusion:
                        root_cause = dd2_conclusion["conclusion"]
                        confidence = dd2_conclusion["confidence"]
                        explanation = dd2_conclusion.get("fix", explanation)
                        drilldown_conclusion = dd2_conclusion
            else:
                print(f"        {tag} ⚠ Drilldown inconclusive", flush=True)

            next_steps = matched_rule.get("next_steps", [])

        issue_obj = representative.get("matched_issue", {})
        inv_cmds = issue_obj.get("investigation_commands", [])
        jira_refs = issue_obj.get("jira", [])
        print(f"        {tag} ↳ AI investigating...", flush=True)
        fu_results, fu_conclusion = ai_investigate(
            issue_title=issue_obj.get("title", symptom_key),
            issue_desc=issue_obj.get("description", ""),
            failure=representative["failure"],
            investigation_results=investigation_results,
            drilldown_results=drilldown_results,
            drilldown_conclusion=drilldown_conclusion,
            ssh_command_func=ssh_command_func,
            matched_inv_commands=inv_cmds if inv_cmds else None,
            jira_refs=jira_refs if jira_refs else None,
        )
        followup_results = fu_results
        if fu_conclusion:
            followup_conclusion = fu_conclusion
            root_cause = fu_conclusion["conclusion"]
            confidence = fu_conclusion["confidence"]
            explanation = fu_conclusion.get("fix", explanation)
            print(f"        {tag} ✓ AI verified: {root_cause[:70]}", flush=True)
            if fu_conclusion.get("needs_manual"):
                next_steps = [fu_conclusion["needs_manual"]]
        elif fu_results:
            print(f"        {tag} ✓ AI collected {len(fu_results)} checks", flush=True)
        else:
            print(f"        {tag} ⚠ AI skipped (no API key)", flush=True)

        for item in items:
            item["investigation"] = investigation_results
            item["determined_cause"] = {
                "cause": root_cause,
                "confidence": confidence,
                "explanation": explanation,
                "investigation_id": inv_id,
                "shared_with": len(items) - 1,
            }
            if drilldown_results:
                item["drilldown"] = {"results": drilldown_results, "conclusion": drilldown_conclusion}
            if followup_results:
                item["followup"] = {"results": followup_results, "conclusion": followup_conclusion}
            if next_steps:
                item["determined_cause"]["next_steps"] = next_steps
            if followup_conclusion and followup_conclusion.get("doc"):
                item["determined_cause"]["doc_url"] = followup_conclusion["doc"]
            elif drilldown_conclusion and drilldown_conclusion.get("doc"):
                item["determined_cause"]["doc_url"] = drilldown_conclusion["doc"]

        return symptom_key, items

    # Run all investigations in parallel (max 4 concurrent to avoid SSH/API overload)
    t0 = _time.time()
    max_workers = min(4, len(groups_to_investigate))
    print(f"        ⚡ Running {len(groups_to_investigate)} investigations in parallel (max {max_workers} workers)", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_investigate_one, idx, sk, items): sk
            for idx, (sk, items) in enumerate(groups_to_investigate)
        }
        investigation_count = 0
        for future in concurrent.futures.as_completed(futures):
            sk = futures[future]
            try:
                _, result_items = future.result(timeout=480)
                if result_items and result_items[0].get("investigation"):
                    investigation_count += 1
            except Exception as exc:
                print(f"        ⚠ Investigation failed for {sk[:40]}: {exc}", flush=True)

    elapsed = _time.time() - t0
    if unique_symptoms > max_unique_types:
        print(f"        (Skipped {unique_symptoms - max_unique_types} additional issue types)", flush=True)

    print(f"        Deep investigation complete: {investigation_count} investigations in {elapsed:.0f}s", flush=True)

    return analysis
