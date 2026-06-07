/**
 * Sea Route Validator — front-end logic
 *
 * Interaction model:
 *   - Click map → drop numbered markers
 *   - "Validate" → POST /leg (2 points) or POST /route (3+ points)
 *   - Results drawn as coloured polylines; summary shown in side panel
 *   - "Clear" → reset everything
 */

// ---------------------------------------------------------------------------
// Map setup
// ---------------------------------------------------------------------------

const map = L.map('map').setView([30, 0], 2);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
}).addTo(map);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {{ lat: number, lon: number }[]} */
let waypoints = [];

/** @type {L.Marker[]} */
let markers = [];

/** @type {L.Polyline[]} */
let polylines = [];

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const btnValidate    = document.getElementById('btn-validate');
const btnClear       = document.getElementById('btn-clear');
const hintEl         = document.getElementById('hint');
const summaryEl      = document.getElementById('result-summary');
const rawDetailsEl   = document.getElementById('result-raw');
const rawJsonEl      = document.getElementById('result-json');
const waypointListEl = document.getElementById('waypoint-list');

// ---------------------------------------------------------------------------
// Marker helpers
// ---------------------------------------------------------------------------

/**
 * Create a numbered divIcon for a marker.
 * @param {number} index  0-based index
 * @returns {L.DivIcon}
 */
