// ── Shared helpers ──────────────────────────────────────────
// Success messages shown ONLY after backend confirms success=true.

async function api(url, method = 'GET', data) {
  try {
    const opts = {
      method, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: data ? JSON.stringify(data) : undefined
    };
    const r = await fetch(url, opts);
    if (r.status === 401 && !url.includes('/auth/')) { location.href = '/login'; return {}; }
    return await r.json();
  } catch (e) {
    return {success: false, error: 'Network error. Please check your connection.'};
  }
}

function toast(msg, type = 'dark') {
  const el = document.getElementById('toast');
  const body = document.getElementById('toastMsg');
  if (!el || !body) return;
  body.textContent = msg;
  el.className = `toast text-bg-${type}`;
  const t = bootstrap.Toast.getOrCreateInstance(el, {delay: 3500});
  t.show();
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Status → badge pill mapping
const PILL_MAP = {
  'Open':               'pill-new',
  'In progress':        'pill-active',
  'Closed':             'pill-completed',
  'Cancelled':          'pill-cancelled',
  'Active':             'pill-active',
  'Completed':          'pill-completed',
  'Available':          'pill-available',
  'En route':           'pill-enroute',
  'Dispatched':         'pill-active',
  'At scene':           'pill-active',
  'Transporting patient':'pill-active',
  'Assigned':           'pill-active',
  'Out of service':     'pill-cancelled',
};

function badge(s) {
  const [label, cls] = PILL_MAP[s]
    ? [s, PILL_MAP[s]]
    : [s, 'pill-active'];
  return `<span class="status-pill ${cls}">${esc(label)}</span>`;
}

const when = d => d ? new Date(d).toLocaleString('en-IN', {dateStyle:'short', timeStyle:'short'}) : '—';

function stat(ico, cls, n, label) {
  return `<div class="col-6 col-lg">
    <div class="stat">
      <div class="ico ${cls}">${ico}</div>
      <div class="stat-body"><b>${n}</b><small>${label}</small></div>
    </div>
  </div>`;
}

async function logout() {
  await api('/api/auth/logout', 'POST');
  location.href = '/login';
}

// ── Section navigation (hash-based sidebar) ─────────────────
function showSec() {
  const first = document.querySelector('[data-sec]');
  if (!first) return;
  const id = (location.hash || '#' + first.dataset.sec).slice(1);
  document.querySelectorAll('.sec').forEach(s => s.classList.toggle('d-none', s.id !== id));
  document.querySelectorAll('[data-sec]').forEach(a => {
    const active = a.dataset.sec === id;
    a.classList.toggle('active', active);
  });
  document.body.classList.remove('nav-open');
  window.dispatchEvent(new CustomEvent('sec', {detail: id}));
}

window.addEventListener('hashchange', showSec);
document.addEventListener('DOMContentLoaded', () => { showSec(); });

// ── Leaflet Map helpers (replaces Google Maps — free, no API key) ──
const _maps = {};

const LEAFLET_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const LEAFLET_ATTR  = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Custom marker icons — distinct states for ambulances
const ICONS = {
  'ambulance-available': L.divIcon({
    className: '',
    html: `<div style="background:#16a34a;color:#fff;border-radius:50%;width:30px;height:30px;
           display:flex;align-items:center;justify-content:center;font-size:14px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">🚑</div>`,
    iconSize: [30,30], iconAnchor:[15,15], popupAnchor:[0,-15]
  }),
  'ambulance-busy': L.divIcon({
    className: '',
    html: `<div style="background:#d97706;color:#fff;border-radius:50%;width:30px;height:30px;
           display:flex;align-items:center;justify-content:center;font-size:14px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">🚑</div>`,
    iconSize: [30,30], iconAnchor:[15,15], popupAnchor:[0,-15]
  }),
  'ambulance-oos': L.divIcon({
    className: '',
    html: `<div style="background:#6b7280;color:#fff;border-radius:50%;width:28px;height:28px;
           display:flex;align-items:center;justify-content:center;font-size:12px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3)">🚑</div>`,
    iconSize: [28,28], iconAnchor:[14,14], popupAnchor:[0,-14]
  }),
  ambulance: L.divIcon({
    className: '',
    html: `<div style="background:#1d4ed8;color:#fff;border-radius:50%;width:30px;height:30px;
           display:flex;align-items:center;justify-content:center;font-size:14px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">🚑</div>`,
    iconSize: [30,30], iconAnchor:[15,15], popupAnchor:[0,-15]
  }),
  incident: L.divIcon({
    className: '',
    html: `<div style="background:#dc2626;color:#fff;border-radius:50%;width:32px;height:32px;
           display:flex;align-items:center;justify-content:center;font-size:16px;
           border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.5)">🚨</div>`,
    iconSize: [32,32], iconAnchor:[16,16], popupAnchor:[0,-16]
  }),
  user: L.divIcon({
    className: '',
    html: `<div style="background:#16a34a;color:#fff;border-radius:50%;width:30px;height:30px;
           display:flex;align-items:center;justify-content:center;font-size:14px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">📍</div>`,
    iconSize: [30,30], iconAnchor:[15,30], popupAnchor:[0,-30]
  }),
  default: L.divIcon({
    className: '',
    html: `<div style="background:#7c3aed;color:#fff;border-radius:50%;width:28px;height:28px;
           display:flex;align-items:center;justify-content:center;font-size:13px;
           border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">📌</div>`,
    iconSize: [28,28], iconAnchor:[14,28], popupAnchor:[0,-28]
  })
};

function _pickIcon(p) {
  const type = p.type || '';
  if (type === 'ambulance-available') return ICONS['ambulance-available'];
  if (type === 'ambulance-busy')      return ICONS['ambulance-busy'];
  if (type === 'ambulance-oos')       return ICONS['ambulance-oos'];
  if (type === 'ambulance')           return ICONS.ambulance;
  if (type === 'incident')            return ICONS.incident;
  if (type === 'user')                return ICONS.user;
  const lbl = (p.label||'').toString().toUpperCase();
  if (lbl === '!' ) return ICONS.incident;
  if (lbl === 'Y' ) return ICONS.user;
  if (lbl === 'A' ) return ICONS.ambulance;
  return ICONS.default;
}

// lmap: initializes or returns Leaflet map.
// Default center: Pollachi, Tamil Nadu (10.6550, 76.9988)
function lmap(id, defLat=10.6550, defLng=76.9988, defZoom=12) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (!_maps[id]) {
    if (!el.style.height && el.offsetHeight < 50) el.style.height = '380px';
    const m = L.map(id, {zoomControl: true}).setView([defLat, defLng], defZoom);
    L.tileLayer(LEAFLET_TILES, {attribution: LEAFLET_ATTR, maxZoom: 19}).addTo(m);
    m._markers   = [];
    m._routeLine = null;
    _maps[id] = m;
  }
  setTimeout(() => _maps[id].invalidateSize(), 100);
  return _maps[id];
}

