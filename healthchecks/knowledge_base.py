"""
Dynamic knowledge base for the RCA pattern engine.

Loads known issues, investigation commands, and bug data from JSON files
in the knowledge/ directory. Supports multiple sources: built-in patterns
shipped with the code, user-added patterns, auto-learned patterns,
Gemini AI suggestions, and Jira scan results.

Each pattern has a 'source' field: "built-in", "user", "learned", "gemini",
or "jira-scan".

Built-in seed dicts for first-run JSON creation live in knowledge_seed_issues.py
and knowledge_seed_bugs.py.
"""

import json
import logging
import os
from datetime import datetime

from healthchecks.knowledge_seed_bugs import _BUILTIN_BUGS
from healthchecks.knowledge_seed_issues import _BUILTIN_INV_COMMANDS, _BUILTIN_SEED

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(_PROJECT_ROOT, "knowledge")
KNOWN_ISSUES_FILE = os.path.join(KNOWLEDGE_DIR, "known_issues.json")
KNOWN_BUGS_FILE = os.path.join(KNOWLEDGE_DIR, "known_bugs.json")
ROOT_CAUSE_RULES_FILE = os.path.join(KNOWLEDGE_DIR, "root_cause_rules.json")


def _ensure_dir():
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)


def _write_json(path, data):
    _ensure_dir()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_known_issues():
    """Load all known issue patterns from the JSON knowledge base.

    Returns a dict keyed by issue ID. Each entry has the original fields
    (pattern, jira, title, description, root_cause, suggestions, verify_cmd)
    plus: source, confidence, created, last_matched, investigation_commands.

    If the JSON file doesn't exist yet, it is seeded from the hardcoded
    dicts in hybrid_health_check.py (backward compatibility).
    """
    if not os.path.exists(KNOWN_ISSUES_FILE):
        _seed_known_issues()
    try:
        with open(KNOWN_ISSUES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load %s: %s", KNOWN_ISSUES_FILE, exc)
        return {}


def load_known_bugs():
    """Load the Jira bug cache from JSON.

    Returns a dict keyed by Jira key (e.g. "CNV-66551").
    """
    if not os.path.exists(KNOWN_BUGS_FILE):
        _seed_known_bugs()
    try:
        with open(KNOWN_BUGS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load %s: %s", KNOWN_BUGS_FILE, exc)
        return {}


def load_root_cause_rules():
    """Load root cause determination rules from JSON.

    Returns a dict keyed by rule ID. Each entry has: issue_types,
    keywords_all, keywords_any, cause, confidence, explanation,
    source, created, last_matched. Optional: extra_required,
    extra_required_any, special.
    """
    if not os.path.exists(ROOT_CAUSE_RULES_FILE):
        logger.warning("No %s found - determine_root_cause() will use empty ruleset", ROOT_CAUSE_RULES_FILE)
        return {}
    try:
        with open(ROOT_CAUSE_RULES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load %s: %s", ROOT_CAUSE_RULES_FILE, exc)
        return {}


def save_root_cause_rule(key, entry):
    """Add or update a single root cause rule and persist to disk."""
    rules = load_root_cause_rules()
    rules[key] = entry
    _write_json(ROOT_CAUSE_RULES_FILE, rules)
    logger.info("Saved root cause rule '%s' (source=%s)", key, entry.get("source"))


def delete_root_cause_rule(key):
    """Remove a root cause rule. Returns True if deleted."""
    rules = load_root_cause_rules()
    if key in rules:
        del rules[key]
        _write_json(ROOT_CAUSE_RULES_FILE, rules)
        return True
    return False


def update_root_cause_rule_matched(key):
    """Update the last_matched timestamp for a root cause rule."""
    rules = load_root_cause_rules()
    if key in rules:
        rules[key]["last_matched"] = datetime.now().isoformat()
        _write_json(ROOT_CAUSE_RULES_FILE, rules)


def load_investigation_commands():
    """Return a dict mapping issue-type keys to investigation command lists.

    Built from known_issues.json: each pattern that has an
    investigation_commands field is indexed by the issue key *and* by
    the inv_type value it maps to. Also includes built-in commands for
    issue types that are not knowledge-base entries (e.g. pod-crashloop).
    """
    inv = dict(_BUILTIN_INV_COMMANDS)
    issues = load_known_issues()
    for key, entry in issues.items():
        cmds = entry.get("investigation_commands")
        if cmds:
            inv[key] = cmds
            inv_type = entry.get("inv_type")
            if inv_type and inv_type != key:
                inv[inv_type] = cmds
    return inv


# ---------------------------------------------------------------------------
# Saving / mutating
# ---------------------------------------------------------------------------

def save_known_issue(key, entry):
    """Add or update a single known-issue pattern and persist to disk."""
    issues = load_known_issues()
    if key in issues and issues[key].get("source") == "built-in" and entry.get("source") != "built-in":
        entry["overrides_built_in"] = True
    issues[key] = entry
    _write_json(KNOWN_ISSUES_FILE, issues)
    logger.info("Saved known issue '%s' (source=%s)", key, entry.get("source"))


def save_known_bug(jira_key, bug_data):
    """Add or update a single Jira bug entry and persist to disk."""
    bugs = load_known_bugs()
    bug_data["last_updated"] = datetime.now().isoformat()
    bugs[jira_key] = bug_data
    _write_json(KNOWN_BUGS_FILE, bugs)


def delete_known_issue(key):
    """Remove a known-issue pattern. Returns True if deleted."""
    issues = load_known_issues()
    if key in issues:
        del issues[key]
        _write_json(KNOWN_ISSUES_FILE, issues)
        return True
    return False


def delete_known_bug(jira_key):
    """Remove a bug entry. Returns True if deleted."""
    bugs = load_known_bugs()
    if jira_key in bugs:
        del bugs[jira_key]
        _write_json(KNOWN_BUGS_FILE, bugs)
        return True
    return False


def update_last_matched(key):
    """Update the last_matched timestamp for a pattern."""
    issues = load_known_issues()
    if key in issues:
        issues[key]["last_matched"] = datetime.now().isoformat()
        _write_json(KNOWN_ISSUES_FILE, issues)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats():
    """Return summary stats for the knowledge base."""
    issues = load_known_issues()
    bugs = load_known_bugs()
    rc_rules = load_root_cause_rules()
    by_source = {}
    for entry in issues.values():
        src = entry.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
    rc_by_source = {}
    for entry in rc_rules.values():
        src = entry.get("source", "unknown")
        rc_by_source[src] = rc_by_source.get(src, 0) + 1
    return {
        "total_patterns": len(issues),
        "total_bugs": len(bugs),
        "total_root_cause_rules": len(rc_rules),
        "by_source": by_source,
        "rc_rules_by_source": rc_by_source,
    }


# ---------------------------------------------------------------------------
# Duplicate detection (for Gemini / learning suggestions)
# ---------------------------------------------------------------------------

def pattern_exists(keywords):
    """Check if a pattern with similar keywords already exists.

    Returns the key of the existing pattern if >= 60% keyword overlap,
    else None.
    """
    if not keywords:
        return None
    kw_set = set(k.lower() for k in keywords)
    issues = load_known_issues()
    for key, entry in issues.items():
        existing_kw = set(k.lower() for k in entry.get("pattern", []))
        if not existing_kw:
            continue
        overlap = len(kw_set & existing_kw) / max(len(kw_set), len(existing_kw))
        if overlap >= 0.6:
            return key
    return None



# ---------------------------------------------------------------------------
# Seeding (first-run only)
# ---------------------------------------------------------------------------


def _seed_known_issues():
    """Generate known_issues.json from the built-in seed data on first run."""
    now = datetime.now().isoformat()
    merged = {}
    for key, entry in _BUILTIN_SEED.items():
        merged[key] = {
            **entry,
            "source": "built-in",
            "confidence": 1.0,
            "created": now,
            "last_matched": None,
        }

    _write_json(KNOWN_ISSUES_FILE, merged)
    logger.info("Seeded %s with %d built-in patterns", KNOWN_ISSUES_FILE, len(merged))


def _seed_known_bugs():
    """Generate known_bugs.json from built-in Jira metadata."""
    now = datetime.now().isoformat()
    bugs = {}
    for jira_key, data in _BUILTIN_BUGS.items():
        bugs[jira_key] = {**data, "source": "built-in", "last_updated": now}
    _write_json(KNOWN_BUGS_FILE, bugs)
    logger.info("Seeded %s with %d built-in bugs", KNOWN_BUGS_FILE, len(bugs))
