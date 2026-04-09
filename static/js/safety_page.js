document.addEventListener('DOMContentLoaded', () => {
  const clockEl = document.getElementById('tacticalSyncClock');
  if (!clockEl) return;

  const draw = () => {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hh}:${mm}:${ss}`;
  };

  draw();
  setInterval(draw, 1000);
});

function formatRemaining(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

const checkinStatusEl = document.getElementById('checkinStatus');

function setCheckinStatus(message, tone = '') {
  if (!checkinStatusEl) return;
  checkinStatusEl.textContent = message || '\u00A0';
  checkinStatusEl.classList.remove('text-danger', 'text-success', 'text-warning');
  if (tone === 'danger') checkinStatusEl.classList.add('text-danger');
  if (tone === 'success') checkinStatusEl.classList.add('text-success');
  if (tone === 'warning') checkinStatusEl.classList.add('text-warning');
}

function closestEtaOption(minutes) {
  const value = Math.max(5, Number(minutes) || 30);
  const options = [15, 30, 45, 60, 90];
  return options.reduce((best, current) => (
    Math.abs(current - value) < Math.abs(best - value) ? current : best
  ), options[0]);
}

function loadPendingCheckinPlan() {
  const params = new URLSearchParams(window.location.search);
  let stored = null;
  try {
    stored = JSON.parse(sessionStorage.getItem('violeta.pendingCheckin') || 'null');
  } catch (_) {
    stored = null;
  }

  return {
    ...(stored && typeof stored === 'object' ? stored : {}),
    source: params.get('source') || stored?.source || '',
    destinationLabel: params.get('destination') || stored?.destinationLabel || '',
    etaMinutes: Number(params.get('eta') || stored?.etaMinutes || 30),
    mode: params.get('mode') || stored?.mode || '',
    missingContact: params.get('missing_contact') === '1',
    verifyRequired: params.get('verify_required') === '1',
    started: params.get('started') === '1',
  };
}

function applyPendingCheckinPlan() {
  const pending = loadPendingCheckinPlan();
  const destinationInput = document.getElementById('checkinDestination');
  const etaSelect = document.getElementById('checkinEta');
  const noteInput = document.getElementById('checkinNote');
  const hasActiveCheckin = !!document.getElementById('checkinArrivedBtn');

  if (hasActiveCheckin) {
    if (pending.started) {
      setCheckinStatus('Trayecto iniciado desde Hotspots. Seguimiento activo.', 'success');
    }
    try { sessionStorage.removeItem('violeta.pendingCheckin'); } catch (_) {}
    return;
  }

  if (!pending.destinationLabel && !pending.missingContact && !pending.verifyRequired) return;

  if (destinationInput && !destinationInput.value.trim() && pending.destinationLabel) {
    destinationInput.value = pending.destinationLabel;
  }
  if (etaSelect && pending.etaMinutes) {
    etaSelect.value = String(closestEtaOption(pending.etaMinutes));
  }
  if (noteInput && !noteInput.value && pending.mode) {
    noteInput.value = `Ruta desde Hotspots · ${pending.mode === 'transit' ? 'Transporte' : 'Caminando'}`.slice(0, 255);
  }

  if (pending.missingContact) {
    setCheckinStatus('Agrega un contacto de confianza para poder iniciar este trayecto.', 'danger');
    return;
  }
  if (pending.verifyRequired) {
    setCheckinStatus('Necesitas verificar tu cuenta para activar este trayecto.', 'warning');
    return;
  }
  setCheckinStatus('Ruta sugerida lista desde Hotspots. Presiona "Iniciar Ruta" para activar el seguimiento.', 'success');
}

applyPendingCheckinPlan();

async function unblockFromSafety(userId){
  try {
    const response = await fetch(`/api/user/unblock/${userId}`, {
      method: 'POST',
      headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      alert(data.error || 'No se pudo desbloquear la cuenta');
      return;
    }
    window.location.reload();
  } catch (e) {
    alert('No se pudo desbloquear la cuenta');
  }
}

async function setPrimaryContact(contactId) {
  const response = await fetch(`/api/safety/contact/${contactId}/primary`, {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    alert(data.error || 'No se pudo actualizar el contacto principal');
    return;
  }
  window.location.reload();
}

async function deleteContact(contactId) {
  const response = await fetch(`/api/safety/contact/${contactId}/delete`, {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    alert(data.error || 'No se pudo eliminar el contacto');
    return;
  }
  window.location.reload();
}

const safetyContactForm = document.getElementById('safetyContactForm');
if (safetyContactForm) {
  safetyContactForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('contactName')?.value?.trim() || '';
    const phone = document.getElementById('contactPhone')?.value?.trim() || '';
    const relationship = document.getElementById('contactRel')?.value?.trim() || '';
    const response = await fetch('/api/safety/contact', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
      },
      body: JSON.stringify({ name, phone, relationship })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      alert(data.error || 'No se pudo guardar el contacto');
      return;
    }
    window.location.reload();
  });
}

const checkinRemainingLabel = document.getElementById('checkinRemainingLabel');
if (checkinRemainingLabel) {
  const expiresAt = new Date(checkinRemainingLabel.dataset.expires || '').getTime();
  const updateCheckinTimer = () => {
    if (!expiresAt) return;
    const secs = Math.floor((expiresAt - Date.now()) / 1000);
    checkinRemainingLabel.textContent = formatRemaining(secs);
    if (secs <= 0) {
      checkinRemainingLabel.textContent = '0s';
      setTimeout(() => window.location.reload(), 1000);
    }
  };
  updateCheckinTimer();
  setInterval(updateCheckinTimer, 1000);
}

async function sendCheckinWithGeo(payload) {
  const send = (lat = null, lng = null) => fetch('/api/safety/checkin/start', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
    },
    body: JSON.stringify({ ...payload, lat, lng })
  }).then(async (r) => ({ ok: r.ok, data: await r.json() }));

  if (!navigator.geolocation) return send(null, null);

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      async (pos) => resolve(await send(pos.coords.latitude, pos.coords.longitude)),
      async () => resolve(await send(null, null)),
      { enableHighAccuracy: true, timeout: 7000, maximumAge: 0 }
    );
  });
}

const startCheckinBtn = document.getElementById('startCheckinBtn');
if (startCheckinBtn) {
  startCheckinBtn.addEventListener('click', async () => {
    const destination = document.getElementById('checkinDestination')?.value?.trim() || '';
    const note = document.getElementById('checkinNote')?.value?.trim() || '';
    const etaMinutes = Number(document.getElementById('checkinEta')?.value || '30');
    startCheckinBtn.disabled = true;
    const out = await sendCheckinWithGeo({ destination, note, eta_minutes: etaMinutes });
    startCheckinBtn.disabled = false;
    if (!out.ok || !out.data.ok) {
      setCheckinStatus(out.data.error || 'No se pudo iniciar el check-in.', 'danger');
      return;
    }
    try { sessionStorage.removeItem('violeta.pendingCheckin'); } catch (_) {}
    setCheckinStatus(out.data.message || 'Check-in iniciado.', 'success');
    setTimeout(() => window.location.reload(), 1000);
  });
}

const checkinArrivedBtn = document.getElementById('checkinArrivedBtn');
if (checkinArrivedBtn) {
  checkinArrivedBtn.addEventListener('click', async () => {
    if (typeof window.__stopMyRouteTracker === 'function') {
      try { window.__stopMyRouteTracker(); } catch (e) {}
    }
    const response = await fetch('/api/safety/checkin/arrived', {
      method: 'POST',
      headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      setCheckinStatus(data.error || 'No se pudo cerrar el check-in.', 'danger');
      return;
    }
    setCheckinStatus(data.message || 'Llegada confirmada.', 'success');
    if (data.summary_url) {
      window.location.href = data.summary_url;
      return;
    }
    setTimeout(() => window.location.reload(), 1000);
  });
}

const checkinCancelBtn = document.getElementById('checkinCancelBtn');
if (checkinCancelBtn) {
  checkinCancelBtn.addEventListener('click', async () => {
    if (typeof window.__stopMyRouteTracker === 'function') {
      try { window.__stopMyRouteTracker(); } catch (e) {}
    }
    const response = await fetch('/api/safety/checkin/cancel', {
      method: 'POST',
      headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      setCheckinStatus(data.error || 'No se pudo cancelar.', 'danger');
      return;
    }
    setCheckinStatus(data.message || 'Check-in cancelado.', 'warning');
    setTimeout(() => window.location.reload(), 1000);
  });
}

async function triggerEmergencyWithGeo() {
  const send = (lat = null, lng = null) => fetch('/api/safety/emergency/trigger', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
    },
    body: JSON.stringify({ lat, lng })
  }).then(async (response) => ({
    ok: response.ok,
    status: response.status,
    data: await response.json().catch(() => ({}))
  }));

  if (!navigator.geolocation) return send(null, null);

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      async (pos) => resolve(await send(pos.coords.latitude, pos.coords.longitude)),
      async () => resolve(await send(null, null)),
      { enableHighAccuracy: true, timeout: 7000, maximumAge: 0 }
    );
  });
}

const checkinEmergencyBtn = document.getElementById('checkinEmergencyBtn');
if (checkinEmergencyBtn) {
  checkinEmergencyBtn.addEventListener('click', async () => {
    checkinEmergencyBtn.disabled = true;
    setCheckinStatus('Activando protocolo de emergencia...', 'danger');
    const result = await triggerEmergencyWithGeo();
    checkinEmergencyBtn.disabled = false;

    if (!result?.ok || !result?.data?.ok) {
      setCheckinStatus(result?.data?.error || 'No se pudo activar el protocolo de emergencia.', 'danger');
      return;
    }

    const contacts = Number(result.data.contacts_notified || 0);
    const fallback = Number(result.data.contacts_total || 0);
    const notifiedLabel = contacts > 0
      ? `${contacts} contacto${contacts === 1 ? '' : 's'} notificado${contacts === 1 ? '' : 's'}`
      : fallback > 0
        ? 'No se pudo notificar automáticamente a tus contactos'
        : 'No tienes contactos de confianza registrados';
    setCheckinStatus(`${result.data.message || 'Protocolo activado.'} ${notifiedLabel}.`, 'danger');
  });
}

// --- Mi ruta (dibujo en mapa conforme avanza el check-in) --------------------
document.addEventListener('DOMContentLoaded', () => {
  const mapEl = document.getElementById('myRouteMap');
  if (!mapEl) return;
  if (!window.L) return;

  const checkinId = mapEl.dataset.checkinId;
  if (!checkinId) return;

  const isAdmin = !!(window.CURRENT_USER && String(window.CURRENT_USER.username || '').toLowerCase() === 'admin');
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const statusEl = document.getElementById('myRouteStatus');
  const speedEl = document.getElementById('myRouteSpeed');
  const distEl = document.getElementById('myRouteDistance');
  const elapsedEl = document.getElementById('myRouteElapsed');
  const segCountEl = document.getElementById('myRouteSegmentsCount');
  const segWrap = document.getElementById('myRouteSegments');

  const state = {
    startTs: null,
    points: [],
    totalM: 0,
    lastPoint: null,
    watchId: null,
    userInteracted: false,
    segments: new Map(),
    segmentWindowMs: 30000,
    lastSentAt: 0,
    lastSentPoint: null,
  };

  const setStatus = (msg, danger = false) => {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.toggle('text-danger', !!danger);
    if (!danger) statusEl.classList.remove('text-danger');
  };

  const toRad = (deg) => (deg * Math.PI) / 180;
  const haversineM = (lat1, lon1, lat2, lon2) => {
    const R = 6371000;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.asin(Math.sqrt(a));
    return R * c;
  };

  const formatHms = (secs) => {
    const s = Math.max(0, Math.floor(Number(secs) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
    return `${m}:${String(r).padStart(2, '0')}`;
  };

  const map = L.map(mapEl, { zoomControl: true, attributionControl: false });
  map.on('dragstart zoomstart', () => { state.userInteracted = true; });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    subdomains: ['a', 'b', 'c'],
  }).addTo(map);

  const routeLine = L.polyline([], { color: '#FEC04F', weight: 5, opacity: 0.95 }).addTo(map);
  const cursorIcon = L.divIcon({
    className: '',
    html: '<div style="width:12px;height:12px;border-radius:50%;background:#FEC04F;border:2px solid #ffffff;box-shadow:0 4px 12px rgba(0,0,0,0.35);"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
  // Leaflet solo agrega el handler de dragging si `draggable` es true al crear el marker.
  // Para admin queremos poder simular movimiento arrastrando; para usuarios normales no.
  const cursor = L.marker([0, 0], { icon: cursorIcon, draggable: isAdmin, keyboard: false });
  let cursorAdded = false;

  // Admin simulation handlers (so stopWatch can detach them).
	  const onAdminDragEnd = () => {
	    try {
	      const ll = cursor.getLatLng();
	      pushPoint(ll.lat, ll.lng, Date.now(), null, null, false, true);
	    } catch (e) {}
	  };
		  const onAdminMapClick = (ev) => {
		    if (!ev || !ev.latlng) return;
		    pushPoint(ev.latlng.lat, ev.latlng.lng, Date.now(), null, null, false, true);
		  };

	  // Admin joystick simulation (optional): move the marker continuously with a joystick + speed control.
	  let joystickTimer = null;
	  let joystickLastTick = 0;
		  let joystickPointerId = null;
		  let joystickNx = 0; // [-1..1]
		  let joystickNy = 0; // [-1..1]

		  const adminSpeedInput = document.getElementById('adminSimSpeedKmh');
		  const adminStartLatInput = document.getElementById('adminSimStartLat');
		  const adminStartLngInput = document.getElementById('adminSimStartLng');
		  const adminSetStartBtn = document.getElementById('adminSimSetStartBtn');
		  const adminJoystick = document.getElementById('adminSimJoystick');
		  const adminJoyStatus = document.getElementById('adminSimJoystickStatus');
		  const adminJoyStatusText = document.getElementById('adminSimJoystickStatusText');

		  const setJoyStatus = (text) => {
		    const el = adminJoyStatusText || adminJoyStatus;
		    if (el) el.textContent = text;
		    if (adminJoyStatus) {
		      const t = String(text || '');
		      adminJoyStatus.classList.toggle('is-moving', /moviendo/i.test(t));
		    }
		  };

		  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
		  const getAdminSpeedKmh = () => {
		    const raw = Number(adminSpeedInput?.value ?? 0);
		    return Number.isFinite(raw) ? clamp(raw, 0, 60) : 0;
		  };

		  const setAdminSpeedKmh = (v) => {
		    const nv = Number.isFinite(Number(v)) ? clamp(Number(v), 0, 60) : 0;
		    if (adminSpeedInput) adminSpeedInput.value = String(nv);
		  };

			  if (isAdmin && adminSpeedInput) {
			    adminSpeedInput.addEventListener('input', () => setAdminSpeedKmh(adminSpeedInput.value));
			    // Normaliza el valor inicial (clamp).
			    setAdminSpeedKmh(getAdminSpeedKmh());
			  }

		  const setAdminStartInputs = (lat, lng) => {
		    if (adminStartLatInput) adminStartLatInput.value = Number(lat).toFixed(6);
		    if (adminStartLngInput) adminStartLngInput.value = Number(lng).toFixed(6);
		  };

		  const primeAdminStartInputsFromCurrent = () => {
		    if (!isAdmin) return;
		    if (state.points.length) return;

		    const fallbackFromMap = () => {
		      try {
		        const c = map.getCenter();
		        if (Number.isFinite(c.lat) && Number.isFinite(c.lng)) {
		          setAdminStartInputs(c.lat, c.lng);
		          return true;
		        }
		      } catch (e) {}
		      return false;
		    };

		    if (!navigator.geolocation) {
		      if (!fallbackFromMap()) {
		        setAdminStartInputs(25.6866, -100.3161);
		      }
		      return;
		    }

		    navigator.geolocation.getCurrentPosition(
		      (pos) => {
		        const lat = Number(pos.coords?.latitude);
		        const lng = Number(pos.coords?.longitude);
		        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
		          if (!fallbackFromMap()) setAdminStartInputs(25.6866, -100.3161);
		          return;
		        }
		        setAdminStartInputs(lat, lng);
		        if (!state.userInteracted) {
		          try { map.setView([lat, lng], 16); } catch (e) {}
		        }
		        setStatus('Inicio precargado con tu ubicación actual. Presiona "Establecer inicio" para fijarlo.');
		      },
		      () => {
		        if (!fallbackFromMap()) setAdminStartInputs(25.6866, -100.3161);
		      },
		      { enableHighAccuracy: true, maximumAge: 0, timeout: 9000 }
		    );
		  };

			  const setAdminStartPoint = (lat, lng, tsMs, accuracyM = null) => {
			    if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lng))) {
			      setStatus('Coordenadas inválidas.', true);
			      return;
			    }
			    const nlat = Number(lat);
			    const nlng = Number(lng);
			    if (nlat < -90 || nlat > 90 || nlng < -180 || nlng > 180) {
			      setStatus('Coordenadas fuera de rango.', true);
			      return;
			    }
			    if (state.points.length) {
			      setStatus('Este trayecto ya inició. Para cambiar el inicio, crea un nuevo check-in.', true);
			      return;
			    }
			    setAdminStartInputs(nlat, nlng);
			    pushPoint(nlat, nlng, tsMs || Date.now(), null, accuracyM, false, true);
			    setStatus('Inicio establecido. Ahora puedes moverte con el joystick, arrastrar el marcador o tocar el mapa.');
			  };

			  if (isAdmin && adminSetStartBtn) {
			    adminSetStartBtn.addEventListener('click', () => {
			      const lat = Number(adminStartLatInput?.value);
			      const lng = Number(adminStartLngInput?.value);
			      setAdminStartPoint(lat, lng, Date.now(), null);
			    });
			  }

			  if (isAdmin && (adminStartLatInput || adminStartLngInput) && adminSetStartBtn) {
			    const onEnter = (ev) => {
			      if (ev.key !== 'Enter') return;
			      try { ev.preventDefault(); } catch (e) {}
			      try { adminSetStartBtn.click(); } catch (e) {}
			    };
			    try { adminStartLatInput?.addEventListener('keydown', onEnter); } catch (e) {}
			    try { adminStartLngInput?.addEventListener('keydown', onEnter); } catch (e) {}
			  }

		  const resetJoystickUi = () => {
		    if (!adminJoystick) return;
		    joystickNx = 0;
	    joystickNy = 0;
	    adminJoystick.style.setProperty('--jx', '0px');
	    adminJoystick.style.setProperty('--jy', '0px');
	  };

		  const stopJoystick = () => {
		    if (joystickTimer) {
		      try { clearInterval(joystickTimer); } catch (e) {}
		    }
		    joystickTimer = null;
		    joystickPointerId = null;
		    resetJoystickUi();
		    setJoyStatus('Arrastra el joystick sobre el mapa para moverte. Suelta para detener.');
		  };

	  const stepJoystick = (dtS) => {
	    if (!isAdmin) return;
	    if (!cursorAdded) return;
	    const speedKmh = getAdminSpeedKmh();
	    if (!(speedKmh > 0)) return;

	    const mag = Math.min(1, Math.hypot(joystickNx, joystickNy));
	    if (mag < 0.07) return; // deadzone

	    const speedMps = (speedKmh * 1000) / 3600;
	    // East/North meters for this tick. joystickNy is positive down, so north is -ny.
	    const eastM = speedMps * dtS * joystickNx;
	    const northM = speedMps * dtS * (-joystickNy);

	    try {
	      const ll = cursor.getLatLng();
	      const latRad = toRad(ll.lat);
	      const dLat = northM / 111111;
	      const denom = 111111 * Math.cos(latRad);
	      const dLng = denom ? (eastM / denom) : 0;
	      const nextLat = ll.lat + dLat;
	      const nextLng = ll.lng + dLng;
	      const effSpeed = speedKmh * mag;
	      pushPoint(nextLat, nextLng, Date.now(), effSpeed, null, false, true);
	    } catch (e) {}
	  };

	  const startJoystick = () => {
	    if (joystickTimer) return;
	    joystickLastTick = (window.performance && typeof window.performance.now === 'function') ? window.performance.now() : Date.now();
	    joystickTimer = setInterval(() => {
	      const now = (window.performance && typeof window.performance.now === 'function') ? window.performance.now() : Date.now();
	      const dtS = Math.max(0.02, (now - joystickLastTick) / 1000);
	      joystickLastTick = now;
	      stepJoystick(dtS);
	    }, 120);
	  };

	  const updateJoystickFromPointer = (ev) => {
	    if (!adminJoystick) return;
	    const rect = adminJoystick.getBoundingClientRect();
	    const cx = rect.left + rect.width / 2;
	    const cy = rect.top + rect.height / 2;
	    const knobEl = adminJoystick.querySelector('.admin-joystick-knob');
	    const knobRect = knobEl ? knobEl.getBoundingClientRect() : { width: 28, height: 28 };
	    const knobR = Math.max(10, (Math.min(knobRect.width, knobRect.height) / 2) || 14);
	    const maxR = Math.max(10, (Math.min(rect.width, rect.height) / 2) - knobR - 6);

	    let dx = (ev.clientX - cx);
	    let dy = (ev.clientY - cy);
	    const dist = Math.hypot(dx, dy);
	    if (dist > maxR) {
	      const s = maxR / dist;
	      dx *= s;
	      dy *= s;
	    }

	    // Normalize [-1..1]
	    joystickNx = clamp(dx / maxR, -1, 1);
	    joystickNy = clamp(dy / maxR, -1, 1);

	    adminJoystick.style.setProperty('--jx', `${dx.toFixed(1)}px`);
	    adminJoystick.style.setProperty('--jy', `${dy.toFixed(1)}px`);
	  };

	  if (isAdmin && adminJoystick) {
	    resetJoystickUi();

		    adminJoystick.addEventListener('pointerdown', (ev) => {
		      try { ev.preventDefault(); } catch (e) {}
		      if (joystickPointerId != null) return;
		      joystickPointerId = ev.pointerId;
		      try { adminJoystick.setPointerCapture(ev.pointerId); } catch (e) {}
		      updateJoystickFromPointer(ev);
		      startJoystick();
		      setJoyStatus('Moviendo…');
		    });

	    adminJoystick.addEventListener('pointermove', (ev) => {
	      if (joystickPointerId == null || ev.pointerId !== joystickPointerId) return;
	      try { ev.preventDefault(); } catch (e) {}
	      updateJoystickFromPointer(ev);
	    });

	    const end = (ev) => {
	      if (joystickPointerId == null) return;
	      if (ev && ev.pointerId != null && ev.pointerId !== joystickPointerId) return;
	      try { ev.preventDefault(); } catch (e) {}
	      try { adminJoystick.releasePointerCapture(joystickPointerId); } catch (e) {}
	      stopJoystick();
	    };
	    adminJoystick.addEventListener('pointerup', end);
	    adminJoystick.addEventListener('pointercancel', end);
	    adminJoystick.addEventListener('lostpointercapture', () => stopJoystick());
	  }

	  const updateElapsed = () => {
	    if (state.startTs == null || !elapsedEl) return;
	    elapsedEl.textContent = formatHms((Date.now() - state.startTs) / 1000);
	  };

  const renderSegments = () => {
    if (!segWrap) return;
    const segs = Array.from(state.segments.values()).sort((a, b) => a.idx - b.idx);
    const last = segs.slice(-6);
    if (!last.length) {
      segWrap.innerHTML = '<div class="small text-secondary">Aún no hay tramos registrados.</div>';
      return;
    }
    segWrap.innerHTML = last.map((seg) => {
      const durS = Math.max(1, (seg.endTs - seg.startTs) / 1000);
      const km = seg.distM / 1000;
      const speed = (km / (durS / 3600));
      const a = formatHms((seg.startTs - state.startTs) / 1000);
      const b = formatHms((seg.endTs - state.startTs) / 1000);
      return `
        <div class="p-2 rounded" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <div class="small text-secondary">Tramo ${seg.idx + 1} · ${a}-${b}</div>
            <div class="fw-semibold text-white">${Number.isFinite(speed) ? speed.toFixed(1) : '0.0'} km/h</div>
          </div>
          <div class="small text-secondary">${km.toFixed(2)} km</div>
        </div>
      `;
    }).join('');
  };

  const updateMetrics = () => {
    updateElapsed();
    if (distEl) distEl.textContent = (state.totalM / 1000).toFixed(2);
    if (speedEl) speedEl.textContent = state.lastPoint && Number.isFinite(state.lastPoint.speedKmh) ? state.lastPoint.speedKmh.toFixed(1) : '--';
    if (segCountEl) segCountEl.textContent = String(state.segments.size);
    renderSegments();
  };

	  const maybeSendPoint = async (p) => {
	    const now = Date.now();
	    const movedM = state.lastSentPoint ? haversineM(state.lastSentPoint.lat, state.lastSentPoint.lng, p.lat, p.lng) : Infinity;
	    // Throttle: en admin (modo prueba) guardamos mas seguido para que el resumen quede mas fiel.
	    const throttleMs = isAdmin ? 1000 : 5000;
	    const minMoveM = isAdmin ? 3 : 20;
	    if (now - state.lastSentAt < throttleMs && movedM < minMoveM) return;
	    state.lastSentAt = now;
	    state.lastSentPoint = { lat: p.lat, lng: p.lng };
	    try {
      await fetch(`/api/safety/checkin/${checkinId}/route/point`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
        },
        body: JSON.stringify({
          lat: p.lat,
          lng: p.lng,
          ts_ms: p.ts,
          speed_kmh: p.speedKmh,
          accuracy_m: p.accuracyM,
        }),
      });
    } catch (e) {
      // Silencioso: si falla, seguimos dibujando localmente.
    }
  };

	  const pushPoint = (lat, lng, tsMs, speedKmh, accuracyM, fromServer = false, force = false) => {
	    const ts = Number(tsMs) || Date.now();
	    const p = {
	      lat: Number(lat),
	      lng: Number(lng),
      ts,
      speedKmh: (speedKmh != null && Number.isFinite(Number(speedKmh))) ? Number(speedKmh) : null,
      accuracyM: (accuracyM != null && Number.isFinite(Number(accuracyM))) ? Number(accuracyM) : null,
    };

    if (!Number.isFinite(p.lat) || !Number.isFinite(p.lng)) return;
    if (state.startTs == null) state.startTs = ts;

	    if (state.lastPoint) {
	      const dM = haversineM(state.lastPoint.lat, state.lastPoint.lng, p.lat, p.lng);
	      const dtS = Math.max(0.001, (p.ts - state.lastPoint.ts) / 1000);
	      // Evita ruido GPS (solo para puntos del live tracking)
	      if (!fromServer && !force && dM < 2) return;

      state.totalM += dM;

      if (p.speedKmh == null || !Number.isFinite(p.speedKmh)) {
        p.speedKmh = (dM / dtS) * 3.6;
      }

      const segIdx = Math.floor((state.lastPoint.ts - state.startTs) / state.segmentWindowMs);
      let seg = state.segments.get(segIdx);
      if (!seg) {
        seg = { idx: segIdx, startTs: state.lastPoint.ts, endTs: p.ts, distM: 0 };
        state.segments.set(segIdx, seg);
      }
      seg.distM += dM;
      seg.endTs = p.ts;
    }

    state.points.push(p);
    state.lastPoint = p;

    const ll = [p.lat, p.lng];
    routeLine.addLatLng(ll);
    if (!cursorAdded) {
      cursor.setLatLng(ll).addTo(map);
      cursorAdded = true;
      map.setView(ll, 16);
	    } else {
	      cursor.setLatLng(ll);
	      if (!state.userInteracted) {
	        if (isAdmin) {
	          map.panTo(ll, { animate: false });
	        } else {
	          map.panTo(ll, { animate: true, duration: 0.25 });
	        }
	      }
	    }

    updateMetrics();
    if (!fromServer) maybeSendPoint(p);
  };

  const loadExisting = async () => {
    try {
      const resp = await fetch(`/api/safety/checkin/${checkinId}/route/points`);
      const data = await resp.json();
      if (!resp.ok || !data.ok) return;
      if (Array.isArray(data.points)) {
        data.points.forEach((pt) => pushPoint(pt.lat, pt.lng, pt.ts_ms, pt.speed_kmh, pt.accuracy_m, true));
      }
      if (state.points.length >= 2) {
        try {
          map.fitBounds(routeLine.getBounds(), { padding: [18, 18] });
        } catch (e) {}
      }
    } catch (e) {
      // ignore
    }
  };

	  const startWatch = () => {
	    if (isAdmin) {
	      if (!state.points.length) {
	        setStatus('Modo prueba (admin): inicio precargado. Ajusta coordenadas o usa joystick/tap para simular movimiento.');
	        const fallback = [25.6866, -100.3161];
	        try { map.setView(fallback, 14); } catch (e) {}
	        primeAdminStartInputsFromCurrent();
	      } else {
	        setStatus('Modo prueba (admin): usa el joystick, arrastra el marcador o toca el mapa para simular tu ubicación.');
	      }
	      try { cursor.dragging.enable(); } catch (e) {}
	      try { cursor.on('dragend', onAdminDragEnd); } catch (e) {}
	      try { map.on('click', onAdminMapClick); } catch (e) {}
	      return;
	    }

    if (!navigator.geolocation) {
      setStatus('Geolocalización no disponible en este dispositivo.', true);
      return;
    }

    setStatus('Registrando ruta…');
    state.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        const lat = pos.coords?.latitude;
        const lng = pos.coords?.longitude;
        if (lat == null || lng == null) return;
        const speedKmh = (pos.coords?.speed != null && Number.isFinite(pos.coords.speed)) ? (pos.coords.speed * 3.6) : null;
        const accuracyM = (pos.coords?.accuracy != null && Number.isFinite(pos.coords.accuracy)) ? pos.coords.accuracy : null;
        pushPoint(lat, lng, pos.timestamp, speedKmh, accuracyM, false);
      },
      (err) => {
        setStatus(err?.message || 'No se pudo obtener tu ubicación.', true);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10000 }
    );
  };

  const stopWatch = () => {
    if (state.watchId != null && navigator.geolocation) {
      try { navigator.geolocation.clearWatch(state.watchId); } catch (e) {}
    }
    state.watchId = null;

	    // Admin simulation: detach handlers and disable dragging.
	    if (isAdmin) {
	      try { cursor.off('dragend', onAdminDragEnd); } catch (e) {}
	      try { map.off('click', onAdminMapClick); } catch (e) {}
	      try { cursor.dragging.disable(); } catch (e) {}
	      stopJoystick();
	    }
	  };

  // Exponer para que los botones "Ya llegué / Cancelar" detengan el tracking.
  window.__stopMyRouteTracker = stopWatch;
  window.addEventListener('beforeunload', stopWatch);

  // Timer de UI (por si no llegan puntos constantemente)
  setInterval(updateElapsed, 1000);

  // Pintar lo que ya exista y empezar a seguir.
  loadExisting().finally(() => startWatch());
});

// --- Historial de trayectos (acordeón + resumen animado) ---------------------
document.addEventListener('DOMContentLoaded', () => {
  const accordion = document.getElementById('tripHistoryAccordion');
  if (!accordion) return;
  if (!window.L) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const initialized = new Set();

  const toRad = (deg) => (deg * Math.PI) / 180;
  const haversineM = (lat1, lon1, lat2, lon2) => {
    const R = 6371000;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.asin(Math.sqrt(a));
    return R * c;
  };

  const formatHms = (secs) => {
    const s = Math.max(0, Math.floor(Number(secs) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
    return `${m}:${String(r).padStart(2, '0')}`;
  };
  const formatDuration = (secs) => {
    const s = Math.max(0, Math.floor(Number(secs) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${r}s`;
    return `${r}s`;
  };

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  async function initTripSummary(checkinId) {
    const mapEl = document.getElementById(`tripMap${checkinId}`);
    if (!mapEl) return;

    const statusEl = document.getElementById(`tripStatus${checkinId}`);
    const segWrap = document.getElementById(`tripSegments${checkinId}`);
    if (statusEl) statusEl.textContent = 'Cargando ruta…';

    let data;
    try {
      const resp = await fetch(`/api/safety/checkin/${checkinId}/route/points`);
      data = await resp.json();
      if (!resp.ok || !data.ok) {
        if (statusEl) statusEl.textContent = data?.error || 'No se pudo cargar la ruta.';
        return;
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = 'No se pudo cargar la ruta.';
      return;
    }

    const pts = Array.isArray(data.points) ? data.points : [];
    const coords = pts.map(p => [Number(p.lat), Number(p.lng), Number(p.ts_ms || 0)]).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]) && Number.isFinite(p[2]));

    const map = L.map(mapEl, { zoomControl: true, attributionControl: false });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, subdomains: ['a', 'b', 'c'] }).addTo(map);
    setTimeout(() => { try { map.invalidateSize(); } catch (e) {} }, 0);

    if (coords.length < 2) {
      if (statusEl) statusEl.textContent = 'Aún no hay suficientes puntos para reproducir la ruta.';
      map.setView([25.6866, -100.3161], 12);
      setText(`tripDistance${checkinId}`, '0.00');
      setText(`tripDuration${checkinId}`, '0s');
      setText(`tripAvgSpeed${checkinId}`, '0.0');
      setText(`tripMaxSpeed${checkinId}`, '0.0');
      if (segWrap) segWrap.innerHTML = '<div class="small text-secondary">Sin tramos para mostrar.</div>';
      return;
    }

    const startTs = coords[0][2];
    const endTs = coords[coords.length - 1][2];
    const durationSec = Math.max(0, (endTs - startTs) / 1000);

    let totalM = 0;
    let maxSpeed = 0;
    const segWinMs = 60000;
    const segMap = new Map();

    for (let i = 1; i < coords.length; i++) {
      const a = coords[i - 1];
      const b = coords[i];
      const dtS = (b[2] - a[2]) / 1000;
      if (!(dtS > 0)) continue;
      const dM = haversineM(a[0], a[1], b[0], b[1]);
      totalM += dM;
      const sp = (dM / dtS) * 3.6;
      if (sp > maxSpeed) maxSpeed = sp;

      const idx = Math.floor((a[2] - startTs) / segWinMs);
      let seg = segMap.get(idx);
      if (!seg) {
        seg = { idx, startTs: a[2], endTs: b[2], distM: 0 };
        segMap.set(idx, seg);
      }
      seg.distM += dM;
      seg.endTs = b[2];
    }

    const distanceKm = totalM / 1000;
    const avgSpeed = durationSec > 0 ? (distanceKm / (durationSec / 3600)) : 0;

    setText(`tripDistance${checkinId}`, distanceKm.toFixed(2));
    setText(`tripDuration${checkinId}`, formatDuration(durationSec));
    setText(`tripAvgSpeed${checkinId}`, Number.isFinite(avgSpeed) ? avgSpeed.toFixed(1) : '0.0');
    setText(`tripMaxSpeed${checkinId}`, Number.isFinite(maxSpeed) ? maxSpeed.toFixed(1) : '0.0');

    const segs = Array.from(segMap.values()).sort((x, y) => x.idx - y.idx);
    if (segWrap) {
      if (!segs.length) {
        segWrap.innerHTML = '<div class="small text-secondary">Sin tramos para mostrar.</div>';
      } else {
        const shown = segs.slice(0, 18);
        segWrap.innerHTML = shown.map((seg) => {
          const durS = Math.max(1, (seg.endTs - seg.startTs) / 1000);
          const km = seg.distM / 1000;
          const sp = (km / (durS / 3600));
          const a = formatHms((seg.startTs - startTs) / 1000);
          const b = formatHms((seg.endTs - startTs) / 1000);
          return `
            <div class="p-2 rounded" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);">
              <div class="d-flex align-items-center justify-content-between gap-2">
                <div class="small text-secondary">Tramo ${seg.idx + 1} · ${a}-${b}</div>
                <div class="fw-semibold text-white">${Number.isFinite(sp) ? sp.toFixed(1) : '0.0'} km/h</div>
              </div>
              <div class="small text-secondary">${km.toFixed(2)} km</div>
            </div>
          `;
        }).join('');
      }
    }

    const lineCoords = coords.map(p => [p[0], p[1]]);
    const full = L.polyline(lineCoords, { color: '#a78bfa', weight: 5, opacity: 0.22 }).addTo(map);
    const anim = L.polyline([], { color: '#FEC04F', weight: 5, opacity: 0.95 }).addTo(map);
    const marker = L.circleMarker(lineCoords[0], { radius: 6, color: '#ffffff', weight: 2, fillColor: '#FEC04F', fillOpacity: 1 }).addTo(map);

    try { map.fitBounds(full.getBounds(), { padding: [18, 18] }); } catch (e) {}

    if (statusEl) statusEl.textContent = 'Reproduciendo ruta…';
    let i = 0;
    const step = Math.max(1, Math.floor(lineCoords.length / 220));
    const tickMs = 18;
    const timer = setInterval(() => {
      if (i >= lineCoords.length) {
        clearInterval(timer);
        if (statusEl) statusEl.textContent = 'Ruta completa.';
        return;
      }
      for (let k = 0; k < step && i < lineCoords.length; k++, i++) {
        anim.addLatLng(lineCoords[i]);
      }
      marker.setLatLng(lineCoords[Math.max(0, i - 1)]);
    }, tickMs);
  }

  accordion.addEventListener('shown.bs.collapse', (e) => {
    const collapseEl = e.target;
    const checkinId = collapseEl?.getAttribute?.('data-checkin-id');
    if (!checkinId) return;
    if (initialized.has(checkinId)) return;
    initialized.add(checkinId);
    initTripSummary(checkinId);
  });

  document.querySelectorAll('[data-trip-save-title]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const id = btn.getAttribute('data-trip-save-title');
      if (!id) return;
      const input = document.getElementById(`tripTitleInput${id}`);
      const status = document.getElementById(`tripTitleSaveStatus${id}`);
      const header = document.getElementById(`tripTitleHeader${id}`);
      const raw = (input && 'value' in input) ? String(input.value || '') : '';
      const next = raw.trim();
      const def = input?.getAttribute?.('data-default-title') || `Trayecto`;

      if (status) status.textContent = 'Guardando…';
      try {
        const resp = await fetch(`/api/safety/checkin/${id}/title`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ title: next })
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          if (status) status.textContent = data?.error || 'No se pudo guardar el título.';
          return;
        }
        const finalTitle = (data.title || '').trim() || def;
        if (header) header.textContent = finalTitle;
        if (input) input.value = finalTitle;
        if (status) status.textContent = 'Título actualizado.';
        setTimeout(() => { if (status) status.textContent = ''; }, 1500);
      } catch (err) {
        if (status) status.textContent = 'No se pudo guardar el título.';
      }
    });
  });
});
