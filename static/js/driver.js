// ── Driver Portal JavaScript ─────────────────────────────────
let me = null, watchId = null, lastSent = 0, here = null;

// Maps ambulance/dispatch status to progress step index
const STATUS_IDX = {
  'Dispatched': 0, 'Assigned': 0,
  'En route': 1, 'At scene': 2,
  'Transporting patient': 3, 'Completed': 4
};
const STEP_LABELS = ['Assigned', 'En Route', 'Arrived', 'Transporting', 'Completed'];

// ── Load driver data ──────────────────────────────────────────
async function load() {
  const r = await api('/api/driver/me');
  if (!r.success) { toast(r.error, 'danger'); return; }
  me = r.data;
  renderStats();
  renderAmbulanceBanner();
  renderCurrentAssignment();
  renderHistory();
  renderSteps();
  drawMap();
}

function renderStats() {
  const el = document.getElementById('d_stats');
  if (!el) return;
  const c = me.counts || {};
  el.innerHTML = `<div class="row g-3">` +
    stat('📍', 'i-b', me.assignments.length,   'Current Assignment') +
    stat('✅', 'i-g', c.Completed  || 0,        'Completed') +
    stat('⏳', 'i-o', c.Active     || 0,        'Pending') +
    `</div>`;
}

function renderAmbulanceBanner() {
  const el = document.getElementById('d_amb');
  if (!el) return;
  const a = me.ambulance;
  const u = me.user || {};
  if (a) {
    el.innerHTML = `
      <div class="d-flex align-items-center gap-3 flex-wrap">
        <span style="font-size:2.4rem">🚑</span>
        <div>
          <div class="fw-800 fs-5">${esc(a.ambulance_code)} <span class="badge bg-light text-dark ms-2" style="font-size:.75rem">${esc(a.registration_number)}</span></div>
          <div style="opacity:.9;font-size:.85rem">📍 <b>${esc(a.service_area || 'Pollachi Region')}</b> &middot; ${when(a.last_location_update)}</div>
          <div style="opacity:.8;font-size:.78rem">👨‍✈️ Driver: <b>${esc(u.name || '')}</b> (${esc(u.email || '')}) &middot; Cap: ${a.capacity || 2} &middot; Equip: ${esc(a.equipment || 'Standard BLS')}</div>
        </div>
        <div class="ms-auto text-end">
          <span class="status-pill pill-available" style="background:rgba(255,255,255,.2);color:#fff">${esc(a.status)}</span>
          ${a.is_simulated ? '<div class="badge bg-info mt-1 text-white" style="font-size:.7rem">Simulated Fleet</div>' : ''}
        </div>
      </div>`;
  } else {
    el.innerHTML = `<div style="opacity:.8">No ambulance linked. Contact an administrator.</div>`;
  }
}

function renderCurrentAssignment() {
  const el = document.getElementById('d_cur');
  const badgeEl = document.getElementById('d_assign_badge');
  if (!el) return;
  const x = me.assignments[0];
  if (!x) {
    el.innerHTML = '<div class="text-muted text-center py-4">No active assignment at this time.</div>';
    if (badgeEl) badgeEl.innerHTML = '';
    return;
  }
  if (badgeEl) badgeEl.innerHTML = badge(x.status || 'Active');
  const dest = here ? `&origin=${here}` : '';
  el.innerHTML = `
    <table class="table table-sm mb-3">
      <tbody>
        <tr><td class="text-muted">Incident ID</td><td><b>${esc(x.incident_code)}</b></td></tr>
        <tr><td class="text-muted">Patient Location</td><td>${(+x.latitude).toFixed(4)}, ${(+x.longitude).toFixed(4)}</td></tr>
        <tr><td class="text-muted">Emergency Type</td><td>${esc(x.incident_type)}</td></tr>
        <tr><td class="text-muted">Patient(s)</td><td>~${x.estimated_patient_count}</td></tr>
        <tr><td class="text-muted">Distance</td><td>${x.distance_km ? x.distance_km + ' km (straight line)' : '—'}</td></tr>
        <tr><td class="text-muted">ETA</td><td>${x.estimated_travel_seconds != null ? Math.round(x.estimated_travel_seconds / 60) + ' mins (at dispatch)' : '—'}</td></tr>
        <tr><td class="text-muted">Details</td><td>${esc(x.description || '—')}</td></tr>
      </tbody>
    </table>
    <a class="btn btn-success btn-sm" target="_blank" rel="noopener"
       href="https://www.google.com/maps/dir/?api=1&destination=${x.latitude},${x.longitude}${dest}&travelmode=driving">
      🗺️ View on Google Maps
    </a>`;
}

