/* Upgrade policy modal and page interactions. */
var _policyActions = [];
var _scheduleDates = [];

function onStepTypeSelected() {
    var type = document.getElementById('newActionType').value;
    var sel = document.getElementById('newActionId');
    sel.innerHTML = '';
    sel.style.display = 'none';

    if (type === 'health_check' || type === 'upgrade_cvo') {
        addStepEntry(type, '', '');
        return;
    }
    if (type === 'upgrade_olm') {
        addStepEntry(type, '*', '');
        return;
    }
    if (type === 'test_suite') {
        sel.innerHTML = '<option value="" disabled selected>-- select suite --</option>';
        window._suites.forEach(function(s) { sel.innerHTML += '<option value="' + s.id + '">' + s.name + ' (' + s.item_count + ' items)</option>'; });
        sel.style.display = '';
    } else if (type === 'template') {
        sel.innerHTML = '<option value="" disabled selected>-- select template --</option>';
        window._templates.forEach(function(t) { sel.innerHTML += '<option value="' + t.id + '">' + t.name + '</option>'; });
        sel.style.display = '';
    }
}

function onStepValueSelected() {
    var type = document.getElementById('newActionType').value;
    var sel = document.getElementById('newActionId');
    var val = sel.value;
    if (!val) return;
    var label = sel.selectedOptions[0].text;
    addStepEntry(type, val, label);
}

function addStepEntry(type, val, label) {
    var entry = {type: type, id: null, label: '', target: '', enabled: true};
    if (type === 'upgrade_olm') {
        entry.target = val || '*';
        entry.label = 'Upgrade OLM: ' + (entry.target === '*' ? 'all operators' : entry.target);
    } else if (type === 'upgrade_cvo') {
        entry.label = 'Upgrade Cluster (CVO)';
    } else if (type === 'health_check') {
        entry.label = 'Health Check (all)';
    } else if (type === 'test_suite') {
        entry.id = parseInt(val);
        entry.label = label;
    } else if (type === 'template') {
        entry.id = parseInt(val);
        entry.label = label;
    }
    _policyActions.push(entry);
    renderActions();
    document.getElementById('newActionType').value = '';
    document.getElementById('newActionId').style.display = 'none';
    document.getElementById('newActionId').innerHTML = '';
}

function removeAction(idx) { _policyActions.splice(idx, 1); renderActions(); }
function moveAction(idx, dir) {
    var n = idx + dir;
    if (n < 0 || n >= _policyActions.length) return;
    var tmp = _policyActions[idx]; _policyActions[idx] = _policyActions[n]; _policyActions[n] = tmp;
    renderActions();
}

function toggleStepEnabled(idx) {
    _policyActions[idx].enabled = !_policyActions[idx].enabled;
    renderActions();
}

function renderActions() {
    var c = document.getElementById('actionsList');
    if (!_policyActions.length) { c.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);padding:4px 0;">No steps added yet. Add upgrades and tests below.</div>'; return; }
    c.innerHTML = _policyActions.map(function(a, i) {
        var enabled = a.enabled !== false;
        var badge = a.type === 'test_suite' ? 'green' : a.type === 'template' ? 'blue' : (a.type.startsWith('upgrade') ? 'yellow' : 'gray');
        var opacity = enabled ? '1' : '0.4';
        return '<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;opacity:' + opacity + ';">' +
            '<label class="toggle" style="flex-shrink:0;"><input type="checkbox" ' + (enabled?'checked':'') + ' onchange="toggleStepEnabled(' + i + ')"><span class="slider"></span></label>' +
            '<span style="font-size:12px;font-weight:600;width:22px;text-align:center;">' + (i+1) + '</span>' +
            '<span class="ug-badge ' + badge + '">' + a.type.replace('_',' ') + '</span>' +
            '<span style="flex:1;font-size:13px;">' + (a.label || '') + '</span>' +
            '<button type="button" onclick="moveAction(' + i + ',-1)" style="border:none;background:none;cursor:pointer;font-size:12px;" ' + (i===0?'disabled':'') + '>↑</button>' +
            '<button type="button" onclick="moveAction(' + i + ',1)" style="border:none;background:none;cursor:pointer;font-size:12px;" ' + (i===_policyActions.length-1?'disabled':'') + '>↓</button>' +
            '<button type="button" onclick="removeAction(' + i + ')" style="border:none;background:none;cursor:pointer;color:var(--danger);font-size:14px;">✕</button>' +
            '</div>';
    }).join('');
}

