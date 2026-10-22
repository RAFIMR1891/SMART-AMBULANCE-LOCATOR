// ── Admin/Dispatcher Portal JavaScript ───────────────────────
let lastRec = null, AMB = [], INC = [];

// ── Load all dashboard data ───────────────────────────────────
async function load() {
  const [s, a, i, d, u, h, hi] = await Promise.all([
    '/api/dashboard/summary', '/api/ambulances', '/api/incidents',
    '/api/dispatches', '/api/admin/users', '/api/hospitals', '/api/dispatch-history'
  ].map(url => api(url)));

  if (s.success) renderStats(s.data);
  if (a.success) { AMB = a.data; renderAmbulances(); }
  if (i.success) { INC = i.data; renderIncidents(); }
  if (d.success) renderDispatches(d.data);
  if (u.success) renderUsers(u.data);
  if (h.success) renderHospitals(h.data);
  if (hi.success) renderHistory(hi.data);
  drawMap();
}

// ── Dashboard stats ───────────────────────────────────────────
function renderStats(v) {
  const el = document.getElementById('a_stats');
  if (!el) return;
  el.innerHTML = `<div class="row g-3">` +
    stat('🚨', 'i-r', v.new_requests,    'New Requests') +
    stat('🚑', 'i-b', v.total_ambulances - v.available - (v.status_counts?.['Out of service'] || 0), 'Active Ambulances') +
    stat('➡️', 'i-g', v.en_route,         'En Route') +
    stat('✅', 'i-o', v.completed_today,  'Completed Today') +
    stat('🟢', 'i-g', v.available,        'Available') +
    `</div>`;
}