function renderHistory() {
  const el = document.getElementById('d_hist');
  if (!el) return;
  const all = [...me.assignments, ...me.history];
  el.innerHTML = all.map(h => `<tr>
    <td><b>${esc(h.incident_code)}</b></td>
    <td>${esc(h.incident_type)}</td>
    <td>${when(h.assigned_at)}</td>
    <td>${h.completed_at ? when(h.completed_at) : '—'}</td>
    <td>${badge(h.status)}</td>
  </tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted py-4">No assignment history.</td></tr>';
}

function renderSteps() {
  const el = document.getElementById('d_steps');
  if (!el) return;
  const a = me.ambulance;
  const curIdx = a ? (STATUS_IDX[a.status] ?? -1) : -1;
  el.innerHTML = STEP_LABELS.map((label, k) => {
    const done = k < curIdx;
    const now  = k === curIdx;
    return `<div class="step-item ${done?'done':''} ${now?'now':''}">
      <div class="step-dot">${done ? '✓' : k + 1}</div>
      <div class="step-label">${label}</div>
    </div>`;
  }).join('');
}

// ── Map ───────────────────────────────────────────────────────
function drawMap() {
  if (!me || !me.ambulance) return;
  const P = [{lat: me.ambulance.latitude, lng: me.ambulance.longitude, title: 'My Ambulance', label: 'A', type: 'ambulance'}];
  const x = me.assignments[0];
  if (x) P.push({lat: x.latitude, lng: x.longitude, title: 'Patient Location', label: '!', type: 'incident'});
  pins('dmap', P);

  // Draw route line if there is an active assignment
  if (x) {
    drawRoute('dmap',
      {lat: me.ambulance.latitude, lng: me.ambulance.longitude},
      {lat: x.latitude, lng: x.longitude}
    );
  }
  const noteEl = document.getElementById('mapRefresh');
  if (noteEl) noteEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
}

// ── Status update ─────────────────────────────────────────────
async function updStatus() {
  const errEl = document.getElementById('statusErr');
  if (errEl) errEl.classList.add('d-none');
  const v = document.querySelector('input[name=st]:checked');
  if (!v) { toast('Please select a status first', 'warning'); return; }
  const r = await api('/api/driver/status', 'PATCH', {status: v.value});
  if (r.success) { toast('✅ Status updated to: ' + r.data.status, 'success'); load(); }
  else {
    if (errEl) { errEl.textContent = r.error; errEl.classList.remove('d-none'); }
    else toast(r.error, 'danger');
  }
}

// ── GPS sharing ───────────────────────────────────────────────
function toggleGps() {
  const btn  = document.getElementById('gpsBtn');
  const note = document.getElementById('gpsNote');
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
    if (btn)  btn.textContent = '📡 Share My Location';
    if (note) note.textContent = 'Location sharing stopped.';
    return;
  }
  if (!navigator.geolocation) { toast('Geolocation not supported by your browser', 'warning'); return; }
  if (btn)  btn.textContent = '🛑 Stop Sharing';
  if (note) note.textContent = 'Waiting for GPS fix…';

  watchId = navigator.geolocation.watchPosition(async p => {
    here = `${p.coords.latitude},${p.coords.longitude}`;
    if (Date.now() - lastSent < 15000) return;
    lastSent = Date.now();
    const r = await api('/api/driver/location', 'POST', {
      latitude: p.coords.latitude, longitude: p.coords.longitude
    });
    if (note) note.textContent = r.success
      ? '📍 Shared at ' + new Date().toLocaleTimeString()
      : r.error;
  }, () => {
    toast('Location permission denied', 'warning');
    watchId = null;
    if (btn) btn.textContent = '📡 Share My Location';
  }, {enableHighAccuracy: true});
}

// ── Profile ───────────────────────────────────────────────────
async function loadProfile() {
  const r = await api('/api/me');
  const el = document.getElementById('prof');
  if (!el) return;
  const a = me?.ambulance || {};
  if (r.success) {
    el.innerHTML = `
      <div class="row g-3">
        <div class="col-12 text-center mb-2">
          <div style="width:72px;height:72px;border-radius:50%;background:var(--blue);color:#fff;font-size:1.8rem;display:grid;place-items:center;margin:0 auto;font-weight:700">
            ${(r.data.name || '?')[0].toUpperCase()}
          </div>
          <div class="fw-700 mt-2 fs-5">${esc(r.data.name)}</div>
          <span class="badge bg-primary">Emergency Ambulance Driver</span>
        </div>
        <div class="col-md-6"><div class="small text-muted">Email (Staff ID)</div><div class="fw-600">${esc(r.data.email)}</div></div>
        <div class="col-md-6"><div class="small text-muted">Contact Phone</div><div class="fw-600">${esc(r.data.phone || '9800000101')}</div></div>
        <div class="col-12"><hr class="my-2"></div>
        <div class="col-12"><h6>🚑 Assigned Ambulance Details (Pollachi Fleet)</h6></div>
        <div class="col-md-6"><div class="small text-muted">Ambulance Code</div><div class="fw-700 text-primary">${esc(a.ambulance_code || 'Unassigned')}</div></div>
        <div class="col-md-6"><div class="small text-muted">Registration Number</div><div class="fw-600">${esc(a.registration_number || '—')}</div></div>
        <div class="col-md-6"><div class="small text-muted">Assigned Area</div><div class="fw-600">📍 ${esc(a.service_area || 'Pollachi Region')}</div></div>
        <div class="col-md-6"><div class="small text-muted">Operational Status</div><div><span class="badge bg-success">${esc(a.status || 'Available')}</span></div></div>
        <div class="col-md-6"><div class="small text-muted">Patient Capacity</div><div class="fw-600">${a.capacity || 2} Patients</div></div>
        <div class="col-md-6"><div class="small text-muted">Medical Equipment</div><div class="fw-600 small">${esc(a.equipment || 'ALS,Oxygen')}</div></div>
      </div>`;
  }
}

// ── Event listeners ───────────────────────────────────────────
window.addEventListener('sec', e => {
  if (e.detail === 'dashboard') setTimeout(() => drawMap(), 200);
  if (e.detail === 'profile')   loadProfile();
});

// Initial load
load(); loadProfile();
setInterval(load, 15000);
