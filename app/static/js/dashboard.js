function toggleCard(header) {
    header.classList.toggle('collapsed');
    var body = header.nextElementSibling;
    if (body && body.classList.contains('card-body')) {
        body.classList.toggle('collapsed');
    }
}

function toggleSidebarSection(title) {
    title.classList.toggle('collapsed');
    var content = title.nextElementSibling;
    if (content && content.classList.contains('sidebar-content')) {
        content.classList.toggle('collapsed');
    }
}

function runSuiteFromDashboard(suiteId, name, itemCount) {
    if (!confirm('Run suite "' + name + '" (' + itemCount + ' items)?')) return;
    fetch('/api/suites/' + suiteId + '/run', {method: 'POST'})
        .then(function(r) { return r.json(); })
        .then(function(sr) {
            if (sr.error) return alert(sr.error);
            window.location.href = '/suite-run/' + sr.id;
        });
}

function runTemplate(templateId, name) {
    if (!confirm('Run "' + name + '" now?')) return;
    fetch('/api/templates/' + templateId + '/run', {method: 'POST'})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) return alert(data.error);
            window.location.href = '/job/' + data.build_number + '/console';
        });
}

function toggleSelectAll() {
    var selectAll = document.getElementById('selectAll').checked;
    document.querySelectorAll('.build-checkbox').forEach(function(cb) {
        cb.checked = selectAll;
    });
    updateSelectedCount();
}

function updateSelectedCount() {
    var count = document.querySelectorAll('.build-checkbox:checked').length;
    document.getElementById('selectedCount').textContent = count;
    document.getElementById('deleteSelectedBtn').style.display = count > 0 ? 'inline-flex' : 'none';
}

function deleteSelected() {
    var selected = [];
    document.querySelectorAll('.build-checkbox:checked').forEach(function(cb) {
        selected.push(cb.value);
    });
    if (selected.length === 0) return;
    if (confirm('Are you sure you want to delete ' + selected.length + ' build(s) and their reports?')) {
        Promise.all(selected.map(function(buildNum) {
            return fetch('/api/delete/' + buildNum, { method: 'POST' });
        })).then(function() { location.reload(); });
    }
}

function deleteBuild(buildNum) {
    if (confirm('Are you sure you want to delete Run #' + buildNum + ' and its report?')) {
        fetch('/api/delete/' + buildNum, { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) { location.reload(); }
                else { alert('Failed to delete: ' + data.error); }
            });
    }
}

function deleteBulk(filterType) {
    var messages = {
        'stopped': 'Are you sure you want to delete ALL STOPPED builds?',
        'failed': 'Are you sure you want to delete ALL FAILED builds?',
        'all': 'WARNING: This will delete ALL builds and their reports!\n\nAre you absolutely sure?'
    };
    if (confirm(messages[filterType])) {
        fetch('/api/delete-bulk', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({filter: filterType})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) { alert('Deleted ' + data.deleted + ' build(s)'); location.reload(); }
            else { alert('Failed to delete: ' + data.error); }
        });
    }
}

function toggleTmplMenu(trigger) {
    var menu = trigger.nextElementSibling;
    var isOpen = menu.style.display === 'block';
    document.querySelectorAll('.tmpl-menu').forEach(function(m) { m.style.display = 'none'; });
    if (!isOpen) menu.style.display = 'block';
}

document.addEventListener('click', function() {
    document.querySelectorAll('.tmpl-menu').forEach(function(m) { m.style.display = 'none'; });
});

function pickEditTemplateIcon(el) {
    document.querySelectorAll('.edit-tmpl-icon-opt').forEach(function(e) {
        e.style.borderColor = 'transparent';
    });
    el.style.borderColor = 'var(--accent)';
    window._editTemplateIcon = el.getAttribute('data-icon');
}

