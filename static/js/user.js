// ── User/Patient Portal JavaScript ──────────────────────────
let reqs = [], sel = null, pin = null;
const activeReq = () => reqs.find(x => x.status === 'In progress') || reqs.find(x => x.status === 'Open');

// ── Location helpers ─────────────────────────────────────────
function setPos(lat, lon) {
  const a = (+lat).toFixed(6), b = (+lon).toFixed(6);
  document.getElementById('r_lat').value = a;
  document.getElementById('r_lon').value = b;
  // Update map pin using Leaflet
  const m = lmap('rmap');
  if (m) {
    if (pin) { m.removeLayer(pin); }
    pin = L.marker([+a, +b], {icon: ICONS.user})
      .bindPopup('Your location')
      .addTo(m);
    m.setView([+a, +b], 14);
  }
  // Reverse geocode via Nominatim (free)
  fetch(`https://nominatim.openstreetmap.org/reverse?lat=${a}&lon=${b}&format=json`)
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('r_addr');
      if (el && d.display_name) el.value = d.display_name;
    }).catch(() => {});
}

function useGps() {
  const btn = document.getElementById('gpsBtn');
  if (btn) { btn.disabled = true; btn.textContent = '📡 Detecting…'; }
  getGps((lat, lon) => {
    setPos(lat, lon);
    if (btn) { btn.disabled = false; btn.textContent = '📡 Use My Current Location'; }
  });
  // Re-enable even if denied
  setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = '📡 Use My Current Location'; } }, 6000);
}

function clearPos() {
  document.getElementById('r_lat').value = '';
  document.getElementById('r_lon').value = '';
  document.getElementById('r_addr').value = '';
  const m = lmap('rmap');
  if (pin && m) { m.removeLayer(pin); pin = null; }
}

// ── Request submission ───────────────────────────────────────
async function sendReq() {
  const errEl = document.getElementById('reqErr');
  errEl.classList.add('d-none');
  const lat = document.getElementById('r_lat').value.trim();
  const lon = document.getElementById('r_lon').value.trim();
  const desc = document.getElementById('r_desc').value.trim();
  const type = document.getElementById('r_type').value;
  const n = parseInt(document.getElementById('r_n').value || '1');

  if (!lat || !lon) {
    errEl.textContent = 'Please provide your location (use GPS button or click the map).';
    errEl.classList.remove('d-none'); return;
  }
  if (!type) {
    errEl.textContent = 'Please select an emergency type.';
    errEl.classList.remove('d-none'); return;
  }
  if (!desc) {
    errEl.textContent = 'Please describe the emergency in the Additional Information field.';
    errEl.classList.remove('d-none'); return;
  }

  const btn = document.getElementById('send');
  btn.disabled = true; btn.textContent = '⏳ Submitting…';
  const r = await api('/api/user/requests', 'POST', {
    incident_type: type, description: desc,
    latitude: lat, longitude: lon, estimated_patient_count: n
  });
  btn.disabled = false; btn.textContent = '🚨 Submit Emergency Request';

  if (r.success) {
    toast(`✅ Request ${r.data.incident_code} submitted successfully!`, 'success');
    document.getElementById('r_desc').value = '';
    await loadReqs();
    location.hash = '#track';
  } else {
    errEl.textContent = r.error || 'Failed to submit request. Please try again.';
    errEl.classList.remove('d-none');
  }
}

// ── Row builders ─────────────────────────────────────────────
function reqRow(x, i, showAction) {
  const loc = (x.latitude && x.longitude)
    ? `${(+x.latitude).toFixed(3)}, ${(+x.longitude).toFixed(3)}`
    : '—';
  const act = showAction
    ? `<td><button class="btn btn-primary btn-sm" onclick="view(${x.id})">View</button></td>`
    : '';
  return `<tr>
    <td><span class="fw-600">${i + 1}</span></td>
    <td>${when(x.reported_at)}</td>
    <td class="text-nowrap">${esc(loc)}</td>
    <td>${esc(x.incident_type || '—')}</td>
    <td>${badge(x.status)}</td>
    <td>${esc(x.ambulance_code || '—')}</td>
    ${act}
  </tr>`;
}

// ── Load all requests ────────────────────────────────────────
async function loadReqs() {
  const r = await api('/api/user/requests');
  if (!r.success) { toast(r.error || 'Failed to load requests', 'danger'); return; }
  reqs = r.data;
  const n = s => reqs.filter(x => x.status === s).length;

  // Dashboard stats
  const statsEl = document.getElementById('u_stats');
  if (statsEl) {
    statsEl.innerHTML =
      `<div class="row g-3">` +
      stat('📋', 'i-b', reqs.length, 'Total Requests') +
      stat('🚑', 'i-o', n('Open') + n('In progress'), 'Active') +
      stat('✅', 'i-g', n('Closed') + n('Completed'), 'Completed') +
      stat('✖', 'i-r', n('Cancelled'), 'Cancelled') +
      `</div>`;
  }

  // Recent (dashboard)
  const recentEl = document.getElementById('u_recent');
  if (recentEl) {
    recentEl.innerHTML = reqs.slice(0, 5).map((x, i) => reqRow(x, i, false)).join('')
      || '<tr><td colspan="6" class="text-center text-muted py-4">No requests yet. Click "Request an Ambulance" to get started.</td></tr>';
  }

  // All requests table
  const allEl = document.getElementById('u_all');
  if (allEl) {
    allEl.innerHTML = reqs.map((x, i) => reqRow(x, i, true)).join('')
      || '<tr><td colspan="7" class="text-center text-muted py-4">No requests found.</td></tr>';
  }

  loadTrack();
}

