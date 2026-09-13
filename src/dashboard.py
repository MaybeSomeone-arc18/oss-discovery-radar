import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
import os
from datetime import datetime

from src.database import get_connection
from src.contribution_engine import calculate_first_contribution_score
from src.deep_analysis import check_release_prerequisites
from src.run_log import get_recent_logs
from src.scheduler import schedule_status
from src.hermes_agent import verify_local_provider, get_issue_context, get_reports_dir
from src.prompt_generator import generate_implementation_prompt

PORT = 8787

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OSS Discovery Radar Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --border: #334155;
        }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 2rem;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }
        h1 {
            font-weight: 700;
            margin: 0;
            background: linear-gradient(90deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 2rem;
        }
        .card {
            background: var(--surface);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            border: 1px solid var(--border);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }
        h2 {
            margin-top: 0;
            font-size: 1.25rem;
            color: var(--text);
            border-bottom: 1px solid var(--border);
            padding-bottom: 0.5rem;
            margin-bottom: 1rem;
        }
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
        }
        .status-success { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .status-danger { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
        .status-warning { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        th {
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }
        tr:last-child td { border-bottom: none; }
        
        .btn {
            background: var(--primary);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.875rem;
            transition: background 0.2s ease;
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover { background: var(--primary-hover); }
        
        .btn-small {
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
            background: var(--surface-hover);
            color: var(--text);
            margin-right: 0.25rem;
            margin-bottom: 0.25rem;
        }
        .btn-small:hover { background: var(--primary); }
        
        .event-log {
            font-family: monospace;
            font-size: 0.875rem;
            color: var(--text-muted);
        }
        .event-item {
            padding: 0.5rem 0;
            border-bottom: 1px dashed var(--border);
        }
        .event-item:last-child { border-bottom: none; }
        .event-time { color: var(--primary); }
        .event-action { font-weight: bold; color: var(--text); }
        
        .digest-content {
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 0.875rem;
            color: var(--text-muted);
            background: rgba(0,0,0,0.2);
            padding: 1rem;
            border-radius: 6px;
            max-height: 300px;
            overflow-y: auto;
        }
        
        /* Modal */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.7);
            backdrop-filter: blur(4px);
        }
        .modal-content {
            background-color: var(--surface);
            margin: 5% auto;
            padding: 2rem;
            border: 1px solid var(--border);
            border-radius: 12px;
            width: 80%;
            max-width: 800px;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .close {
            color: var(--text-muted);
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover { color: white; }
        pre {
            background: rgba(0,0,0,0.3);
            padding: 1rem;
            border-radius: 6px;
            overflow-x: auto;
            white-space: pre-wrap;
        }
        
        .system-status {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>OSS Discovery Radar</h1>
            <div style="display: flex; align-items: center; gap: 0.75rem;">
                <span id="refresh-status" class="status-badge status-warning" style="display: none;"></span>
                <button class="btn" id="refresh-btn" onclick="fetchData()">Refresh Data</button>
            </div>
        </div>
        
        <div class="grid">
            <div style="display: flex; flex-direction: column; gap: 2rem;">
                <div class="card">
                    <h2>Top Opportunities</h2>
                    <div id="opportunities-content">Loading...</div>
                </div>
                
                <div class="card">
                    <h2>Latest Digest</h2>
                    <div id="digest-content" class="digest-content">Loading...</div>
                </div>
            </div>
            
            <div style="display: flex; flex-direction: column; gap: 2rem;">
                <div class="card">
                    <h2>System Status</h2>
                    <div class="system-status">
                        <div class="status-row">
                            <span>Hermes / Qwen Agent</span>
                            <span id="hermes-status" class="status-badge">Checking...</span>
                        </div>
                        <div class="status-row">
                            <span>Background Scheduler</span>
                            <span id="scheduler-status" class="status-badge">Checking...</span>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Data Freshness</h2>
                    <div class="system-status">
                        <div class="status-row">
                            <span>Latest issue data</span>
                            <span id="freshness-issues" class="status-badge">Loading...</span>
                        </div>
                        <div class="status-row">
                            <span>Latest daily run</span>
                            <span id="freshness-run" class="status-badge">Loading...</span>
                        </div>
                        <div class="status-row">
                            <span>Last sync</span>
                            <span id="freshness-sync" class="status-badge">Loading...</span>
                        </div>
                        <div class="status-row">
                            <span>Payload generated</span>
                            <span id="freshness-generated" class="status-badge">Loading...</span>
                        </div>
                        <div id="freshness-error" style="display: none; color: var(--danger); font-size: 0.875rem;"></div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Recent Events</h2>
                    <div id="events-content" class="event-log">Loading...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal -->
    <div id="myModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <h2 id="modal-title">Details</h2>
            <div style="margin-bottom: 1rem;">
                <button class="btn" id="copy-btn" onclick="copyModalContent()">Copy to Clipboard</button>
            </div>
            <pre id="modal-body">Loading...</pre>
        </div>
    </div>

    <script>
        function showModal(title, content) {
            document.getElementById('modal-title').innerText = title;
            document.getElementById('modal-body').innerText = content;
            document.getElementById('myModal').style.display = "block";
            document.getElementById('copy-btn').innerText = "Copy to Clipboard";
        }
        
        function closeModal() {
            document.getElementById('myModal').style.display = "none";
        }

        function copyModalContent() {
            const content = document.getElementById('modal-body').innerText;
            navigator.clipboard.writeText(content).then(() => {
                document.getElementById('copy-btn').innerText = "Copied!";
            });
        }
        
        async function fetchEndpoint(url, title) {
            try {
                const res = await fetch(url);
                const data = await res.json();
                if (data.error) {
                    showModal(title, "Error: " + data.error);
                } else {
                    showModal(title, data.content || data.path || JSON.stringify(data, null, 2));
                }
            } catch(e) {
                showModal(title, "Failed to fetch: " + e);
            }
        }

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        function commBadgeClass(status) {
            if (status === 'APPROVED' || status === 'NOT_REQUIRED') return 'status-success';
            if (status === 'REJECTED') return 'status-danger';
            return 'status-warning';
        }

        function commStateFromUrl(url) {
            const data = window._radarData;
            if (data && data.opportunities) {
                for (const o of data.opportunities) {
                    if (o.url === url) return o.communication || {};
                }
            }
            return {};
        }

        function renderCommunicationModal(url, state) {
            state = state || commStateFromUrl(url);
            const status = state.status || 'UNKNOWN';
            const approvedAt = state.approved_at || null;
            const reply = state.recommendation || '';
            const reason = state.reason || '';
            document.getElementById('modal-title').innerText = 'Communication Review \u00b7 ' + url;
            document.getElementById('modal-body').innerHTML = `
                <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; margin-bottom:0.75rem;">
                    <span class="status-badge ${commBadgeClass(status)}">${esc(status)}</span>
                    <span style="color:var(--text-muted); font-size:0.875rem;">Approved at: ${approvedAt ? esc(approvedAt) : 'not approved yet'}</span>
                </div>
                <div style="margin-bottom:0.5rem; font-weight:600;">Suggested maintainer reply (editable)</div>
                <textarea id="comm-reply" rows="6" style="width:100%; box-sizing:border-box; background:rgba(0,0,0,0.3); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:0.5rem; font-family:monospace; font-size:0.875rem;">${esc(reply)}</textarea>
                <div style="margin:0.75rem 0 0.25rem; font-weight:600;">Reason</div>
                <pre id="comm-reason" style="white-space:pre-wrap; margin:0 0 0.75rem;">${esc(reason) || 'No reason recorded.'}</pre>
                <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.5rem;">
                    <button class="btn" id="comm-approve" onclick="commAction('${esc(url)}', 'approve')">Approve</button>
                    <button class="btn" id="comm-reject" onclick="commAction('${esc(url)}', 'reject')" style="background:var(--danger);">Reject</button>
                    <button class="btn" id="comm-save" onclick="commAction('${esc(url)}', 'edit')" style="background:var(--surface-hover); color:var(--text);">Save Reply</button>
                </div>
                <div id="comm-result" style="font-size:0.875rem;"></div>
                <div style="margin-top:0.75rem; color:var(--text-muted); font-size:0.75rem;">Local-only action \u2014 updates the local Radar database. Nothing is posted to GitHub.</div>
            `;
            document.getElementById('myModal').style.display = "block";
            document.getElementById('copy-btn').innerText = "Copy to Clipboard";
        }

        function showCommunication(url) {
            renderCommunicationModal(url);
        }

        async function commAction(url, action) {
            const buttonIds = ['comm-approve', 'comm-reject', 'comm-save'];
            let resultEl = document.getElementById('comm-result');
            buttonIds.forEach(id => { const b = document.getElementById(id); if (b) b.disabled = true; });
            resultEl.style.color = 'var(--text-muted)';
            resultEl.innerText = 'Working...';
            try {
                const body = { url: url };
                if (action === 'edit') {
                    body.recommendation = document.getElementById('comm-reply').value;
                }
                const res = await fetch('/api/communication/' + action, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await res.json();
                if (!res.ok || data.error) {
                    throw new Error(data.error || ('HTTP ' + res.status));
                }
                renderCommunicationModal(url, data.state);
                const msg = action === 'approve' ? 'Approved \u2713'
                    : action === 'reject' ? 'Rejected \u2713'
                    : 'Reply saved \u2713 (status reset to REVIEW_REQUIRED \u2014 approve again when ready)';
                resultEl = document.getElementById('comm-result');
                resultEl.style.color = 'var(--success)';
                resultEl.innerText = msg;
                // Keep the rows/badges in sync with the local DB.
                fetchData();
            } catch(e) {
                resultEl.style.color = 'var(--danger)';
                resultEl.innerText = 'Failed: ' + e.message;
            } finally {
                buttonIds.forEach(id => { const b = document.getElementById(id); if (b) b.disabled = false; });
            }
        }

        async function fetchData() {
            const btn = document.getElementById('refresh-btn');
            const refreshStatus = document.getElementById('refresh-status');
            const errEl = document.getElementById('freshness-error');
            btn.disabled = true;
            btn.innerText = 'Refreshing...';
            refreshStatus.style.display = 'none';
            if (errEl) { errEl.style.display = 'none'; }
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                if (data.error) {
                    throw new Error(data.error);
                }
                // Keep the last snapshot for the Communication review modal.
                window._radarData = data;
                
                // Render Hermes
                const hs = document.getElementById('hermes-status');
                if (data.hermes_available) {
                    hs.className = "status-badge status-success";
                    hs.innerText = "Available";
                } else {
                    hs.className = "status-badge status-danger";
                    hs.innerText = "Unavailable: " + data.hermes_error;
                }
                
                // Render Scheduler
                const ss = document.getElementById('scheduler-status');
                if (data.scheduler_status.includes("Installed and loaded")) {
                    ss.className = "status-badge status-success";
                    ss.innerText = "Active";
                } else if (data.scheduler_status.includes("Not installed")) {
                    ss.className = "status-badge status-danger";
                    ss.innerText = "Inactive";
                } else {
                    ss.className = "status-badge status-warning";
                    ss.innerText = data.scheduler_status;
                }
                
                // Render Events
                let eventsHtml = "";
                if (data.events.length === 0) {
                    eventsHtml = "No recent events.";
                } else {
                    data.events.forEach(e => {
                        let color = "var(--text-muted)";
                        if (e.result === "success") color = "var(--success)";
                        if (e.result === "failed") color = "var(--danger)";
                        eventsHtml += `
                        <div class="event-item">
                            <span class="event-time">[${e.timestamp}]</span>
                            <span class="event-action">${e.action}</span>
                            <span style="color: ${color}">(${e.result})</span>
                            <br><span>${e.message}</span>
                        </div>`;
                    });
                }
                document.getElementById('events-content').innerHTML = eventsHtml;
                
                // Render Digest
                document.getElementById('digest-content').innerText = data.digest || "No digest found.";
                
                // Render Opportunities
                let oppsHtml = "<table><tr><th>Repo/Issue</th><th>Score</th><th>Readiness / GSoC</th><th>Actions</th></tr>";
                if (data.opportunities.length === 0) {
                    oppsHtml = "<tr><td colspan='4'>No top opportunities right now.</td></tr>";
                } else {
                    data.opportunities.forEach(o => {
                        oppsHtml += `
                        <tr>
                            <td>
                                <a href="${o.url}" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">${o.repo}#${o.num}</a>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">${o.title}</div>
                            </td>
                            <td><span class="status-badge status-success">${o.score.toFixed(1)}</span></td>
                            <td>
                                <div style="font-size: 0.875rem;">${o.readiness}</div>
                                <div style="font-size: 0.75rem; color: var(--text-muted);">GSoC: ${o.gsoc ? o.gsoc.toFixed(1) : 'N/A'}</div>
                                <div style="font-size: 0.75rem; margin-top: 0.25rem;">Comm: <span class="status-badge ${commBadgeClass((o.communication || {}).status)}" style="font-size: 0.7rem; padding: 0.1rem 0.45rem;">${(o.communication && o.communication.status) || 'N/A'}</span></div>
                            </td>
                            <td>
                                <button class="btn btn-small" onclick="fetchEndpoint('/api/prompt?url=' + encodeURIComponent('${o.url}'), 'Implementation Prompt')">Prompt</button>
                                <button class="btn btn-small" onclick="fetchEndpoint('/api/workspace?url=' + encodeURIComponent('${o.url}'), 'Workspace Path')">Workspace</button>
                                <button class="btn btn-small" onclick="fetchEndpoint('/api/research?url=' + encodeURIComponent('${o.url}'), 'Research Report')">Research</button>
                                <button class="btn btn-small" onclick="fetchEndpoint('/api/plan?url=' + encodeURIComponent('${o.url}'), 'Implementation Plan')">Plan</button>
                                <button class="btn btn-small" onclick="showCommunication('${esc(o.url)}')">Comm</button>
                            </td>
                        </tr>`;
                    });
                }
                oppsHtml += "</table>";
                document.getElementById('opportunities-content').innerHTML = oppsHtml;
                
                // Render freshness metadata (read-only local state)
                const f = data.freshness || {};
                document.getElementById('freshness-issues').innerText =
                    f.latest_issue_timestamp || 'No issue data yet';
                const run = f.daily_run || null;
                document.getElementById('freshness-run').innerText =
                    run ? (run.status + ' \u00b7 ' + run.run_date) : 'No daily run recorded';
                const sync = f.sync || null;
                document.getElementById('freshness-sync').innerText =
                    sync ? (sync.status + ' \u00b7 ' + (sync.timestamp || 'unknown')
                        + (sync.status === 'failed' && sync.message ? ' \u2014 ' + sync.message.slice(0, 100) : ''))
                    : 'No sync recorded';
                document.getElementById('freshness-generated').innerText = f.generated_at || 'N/A';
                if (f.error) {
                    errEl.innerText = 'Freshness unavailable: ' + f.error;
                    errEl.style.display = 'block';
                }
                
                btn.innerText = 'Updated ' + new Date().toLocaleTimeString();
                refreshStatus.className = "status-badge status-success";
                refreshStatus.innerText = 'OK';
                refreshStatus.style.display = 'inline-block';
            } catch(e) {
                console.error("Failed to load dashboard data", e);
                btn.innerText = 'Refresh failed';
                refreshStatus.className = "status-badge status-danger";
                refreshStatus.innerText = 'Error';
                refreshStatus.style.display = 'inline-block';
                if (errEl) {
                    errEl.innerText = 'Refresh failed: ' + e.message;
                    errEl.style.display = 'block';
                }
            } finally {
                btn.disabled = false;
            }
        }
        
        window.onclick = function(event) {
            const modal = document.getElementById('myModal');
            if (event.target == modal) {
                modal.style.display = "none";
            }
        }

        window.onload = fetchData;
    </script>
</body>
</html>
"""

def collect_freshness_metadata():
    """Read-only freshness snapshot of the current LOCAL state.

    Pure SELECTs against the local SQLite DB and audit log. This never
    triggers GitHub synchronization, AI/model inference, or the daily
    pipeline -- it only re-reads what is already stored.
    """
    freshness = {
        "latest_issue_timestamp": None,
        "daily_run": None,
        "sync": None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with get_connection() as conn:
            # Latest issue/update timestamp available in the local DB.
            row = conn.execute(
                "SELECT MAX(updated_at) FROM issues"
                " WHERE updated_at IS NOT NULL AND updated_at != ''"
            ).fetchone()
            latest = row[0] if row and row[0] else None
            if not latest:
                row = conn.execute(
                    "SELECT MAX(discovered_at) FROM issues"
                ).fetchone()
                latest = row[0] if row and row[0] else None
            freshness["latest_issue_timestamp"] = latest

            # Latest manual daily-run status/date.
            row = conn.execute(
                "SELECT run_date, status, started_at, completed_at, error_message"
                " FROM daily_runs ORDER BY run_date DESC LIMIT 1"
            ).fetchone()
            if row:
                freshness["daily_run"] = {
                    "run_date": row[0],
                    "status": row[1],
                    "started_at": row[2],
                    "completed_at": row[3],
                    "error_message": row[4],
                }

            # Latest sync status/error from the existing audit log.
            row = conn.execute(
                "SELECT timestamp, result, message FROM audit_logs"
                " WHERE action = 'sync' ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row:
                freshness["sync"] = {
                    "timestamp": row[0],
                    "status": row[1],
                    "message": row[2],
                }
    except Exception as e:
        freshness["error"] = str(e)
    return freshness


def normalize_communication_state(state):
    """Map the DB column names from get_communication_state to the dashboard
    payload shape used by /api/data opportunities and the review modal."""
    if not state:
        return None
    return {
        "status": state.get("communication_status"),
        "recommendation": state.get("communication_recommendation"),
        "reason": state.get("communication_reason"),
        "approved_at": state.get("communication_approved_at"),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
        
    def get_dashboard_data(self):
        data = {}
        
        # Hermes status
        try:
            verify_local_provider()
            data['hermes_available'] = True
            data['hermes_error'] = None
        except Exception as e:
            data['hermes_available'] = False
            data['hermes_error'] = str(e)
            
        # Scheduler status
        data['scheduler_status'] = schedule_status()
        
        # Events
        logs = get_recent_logs(10)
        data['events'] = []
        for log in logs:
            data['events'].append({
                'timestamp': log[1],
                'action': log[2],
                'result': log[4],
                'message': log[5]
            })
            
        # Digest
        import glob
        digests = glob.glob("digests/daily_*.md")
        if digests:
            latest = max(digests, key=os.path.getmtime)
            with open(latest, 'r') as f:
                data['digest'] = f.read()
        else:
            data['digest'] = "No digests generated yet."
            
        # Opportunities
        data['opportunities'] = []
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT i.url, i.repo_name, i.issue_number, i.title, i.body_preview, i.org_slug,
                           i.communication_status, i.communication_recommendation,
                           i.communication_reason, i.communication_approved_at
                    FROM issues i
                    LEFT JOIN repositories r ON i.repo_name = r.name
                    WHERE i.state = 'OPEN' 
                    AND (i.eligibility_status IS NULL OR i.eligibility_status NOT IN ('BLOCKED', 'SOLVED', 'DUPLICATE', 'BLOCKED_STUDENT_WORK_REPO', 'BLOCKED_RELATED_PR', 'LIKELY_SOLVED'))
                    AND (i.activity_status IS NULL OR i.activity_status IN ('ACTIVE', 'LIKELY_ACTIVE'))
                    AND (i.assignee_status IS NULL OR i.assignee_status != 'ASSIGNED')
                    AND (r.repo_eligibility IS NULL OR r.repo_eligibility NOT IN ('BLOCKED_STUDENT_WORK_REPO', 'BLOCKED_ARCHIVED', 'BLOCKED_FORK_OR_MIRROR'))
                ''')
                rows = cursor.fetchall()
                
                scored_candidates = []
                for row in rows:
                    (url, repo_name, issue_number, title, body_preview, org_slug,
                     comm_status, comm_recommendation, comm_reason, comm_approved_at) = row
                    score, notes = calculate_first_contribution_score(url)
                    if score > 0:
                        cur2 = conn.cursor()
                        cur2.execute("SELECT gsoc_preparation_score FROM issues WHERE url = ?", (url,))
                        row2 = cur2.fetchone()
                        gsoc = row2[0] if row2 else None
                        
                        readiness, _ = check_release_prerequisites(repo_name, title, body_preview)
                        if readiness == "READY_NOW":
                            scored_candidates.append({
                                "url": url, "repo": repo_name, "num": issue_number, "title": title,
                                "score": score, "gsoc": gsoc, "readiness": readiness,
                                "communication": {
                                    "status": comm_status,
                                    "recommendation": comm_recommendation,
                                    "reason": comm_reason,
                                    "approved_at": comm_approved_at,
                                },
                            })
                            
                scored_candidates.sort(key=lambda x: x["score"], reverse=True)
                data['opportunities'] = scored_candidates[:5]
        except Exception as e:
            print("Error fetching opportunities for dashboard:", e)

        # Read-only freshness metadata for the current LOCAL state (never
        # triggers sync, inference, or the daily pipeline).
        data['freshness'] = collect_freshness_metadata()

        return data

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            
        elif self.path == '/api/data':
            # Read-only snapshot; failures are surfaced to the UI instead of
            # only appearing in server logs/console.
            try:
                self.send_json(self.get_dashboard_data())
            except Exception as e:
                self.send_json(
                    {"error": f"Failed to load dashboard data: {e}"}, 500
                )
            
        elif self.path.startswith('/api/prompt'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            url = qs.get('url', [None])[0]
            if not url:
                self.send_json({"error": "Missing url"}, 400)
                return
            prompt = generate_implementation_prompt(url)
            self.send_json({"content": prompt})
            
        elif self.path.startswith('/api/workspace'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            url = qs.get('url', [None])[0]
            if not url:
                self.send_json({"error": "Missing url"}, 400)
                return
            issue = get_issue_context(url)
            if not issue:
                self.send_json({"error": "Issue not found"}, 404)
                return
            org_slug = issue.get('org_slug')
            repo_name = issue.get('repo_name')
            repo_short = repo_name.split('/')[1] if '/' in repo_name else repo_name
            issue_id = issue.get('issue_number')
            
            from src.workspace_manager import WORKSPACES_ROOT
            wt_path = WORKSPACES_ROOT / org_slug / repo_short / "worktrees" / str(issue_id)
            self.send_json({"path": str(wt_path)})
            
        elif self.path.startswith('/api/research'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            url = qs.get('url', [None])[0]
            if not url:
                self.send_json({"error": "Missing url"}, 400)
                return
            issue = get_issue_context(url)
            if not issue:
                self.send_json({"error": "Issue not found"}, 404)
                return
            org_slug = issue.get('org_slug')
            repo_name = issue.get('repo_name')
            repo_short = repo_name.split('/')[1] if '/' in repo_name else repo_name
            issue_id = issue.get('issue_number')
            rdir = get_reports_dir(org_slug, repo_short, issue_id)
            rfile = rdir / "research.md"
            if rfile.exists():
                with open(rfile, "r") as f:
                    self.send_json({"content": f.read()})
            else:
                self.send_json({"content": "(No research report found. Run hermes research first.)"})
                
        elif self.path.startswith('/api/plan'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            url = qs.get('url', [None])[0]
            if not url:
                self.send_json({"error": "Missing url"}, 400)
                return
            issue = get_issue_context(url)
            if not issue:
                self.send_json({"error": "Issue not found"}, 404)
                return
            org_slug = issue.get('org_slug')
            repo_name = issue.get('repo_name')
            repo_short = repo_name.split('/')[1] if '/' in repo_name else repo_name
            issue_id = issue.get('issue_number')
            pdir = get_reports_dir(org_slug, repo_short, issue_id)
            pfile = pdir / "plan.md"
            if pfile.exists():
                with open(pfile, "r") as f:
                    self.send_json({"content": f.read()})
            else:
                self.send_json({"content": "(No implementation plan found. Run hermes plan first.)"})
        elif self.path.startswith('/api/communication/'):
            # Communication review actions are state-changing: POST only.
            self.send_response(405)
            self.send_header('Allow', 'POST')
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Local-only state-changing dashboard actions.

        Communication review actions (approve / reject / edit) update ONLY the
        local Radar database via the existing opportunity_manager functions.
        They never post to GitHub, never create commits/branches/pushes/PRs,
        and never trigger sync, model inference, or the daily pipeline.
        """
        path = urllib.parse.urlparse(self.path).path

        try:
            content_length = int(self.headers.get('Content-Length', 0) or 0)
        except (TypeError, ValueError):
            content_length = 0
        raw = self.rfile.read(content_length) if content_length else b''
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON body"}, 400)
            return
        if not isinstance(body, dict):
            self.send_json({"error": "Invalid JSON body"}, 400)
            return

        url = body.get('url')
        if not url:
            self.send_json({"error": "Missing url"}, 400)
            return

        from src.opportunity_manager import (
            approve_communication,
            reject_communication,
            set_communication_recommendation,
            get_communication_state,
        )

        if path == '/api/communication/approve':
            if not approve_communication(url):
                self.send_json({"error": "Issue not found"}, 404)
                return
        elif path == '/api/communication/reject':
            if not reject_communication(url, body.get('reason')):
                self.send_json({"error": "Issue not found"}, 404)
                return
        elif path == '/api/communication/edit':
            recommendation = body.get('recommendation')
            if not recommendation or not str(recommendation).strip():
                self.send_json({"error": "Missing recommendation"}, 400)
                return
            current = get_communication_state(url)
            if not current:
                self.send_json({"error": "Issue not found"}, 404)
                return
            # Persist the edited reply locally; keep the existing reason.
            # Mirrors the generation path: a new recommendation resets the
            # review status so it must be re-approved by the human.
            set_communication_recommendation(
                url,
                str(recommendation).strip(),
                current.get("communication_reason") or "",
            )
        else:
            self.send_json({"error": "Not found"}, 404)
            return

        # Return the fresh local state so the UI can update immediately.
        self.send_json({"ok": True, "state": normalize_communication_state(get_communication_state(url))})

def run_dashboard():
    with socketserver.TCPServer(("127.0.0.1", PORT), DashboardHandler) as httpd:
        print(f"OSS Discovery Radar Dashboard serving at http://127.0.0.1:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard...")

if __name__ == '__main__':
    run_dashboard()