function numberedIcon(index) {
  return L.divIcon({
    className: 'numbered-marker',
    html: `<span>${index + 1}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

/** Re-render the sidebar waypoint list. */
function updateWaypointList() {
  if (waypoints.length === 0) {
    waypointListEl.innerHTML = '<span class="muted">No waypoints placed yet.</span>';
    return;
  }
  const items = waypoints
    .map((wp, i) => `<div class="wp-item"><span class="wp-num">${i + 1}</span> ${wp.lat.toFixed(4)}, ${wp.lon.toFixed(4)}</div>`)
    .join('');
  waypointListEl.innerHTML = items;
}

// ---------------------------------------------------------------------------
// Map click → add waypoint
// ---------------------------------------------------------------------------

map.on('click', (e) => {
  const { lat, lng: lon } = e.latlng;

  waypoints.push({ lat, lon });

  const marker = L.marker([lat, lon], {
    icon: numberedIcon(waypoints.length - 1),
  }).addTo(map);

  markers.push(marker);
  updateWaypointList();
  clearResults();
  hideHint();
});

// ---------------------------------------------------------------------------
// Clear button
// ---------------------------------------------------------------------------

btnClear.addEventListener('click', () => {
  // Remove all markers and polylines from the map
  markers.forEach(m => m.remove());
  polylines.forEach(p => p.remove());

  waypoints = [];
  markers   = [];
  polylines = [];

  updateWaypointList();
  clearResults();
  hideHint();
});

// ---------------------------------------------------------------------------
// Validate button
// ---------------------------------------------------------------------------

btnValidate.addEventListener('click', async () => {
  if (waypoints.length < 2) {
    showHint('Place at least 2 waypoints before validating.');
    return;
  }
  hideHint();

  // Remove any previously drawn result lines
  polylines.forEach(p => p.remove());
  polylines = [];

  if (waypoints.length === 2) {
    await validateLeg();
  } else {
    await validateRoute();
  }
});

// ---------------------------------------------------------------------------
// POST /leg  (exactly 2 waypoints)
// ---------------------------------------------------------------------------

async function validateLeg() {
  const [start, end] = waypoints;

  let data;
  try {
    const resp = await fetch('/leg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start, end }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      showError(`API error ${resp.status}: ${err.error ?? JSON.stringify(err)}`);
      return;
    }

    data = await resp.json();
  } catch (networkErr) {
    showError(`Network error: ${networkErr.message}`);
    return;
  }

  // Draw the returned geometry (GeoJSON [lon, lat] → Leaflet [lat, lon])
  const latlngs = data.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
  const colour  = data.valid ? '#2e7d32' : '#c62828';

  const line = L.polyline(latlngs, { color: colour, weight: 4 }).addTo(map);
  polylines.push(line);

  // Show summary
  const distText = data.distance_km != null
    ? `Distance: <strong>${data.distance_km.toFixed(1)} km</strong>`
    : '';

  const statusBadge = data.valid
    ? '<span class="badge valid">Valid</span>'
    : `<span class="badge invalid">Invalid</span>`;

  const reasonText = data.reason
    ? `<p>Reason: <code>${data.reason}</code></p>`
    : '';

  const detailText = data.detail
    ? `<p>${data.detail}</p>`
    : '';

  summaryEl.innerHTML = `
    <h2>Leg result ${statusBadge}</h2>
    ${detailText}
    ${reasonText}
    <p>${distText}</p>
  `;
  summaryEl.className = data.valid ? 'valid-summary' : 'invalid-summary';

  showRaw(data);
}

// ---------------------------------------------------------------------------
// POST /route  (3+ waypoints)
// ---------------------------------------------------------------------------

async function validateRoute() {
  let data;
  try {
    const resp = await fetch('/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ waypoints }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      showError(`API error ${resp.status}: ${err.error ?? JSON.stringify(err)}`);
      return;
    }

    data = await resp.json();
  } catch (networkErr) {
    showError(`Network error: ${networkErr.message}`);
    return;
  }

  // Draw each leg between consecutive waypoints, coloured per-leg validity.
  // The first invalid leg gets a thicker stroke for emphasis.
  data.legs.forEach((leg) => {
    const from   = waypoints[leg.index];
    const to     = waypoints[leg.index + 1];
    const colour = leg.valid ? '#2e7d32' : '#c62828';
    const weight = (leg.index === data.first_invalid_leg && !data.valid) ? 7 : 4;

    const line = L.polyline(
      [[from.lat, from.lon], [to.lat, to.lon]],
      { color: colour, weight },
    ).addTo(map);

    polylines.push(line);
  });

  // Build summary
  const statusBadge = data.valid
    ? '<span class="badge valid">Valid</span>'
    : '<span class="badge invalid">Invalid</span>';

  const totalDist = data.total_distance_km != null
    ? `<p>Total distance: <strong>${data.total_distance_km.toFixed(1)} km</strong></p>`
    : '';

  const firstBadLeg = (!data.valid && data.first_invalid_leg != null)
    ? `<p>First invalid leg: <strong>leg ${data.first_invalid_leg + 1}</strong> (waypoints ${data.first_invalid_leg + 1} → ${data.first_invalid_leg + 2})</p>`
    : '';

  // Per-leg breakdown list
  const legItems = data.legs.map((leg) => {
    const icon   = leg.valid ? '🟢' : '🔴';
    const reason = leg.reason ? ` — <code>${leg.reason}</code>` : '';
    const dist   = leg.distance_km != null ? ` (${leg.distance_km.toFixed(1)} km)` : '';
    return `<li>${icon} Leg ${leg.index + 1}${dist}${reason}</li>`;
  }).join('');

  summaryEl.innerHTML = `
    <h2>Route result ${statusBadge}</h2>
    <p>${data.leg_count} leg${data.leg_count !== 1 ? 's' : ''}</p>
    ${totalDist}
    ${firstBadLeg}
    <ul class="leg-list">${legItems}</ul>
  `;
  summaryEl.className = data.valid ? 'valid-summary' : 'invalid-summary';

  showRaw(data);
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function clearResults() {
  summaryEl.innerHTML = '';
  summaryEl.className = 'hidden';
  rawDetailsEl.className = 'hidden';
  rawJsonEl.textContent = '';
}

function showRaw(data) {
  rawJsonEl.textContent = JSON.stringify(data, null, 2);
  rawDetailsEl.className = '';  // remove 'hidden'
  summaryEl.classList.remove('hidden');
}

function showHint(msg) {
  hintEl.textContent = msg;
  hintEl.classList.remove('hidden');
}

function hideHint() {
  hintEl.classList.add('hidden');
  hintEl.textContent = '';
}

function showError(msg) {
  summaryEl.innerHTML = `<p class="error-msg">${msg}</p>`;
  summaryEl.className = 'invalid-summary';
  summaryEl.classList.remove('hidden');
}