function view(id) { sel = id; location.hash = '#track'; loadTrack(); }

// ── Track ambulance ───────────────────────────────────────────
async function loadTrack() {
  const id = sel || (activeReq() && activeReq().id);
  const infoEl = document.getElementById('t_info');
  const noteEl = document.getElementById('t_note');
  const cancelEl = document.getElementById('t_cancel');

  if (!id) {
    if (infoEl) infoEl.innerHTML = '<div class="text-muted text-center py-4">No active request to track. <a href="#request">Request an ambulance</a></div>';
    if (cancelEl) cancelEl.innerHTML = '';
    pins('tmap', []);
    return;
  }

  const r = await api('/api/user/requests/' + id);
  if (!r.success) { toast(r.error, 'danger'); return; }
  const d = r.data, ambs = d.ambulances || [];

  if (infoEl) {
    if (ambs.length) {
      infoEl.innerHTML = ambs.map(x => `
        <div class="row g-2 mb-3">
          <div class="col-6">
            <div class="small text-muted">Ambulance ID</div>
            <div class="fw-700">${esc(x.ambulance_code)}</div>
          </div>
          <div class="col-6">
            <div class="small text-muted">Driver Name</div>
            <div class="fw-700">${esc(x.driver_name || '—')}</div>
          </div>
          <div class="col-6">
            <div class="small text-muted">Status</div>
            <div>${badge(x.ambulance_status)}</div>
          </div>
          <div class="col-6">
            <div class="small text-muted">Estimated Arrival</div>
            <div class="fw-700 text-primary">${x.eta_seconds != null ? Math.round(x.eta_seconds / 60) + ' mins' : '—'}</div>
          </div>
          <div class="col-12">
            <small class="text-muted">Last reported: ${(+x.latitude).toFixed(4)}, ${(+x.longitude).toFixed(4)} at ${when(x.last_location_update)}</small>
          </div>
        </div>`).join('<hr class="my-2">');
    } else {
      infoEl.innerHTML = `
        <div class="text-center py-3">
          ${badge(d.status)}
          <p class="mt-2 text-muted small">${d.status === 'Open' ? 'Waiting for a dispatcher to assign an ambulance.' : 'No ambulance assigned yet.'}</p>
        </div>`;
    }
  }

  if (noteEl) noteEl.textContent = r.eta_note || '';
  if (cancelEl) {
    cancelEl.innerHTML = d.status === 'Open'
      ? `<button class="btn btn-outline-danger btn-sm mt-2" onclick="cancelReq(${id})">Cancel Request</button>`
      : '';
  }

  // Map pins: patient + ambulances
  const P = [
    {lat: d.latitude, lng: d.longitude, title: 'Your location', label: 'Y'},
    ...ambs.map(x => ({lat: x.latitude, lng: x.longitude, title: x.ambulance_code, label: 'A'}))
  ];
  pins('tmap', P);

  // Draw route if 1 ambulance
  if (ambs.length === 1 && window.google) {
    drawRoute('tmap', {lat: ambs[0].latitude, lng: ambs[0].longitude}, {lat: d.latitude, lng: d.longitude});
  }
}

async function cancelReq(id) {
  if (!confirm('Cancel this ambulance request?')) return;
  const r = await api(`/api/user/requests/${id}/cancel`, 'POST');
  if (r.success) { toast('Request cancelled.', 'info'); sel = null; loadReqs(); }
  else toast(r.error, 'danger');
}

// ── Profile ───────────────────────────────────────────────────
async function loadProfile() {
  const r = await api('/api/me');
  const el = document.getElementById('prof');
  if (!el) return;
  if (r.success) {
    el.innerHTML = `
      <div class="row g-3">
        <div class="col-12 text-center mb-2">
          <div style="width:72px;height:72px;border-radius:50%;background:var(--blue);color:#fff;font-size:1.8rem;display:grid;place-items:center;margin:0 auto;font-weight:700">
            ${(r.data.name || '?')[0].toUpperCase()}
          </div>
          <div class="fw-700 mt-2">${esc(r.data.name)}</div>
          <div class="text-muted small">${esc(r.data.role || 'User')}</div>
        </div>
        <div class="col-md-6"><div class="small text-muted">Email</div><div class="fw-600">${esc(r.data.email)}</div></div>
        <div class="col-md-6"><div class="small text-muted">Phone</div><div class="fw-600">${esc(r.data.phone || '—')}</div></div>
        <div class="col-md-6"><div class="small text-muted">Member Since</div><div class="fw-600">${when(r.data.created_at)}</div></div>
        <div class="col-md-6"><div class="small text-muted">Role</div><div class="fw-600">${esc(r.data.role || '—')}</div></div>
      </div>`;
  }
}

// ── Event listeners ───────────────────────────────────────────
window.addEventListener('sec', e => {
  if (e.detail === 'request') {
    const m = lmap('rmap');
    if (m && !m._clickBound) {
      m._clickBound = true;
      m.on('click', ev => setPos(ev.latlng.lat, ev.latlng.lng));
    }
  }
  if (e.detail === 'track') loadTrack();
  if (e.detail === 'profile') loadProfile();
});

window.addEventListener('sec', e => {
  if (e.detail === 'request') setTimeout(() => lmap('rmap'), 200);
  if (e.detail === 'track')   setTimeout(() => lmap('tmap'), 200);
});

// Initial load
loadReqs(); loadProfile();
setInterval(loadReqs, 15000);  // refresh every 15s
