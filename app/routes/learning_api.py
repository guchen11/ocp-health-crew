"""Jira suggestions and learning API routes."""
import sys
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required

from config.settings import AVAILABLE_CHECKS

from app.decorators import operator_required

import app.routes as routes_pkg

from app.routes import (
    dashboard_bp,
    load_suggested_checks,
    save_suggested_checks,
)

@dashboard_bp.route('/api/jira/suggestions')
@login_required
def api_jira_suggestions():
    """API endpoint to get Jira-based test suggestions"""
    try:
        sys.path.insert(0, routes_pkg.BASE_DIR)
        from healthchecks.hybrid_health_check import (
            get_known_recent_bugs,
            get_existing_check_names,
            analyze_bugs_for_new_checks,
            search_jira_for_new_bugs
        )
        existing_checks = get_existing_check_names()
        load_suggested_checks()
        accepted_checks = {s['name'] for s in routes_pkg.suggested_checks if s.get('status') == 'accepted'}
        existing_checks.extend(list(accepted_checks))

        try:
            bugs = search_jira_for_new_bugs(days=30, limit=50)
        except Exception:
            bugs = None
        if not bugs:
            bugs = get_known_recent_bugs()

        suggestions = analyze_bugs_for_new_checks(bugs, existing_checks)
        rejected_recently = {
            s['name'] for s in routes_pkg.suggested_checks
            if s.get('status') == 'rejected' and s.get('rejected_at')
        }
        suggestions = [s for s in suggestions if s['suggested_check'] not in rejected_recently]

        # Enrich suggestions with command info
        from healthchecks.hybrid_health_check import generate_check_code
        for s in suggestions:
            check_code = generate_check_code(s)
            s['command'] = check_code.get('command', '')

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions),
            'bugs_analyzed': len(bugs)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'suggestions': []})


@dashboard_bp.route('/api/jira/accept-check', methods=['POST'])
@operator_required
def api_jira_accept_check():
    load_suggested_checks()
    try:
        data = request.get_json() or {}
        check_name = data.get('name', '')
        jira_key = data.get('jira_key', '')
        description = data.get('description', '')
        category = data.get('category', 'Custom')
        if not check_name:
            return jsonify({'success': False, 'error': 'Check name is required'})

        check_record = {
            'name': check_name, 'jira_key': jira_key, 'description': description,
            'category': category, 'status': 'accepted',
            'accepted_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        existing = next((s for s in routes_pkg.suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            routes_pkg.suggested_checks.append(check_record)
        save_suggested_checks()

        AVAILABLE_CHECKS[check_name] = {
            'name': check_name.replace('_', ' ').title(),
            'description': description, 'category': category,
            'default': True, 'jira': jira_key, 'custom': True
        }

        # Also write into the dynamic knowledge base so the RCA pattern
        # engine matches this issue on subsequent runs.
        try:
            from healthchecks.knowledge_base import save_known_issue, pattern_exists
            keywords = [w for w in check_name.replace('_', ' ').lower().split() if len(w) > 2]
            if not pattern_exists(keywords):
                kb_key = f"jira-{check_name}"
                save_known_issue(kb_key, {
                    'pattern': keywords,
                    'jira': [jira_key] if jira_key else [],
                    'title': check_name.replace('_', ' ').title(),
                    'description': description,
                    'root_cause': [f'Related to {jira_key}'] if jira_key else [],
                    'suggestions': [f'See {jira_key} for details'] if jira_key else [],
                    'verify_cmd': '',
                    'source': 'jira-scan',
                    'confidence': 0.7,
                    'created': datetime.now().isoformat(),
                    'last_matched': None,
                    'investigation_commands': [],
                })
        except Exception:
            pass

        return jsonify({'success': True, 'message': f'Check "{check_name}" added successfully', 'check': check_record})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/reject-check', methods=['POST'])
@operator_required
def api_jira_reject_check():
    load_suggested_checks()
    try:
        data = request.get_json() or {}
        check_name = data.get('name', '')
        if not check_name:
            return jsonify({'success': False, 'error': 'Check name is required'})

        check_record = {'name': check_name, 'status': 'rejected', 'rejected_at': datetime.now().strftime('%Y-%m-%d %H:%M')}
        existing = next((s for s in routes_pkg.suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            routes_pkg.suggested_checks.append(check_record)
        save_suggested_checks()
        return jsonify({'success': True, 'message': f'Check "{check_name}" rejected'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/accepted-checks')
@login_required
def api_jira_accepted_checks():
    load_suggested_checks()
    accepted = [s for s in routes_pkg.suggested_checks if s.get('status') == 'accepted']
    return jsonify({'success': True, 'checks': accepted, 'count': len(accepted)})


# =============================================================================
# LEARNING & PATTERNS API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/learning/stats')
@login_required
def api_learning_stats():
    try:
        from app.learning import get_learning_stats, get_issue_trends, get_recurring_issues
        stats = get_learning_stats()
        trends = get_issue_trends(days=7)
        recurring = get_recurring_issues(min_count=2)
        return jsonify({'success': True, 'stats': stats, 'trends': trends, 'recurring_count': len(recurring)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/patterns')
@login_required
def api_learning_patterns():
    try:
        from app.learning import get_learned_patterns
        patterns = get_learned_patterns()
        return jsonify({'success': True, 'patterns': patterns, 'count': len(patterns)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/recurring')
@login_required
def api_learning_recurring():
    try:
        from app.learning import get_recurring_issues
        min_count = request.args.get('min_count', 2, type=int)
        recurring = get_recurring_issues(min_count=min_count)
        sorted_recurring = dict(sorted(recurring.items(), key=lambda x: -x[1]['count']))
        return jsonify({'success': True, 'recurring_issues': sorted_recurring, 'count': len(sorted_recurring)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/trends')
@login_required
def api_learning_trends():
    try:
        from app.learning import get_issue_trends
        days = request.args.get('days', 7, type=int)
        trends = get_issue_trends(days=days)
        return jsonify({'success': True, 'trends': trends})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
