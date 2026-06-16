"""API endpoints for perf report inline comments and content editing."""

import json
import os
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from flask_login import current_user

from app.decorators import operator_required
from app.routes import dashboard_bp
from app.routes.perf_reports import _safe_path, PERF_REPORTS_DIR


def _comments_file(report_abs_path):
    """Return the .comments.json path for a given report file."""
    base, _ = os.path.splitext(report_abs_path)
    return base + ".comments.json"


def _load_comments(report_abs_path):
    path = _comments_file(report_abs_path)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_comments(report_abs_path, comments):
    path = _comments_file(report_abs_path)
    with open(path, "w") as f:
        json.dump(comments, f, indent=2)


def _get_author():
    """Get author name from logged-in user or return None."""
    try:
        if current_user and current_user.is_authenticated:
            return current_user.username
    except Exception:
        pass
    return None


@dashboard_bp.route('/perf-reports/api/comments/<path:subpath>', methods=['GET'])
def perf_reports_get_comments(subpath):
    """Return comments JSON for a report."""
    target = _safe_path(subpath.strip("/"))
    if not target or not os.path.isfile(target):
        return jsonify([])
    return jsonify(_load_comments(target))


@dashboard_bp.route('/perf-reports/api/comments/<path:subpath>', methods=['POST'])
def perf_reports_add_comment(subpath):
    """Add a comment to a report (no login required - uses name field)."""
    target = _safe_path(subpath.strip("/"))
    if not target or not os.path.isfile(target):
        return jsonify({"error": "Report not found"}), 404

    data = request.get_json(force=True)
    anchor = data.get("anchor_text", "").strip()
    body = data.get("comment_text", "").strip()
    if not body:
        return jsonify({"error": "Comment text is required"}), 400

    author_name = data.get("author_name", "").strip()
    login_name = _get_author()
    if author_name and login_name:
        author = f"{author_name} ({login_name})"
    elif author_name:
        author = author_name
    elif login_name:
        author = login_name
    else:
        author = "Anonymous"

    comment = {
        "id": str(uuid.uuid4()),
        "author": author,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "anchor_text": anchor,
        "comment_text": body,
    }

    comments = _load_comments(target)
    comments.append(comment)
    _save_comments(target, comments)
    return jsonify(comment), 201


@dashboard_bp.route('/perf-reports/api/comments/<path:subpath>/<comment_id>', methods=['DELETE'])
def perf_reports_delete_comment(subpath, comment_id):
    """Delete a comment by ID."""
    target = _safe_path(subpath.strip("/"))
    if not target or not os.path.isfile(target):
        return jsonify({"error": "Report not found"}), 404

    comments = _load_comments(target)
    original_len = len(comments)
    comments = [c for c in comments if c.get("id") != comment_id]
    if len(comments) == original_len:
        return jsonify({"error": "Comment not found"}), 404

    _save_comments(target, comments)
    return jsonify({"ok": True})


@dashboard_bp.route('/perf-reports/api/comments/<path:subpath>/<comment_id>/reply', methods=['POST'])
def perf_reports_reply_comment(subpath, comment_id):
    """Add a reply to a comment thread."""
    target = _safe_path(subpath.strip("/"))
    if not target or not os.path.isfile(target):
        return jsonify({"error": "Report not found"}), 404

    data = request.get_json(force=True)
    body = data.get("comment_text", "").strip()
    if not body:
        return jsonify({"error": "Reply text is required"}), 400

    author_name = data.get("author_name", "").strip()
    login_name = _get_author()
    if author_name and login_name:
        author = f"{author_name} ({login_name})"
    elif author_name:
        author = author_name
    elif login_name:
        author = login_name
    else:
        author = "Anonymous"

    reply = {
        "id": str(uuid.uuid4()),
        "author": author,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comment_text": body,
    }

    comments = _load_comments(target)
    for c in comments:
        if c.get("id") == comment_id:
            c.setdefault("replies", []).append(reply)
            _save_comments(target, comments)
            return jsonify(reply), 201

    return jsonify({"error": "Comment not found"}), 404


@dashboard_bp.route('/perf-reports/api/comments/<path:subpath>/<comment_id>/resolve', methods=['POST'])
def perf_reports_resolve_comment(subpath, comment_id):
    """Toggle resolved/done status on a comment."""
    target = _safe_path(subpath.strip("/"))
    if not target or not os.path.isfile(target):
        return jsonify({"error": "Report not found"}), 404

    comments = _load_comments(target)
    for c in comments:
        if c.get("id") == comment_id:
            c["resolved"] = not c.get("resolved", False)
            _save_comments(target, comments)
            return jsonify({"ok": True, "resolved": c["resolved"]})

    return jsonify({"error": "Comment not found"}), 404


@dashboard_bp.route('/perf-reports/api/content/<path:subpath>', methods=['PUT'])
def perf_reports_save_content(subpath):
    """Save edited HTML content back to the report file."""
    subpath = subpath.strip("/")
    if not subpath.endswith(".html"):
        return jsonify({"error": "Only HTML files can be saved"}), 400

    target = _safe_path(subpath)
    if not target or not os.path.isfile(target):
        return jsonify({"error": "Report not found"}), 404

    data = request.get_json(force=True)
    content = data.get("content")
    if content is None:
        return jsonify({"error": "Content is required"}), 400

    try:
        with open(target, "r") as f:
            original = f.read()
    except OSError:
        original = ""

    has_full_doc = "<html" in original.lower()[:200]

    if has_full_doc:
        import re
        body_match = re.search(
            r'(<body[^>]*>)(.*?)(</body>)', original, re.DOTALL | re.IGNORECASE
        )
        if body_match:
            new_html = (
                original[:body_match.start(2)] + content + original[body_match.end(2):]
            )
        else:
            new_html = content
    else:
        new_html = content

    with open(target, "w") as f:
        f.write(new_html)

    return jsonify({"ok": True})
