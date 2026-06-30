"""Performance reports file manager - browse folders, create folders, move files."""

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from flask import jsonify, request, send_from_directory, render_template, session

from app.routes import dashboard_bp
from config.settings import Config

PERF_REPORTS_DIR = Config.PERF_REPORTS_DIR


def _safe_path(relative):
    """Resolve a relative path inside PERF_REPORTS_DIR, reject traversal."""
    clean = os.path.normpath(relative).lstrip("/")
    if clean == ".":
        clean = ""
    full = os.path.realpath(os.path.join(PERF_REPORTS_DIR, clean))
    if not full.startswith(os.path.realpath(PERF_REPORTS_DIR)):
        return None
    return full


def _list_directory(abs_path, rel_prefix=""):
    """Return folders and files for a directory, hiding .recycle-bin."""
    folders = []
    files = []
    for entry in sorted(os.listdir(abs_path)):
        if entry == ".recycle-bin":
            continue
        entry_path = os.path.join(abs_path, entry)
        rel = os.path.join(rel_prefix, entry) if rel_prefix else entry
        if os.path.isdir(entry_path):
            folders.append({"name": entry, "path": rel})
        elif entry.endswith((".html", ".pdf", ".csv", ".json", ".txt")):
            size_bytes = os.path.getsize(entry_path)
            size_kb = round(size_bytes / 1024)
            files.append({"name": entry, "path": rel, "size_kb": size_kb})
    return folders, files


def _all_folders(base, prefix=""):
    """Recursively collect all folder paths relative to base, excluding .recycle-bin."""
    result = []
    try:
        for entry in sorted(os.listdir(base)):
            if entry == ".recycle-bin":
                continue
            full = os.path.join(base, entry)
            if os.path.isdir(full):
                rel = os.path.join(prefix, entry) if prefix else entry
                result.append(rel)
                result.extend(_all_folders(full, rel))
    except OSError:
        pass
    return result


def _render_listing(subpath):
    """Render the folder listing for a given subpath."""
    os.makedirs(PERF_REPORTS_DIR, exist_ok=True)
    target = _safe_path(subpath)
    if not target or not os.path.isdir(target):
        return None

    folders, files = _list_directory(target, subpath)
    all_folders = _all_folders(PERF_REPORTS_DIR)

    breadcrumbs = []
    if subpath:
        parts = subpath.strip("/").split("/")
        for i, part in enumerate(parts):
            breadcrumbs.append({
                "name": part,
                "path": "/".join(parts[:i + 1]),
            })

    bin_path = os.path.join(PERF_REPORTS_DIR, ".recycle-bin")
    bin_items = []
    if os.path.isdir(bin_path):
        for entry in sorted(os.listdir(bin_path)):
            entry_path = os.path.join(bin_path, entry)
            is_dir = os.path.isdir(entry_path)
            size_kb = 0 if is_dir else round(os.path.getsize(entry_path) / 1024)
            bin_items.append({"name": entry, "is_dir": is_dir, "size_kb": size_kb})

    return render_template(
        "perf_reports.html",
        folders=folders,
        files=files,
        all_folders=all_folders,
        current_path=subpath,
        breadcrumbs=breadcrumbs,
        bin_items=bin_items,
    )


@dashboard_bp.route('/perf-reports/', defaults={'subpath': ''})
@dashboard_bp.route('/perf-reports/<path:subpath>')
def perf_reports_catch_all(subpath):
    """Single catch-all: serve files directly, render folder listings."""
    subpath = subpath.strip("/")

    if not subpath:
        return _render_listing("")

    target = _safe_path(subpath)
    if not target:
        return "Not found", 404

    if os.path.isfile(target):
        if target.endswith(".html"):
            return render_template(
                "perf_report_viewer.html",
                report_path=subpath,
                report_name=os.path.basename(target),
            )
        directory = os.path.dirname(target)
        filename = os.path.basename(target)
        return send_from_directory(directory, filename)

    if os.path.isdir(target):
        return _render_listing(subpath)

    return "Not found", 404


@dashboard_bp.route('/perf-reports/raw/<path:subpath>')
def perf_reports_raw(subpath):
    """Serve raw file content (used by viewer to fetch HTML body)."""
    target = _safe_path(subpath)
    if not target or not os.path.isfile(target):
        return "Not found", 404
    directory = os.path.dirname(target)
    filename = os.path.basename(target)
    return send_from_directory(directory, filename)