// Alias for backward compatibility
const gmap = lmap;


function pins(id, list) {
  const m = lmap(id);
  if (!m) return;
  // Clear existing markers
  (m._markers || []).forEach(mk => m.removeLayer(mk));
  m._markers = [];
  if (m._routeLine) { m.removeLayer(m._routeLine); m._routeLine = null; }

  list.forEach(p => {
    if (p.lat == null || p.lng == null) return;
    const mk = L.marker([+p.lat, +p.lng], {icon: _pickIcon(p)})
      .bindPopup(`<b>${esc(p.title || '')}</b>`)
      .addTo(m);
    m._markers.push(mk);
  });

  if (list.length === 1) {
    m.setView([+list[0].lat, +list[0].lng], 14);
  } else if (list.length > 1) {
    const valid = list.filter(p => p.lat != null && p.lng != null);
    if (valid.length) {
      const bounds = L.latLngBounds(valid.map(p => [+p.lat, +p.lng]));
      m.fitBounds(bounds, {padding: [40, 40]});
    }
  }
}

function drawRoute(id, from, to) {
  const m = lmap(id);
  if (!m) return;
  if (m._routeLine) { m.removeLayer(m._routeLine); m._routeLine = null; }
  // Draw a straight dashed line (no routing API needed)
  m._routeLine = L.polyline(
    [[+from.lat, +from.lng], [+to.lat, +to.lng]],
    {color: '#1d4ed8', weight: 3, dashArray: '8 6', opacity: 0.8}
  ).addTo(m);
}

function getGps(cb) {
  if (!navigator.geolocation) { toast('Geolocation is not supported by this browser', 'warning'); return; }
  navigator.geolocation.getCurrentPosition(
    p => cb(p.coords.latitude, p.coords.longitude),
    () => toast('Location permission denied. Pick on the map or type coordinates manually.', 'warning')
  );
}
