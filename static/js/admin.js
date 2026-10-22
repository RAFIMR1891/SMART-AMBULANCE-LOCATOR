// ── Smart Ambulance Locator — Admin/Dispatcher Portal JS ──────────────────
// Pollachi-centered map | Auto-dispatch | Manual fallback | Fleet filters
"use strict";
let lastRec = null, AMB = [], INC = [], currentMode = 'manual';
// Default Pollachi, Tamil Nadu
const POLLACHI = {lat: 10.6550, lng: 76.9988};
let ambFilter = '';

// ── Load all dashboard data ────────────────────────────────────────────────
async function load() {
  const [s, a, i, d, u, h, hi, fallback] = await Promise.all([
    '/api/dashboard/summary',
    '/api/ambulances',
    '/api/incidents',
    '/api/dispatches',
    '/api/admin/users',
    '/api/hospitals',
    '/api/dispatch-history',
    '/api/incidents/needs-dispatch',
  ].map(url => api(url)));

  if (s.success) { renderStats(s.data); currentMode = s.data.dispatch_mode || 'manual'; updateModeBanner(); }
  if (a.success) { AMB = a.data; renderAmbulances(); }
  if (i.success) { INC = i.data; renderIncidents(); }
  if (d.success) renderDispatches(d.data);
  if (u.success) renderUsers(u.data);
  if (h.success) renderHospitals(h.data);
  if (hi.success) renderHistory(hi.data);
  if (fallback.success) renderFallback(fallback.data);
  drawMap();
  checkGemini();
}

// ── Mode banner ────────────────────────────────────────────────────────────
let modeSwitching = false;

function updateModeBanner() {
  const banner = document.getElementById('dispatchModeBanner');
  const label  = document.getElementById('dispatchModeLabel');
  const desc   = document.getElementById('dispatchModeDesc');
  const btnToggle = document.getElementById('btnToggleMode');
  if (!banner || !label) return;

  if (currentMode === 'automatic') {
    banner.className = 'dispatch-mode-banner mode-automatic';
    label.innerHTML  = '⚡ <strong>AI AUTOMATIC DISPATCH: ON</strong>';
    if (desc) desc.textContent = 'Rule-based engine automatically assigns eligible ambulances';
    if (btnToggle) {
      btnToggle.className = 'btn btn-sm btn-outline-danger fw-semibold';
      btnToggle.innerHTML = '⏸️ Turn AI Dispatch OFF';
      btnToggle.disabled = modeSwitching;
    }
  } else {
    banner.className = 'dispatch-mode-banner mode-manual';
    label.innerHTML  = '🔧 <strong>MANUAL DISPATCH MODE</strong>';
    if (desc) desc.textContent = 'Automatic dispatch paused — requests await dispatcher assignment';
    if (btnToggle) {
      btnToggle.className = 'btn btn-sm btn-success fw-semibold';
      btnToggle.innerHTML = '⚡ Turn AI Dispatch ON';
      btnToggle.disabled = modeSwitching;
    }
  }
}

async function toggleMode() {
  if (modeSwitching) return;
  const targetMode = currentMode === 'automatic' ? 'manual' : 'automatic';
  const actionText = targetMode === 'automatic' ? 'TURN ON AI Automatic Dispatch' : 'TURN OFF AI Automatic Dispatch and switch to Manual Mode';
  
  if (!confirm(`Are you sure you want to ${actionText}?`)) return;
  const reason = prompt(`Please enter a reason for switching to ${targetMode.toUpperCase()} mode:`, `Administrative mode change to ${targetMode}`);
  if (reason === null) return;
  if (!reason.trim()) {
    toast('A reason is required to switch dispatch modes.', 'warning');
    return;
  }

  modeSwitching = true;
  updateModeBanner();
  try {
    const r = await api('/api/settings/dispatch-mode', 'POST', {mode: targetMode, reason: reason.trim()});
    if (r.success) {
      toast(`✅ Successfully switched to ${targetMode.toUpperCase()} mode!`, 'success');
      currentMode = targetMode;
      updateModeBanner();
      await load();
    } else {
      toast(`❌ Failed to change mode: ${r.error}`, 'danger');
    }
  } catch (err) {
    toast(`❌ Communication error: ${err.message}`, 'danger');
  } finally {
    modeSwitching = false;
    updateModeBanner();
  }
}

