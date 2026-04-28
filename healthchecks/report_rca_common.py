"""Shared RCA HTML helpers: palette, escaping."""

_COLOR_HIGH = "#73BF69"
_COLOR_MEDIUM = "#FF9830"
_COLOR_LOW = "#8b949e"
_COLOR_OPEN = "#F2495C"


def confidence_color(conf: str) -> str:
    """Badge color for high / medium / low confidence."""
    if conf == "high":
        return _COLOR_HIGH
    if conf == "medium":
        return _COLOR_MEDIUM
    return _COLOR_LOW


def jira_assessment_badge_style(assessment: str) -> tuple[str, str]:
    """Return (badge_color, badge_bg) for Jira assessment."""
    if assessment == "open":
        return _COLOR_OPEN, "rgba(242,73,92,0.2)"
    if assessment == "regression":
        return _COLOR_MEDIUM, "rgba(255,152,48,0.2)"
    if assessment in ("fixed", "fixed_newer"):
        return _COLOR_HIGH, "rgba(115,191,105,0.2)"
    return _COLOR_LOW, "rgba(139,148,158,0.2)"


def failures_severity_border_color(num_failures: int) -> str:
    """Left border color by number of affected failures."""
    if num_failures > 3:
        return _COLOR_OPEN
    if num_failures > 1:
        return _COLOR_MEDIUM
    return "#FADE2A"


def escape_html_basic(text: str, max_len: int | None = None) -> str:
    """Escape HTML in command/output snippets. Optionally truncate."""
    s = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if max_len is not None:
        return s[:max_len]
    return s