@dashboard_bp.route('/perf-reports/api/create-folder', methods=['POST'])
def perf_reports_create_folder():
    """Create a new subfolder."""
    data = request.get_json(force=True)
    parent = data.get("parent", "")
    name = data.get("name", "").strip()

    if not name or not re.match(r'^[\w\-. ]+$', name):
        return jsonify({"error": "Invalid folder name"}), 400

    parent_abs = _safe_path(parent)
    if not parent_abs or not os.path.isdir(parent_abs):
        return jsonify({"error": "Parent directory not found"}), 404

    new_dir = os.path.join(parent_abs, name)
    if os.path.exists(new_dir):
        return jsonify({"error": "Folder already exists"}), 409

    os.makedirs(new_dir)
    return jsonify({"ok": True, "path": os.path.join(parent, name) if parent else name})


@dashboard_bp.route('/perf-reports/api/move', methods=['POST'])
def perf_reports_move():
    """Move a file or folder to a different folder."""
    data = request.get_json(force=True)
    source = data.get("source", "").strip()
    destination = data.get("destination", "").strip()

    if not source:
        return jsonify({"error": "Source path required"}), 400

    src_abs = _safe_path(source)
    if not src_abs or not os.path.exists(src_abs):
        return jsonify({"error": "Source not found"}), 404

    dst_dir_abs = _safe_path(destination)
    if not dst_dir_abs or not os.path.isdir(dst_dir_abs):
        return jsonify({"error": "Destination folder not found"}), 404

    basename = os.path.basename(src_abs)
    dst_abs = os.path.join(dst_dir_abs, basename)

    if os.path.dirname(src_abs) == dst_dir_abs:
        return jsonify({"ok": True, "skipped": True, "new_path": source})

    if os.path.exists(dst_abs):
        if os.path.isdir(dst_abs):
            shutil.rmtree(dst_abs)
        else:
            os.remove(dst_abs)

    shutil.move(src_abs, dst_abs)
    return jsonify({"ok": True, "new_path": os.path.join(destination, basename) if destination else basename})


RECYCLE_BIN = os.path.join(PERF_REPORTS_DIR, ".recycle-bin")


@dashboard_bp.route('/perf-reports/api/delete', methods=['POST'])
def perf_reports_delete():
    """Soft-delete: move file/folder to .recycle-bin instead of removing."""
    data = request.get_json(force=True)
    path = data.get("path", "").strip()

    if not path:
        return jsonify({"error": "Path required"}), 400

    abs_path = _safe_path(path)
    if not abs_path or not os.path.exists(abs_path):
        return jsonify({"error": "Not found"}), 404

    os.makedirs(RECYCLE_BIN, exist_ok=True)
    basename = os.path.basename(abs_path)
    dest = os.path.join(RECYCLE_BIN, basename)

    counter = 1
    while os.path.exists(dest):
        name, ext = os.path.splitext(basename)
        dest = os.path.join(RECYCLE_BIN, f"{name}_{counter}{ext}")
        counter += 1

    shutil.move(abs_path, dest)
    return jsonify({"ok": True, "moved_to": ".recycle-bin"})


@dashboard_bp.route('/perf-reports/api/restore', methods=['POST'])
def perf_reports_restore():
    """Restore a file from the recycle bin back to its original location (root)."""
    data = request.get_json(force=True)
    filename = data.get("filename", "").strip()
    destination = data.get("destination", "").strip()

    if not filename:
        return jsonify({"error": "Filename required"}), 400

    src = os.path.join(RECYCLE_BIN, filename)
    if not os.path.exists(src):
        return jsonify({"error": "Not found in recycle bin"}), 404

    dst_dir = _safe_path(destination)
    if not dst_dir or not os.path.isdir(dst_dir):
        return jsonify({"error": "Destination folder not found"}), 404

    dst = os.path.join(dst_dir, filename)
    if os.path.exists(dst):
        return jsonify({"error": f"'{filename}' already exists in destination"}), 409

    shutil.move(src, dst)
    return jsonify({"ok": True})


@dashboard_bp.route('/perf-reports/api/empty-bin', methods=['POST'])
def perf_reports_empty_bin():
    """Permanently delete all items in the recycle bin."""
    if not os.path.isdir(RECYCLE_BIN):
        return jsonify({"ok": True, "deleted": 0})

    count = 0
    for entry in os.listdir(RECYCLE_BIN):
        entry_path = os.path.join(RECYCLE_BIN, entry)
        if os.path.isdir(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)
        count += 1

    return jsonify({"ok": True, "deleted": count})