function toggleSection(h2) {
    h2.classList.toggle('collapsed');
    var content = h2.nextElementSibling;
    if (content && content.classList.contains('ug-collapsible')) {
        content.classList.toggle('collapsed');
    }
}

function editPolicy(id) {
    var p = window.ALL_POLICIES.find(function(x) { return x.id === id; });
    if (!p) { fetch('/api/upgrades/policies/' + id).then(function(r){return r.json();}).then(function(data){ _loadPolicyIntoModal(data); }); return; }
    _loadPolicyIntoModal(p);
}

function toggleScheduleSection() {
    var isAuto = document.getElementById('polAutoApprove').value === 'true';
    var section = document.getElementById('polScheduleSection');
    var hint = document.getElementById('polManualHint');
    if (isAuto) {
        section.classList.remove('is-hidden');
        hint.style.display = 'none';
    } else {
        section.classList.add('is-hidden');
        hint.style.display = '';
    }
}

function toggleScheduleMode() {
    var mode = document.getElementById('polScheduleMode').value;
    document.getElementById('schedModeInterval').style.display = mode === 'interval' ? '' : 'none';
    document.getElementById('schedModeDaily').style.display = mode === 'daily' ? '' : 'none';
    document.getElementById('schedModeDates').style.display = mode === 'dates' ? '' : 'none';
}

function addScheduleDate() {
    var d = document.getElementById('schedNewDate').value;
    var t = document.getElementById('schedNewTime').value || '03:00';
    if (!d) return;
    _scheduleDates.push(d + 'T' + t);
    _scheduleDates.sort();
    renderScheduleDates();
    document.getElementById('schedNewDate').value = '';
}

function removeScheduleDate(idx) {
    _scheduleDates.splice(idx, 1);
    renderScheduleDates();
}

function renderScheduleDates() {
    var c = document.getElementById('schedDatesList');
    if (!_scheduleDates.length) { c.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);padding:4px 0;">No dates added yet.</div>'; return; }
    c.innerHTML = _scheduleDates.map(function(dt, i) {
        var parts = dt.split('T');
        var label = parts[0] + ' at ' + (parts[1] || '03:00') + ' UTC';
        return '<div class="sched-date-entry"><span>' + label + '</span>' +
            '<button type="button" onclick="removeScheduleDate(' + i + ')" style="border:none;background:none;cursor:pointer;color:var(--danger);font-size:14px;">✕</button></div>';
    }).join('');
}

function _loadPolicyIntoModal(p) {
    document.getElementById('policyEditId').value = p.id;
    document.getElementById('policyModalTitle').textContent = 'Edit Policy: ' + p.name;
    document.getElementById('polName').value = p.name;
    document.getElementById('polDesc').value = p.description || '';
    document.getElementById('polAutoApprove').value = p.auto_approve ? 'true' : 'false';
    document.getElementById('polInterval').value = p.scan_interval_minutes || 60;
    document.getElementById('polScheduleMode').value = p.schedule_mode || 'interval';
    document.getElementById('polScheduleTime').value = p.schedule_time || '03:00';
    var pDays = p.schedule_days || [];
    document.querySelectorAll('.sched-day').forEach(function(cb) { cb.checked = pDays.indexOf(cb.value) >= 0; });
    _scheduleDates = (p.schedule_dates || []).slice();
    renderScheduleDates();
    toggleScheduleSection();
    toggleScheduleMode();
    _policyActions = (p.steps || []).map(function(s) {
        return {type: s.type, id: s.id, target: s.target || '', enabled: s.enabled !== false, label: s.label || s.type, namespace: s.namespace || ''};
    });
    renderActions();
    document.getElementById('policyModal').classList.add('show');
    document.body.classList.add('modal-open');
}

