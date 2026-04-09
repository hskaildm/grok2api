/* Status page logic */

const AUTO_REFRESH_INTERVAL = 10000;
let autoRefreshTimer = null;

// ── API ──────────────────────────────────────────────────────────────────

async function fetchStatus() {
  const apiKey = await ensureAdminKey();
  if (!apiKey) return null;
  try {
    const res = await fetch('/v1/admin/status', {
      headers: buildAuthHeaders(apiKey),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function formatDuration(ms) {
  const val = Number(ms) || 0;
  if (val >= 1000) return `${(val / 1000).toFixed(2)}s`;
  return `${val.toFixed(0)}ms`;
}

function barColor(pct) {
  if (pct < 60) return 'green';
  if (pct < 85) return 'orange';
  return 'red';
}

// ── Section 1: System info ──────────────────────────────────────────────

function renderSystem(data) {
  const s = data.system || {};
  setText('s-uptime', s.uptime ?? '—');
  setText('s-started-at', s.started_at ?? '—');
  setText('s-python', s.python_version ?? '—');
  setText('s-platform', s.platform ?? '—');
}

// ── Section 2: Resources ────────────────────────────────────────────────

function renderResources(data) {
  const r = data.resources || {};

  if (!r.psutil_available) {
    document.getElementById('resource-section').classList.add('hidden');
    document.getElementById('psutil-notice').classList.remove('hidden');
    return;
  }

  document.getElementById('resource-section').classList.remove('hidden');
  document.getElementById('psutil-notice').classList.add('hidden');

  // CPU
  setText('s-cpu', `${r.cpu_percent ?? '—'}%`);
  setText('s-cpu-cores', `${r.cpu_count ?? '—'} 核`);
  const cpuBar = document.getElementById('cpu-bar');
  if (cpuBar && r.cpu_percent != null) {
    cpuBar.style.width = `${r.cpu_percent}%`;
    cpuBar.className = `resource-bar ${barColor(r.cpu_percent)}`;
  }

  // Memory
  setText('s-mem-proc', `${r.memory_used_mb ?? '—'} MB`);
  setText('s-mem-total', `${r.memory_total_mb ?? '—'} MB`);
  setText('s-mem-avail', `${r.memory_available_mb ?? '—'} MB`);
  setText('s-mem-pct', `${r.memory_percent ?? '—'}%`);
  const memBar = document.getElementById('mem-bar');
  if (memBar && r.memory_percent != null) {
    memBar.style.width = `${r.memory_percent}%`;
    memBar.className = `resource-bar ${barColor(r.memory_percent)}`;
  }

  // Disk
  setText('s-disk-total', r.disk_total ?? '—');
  setText('s-disk-used', r.disk_used ?? '—');
  setText('s-disk-free', r.disk_free ?? '—');
  setText('s-disk-pct', `${r.disk_percent ?? '—'}%`);
  const diskBar = document.getElementById('disk-bar');
  if (diskBar && r.disk_percent != null) {
    diskBar.style.width = `${r.disk_percent}%`;
    diskBar.className = `resource-bar ${barColor(r.disk_percent)}`;
  }

  // Network
  setText('s-net-sent', r.net_sent ?? '—');
  setText('s-net-recv', r.net_recv ?? '—');
}

// ── Section 3: Token stats ──────────────────────────────────────────────

function renderTokens(data) {
  const tk = data.tokens || {};
  const tot = tk.totals || {};

  setText('t-total', tot.total ?? '—');
  setText('t-active', tot.active ?? '—');
  setText('t-cooling', tot.cooling ?? '—');
  setText('t-expired', tot.expired ?? '—');

  const pools = tk.pools || {};
  const tbody = document.getElementById('token-pools-body');
  const entries = Object.entries(pools);

  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="table-empty">无 Token 池数据</td></tr>';
    return;
  }

  tbody.innerHTML = entries.map(([name, s]) => `
    <tr>
      <td class="text-left"><span class="pool-name">${escapeHtml(name)}</span></td>
      <td class="text-right mono-num">${s.total}</td>
      <td class="text-right mono-num" style="color:#059669">${s.active}</td>
      <td class="text-right mono-num" style="color:#d97706">${s.cooling}</td>
      <td class="text-right mono-num" style="color:#dc2626">${s.expired}</td>
      <td class="text-right mono-num" style="color:#6b7280">${s.disabled}</td>
      <td class="text-right mono-num">${s.total_quota}</td>
      <td class="text-right mono-num">${s.avg_quota}</td>
      <td class="text-right mono-num">${s.total_consumed}</td>
    </tr>
  `).join('');
}

// ── Section 4: Call stats ───────────────────────────────────────────────

function renderCalls(data) {
  const c = data.calls || {};

  setText('c-total', c.total ?? '—');
  setText('c-success', c.success ?? '—');
  setText('c-4xx', c.client_errors ?? '—');
  setText('c-5xx', c.server_errors ?? '—');
  setText('c-rate', c.total ? `${c.success_rate}%` : '—');
  setText('c-avg-dur', c.total ? formatDuration(c.avg_duration_ms) : '—');

  const models = c.by_model || [];
  const tbody = document.getElementById('model-stats-body');

  if (!models.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="table-empty">暂无调用记录</td></tr>';
    return;
  }

  tbody.innerHTML = models.map(m => `
    <tr>
      <td class="text-left"><span class="model-name" title="${escapeHtml(m.model)}">${escapeHtml(m.model)}</span></td>
      <td class="text-right mono-num">${m.calls}</td>
      <td class="text-right mono-num" style="color:#059669">${m.success}</td>
      <td class="text-right mono-num" style="color:#dc2626">${m.errors}</td>
      <td class="text-right mono-num">${formatDuration(m.avg_duration_ms)}</td>
    </tr>
  `).join('');
}

// ── Load & refresh ──────────────────────────────────────────────────────

async function loadStatus() {
  const data = await fetchStatus();
  if (!data) return;
  renderSystem(data);
  renderResources(data);
  renderTokens(data);
  renderCalls(data);
}

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(loadStatus, AUTO_REFRESH_INTERVAL);
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

// ── Init ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await loadStatus();
  startAutoRefresh();

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopAutoRefresh();
    } else {
      loadStatus();
      startAutoRefresh();
    }
  });
});