function openEditTemplateModal(id) {
    document.querySelectorAll('.tmpl-menu').forEach(function(m) { m.style.display = 'none'; });
    var tmpl = window._templateData.find(function(t) { return t.id === id; });
    if (!tmpl) return;
    document.getElementById('edit-tmpl-id').value = id;
    document.getElementById('edit-tmpl-name').value = tmpl.name;
    document.getElementById('edit-tmpl-desc').value = tmpl.description || '';
    document.getElementById('edit-tmpl-shared').checked = tmpl.shared;
    window._editTemplateIcon = tmpl.icon || '📋';
    document.querySelectorAll('.edit-tmpl-icon-opt').forEach(function(e) {
        e.style.borderColor = e.getAttribute('data-icon') === window._editTemplateIcon ? 'var(--accent)' : 'transparent';
    });
    document.getElementById('editTemplateModal').style.display = 'flex';
    document.getElementById('edit-tmpl-name').focus();
}

function closeEditTemplateModal() {
    document.getElementById('editTemplateModal').style.display = 'none';
}

function submitEditTemplate() {
    var id = document.getElementById('edit-tmpl-id').value;
    var name = document.getElementById('edit-tmpl-name').value.trim();
    if (!name) { alert('Name is required'); return; }
    var btn = document.getElementById('edit-tmpl-save-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    fetch('/api/templates/' + id, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            name: name,
            description: document.getElementById('edit-tmpl-desc').value.trim(),
            icon: window._editTemplateIcon,
            shared: document.getElementById('edit-tmpl-shared').checked
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { alert('Error: ' + data.error); }
        else { closeEditTemplateModal(); location.reload(); }
    })
    .catch(function(err) { alert('Save failed: ' + err); })
    .finally(function() { btn.disabled = false; btn.textContent = 'Save Changes'; });
}

function deleteTemplate(id, name) {
    document.querySelectorAll('.tmpl-menu').forEach(function(m) { m.style.display = 'none'; });
    if (!confirm('Delete template "' + name + '"?')) return;
    fetch('/api/templates/' + id, {method: 'DELETE'})
    .then(function(r) { return r.json(); })
    .then(function() { location.reload(); })
    .catch(function(err) { alert('Failed: ' + err); });
}

function initSidebarResize() {
    var handle = document.getElementById('sidebarResizeHandle');
    var sidebar = document.getElementById('dashSidebar');
    if (!handle || !sidebar) return;
    var dragging = false;
    handle.addEventListener('mousedown', function(e) {
        e.preventDefault();
        dragging = true;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        var rect = sidebar.parentElement.getBoundingClientRect();
        var newWidth = Math.min(500, Math.max(160, e.clientX - rect.left));
        sidebar.style.width = newWidth + 'px';
        try { localStorage.setItem('hc_sidebar_w', newWidth); } catch(ex) {}
    });
    document.addEventListener('mouseup', function() {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
    try {
        var saved = localStorage.getItem('hc_sidebar_w');
        if (saved) sidebar.style.width = saved + 'px';
    } catch(ex) {}
}
initSidebarResize();

function copyPublicLink(filename) {
    var url = location.origin + '/public/report/' + encodeURIComponent(filename);
    navigator.clipboard.writeText(url).then(function() {
        var el = event.currentTarget;
        var orig = el.innerHTML;
        el.innerHTML = '✅';
        setTimeout(function() { el.innerHTML = '🔗'; }, 1500);
    });
}

function initColumnResize(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var ths = table.querySelectorAll('thead th');
    ths.forEach(function(th) {
        if (th.dataset.noResize !== undefined) return;
        var handle = document.createElement('div');
        handle.className = 'col-resize-handle';
        th.appendChild(handle);
        var startX, startW;
        handle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            startX = e.pageX;
            startW = th.offsetWidth;
            handle.classList.add('active');
            function onMove(e2) {
                th.style.width = Math.max(40, startW + e2.pageX - startX) + 'px';
            }
            function onUp() {
                handle.classList.remove('active');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                try {
                    var widths = [];
                    ths.forEach(function(t) { widths.push(t.style.width || ''); });
                    localStorage.setItem('hc_col_widths', JSON.stringify(widths));
                } catch(ex) {}
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });
    try {
        var saved = localStorage.getItem('hc_col_widths');
        if (saved) {
            var widths = JSON.parse(saved);
            ths.forEach(function(th, i) { if (widths[i]) th.style.width = widths[i]; });
        }
    } catch(ex) {}
}

setInterval(function() { location.reload(); }, 30000);