function scanNow() {
    var sp = document.getElementById('scanSpinner');
    sp.classList.add('active');
    fetch('/api/upgrades/scan').then(r => r.json()).then(data => {
        sp.classList.remove('active');
        if (data.error) { document.getElementById('scanResults').innerHTML = '<div class="ug-warn">' + data.error + '</div>'; return; }
        renderScanResults(data);
    }).catch(() => sp.classList.remove('active'));
}

function renderScanResults(data) {
    var html = '<div class="ug-grid">';
    var cvo = data.cvo || {};
    html += '<div class="ug-card"><h3>Cluster Version (CVO)</h3>';
    html += '<div class="meta">Current: <strong>' + (cvo.current_version || 'N/A') + '</strong> | Channel: ' + (cvo.channel || 'N/A') + '</div>';
    var updates = cvo.available_updates || [];
    if (updates.length) {
        html += '<div style="margin-top:8px;">';
        updates.forEach(function(u) {
            var blocked = !cvo.upgradeable;
            html += '<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">';
            html += '<span class="ug-badge ' + (blocked ? 'red' : 'green') + '">' + u.version + '</span>';
            if (!blocked) html += '<button class="btn-sm" onclick="triggerCvoUpgrade(\'' + u.version + '\')" style="font-size:11px;">Upgrade</button>';
            else html += '<span style="font-size:11px;color:var(--danger);">blocked</span>';
            html += '</div>';
        });
        html += '</div>';
        if (cvo.warnings && cvo.warnings.length) {
            cvo.warnings.forEach(function(w) { html += '<div class="ug-warn">' + w + '</div>'; });
        }
    } else { html += '<div class="meta" style="margin-top:8px;">No updates available</div>'; }
    html += '</div>';

    var olm = data.olm || [];
    html += '<div class="ug-card"><h3>OLM Operators</h3>';
    if (olm.length) {
        olm.forEach(function(op) {
            html += '<div style="margin:6px 0;padding:6px 0;border-bottom:1px solid var(--border);">';
            html += '<strong>' + op.name + '</strong> <span class="meta">(' + op.namespace + ')</span><br>';
            html += '<span class="meta">' + (op.installed_csv||'').substring(0,40) + ' \u2192 ' + (op.current_csv||'').substring(0,40) + '</span>';
            if (op.pending_plans && op.pending_plans.length) {
                html += ' <span class="ug-badge yellow">' + op.pending_plans.length + ' pending</span>';
            }
            html += ' <button class="btn-sm" onclick="triggerOlmUpgrade(\'' + op.name.replace(/'/g, "\\'") + '\',\'' + op.namespace.replace(/'/g, "\\'") + '\')" style="font-size:11px;margin-left:6px;">Upgrade</button>';
            html += '</div>';
        });
    } else { html += '<div class="meta">No pending OLM upgrades</div>'; }
    html += '</div></div>';
    document.getElementById('scanResults').innerHTML = html;
}

function triggerCvoUpgrade(version) {
    if (!confirm('Trigger cluster upgrade to ' + version + '?')) return;
    fetch('/api/upgrades/policies', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name:'Manual CVO ' + version, upgrade_type:'cvo', target_operator:'cluster', auto_approve:true, post_upgrade_action:'none', scan_interval_minutes:9999})
    }).then(r => r.json()).then(p => {
        if (p.error) return alert(p.error);
        fetch('/api/upgrades/policies/' + p.id + '/trigger', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({to_version: version})
        }).then(r => r.json()).then(run => {
            if (run.error) return alert(run.error);
            location.reload();
        });
    });
}

function triggerOlmUpgrade(operator, namespace) {
    if (!confirm('Upgrade ' + operator + ' in ' + namespace + '?')) return;
    fetch('/api/upgrades/operator', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({operator: operator, namespace: namespace})
    }).then(r => r.json()).then(run => {
        if (run.error) return alert(run.error);
        window.location.href = '/upgrade-run/' + run.id;
    }).catch(e => alert('Upgrade failed: ' + e));
}

function onTypeChange() {
    var t = document.getElementById('polType').value;
    document.getElementById('olmFields').style.display = t === 'olm' ? '' : 'none';
    if (t === 'cvo') { document.getElementById('polTarget').value = 'cluster'; document.getElementById('polNs').value = ''; }
}
function onActionChange() {
    var a = document.getElementById('polAction').value;
    document.getElementById('suiteField').style.display = a === 'test_suite' ? '' : 'none';
    document.getElementById('templateField').style.display = a === 'template' ? '' : 'none';
}