async function setMode(mode) {
  if (mode === currentMode) return;
  await toggleMode();
}

// ── Gemini status & settings ───────────────────────────────────────────────
async function checkGemini() {
  const el = document.getElementById('geminiStatus');
  const badge = document.getElementById('geminiKeyBadge');
  const currentKey = document.getElementById('geminiCurrentKeyLabel');
  const modelSelect = document.getElementById('geminiModelInput');
  const r = await api('/api/settings/gemini');
  if (r.success) {
    if (modelSelect && r.data.model) modelSelect.value = r.data.model;
    if (r.data.configured) {
      if (badge) { badge.className = 'badge bg-success'; badge.textContent = 'Active & Configured'; }
      if (currentKey) currentKey.textContent = `Current key: ${r.data.masked_key || 'Configured'} (${r.data.model})`;
      if (el) el.classList.add('d-none');
    } else {
      if (badge) { badge.className = 'badge bg-warning text-dark'; badge.textContent = 'Unconfigured'; }
      if (currentKey) currentKey.textContent = `Status: ${r.data.masked_key || 'No valid API key'}`;
      if (el) {
        el.className = 'alert alert-warning py-2 small';
        el.textContent = '⚠️ Gemini AI not configured — enter your Google Gemini API key above or set GEMINI_API_KEY in .env';
        el.classList.remove('d-none');
      }
    }
  }
}

async function saveGeminiSettings() {
  const keyInput = document.getElementById('geminiApiKeyInput');
  const modelSelect = document.getElementById('geminiModelInput');
  const apiKey = (keyInput?.value || '').trim();
  const model = modelSelect?.value || 'gemini-1.5-flash-latest';
  if (!apiKey) {
    toast('Please enter a Gemini API Key', 'warning');
    return;
  }
  const r = await api('/api/settings/gemini', 'POST', {api_key: apiKey, model});
  if (r.success) {
    toast('✅ Google Gemini API Key saved and activated!', 'success');
    if (keyInput) keyInput.value = '';
    checkGemini();
  } else {
    toast('Failed to save Gemini key: ' + (r.error || 'Unknown error'), 'danger');
  }
}

// ── Dashboard stats ────────────────────────────────────────────────────────
function renderStats(v) {
  const el = document.getElementById('a_stats');
  if (!el) return;
  const needs = v.needs_human || 0;
  el.innerHTML = `<div class="row g-3">` +
    stat('🚨', 'i-r', v.new_requests,    'Pending Requests') +
    stat('🟢', 'i-g', v.available,        'Available') +
    stat('🚑', 'i-b', v.assigned,          'Assigned/Dispatched') +
    stat('➡️', 'i-g', v.en_route,          'En Route') +
    stat('✅', 'i-o', v.completed_today,   'Completed Today') +
    stat('⚡', 'i-b', v.auto_dispatched || 0, 'Auto-Dispatched') +
    stat('👤', 'i-o', v.manual_fallback || 0, 'Manual Fallback') +
    stat(needs > 0 ? '🔴' : '⚪', needs > 0 ? 'i-r' : 'i-g', needs, 'Needs Human Action') +
    `</div>`;

  // Show/hide failure banner
  const banner = document.getElementById('failureBanner');
  if (banner) {
    if (needs > 0) {
      document.getElementById('failureBannerText').textContent =
        ` ${needs} incident(s) could not be auto-dispatched and require manual assignment.`;
      banner.classList.remove('d-none');
    } else {
      banner.classList.add('d-none');
    }
  }

  // Update fallback nav badge
  const navBadge = document.getElementById('navFallbackBadge');
  if (navBadge && needs > 0)
    navBadge.innerHTML = `Dispatcher Fallback <span class="badge bg-danger ms-1">${needs}</span>`;
}