// ── Incidents (active + full list) ───────────────────────────
function renderIncidents() {
  const open = INC.filter(x => !['Closed', 'Cancelled'].includes(x.status));

  // Active requests on dashboard
  const activeEl = document.getElementById('a_active');
  if (activeEl) {
    activeEl.innerHTML = open.map(x => `<tr>
      <td class="text-nowrap">${when(x.reported_at)}</td>
      <td class="text-nowrap">${(+x.latitude).toFixed(3)}, ${(+x.longitude).toFixed(3)}</td>
      <td>${esc(x.incident_type)}</td>
      <td>${badge(x.status)}</td>
      <td>
        <a class="btn btn-primary btn-sm" href="#requests" onclick="recommend(${x.id})">Assign</a>
        <a class="btn btn-outline-secondary btn-sm ms-1" href="#requests" onclick="viewInc(${x.id})">View</a>
      </td>
    </tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted py-4">No active requests.</td></tr>';
  }

  // Full incident list
  const incEl = document.getElementById('a_inc');
  if (incEl) {
    incEl.innerHTML = INC.map(x => `<tr>
      <td><b>${esc(x.incident_code)}</b></td>
      <td class="text-nowrap">${when(x.reported_at)}</td>
      <td>${esc(x.incident_type)}</td>
      <td><span class="badge ${x.priority === 'Critical' ? 'bg-danger' : x.priority === 'High' ? 'bg-warning text-dark' : 'bg-secondary'}">${esc(x.priority)}</span></td>
      <td>${x.estimated_patient_count}</td>
      <td>${badge(x.status)}</td>
      <td class="text-nowrap">
        <button class="btn btn-outline-primary btn-sm" onclick="recommend(${x.id})">Find Ambulances</button>
        <button class="btn btn-outline-secondary btn-sm ms-1" onclick="addPatients(${x.id})">+ Patients</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="7" class="text-center text-muted py-4">No incidents found.</td></tr>';
  }

  // AI incident selector
  const aiEl = document.getElementById('ai_inc');
  if (aiEl) {
    aiEl.innerHTML = INC.map(x => `<option value="${x.id}">${esc(x.incident_code)} — ${esc(x.title)}</option>`).join('');
  }
}

// ── Ambulances table ──────────────────────────────────────────
function renderAmbulances() {
  const el = document.getElementById('a_amb');
  if (!el) return;
  el.innerHTML = AMB.map(x => `<tr>
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
    <td>${esc(x.current_incident || '—')}</td>
  </tr>`).join('') || '<tr><td colspan="7" class="text-center text-muted py-4">No ambulances registered.</td></tr>';
}

// ── Dispatches table ──────────────────────────────────────────
function renderDispatches(data) {
  const el = document.getElementById('a_disp');
  if (!el) return;
  el.innerHTML = data.map(x => `<tr>
    <td><b>${esc(x.ambulance_code)}</b></td>
    <td>${esc(x.incident_code)}</td>
    <td>${x.distance_km ? x.distance_km + ' km' : '—'}</td>
    <td class="small">${esc(x.eta_source || '—')}</td>
    <td>${when(x.assigned_at)}</td>
    <td>${badge(x.status)}</td>
    <td>${x.status === 'Active' ? `<button class="btn btn-outline-danger btn-sm" onclick="cancelDispatch(${x.id})">Cancel</button>` : ''}</td>
  </tr>`).join('') || '<tr><td colspan="7" class="text-center text-muted py-4">No dispatches yet.</td></tr>';
}

// ── Users table ───────────────────────────────────────────────
function renderUsers(data) {
  const el = document.getElementById('a_users');
  if (!el) return;
  el.innerHTML = data.map(x => `<tr>
    <td>${esc(x.name)}</td>
    <td>${esc(x.email)}</td>
    <td><span class="badge bg-secondary">${esc(x.role)}</span></td>
    <td>${esc(x.ambulance_code || '—')}</td>
    <td>${x.is_active ? '<span class="text-success fw-600">Yes</span>' : '<span class="text-danger">No</span>'}</td>
  </tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted py-4">No users found.</td></tr>';
}

// ── Hospitals table ───────────────────────────────────────────
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

// ── Dispatch history ──────────────────────────────────────────
function renderHistory(data) {
  const el = document.getElementById('a_hist');
  if (!el) return;
  el.innerHTML = data.map(x => `
    <div class="d-flex gap-2 align-items-start mb-2 pb-2 border-bottom">
      <span class="text-muted text-nowrap" style="font-size:.75rem">${when(x.created_at)}</span>
      <div>
        <b>${esc(x.ambulance_code)}</b> / ${esc(x.incident_code)}:
        <span class="text-muted">${esc(x.previous_status)} → ${esc(x.new_status)}</span>
        ${x.reason ? `<span class="text-muted small">(${esc(x.reason)})</span>` : ''}
      </div>
    </div>`).join('') || '<div class="text-muted text-center py-3">No history yet.</div>';
}

// ── Map ───────────────────────────────────────────────────────
function drawMap() {
  const m = lmap('amap');
  if (!m) return;

  // Click on map → fill incident lat/lon
  if (!m._clickBound) {
    m._clickBound = true;
    m.on('click', e => {
      const lat = e.latlng.lat.toFixed(6), lon = e.latlng.lng.toFixed(6);
      const latEl = document.getElementById('i_lat'), lonEl = document.getElementById('i_lon');
      if (latEl) latEl.value = lat;
      if (lonEl) lonEl.value = lon;
      toast('📍 Coordinates set in emergency form');
    });
  }

  const ambPins = AMB.map(x => ({
    lat: x.latitude, lng: x.longitude,
    title: `${x.ambulance_code} (${x.status})`, label: 'A', type: 'ambulance'
  }));
  const incPins = INC
    .filter(x => !['Closed', 'Cancelled'].includes(x.status))
    .map(x => ({lat: x.latitude, lng: x.longitude, title: x.title || x.incident_code, label: '!', type: 'incident'}));

  pins('amap', [...ambPins, ...incPins]);

  const noteEl = document.getElementById('mapNote');
  if (noteEl) noteEl.textContent = `Refreshed ${new Date().toLocaleTimeString()} (last reported positions)`;
}

// ── Actions ───────────────────────────────────────────────────
async function createIncident() {
  const r = await api('/api/incidents', 'POST', {
    title:                   document.getElementById('i_title')?.value,
    incident_type:           document.getElementById('i_type')?.value,
    priority:                document.getElementById('i_prio')?.value,
    description:             document.getElementById('i_desc')?.value,
    latitude:                document.getElementById('i_lat')?.value,
    longitude:               document.getElementById('i_lon')?.value,
    estimated_patient_count: parseInt(document.getElementById('i_n')?.value || '1')
  });
  toast(r.success ? `✅ Incident ${r.data.incident_code} created` : r.error, r.success ? 'success' : 'danger');
  if (r.success) { document.getElementById('i_title').value = ''; load(); }
}

async function addAmb() {
  const r = await api('/api/ambulances', 'POST', {
    ambulance_code:      document.getElementById('n_code')?.value,
    registration_number: document.getElementById('n_reg')?.value,
    latitude:            document.getElementById('n_lat')?.value,
    longitude:           document.getElementById('n_lon')?.value,
    capacity:            parseInt(document.getElementById('n_cap')?.value || '1'),
    equipment:           document.getElementById('n_eq')?.value
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

function viewInc(id) { recommend(id); }

async function recommend(id) {
  lastRec = id;
  const recEl = document.getElementById('rec');
  if (!recEl) return;
  recEl.innerHTML = '<div class="d-flex align-items-center gap-2 mt-3"><div class="spinner-border spinner-border-sm text-primary"></div> Finding nearest ambulances…</div>';
  const r = await api(`/api/incidents/${id}/recommend-ambulances`, 'POST', {});
  if (!r.success) { recEl.innerHTML = ''; toast(r.error, 'danger'); return; }

  const warn = r.maps_warning
    ? `<div class="alert alert-warning py-2 small">⚠️ ${esc(r.maps_warning)} — Ranked by straight-line distance.</div>`
    : '';

  recEl.innerHTML = `<hr><h6>Recommended Ambulances</h6>${warn}` + (r.data.length
    ? `<div class="table-responsive"><table class="table">
        <thead><tr><th></th><th>Ambulance</th><th>Distance</th><th>ETA</th><th>Status</th><th>Why Selected</th></tr></thead>
        <tbody>` +
      r.data.map(x => `<tr>
        <td><input type="checkbox" class="pick form-check-input" value="${x.id}"></td>
        <td><b>${esc(x.ambulance)}</b></td>
        <td>${x.distance_km} km</td>
        <td>${x.eta_seconds != null ? Math.round(x.eta_seconds / 60) + ' min' : '—'}</td>
        <td>${badge(x.status)}</td>
        <td class="small text-muted">${esc(x.reason)}</td>
      </tr>`).join('') +
      `</tbody></table></div>
      <button class="btn btn-success" onclick="confirmDispatch()">✅ Confirm Dispatch Selected</button>`
    : '<div class="alert alert-danger">No eligible ambulances available. Request additional resources.</div>');
}

async function confirmDispatch() {
  const ids = [...document.querySelectorAll('.pick:checked')].map(e => +e.value);
  if (!ids.length) { toast('Select at least one ambulance first', 'warning'); return; }
  if (!confirm(`Dispatch ${ids.length} ambulance(s) to this incident?`)) return;
  const r = await api(`/api/incidents/${lastRec}/dispatch`, 'POST', {ambulance_ids: ids});
  toast(r.success ? `✅ ${ids.length} ambulance(s) dispatched` : r.error, r.success ? 'success' : 'danger');
  if (r.success) { document.getElementById('rec').innerHTML = ''; load(); }
}

async function cancelDispatch(id) {
  const reason = prompt('Reason for cancelling this dispatch?');
  if (!reason) return;
  const r = await api(`/api/dispatches/${id}/cancel`, 'POST', {reason});
  toast(r.success ? '✅ Dispatch cancelled; ambulance now available' : r.error, r.success ? 'success' : 'danger');
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

// ── Gemini AI ─────────────────────────────────────────────────
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

// ── Event listeners ───────────────────────────────────────────
window.addEventListener('sec', e => {
  if (e.detail === 'dashboard') setTimeout(() => drawMap(), 200);
});

// Initial load + auto-refresh
load();
setInterval(load, 30000);
