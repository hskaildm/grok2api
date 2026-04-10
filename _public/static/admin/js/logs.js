/* Logs page logic */

let currentPage = 1;
let pageSize = 20;
let autoRefreshTimer = null;

const AUTO_REFRESH_INTERVAL = 10000; // 10s

// ---- API ----

async function fetchLogs(page, size) {
  const apiKey = await ensureAdminKey();
  if (!apiKey) return null;
  try {
    const res = await fetch(`/v1/admin/logs?page=${page}&page_size=${size}`, {
      headers: buildAuthHeaders(apiKey),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function clearLogsApi() {
  const apiKey = await ensureAdminKey();
  if (!apiKey) return null;
  try {
    const res = await fetch('/v1/admin/logs/clear', {
      method: 'POST',
      headers: buildAuthHeaders(apiKey),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

// ---- Render ----

function statusBadge(code) {
  if (code >= 500) return `<span class="log-badge log-badge-red">${code}</span>`;
  if (code >= 400) return `<span class="log-badge log-badge-orange">${code}</span>`;
  if (code >= 200 && code < 300) return `<span class="log-badge log-badge-green">${code}</span>`;
  return `<span class="log-badge log-badge-gray">${code}</span>`;
}

function methodBadge(method) {
  const m = (method || '').toUpperCase();
  if (m === 'POST') return `<span class="method-badge method-post">${m}</span>`;
  if (m === 'GET') return `<span class="method-badge method-get">${m}</span>`;
  return `<span class="method-badge method-other">${m}</span>`;
}

function durationText(ms) {
  const val = Number(ms) || 0;
  const text = val >= 1000 ? `${(val / 1000).toFixed(2)}s` : `${val.toFixed(0)}ms`;
  if (val >= 10000) return `<span class="log-duration log-duration-very-slow">${text}</span>`;
  if (val >= 3000) return `<span class="log-duration log-duration-slow">${text}</span>`;
  return `<span class="log-duration">${text}</span>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function taskProgressHtml(log) {
  const status = log.task_status;
  if (!status) return '<span class="log-badge log-badge-gray">—</span>';
  if (status === 'completed') return '<span class="log-badge log-badge-green">completed</span>';
  if (status === 'failed') return '<span class="log-badge log-badge-red">failed</span>';
  if (status === 'in_progress') {
    const pct = (log.task_progress != null) ? `${log.task_progress}%` : '...';
    const detail = log.task_progress_detail ? ` ${escapeHtml(log.task_progress_detail)}` : '';
    return `<span class="log-badge log-badge-blue">${pct}${detail}</span>`;
  }
  return `<span class="log-badge log-badge-gray">${escapeHtml(status)}</span>`;
}

function renderDetailRow(log) {
  const parts = [];
  if (log.task_id) parts.push(`<b>Task ID:</b> ${escapeHtml(log.task_id)}`);
  if (log.task_status) parts.push(`<b>状态:</b> ${escapeHtml(log.task_status)}`);
  if (log.task_progress != null) parts.push(`<b>进度:</b> ${log.task_progress}%`);
  if (log.task_progress_detail) parts.push(`<b>轮次:</b> ${escapeHtml(log.task_progress_detail)}`);
  if (log.task_error) parts.push(`<b>错误:</b> <span style="color:#dc2626">${escapeHtml(log.task_error)}</span>`);
  if (log.task_result) {
    const r = log.task_result;
    if (r.url) parts.push(`<b>视频链接:</b> <a href="${escapeHtml(r.url)}" target="_blank" style="color:#2563eb;text-decoration:underline;word-break:break-all">${escapeHtml(r.url)}</a>`);
    if (r.prompt) parts.push(`<b>提示词:</b> ${escapeHtml(r.prompt)}`);
    if (r.model) parts.push(`<b>模型:</b> ${escapeHtml(r.model)}`);
    if (r.size) parts.push(`<b>尺寸:</b> ${escapeHtml(r.size)}`);
    if (r.seconds) parts.push(`<b>时长:</b> ${escapeHtml(r.seconds)}s`);
    if (r.quality) parts.push(`<b>质量:</b> ${escapeHtml(r.quality)}`);
  }
  if (log.trace_id) parts.push(`<b>Trace ID:</b> <span style="opacity:0.5">${escapeHtml(log.trace_id)}</span>`);
  if (log.error) parts.push(`<b>异常:</b> <span style="color:#dc2626">${escapeHtml(log.error)}</span>`);
  return parts.join('<br>');
}

function renderTable(data) {
  const tbody = document.getElementById('logs-body');
  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="table-empty">暂无调用记录</td></tr>';
    return;
  }
  tbody.innerHTML = data.map((log, idx) => {
    const hasDetail = log.task_id || log.error || log.trace_id;
    const cursorStyle = hasDetail ? 'cursor:pointer' : '';
    const row = `
    <tr class="log-row" style="${cursorStyle}" onclick="${hasDetail ? `toggleDetail('detail-${idx}')` : ''}">
      <td class="text-left"><span class="log-time">${escapeHtml(log.time)}</span></td>
      <td>${methodBadge(log.method)}</td>
      <td class="text-left"><span class="log-path" title="${escapeHtml(log.path)}">${escapeHtml(log.path)}</span></td>
      <td class="text-left"><span class="log-model" title="${escapeHtml(log.model)}">${escapeHtml(log.model) || '-'}</span></td>
      <td>${statusBadge(log.status)}</td>
      <td class="text-center">${taskProgressHtml(log)}</td>
      <td class="text-right">${durationText(log.duration_ms)}</td>
      <td class="text-left"><span class="log-ip">${escapeHtml(log.ip) || '-'}</span></td>
    </tr>`;
    const detail = hasDetail ? `
    <tr id="detail-${idx}" class="log-detail-row" style="display:none">
      <td colspan="8" class="log-detail-cell">${renderDetailRow(log)}</td>
    </tr>` : '';
    return row + detail;
  }).join('');
}

function toggleDetail(id) {
  const row = document.getElementById(id);
  if (row) {
    row.style.display = row.style.display === 'none' ? '' : 'none';
  }
}

function renderStats(data) {
  if (!data) return;
  let total = 0, success = 0, clientErr = 0, serverErr = 0;
  // Stats are computed from the full dataset total, but we only have page data
  // Use the total count from API and compute from visible data as approximation
  document.getElementById('stat-total').textContent = data.total || 0;

  // Compute from current page data
  const items = data.data || [];
  items.forEach(log => {
    if (log.status >= 500) serverErr++;
    else if (log.status >= 400) clientErr++;
    else if (log.status >= 200 && log.status < 300) success++;
  });
  // For stats, show page-level counts with total
  document.getElementById('stat-success').textContent = success;
  document.getElementById('stat-client-err').textContent = clientErr;
  document.getElementById('stat-server-err').textContent = serverErr;
}

function renderPagination(data) {
  if (!data) return;
  const pages = data.pages || 1;
  const page = data.page || 1;
  const total = data.total || 0;

  document.getElementById('page-info').textContent = `${page} / ${pages} (${total} 条)`;

  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  btnPrev.disabled = page <= 1;
  btnNext.disabled = page >= pages;
}

// ---- Actions ----

async function loadLogs() {
  const data = await fetchLogs(currentPage, pageSize);
  if (data) {
    renderTable(data.data);
    renderStats(data);
    renderPagination(data);
  }
}

async function handleClearLogs() {
  if (!confirm('确定要清空所有调用日志吗？')) return;
  const result = await clearLogsApi();
  if (result && result.status === 'success') {
    if (typeof showToast === 'function') {
      showToast(`已清空 ${result.cleared} 条日志`, 'success');
    }
    currentPage = 1;
    await loadLogs();
  } else {
    if (typeof showToast === 'function') {
      showToast('清空失败', 'error');
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshTimer = setInterval(loadLogs, AUTO_REFRESH_INTERVAL);
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', async () => {
  // Page size selector
  const pageSizeSelect = document.getElementById('page-size-select');
  pageSizeSelect.addEventListener('change', () => {
    pageSize = parseInt(pageSizeSelect.value, 10) || 20;
    currentPage = 1;
    loadLogs();
  });

  // Pagination buttons
  document.getElementById('btn-prev').addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      loadLogs();
    }
  });

  document.getElementById('btn-next').addEventListener('click', () => {
    currentPage++;
    loadLogs();
  });

  // Initial load
  await loadLogs();

  // Auto refresh
  startAutoRefresh();

  // Pause auto refresh when page is hidden
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopAutoRefresh();
    } else {
      loadLogs();
      startAutoRefresh();
    }
  });
});
