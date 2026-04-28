"""Google Gemini API calls for health analysis and pattern/rule suggestions."""
import json
import logging
import os

from healthchecks.ai_prompts import (
    PATTERN_SUGGESTION_PROMPT,
    RC_RULE_SUGGESTION_PROMPT,
    SYSTEM_PROMPT,
    _build_health_summary,
    _build_rule_analysis_summary,
)

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
INVESTIGATE_MODEL = os.getenv("GEMINI_INVESTIGATE_MODEL", "gemini-2.5-pro")


def analyze_with_gemini(data, rule_analysis=None):
    """Send health data to Gemini and return AI-generated RCA markdown.

    Args:
        data: The health check data dict from collect_data().
        rule_analysis: Optional list of dicts from analyze_failures() /
            run_deep_investigation(). When provided, Gemini uses these
            pattern-matched findings as a starting point.

    Returns None if the API key is missing, the SDK is unavailable, or the
    call fails for any reason (never breaks the pipeline).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set - skipping AI analysis")
        return None

    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai package not installed - skipping AI analysis")
        return None

    summary = _build_health_summary(data)
    rule_summary = _build_rule_analysis_summary(rule_analysis) if rule_analysis else ""

    if rule_summary:
        user_prompt = (
            "Analyze the following OpenShift cluster health data and provide a "
            "root cause analysis. A rule-based pattern engine has already produced "
            "initial findings (included below). Use those as a starting point: "
            "confirm or challenge them, identify cross-subsystem correlations the "
            "rules missed, and fill any gaps.\n\n"
            f"{summary}\n\n{rule_summary}"
        )
    else:
        user_prompt = (
            "Analyze the following OpenShift cluster health data and provide a "
            "root cause analysis. Correlate failures, identify the primary root "
            "cause, rank by severity, and give remediation steps.\n\n"
            f"{summary}"
        )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
        return response.text
    except Exception as e:
        logger.warning("Gemini API call failed: %s", e)
        return None


def suggest_new_patterns(data, ai_rca_text, rule_analysis=None):
    """Ask Gemini to suggest new patterns based on its RCA.

    Parses the JSON response, deduplicates against existing patterns,
    and saves new ones to the knowledge base with source="gemini".
    Returns the list of newly added pattern keys, or [].
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not ai_rca_text:
        return []

    try:
        from google import genai
    except ImportError:
        return []

    summary = _build_health_summary(data)
    rule_summary = _build_rule_analysis_summary(rule_analysis) if rule_analysis else ""

    context = (
        f"Health data:\n{summary}\n\n"
        f"Rule-based findings:\n{rule_summary}\n\n"
        f"Your AI RCA:\n{ai_rca_text}\n\n"
        f"{PATTERN_SUGGESTION_PROMPT}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=context,
            config=genai.types.GenerateContentConfig(
                system_instruction="You are a pattern extraction assistant. Return ONLY valid JSON.",
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        suggestions = json.loads(raw)
    except Exception as exc:
        logger.warning("Gemini pattern suggestion failed: %s", exc)
        return []

    if not isinstance(suggestions, list):
        return []

    from healthchecks.knowledge_base import pattern_exists, save_known_issue
    from datetime import datetime as _dt

    added = []
    now = _dt.now().isoformat()
    for s in suggestions[:10]:
        if not isinstance(s, dict) or "key" not in s or "pattern" not in s:
            continue
        keywords = s.get("pattern", [])
        if pattern_exists(keywords):
            continue
        key = f"gemini-{s['key']}"
        entry = {
            "pattern": keywords,
            "jira": [],
            "title": s.get("title", key),
            "description": "AI-suggested pattern from Gemini analysis",
            "root_cause": s.get("root_cause", []),
            "suggestions": s.get("suggestions", []),
            "verify_cmd": "",
            "source": "gemini",
            "confidence": 0.5,
            "created": now,
            "last_matched": None,
            "investigation_commands": [],
        }
        save_known_issue(key, entry)
        added.append(key)
        logger.info("Gemini suggested new pattern: %s", key)

    return added


def suggest_root_cause_rules(data, ai_rca_text, rule_analysis=None):
    """Ask Gemini to suggest new root cause determination rules.

    Saves new rules to root_cause_rules.json with source="gemini".
    Returns list of newly added rule keys, or [].
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not ai_rca_text:
        return []

    try:
        from google import genai
    except ImportError:
        return []

    summary = _build_health_summary(data)
    rule_summary = _build_rule_analysis_summary(rule_analysis) if rule_analysis else ""

    context = (
        f"Health data:\n{summary}\n\n"
        f"Rule-based findings:\n{rule_summary}\n\n"
        f"Your AI RCA:\n{ai_rca_text}\n\n"
        f"{RC_RULE_SUGGESTION_PROMPT}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=context,
            config=genai.types.GenerateContentConfig(
                system_instruction="You are a root cause rule extraction assistant. Return ONLY valid JSON.",
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        suggestions = json.loads(raw)
    except Exception as exc:
        logger.warning("Gemini root cause rule suggestion failed: %s", exc)
        return []

    if not isinstance(suggestions, list):
        return []

    from healthchecks.knowledge_base import load_root_cause_rules, save_root_cause_rule
    from datetime import datetime as _dt

    existing = load_root_cause_rules()
    added = []
    now = _dt.now().isoformat()
    for s in suggestions[:10]:
        if not isinstance(s, dict) or "key" not in s:
            continue
        key = f"gemini-{s['key']}"
        if key in existing:
            continue
        existing_causes = {r.get("cause", "").lower() for r in existing.values()}
        if s.get("cause", "").lower() in existing_causes:
            continue
        entry = {
            "issue_types": s.get("issue_types", []),
            "keywords_all": s.get("keywords_all", []),
            "keywords_any": s.get("keywords_any", []),
            "cause": s.get("cause", key),
            "confidence": s.get("confidence", "medium"),
            "explanation": s.get("explanation", "AI-suggested root cause rule"),
            "source": "gemini",
            "created": now,
            "last_matched": None,
        }
        save_root_cause_rule(key, entry)
        added.append(key)
        logger.info("Gemini suggested new root cause rule: %s", key)

    return added


def _try_repair_json(raw):
    """Attempt to repair truncated JSON from the model (e.g. when max_tokens cuts off mid-response)."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    if open_braces > 0 or open_brackets > 0:
        in_string = False
        escape = False
        for i, c in enumerate(s):
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_string = not in_string
        if in_string:
            s += '"'
        s += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    try:
        last_brace = s.rfind("}")
        if last_brace > 0:
            return json.loads(s[:last_brace + 1])
    except json.JSONDecodeError:
        pass
    return None


def _call_gemini_json(system_prompt, user_prompt, max_tokens=4096, timeout_sec=90):
    """Call Gemini with JSON response mode. Times out after timeout_sec."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
    except ImportError:
        return None

    import concurrent.futures

    def _do_call():
        client = genai.Client(api_key=api_key)
        config_kwargs = {
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "max_output_tokens": max_tokens,
        }
        return client.models.generate_content(
            model=INVESTIGATE_MODEL,
            contents=system_prompt + "\n\n" + user_prompt,
            config=genai.types.GenerateContentConfig(**config_kwargs),
        )

    raw = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_call)
            response = future.result(timeout=timeout_sec)

        raw = getattr(response, "text", None)
        if not raw:
            candidates = getattr(response, "candidates", None)
            if candidates and len(candidates) > 0:
                parts = getattr(candidates[0], "content", None)
                if parts and getattr(parts, "parts", None):
                    for part in parts.parts:
                        t = getattr(part, "text", None)
                        if t and t.strip():
                            raw = t
                            break
            if not raw:
                logger.warning("Gemini returned empty response")
                return None
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except concurrent.futures.TimeoutError:
        logger.warning("Gemini call timed out after %ds", timeout_sec)
        return None
    except json.JSONDecodeError:
        if raw:
            repaired = _try_repair_json(raw)
            if repaired:
                return repaired
        logger.warning("Gemini JSON parse failed: %.300s", raw[:300] if raw else "empty")
        return None
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return None