function openPolicyModal() {
    document.getElementById('policyEditId').value = '';
    document.getElementById('policyModalTitle').textContent = 'Add Upgrade Policy';
    document.getElementById('polName').value = '';
    document.getElementById('polDesc').value = '';
    document.getElementById('polAutoApprove').value = 'false';
    document.getElementById('polInterval').value = '60';
    document.getElementById('polScheduleMode').value = 'interval';
    document.getElementById('polScheduleTime').value = '03:00';
    document.querySelectorAll('.sched-day').forEach(function(cb) { cb.checked = false; });
    _scheduleDates = [];
    renderScheduleDates();
    toggleScheduleSection();
    toggleScheduleMode();
    _policyActions = [];
    renderActions();
    document.getElementById('policyModal').classList.add('show');
    document.body.classList.add('modal-open');
}
function closePolicyModal() {
    document.getElementById('policyModal').classList.remove('show');
    document.body.classList.remove('modal-open');
}

function savePolicy() {
    var isAuto = document.getElementById('polAutoApprove').value === 'true';
    var schedMode = 'interval';
    var schedTime = null;
    var schedDays = null;
    var schedDates = null;
    if (isAuto) {
        schedMode = document.getElementById('polScheduleMode').value;
        if (schedMode === 'daily') {
            schedTime = document.getElementById('polScheduleTime').value || '03:00';
            var days = [];
            document.querySelectorAll('.sched-day:checked').forEach(function(cb) { days.push(cb.value); });
            schedDays = days.length ? days : null;
        } else if (schedMode === 'dates') {
            schedDates = _scheduleDates.length ? _scheduleDates : null;
        }
    }
    var data = {
        name: document.getElementById('polName').value.trim(),
        description: document.getElementById('polDesc').value.trim(),
        auto_approve: isAuto,
        steps: _policyActions.map(function(a) {
            return {type: a.type, id: a.id, target: a.target || '', enabled: a.enabled !== false, label: a.label || a.type};
        }),
        scan_interval_minutes: parseInt(document.getElementById('polInterval').value) || 60,
        schedule_mode: schedMode,
        schedule_time: schedTime,
        schedule_days: schedDays,
        schedule_dates: schedDates,
    };
    if (!data.name) return alert('Name is required');
    var editId = document.getElementById('policyEditId').value;
    var url = editId ? '/api/upgrades/policies/' + editId : '/api/upgrades/policies';
    var method = editId ? 'PUT' : 'POST';
    fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
        .then(r => { if (!r.ok && r.status === 302 || r.redirected) { location.href = '/login'; return; } return r.json(); })
        .then(p => { if (!p) return; if (p.error) return alert(p.error); closePolicyModal(); location.reload(); })
        .catch(e => alert('Save failed: ' + e));
}

function togglePolicy(id, enabled) {
    fetch('/api/upgrades/policies/' + id, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled})});
}
function deletePolicy(id) {
    if (!confirm('Delete this policy?')) return;
    fetch('/api/upgrades/policies/' + id, {method:'DELETE'}).then(() => location.reload());
}
function triggerPolicy(id) {
    if (!confirm('Trigger this upgrade policy now?')) return;
    fetch('/api/upgrades/policies/' + id + '/trigger', {method:'POST'}).then(r => r.json()).then(run => {
        if (run.no_upgrades) {
            alert('No upgrades available. Tests will not run.');
            return;
        }
        if (run.error) return alert(run.error);
        window.location.href = '/upgrade-run/' + run.id;
    });
}
function showRunLog(id) {
    fetch('/api/upgrades/runs/' + id).then(r => r.json()).then(run => {
        document.getElementById('logContent').textContent = run.log || 'No log entries';
        document.getElementById('logModal').classList.add('show');
    });
}
function abortRun(id) {
    if (!confirm('Abort this upgrade run?')) return;
    fetch('/api/upgrades/runs/' + id + '/abort', {method:'POST'}).then(() => location.reload());
}