// ── Incidents ──────────────────────────────────────────────────────────────
function renderIncidents() {
  const filterVal = document.getElementById('reqFilter')?.value || '';
  const filtered  = filterVal ? INC.filter(x => x.status === filterVal) : INC;
  const open      = INC.filter(x => !['Closed','Cancelled'].includes(x.status));

  const activeEl = document.getElementById('a_active');
  if (activeEl) {
    activeEl.innerHTML = open.map(x => `<tr>
      <td class="text-nowrap">${when(x.reported_at)}</td>
      <td class="text-nowrap">${(+x.latitude).toFixed(3)}, ${(+x.longitude).toFixed(3)}</td>
      <td>${esc(x.incident_type)}</td>
      <td>${badge(x.status)}</td>
      <td><span class="badge ${x.dispatch_mode === 'Automatic' ? 'bg-info text-dark' : 'bg-secondary'}">${esc(x.dispatch_mode || 'Manual')}</span></td>
      <td>
        <a class="btn btn-primary btn-sm" href="#requests" onclick="nav('requests');recommend(${x.id})">Assign</a>
        <button class="btn btn-outline-success btn-sm ms-1" onclick="autoDispatchNow(${x.id})">⚡ Auto</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="6" class="text-center text-muted py-4">No active requests.</td></tr>';
  }

  const incEl = document.getElementById('a_inc');
  if (incEl) {
    incEl.innerHTML = filtered.map(x => `<tr>
      <td><b>${esc(x.incident_code)}</b></td>
      <td class="text-nowrap">${when(x.reported_at)}</td>
      <td>${esc(x.incident_type)}</td>
      <td class="text-nowrap small">${(+x.latitude).toFixed(4)}, ${(+x.longitude).toFixed(4)}</td>
      <td>${x.estimated_patient_count}</td>
      <td>${badge(x.status)}</td>
      <td><span class="badge ${x.dispatch_mode === 'Automatic' ? 'bg-info text-dark' : x.dispatch_mode === 'Manual Fallback' ? 'bg-warning text-dark' : 'bg-secondary'}">${esc(x.dispatch_mode || '—')}</span></td>
      <td class="text-nowrap">
        <button class="btn btn-outline-primary btn-sm" onclick="recommend(${x.id})">🔍 Find Ambulances</button>
        <button class="btn btn-outline-success btn-sm ms-1" onclick="autoDispatchNow(${x.id})" title="Auto-Dispatch Now">⚡</button>
        ${x.status !== 'Closed' && x.status !== 'Cancelled' ? `<button class="btn btn-outline-secondary btn-sm ms-1" onclick="addPatients(${x.id})">+ Patients</button>` : ''}
      </td>
    </tr>`).join('') || '<tr><td colspan="8" class="text-center text-muted py-4">No incidents found.</td></tr>';
  }

  const aiEl = document.getElementById('ai_inc');
  if (aiEl)
    aiEl.innerHTML = INC.map(x => `<option value="${x.id}">${esc(x.incident_code)} — ${esc(x.title)}</option>`).join('');
}

// ── Ambulances ─────────────────────────────────────────────────────────────
let _ambFilterVal = '';
function filterAmb(val) {
  _ambFilterVal = val;
  const label = document.getElementById('ambFilterLabel');
  if (label) label.textContent = val ? `Showing: ${val}` : 'Showing all';
  renderAmbulances();
}

function renderAmbulances() {
  const el = document.getElementById('a_amb');
  if (!el) return;
  let data = AMB;
  if (_ambFilterVal === 'simulated') data = AMB.filter(x => x.is_simulated);
  else if (_ambFilterVal === 'real')  data = AMB.filter(x => !x.is_simulated);
  else if (_ambFilterVal)             data = AMB.filter(x => x.status === _ambFilterVal);

  el.innerHTML = data.map(x => `<tr class="${x.is_simulated ? 'table-secondary' : ''}">
    <td><b>${esc(x.ambulance_code)}</b></td>
    <td>${esc(x.registration_number)}</td>
    <td>${esc(x.driver_name || '—')}</td>
    <td>
      <select class="form-select form-select-sm" style="min-width:130px" onchange="setStatus(${x.id},this.value)">
        ${['Available','Assigned','Dispatched','En route','At scene','Transporting patient','Out of service']
          .map(o => `<option ${o === x.status ? 'selected' : ''}>${o}</option>`).join('')}
      </select>
    </td>
    <td class="text-nowrap">${(+x.latitude).toFixed(4)}, ${(+x.longitude).toFixed(4)}</td>
    <td class="text-nowrap">${when(x.last_location_update)}</td>
    <td>${x.capacity || '—'}</td>
    <td class="small">${esc(x.equipment || '—')}</td>
    <td>${esc(x.current_incident || '—')}</td>
    <td>${x.is_simulated ? '<span class="badge bg-info text-dark">Simulated</span>' : '<span class="badge bg-success">Real</span>'}</td>
  </tr>`).join('') || '<tr><td colspan="10" class="text-center text-muted py-4">No ambulances found.</td></tr>';
}

// ── Dispatcher Fallback Panel ──────────────────────────────────────────────
async function renderFallback(incidents) {
  const el = document.getElementById('fallbackContent');
  if (!el) return;

  const needsAction = incidents.filter(x => !['Closed','Cancelled'].includes(x.status));
  if (!needsAction.length) {
    el.innerHTML = `<div class="cardx text-center py-4 text-success">
      <h5>✅ No incidents requiring manual dispatch action</h5>
      <p class="text-muted">All open incidents are either assigned or no pending requests exist.</p>
    </div>`;
    return;
  }

  el.innerHTML = needsAction.map(x => `
    <div class="cardx fallback-card" id="fallback_${x.id}">
      <div class="d-flex justify-content-between align-items-start">
        <div>
          <h6 class="mb-1">🚨 <strong>${esc(x.incident_code)}</strong> — ${esc(x.incident_type)}</h6>
          <div class="text-muted small mb-2">
            📍 ${(+x.latitude).toFixed(4)}, ${(+x.longitude).toFixed(4)} &nbsp;|&nbsp;
            👥 ${x.estimated_patient_count} patient(s) &nbsp;|&nbsp;
            ⏱ Received: ${when(x.reported_at)} &nbsp;|&nbsp;
            Status: ${badge(x.status)}
          </div>
          ${x.last_fail_reason ? `<div class="alert alert-warning py-1 small mb-2">
            <strong>⚠️ Auto-dispatch failure:</strong> ${esc(x.last_fail_reason)}
          </div>` : ''}
        </div>
        <span class="badge bg-danger">Needs Action</span>
      </div>
      <div id="fallbackRec_${x.id}" class="mt-2">
        <button class="btn btn-warning btn-sm" onclick="findFallbackAmb(${x.id})">
          🔍 Find Eligible Ambulances
        </button>
        <span class="text-muted small ms-2">Review candidates before dispatching</span>
      </div>
    </div>
  `).join('');
}

async function findFallbackAmb(iid) {
  const el = document.getElementById(`fallbackRec_${iid}`);
  if (!el) return;
  el.innerHTML = '<div class="spinner-border spinner-border-sm text-warning me-2"></div> Searching…';
  const r = await api(`/api/incidents/${iid}/recommend-ambulances`, 'POST', {});
  if (!r.success) { el.innerHTML = `<div class="alert alert-danger">${esc(r.error)}</div>`; return; }

  const {eligible, excluded} = r.data;
  const warn = r.maps_warning
    ? `<div class="alert alert-warning py-1 small">⚠️ ${esc(r.maps_warning)} — Ranked by straight-line distance.</div>` : '';

  el.innerHTML = warn + (eligible.length
    ? `<div class="table-responsive">
        <table class="table table-sm">
          <thead><tr>
            <th></th><th>Ambulance</th><th>Driver</th><th>Area</th><th>Capacity</th>
            <th>Equipment</th><th>Distance</th><th>ETA</th><th>GPS Age</th><th>Type</th><th>Why Chosen</th>
          </tr></thead>
          <tbody>` +
        eligible.map(x => `<tr ${x.is_simulated ? 'class="table-secondary"' : ''}>
          <td><input type="radio" name="fallback_pick_${iid}" class="fallback-pick form-check-input" value="${x.id}"></td>
          <td><b>${esc(x.ambulance)}</b></td>
          <td>${esc(x.driver_name || '—')}</td>
          <td>${esc(x.service_area || '—')}</td>
          <td>${x.capacity}</td>
          <td class="small">${esc(x.equipment || '—')}</td>
          <td>${x.distance_km} km</td>
          <td>${x.eta_seconds != null ? Math.round(x.eta_seconds/60)+' min' : '—'}</td>
          <td class="small">${x.last_location_update ? 'OK' : 'N/A'}</td>
          <td>${x.is_simulated ? '<span class="badge bg-info text-dark">Sim</span>' : '<span class="badge bg-success">Real</span>'}</td>
          <td class="small text-muted">${esc(x.reason)}</td>
        </tr>`).join('') +
        `</tbody></table></div>
        <div class="d-flex align-items-center gap-2 mt-2">
          <input id="fallback_override_${iid}" class="form-control form-control-sm" style="max-width:300px" placeholder="Override reason (optional)">
          <button class="btn btn-danger btn-sm" onclick="confirmFallbackDispatch(${iid})">
            ✅ Confirm Manual Dispatch
          </button>
        </div>`
    : `<div class="alert alert-danger">
        <strong>No Eligible Ambulance Available</strong>
        <p class="mb-0 small mt-1">All candidates are unavailable, assigned, or do not meet requirements. 
        ${excluded.length ? 'Excluded: ' + excluded.slice(0,3).map(e => esc(e.reason)).join('; ') : ''}</p>
        <button class="btn btn-outline-secondary btn-sm mt-2" onclick="findFallbackAmb(${iid})">🔄 Retry</button>
      </div>`);
}

async function confirmFallbackDispatch(iid) {
  const picked = document.querySelector(`input[name="fallback_pick_${iid}"]:checked`);
  if (!picked) { toast('Select an ambulance first', 'warning'); return; }
  const override = document.getElementById(`fallback_override_${iid}`)?.value || '';
  if (!confirm(`Confirm manual dispatch of ambulance to incident #${iid}?`)) return;
  const r = await api(`/api/incidents/${iid}/dispatch`, 'POST', {
    ambulance_ids: [+picked.value],
    override_reason: override,
    dispatch_mode_label: 'Manual Fallback'
  });
  toast(r.success ? `✅ Ambulance dispatched (Manual Fallback)` : r.error,
        r.success ? 'success' : 'danger');
  if (r.success) load();
}

// ── Recommend ambulances (manual mode) ────────────────────────────────────
async function recommend(id) {
  lastRec = id;
  const recEl = document.getElementById('rec');
  if (!recEl) return;
  recEl.innerHTML = '<div class="d-flex align-items-center gap-2 mt-3"><div class="spinner-border spinner-border-sm text-primary"></div> Finding eligible ambulances…</div>';
  const r = await api(`/api/incidents/${id}/recommend-ambulances`, 'POST', {});
  if (!r.success) { recEl.innerHTML = ''; toast(r.error, 'danger'); return; }

  const {eligible, excluded} = r.data;
  const warn = r.maps_warning
    ? `<div class="alert alert-warning py-2 small">⚠️ ${esc(r.maps_warning)} — Ranked by straight-line Haversine distance.</div>` : '';

  recEl.innerHTML = `<hr><h6>🔍 Eligible Ambulances for Incident #${id}</h6>${warn}` +
    (eligible.length
      ? `<div class="table-responsive"><table class="table table-sm">
          <thead><tr>
            <th></th><th>Ambulance</th><th>Driver</th><th>Area</th><th>Capacity</th>
            <th>Equipment</th><th>Distance</th><th>ETA</th><th>Type</th><th>Decision Basis</th>
          </tr></thead>
          <tbody>` +
        eligible.map(x => `<tr ${x.is_simulated ? 'class="table-secondary"' : ''}>
          <td><input type="checkbox" class="pick form-check-input" value="${x.id}"></td>
          <td><b>${esc(x.ambulance)}</b></td>
          <td>${esc(x.driver_name || '—')}</td>
          <td>${esc(x.service_area || '—')}</td>
          <td>${x.capacity}</td>
          <td class="small">${esc(x.equipment || '—')}</td>
          <td>${x.distance_km} km</td>
          <td>${x.eta_seconds != null ? Math.round(x.eta_seconds/60)+' min' : '—'}</td>
          <td>${x.is_simulated ? '<span class="badge bg-info text-dark">Sim</span>' : '<span class="badge bg-success">Real</span>'}</td>
          <td class="small text-muted">${esc(x.reason)}</td>
        </tr>`).join('') +
        `</tbody></table></div>
        ${excluded.length ? `<details class="mb-2"><summary class="text-muted small">${excluded.length} excluded (click to view)</summary>
          <ul class="small text-muted mt-1">${excluded.map(e=>`<li>${esc(e.reason)}</li>`).join('')}</ul>
        </details>` : ''}
        <div class="d-flex align-items-center gap-2 mt-2">
          <input id="override_reason" class="form-control form-control-sm" style="max-width:300px" placeholder="Override reason (optional)">
          <button class="btn btn-success" onclick="confirmDispatch()">✅ Confirm Dispatch Selected</button>
          <button class="btn btn-outline-success ms-1" onclick="autoDispatchNow(${id})">⚡ Auto-Dispatch Best</button>
        </div>`
      : `<div class="alert alert-danger">
          <strong>No eligible ambulances available.</strong>
          ${excluded.length ? `<br><small>${excluded.slice(0,3).map(e=>esc(e.reason)).join('; ')}</small>` : ''}
        </div>`);
}

async function confirmDispatch() {
  const ids = [...document.querySelectorAll('.pick:checked')].map(e => +e.value);
  if (!ids.length) { toast('Select at least one ambulance first', 'warning'); return; }
  const override = document.getElementById('override_reason')?.value || '';
  if (!confirm(`Dispatch ${ids.length} ambulance(s) to this incident?`)) return;
  const r = await api(`/api/incidents/${lastRec}/dispatch`, 'POST', {
    ambulance_ids: ids,
    override_reason: override,
    dispatch_mode_label: 'Manual'
  });
  toast(r.success ? `✅ ${ids.length} ambulance(s) dispatched` : r.error,
        r.success ? 'success' : 'danger');
  if (r.success) { document.getElementById('rec').innerHTML = ''; load(); }
}

async function autoDispatchNow(iid) {
  if (!confirm(`Attempt automatic dispatch for incident #${iid}?`)) return;
  const r = await api(`/api/incidents/${iid}/auto-dispatch`, 'POST', {});
  if (r.success) {
    toast(`✅ Auto-dispatched: ${r.data?.ambulance_code || 'Done'}`, 'success');
    load();
  } else {
    toast(`⚠️ Auto-dispatch failed: ${r.error}`, 'danger');
    // Show fallback panel
    nav('fallback');
    load();
  }
}

// ── Dispatches table ───────────────────────────────────────────────────────
function renderDispatches(data) {
  const el = document.getElementById('a_disp');
  if (!el) return;
  el.innerHTML = data.map(x => `<tr>
    <td><b>${esc(x.ambulance_code)}</b>${x.is_simulated ? ' <span class="badge bg-info text-dark">Sim</span>':''}</td>
    <td>${esc(x.incident_code)}</td>
    <td>${x.distance_km ? x.distance_km + ' km' : '—'}</td>
    <td class="small">${esc(x.eta_source || '—')}</td>
    <td><span class="badge ${x.dispatch_mode === 'Automatic' ? 'bg-info text-dark' : x.dispatch_mode === 'Manual Fallback' ? 'bg-warning text-dark' : 'bg-secondary'}">${esc(x.dispatch_mode || 'Manual')}</span></td>
    <td>${when(x.assigned_at)}</td>
    <td>${badge(x.status)}</td>
    <td>${x.status === 'Active' ? `<button class="btn btn-outline-danger btn-sm" onclick="cancelDispatch(${x.id})">Cancel</button>` : ''}</td>
  </tr>`).join('') || '<tr><td colspan="8" class="text-center text-muted py-4">No dispatches yet.</td></tr>';
}

// ── Users, Hospitals, History ──────────────────────────────────────────────
function renderUsers(data) {
  const el = document.getElementById('a_users');
  if (!el) return;
  el.innerHTML = data.map(x => `<tr>
    <td><b>${esc(x.name)}</b></td>
    <td><code>${esc(x.email)}</code></td>
    <td><span class="badge ${x.role === 'admin' ? 'bg-danger' : x.role === 'dispatcher' ? 'bg-primary' : x.role === 'driver' ? 'bg-success' : 'bg-secondary'}">${esc(x.role)}</span></td>
    <td>
      ${x.ambulance_code ? `<b>${esc(x.ambulance_code)}</b> <span class="badge bg-light text-dark border">${esc(x.registration_number || '')}</span>` : '—'}
      ${x.service_area ? `<div class="text-muted small">📍 ${esc(x.service_area)}</div>` : ''}
    </td>
    <td>${x.is_active ? '<span class="text-success fw-600">Active</span>' : '<span class="text-danger">Inactive</span>'}</td>
  </tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted py-4">No users found.</td></tr>';
}

function renderHospitals(data) {
  const el = document.getElementById('a_hosp');
  if (!el) return;
  el.innerHTML = data.map(x => `<tr>
    <td><b>${esc(x.name)}</b></td>
    <td>${esc(x.address || '—')}</td>
    <td>${esc(x.contact_number || '—')}</td>
    <td>${esc(x.services || '—')}</td>
    <td>${when(x.last_verified_at)}</td>
  </tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted py-4">No hospital records found.</td></tr>';
}

function renderHistory(data) {
  const el = document.getElementById('a_hist');
  if (!el) return;
  el.innerHTML = data.map(x => `
    <div class="d-flex gap-2 align-items-start mb-2 pb-2 border-bottom">
      <span class="text-muted text-nowrap" style="font-size:.75rem">${when(x.created_at)}</span>
      <div>
        <b>${esc(x.ambulance_code || 'System')}</b> / ${esc(x.incident_code || '—')}:
        <span class="badge ${x.dispatch_mode === 'Automatic' ? 'bg-info text-dark' : x.dispatch_mode === 'Manual Fallback' ? 'bg-warning text-dark' : 'bg-secondary'} ms-1">${esc(x.dispatch_mode || x.action || '—')}</span>
        <span class="text-muted"> ${esc(x.previous_status||'')} → ${esc(x.new_status||'')}</span>
        ${x.reason ? `<div class="text-muted small">${esc(x.reason.substring(0,120))}${x.reason.length > 120 ? '…' : ''}</div>` : ''}
      </div>
    </div>`).join('') || '<div class="text-muted text-center py-3">No history yet.</div>';
}

// ── Map (Pollachi-centered) ────────────────────────────────────────────────
function drawMap() {
  const m = lmap('amap', POLLACHI.lat, POLLACHI.lng, 12);
  if (!m) return;

  if (!m._clickBound) {
    m._clickBound = true;
    m.on('click', e => {
      const lat = e.latlng.lat.toFixed(6), lon = e.latlng.lng.toFixed(6);
      const latEl = document.getElementById('i_lat'), lonEl = document.getElementById('i_lon');
      if (latEl) latEl.value = lat;
      if (lonEl) lonEl.value = lon;
      toast(`📍 Coordinates set: ${lat}, ${lon}`);
    });
  }

  const ambPins = AMB.map(x => ({
    lat: x.latitude, lng: x.longitude,
    title: `${x.ambulance_code}${x.is_simulated ? ' [SIM]' : ''}\nDriver: ${x.driver_name || '—'}\nStatus: ${x.status}\nCapacity: ${x.capacity}\nLast GPS: ${x.last_location_update || 'unknown'}`,
    label: x.is_simulated ? '⬡' : 'A',
    type: x.status === 'Available' ? 'ambulance-available'
         : x.status === 'Out of service' ? 'ambulance-oos'
         : 'ambulance-busy'
  }));

  const incPins = INC
    .filter(x => !['Closed','Cancelled'].includes(x.status))
    .map(x => ({lat: x.latitude, lng: x.longitude,
                title: `${x.incident_code}\n${x.incident_type}`, label: '!', type: 'incident'}));

  pins('amap', [...ambPins, ...incPins]);

  const noteEl = document.getElementById('mapNote');
  if (noteEl) noteEl.textContent = `${AMB.length} ambulances shown | Pollachi area | Refreshed ${new Date().toLocaleTimeString()}`;
}

// ── Actions ────────────────────────────────────────────────────────────────
async function createIncident() {
  const btn = document.getElementById('btnCreateIncident');
  if (btn) { btn.disabled = true; btn.textContent = '…Creating'; }
  const r = await api('/api/incidents', 'POST', {
    title:                   document.getElementById('i_title')?.value,
    incident_type:           document.getElementById('i_type')?.value,
    priority:                document.getElementById('i_prio')?.value,
    description:             document.getElementById('i_desc')?.value,
    latitude:                document.getElementById('i_lat')?.value,
    longitude:               document.getElementById('i_lon')?.value,
    estimated_patient_count: parseInt(document.getElementById('i_n')?.value || '1')
  });
  if (btn) { btn.disabled = false; btn.textContent = '🚨 Create'; }
  toast(r.success ? `✅ Incident ${r.data?.incident_code} created` : r.error,
        r.success ? 'success' : 'danger');
  if (r.success) {
    document.getElementById('i_title').value = '';
    load();
    if (currentMode === 'automatic') {
      toast('⚡ Auto-dispatch mode active — checking for eligible ambulances…', 'info');
    }
  }
}

async function addAmb() {
  const r = await api('/api/ambulances', 'POST', {
    ambulance_code:      document.getElementById('n_code')?.value,
    registration_number: document.getElementById('n_reg')?.value,
    latitude:            document.getElementById('n_lat')?.value,
    longitude:           document.getElementById('n_lon')?.value,
    capacity:            parseInt(document.getElementById('n_cap')?.value || '2'),
    equipment:           document.getElementById('n_eq')?.value,
    is_simulated:        parseInt(document.getElementById('n_sim')?.value || '1'),
  });
  toast(r.success ? '✅ Ambulance added' : r.error, r.success ? 'success' : 'danger');
  if (r.success) load();
}

async function setStatus(id, v) {
  const r = await api(`/api/ambulances/${id}/status`, 'PATCH', {status: v});
  toast(r.success ? '✅ Status updated' : r.error, r.success ? 'success' : 'danger');
  if (r.success) load();
}

async function addPatients(id) {
  const n = parseInt(prompt('How many patient records to register?', '1'));
  if (!n || isNaN(n)) return;
  const r = await api(`/api/incidents/${id}/patients`, 'POST', {count: n});
  toast(r.success ? `✅ ${n} patient record(s) added` : r.error, r.success ? 'success' : 'danger');
}

async function cancelDispatch(id) {
  const reason = prompt('Reason for cancelling this dispatch?');
  if (!reason) return;
  const r = await api(`/api/dispatches/${id}/cancel`, 'POST', {reason});
  toast(r.success ? '✅ Dispatch cancelled; ambulance now available' : r.error,
        r.success ? 'success' : 'danger');
  if (r.success) load();
}

async function createUser() {
  const r = await api('/api/admin/users', 'POST', {
    name:        document.getElementById('u_name')?.value,
    email:       document.getElementById('u_email')?.value,
    password:    document.getElementById('u_pw')?.value,
    role:        document.getElementById('u_role')?.value,
    ambulance_id:document.getElementById('u_amb')?.value || null
  });
  toast(r.success ? '✅ Account created' : r.error, r.success ? 'success' : 'danger');
  if (r.success) load();
}

// ── AI ──────────────────────────────────────────────────────────────────────
async function ai(kind) {
  const outEl = document.getElementById('aiOut');
  const spEl  = document.getElementById('aiSpinner');
  if (outEl) { outEl.style.display = 'none'; outEl.textContent = ''; }
  if (spEl) spEl.classList.remove('d-none');
  const r = await api(`/api/ai/${kind}`, 'POST', {
    incident_id: +document.getElementById('ai_inc')?.value
  });
  if (spEl) spEl.classList.add('d-none');
  if (outEl) {
    outEl.textContent = r.success ? r.data.text : (r.error || 'AI service unavailable');
    outEl.style.display = 'block';
  }
}

// ── Section navigation helper ──────────────────────────────────────────────
function nav(sec) {
  document.querySelectorAll('.sec').forEach(s => s.classList.add('d-none'));
  const el = document.getElementById(sec);
  if (el) el.classList.remove('d-none');
  window.dispatchEvent(new CustomEvent('sec', {detail: sec}));
}

// ── Event listeners ────────────────────────────────────────────────────────
window.addEventListener('sec', e => {
  if (e.detail === 'dashboard') setTimeout(() => drawMap(), 200);
  if (e.detail === 'fallback')  load();
});

// ── Bootstrap ─────────────────────────────────────────────────────────────
load();
setInterval(load, 30000);
