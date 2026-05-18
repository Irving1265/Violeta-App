(function () {
  const AVATAR_TONES = ['violet', 'rose', 'amber', 'emerald'];
  const ROUTE_CONFIGS = {
    office: {
      startLabel: 'Casa',
      endLabel: 'Oficina',
      summaryPath: 'M 42 142 C 70 130, 88 108, 112 92 S 162 82, 196 72 S 244 46, 278 42',
      miniPath: 'M 28 98 C 48 86, 68 62, 92 56 S 130 52, 158 30',
    },
    metro: {
      startLabel: 'Metro',
      endLabel: 'Casa',
      summaryPath: 'M 58 34 C 92 46, 118 68, 132 92 S 164 126, 196 132 S 238 128, 270 148',
      miniPath: 'M 32 24 C 58 30, 76 52, 92 76 S 122 96, 156 102',
    },
    uni: {
      startLabel: 'Universidad',
      endLabel: 'Casa de Ana',
      summaryPath: 'M 34 120 C 72 108, 92 82, 118 78 S 172 98, 192 92 S 232 62, 286 50',
      miniPath: 'M 24 96 C 52 88, 72 62, 96 58 S 128 62, 160 28',
    },
  };
  const DEFAULT_SAFETY_CENTER = [25.6866, -100.3161];
  const DESTINATION_METRO_BBOX = '-100.80,26.10,-99.90,25.30';
  const DESTINATION_ALLOWED_CITIES = new Set([
    'monterrey',
    'san pedro garza garcia', 'san pedro',
    'san nicolas de los garza',
    'guadalupe',
    'apodaca',
    'general escobedo', 'escobedo',
    'pesqueria',
    'santa catarina', 'sta catarina',
    'garcia',
    'juarez', 'ciudad benito juarez', 'benito juarez', 'cd benito juarez',
  ]);
  const SAFETY_VIEW_STATES = new Set(['idle', 'active', 'contacts', 'history']);

  function parseJSONScript(root, id) {
    const node = root.querySelector(`#${id}`);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent || '{}');
    } catch (error) {
      console.error('No se pudo parsear JSON de safety:', error);
      return null;
    }
  }

  function safeStorage(op, key, value) {
    try {
      if (!window.localStorage) return null;
      if (op === 'get') return window.localStorage.getItem(key);
      if (op === 'set') return window.localStorage.setItem(key, value);
    } catch (error) {
      return null;
    }
    return null;
  }

  function formatContactList(labels) {
    if (!labels.length) return 'Nadie por ahora';
    if (labels.length === 1) return labels[0];
    if (labels.length === 2) return `${labels[0]} y ${labels[1]}`;
    return `${labels.slice(0, -1).join(', ')} y ${labels[labels.length - 1]}`;
  }

  function getContactInitials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'CT';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }

  function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function formatMinutesLabel(totalMinutes) {
    const minutes = Math.max(1, Number(totalMinutes) || 0);
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60);
      const rest = minutes % 60;
      return rest ? `${hours} h ${rest} min` : `${hours} h`;
    }
    return `${minutes} min`;
  }

  function formatDurationFromSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours) {
      return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
    }
    if (minutes) {
      return `${minutes} min`;
    }
    return '0 min';
  }

  function formatCountdown(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.ceil(total / 60);
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60);
      const rest = minutes % 60;
      return rest ? `${hours} h ${rest} min` : `${hours} h`;
    }
    return `${Math.max(0, minutes)} min`;
  }

  function formatNowLabel() {
    const now = new Date();
    const today = now.toLocaleTimeString('es-MX', { hour: 'numeric', minute: '2-digit', hour12: true });
    return `Hoy · ${today}`;
  }

  function loadUiState(data) {
    const storageKey = `violeta:safety-ui:${data.currentUserId || 'anon'}`;
    const raw = safeStorage('get', storageKey);
    let parsed = {};
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch (error) {
      parsed = {};
    }

    const selectedIds = Array.isArray(parsed.selectedIds) ? parsed.selectedIds.map(String) : [];
    const noDestination = Boolean(parsed.noDestination);
    return { storageKey, selectedIds, noDestination };
  }

  function readPendingHotspotsPlan() {
    let params = null;
    try {
      params = new URLSearchParams(window.location.search || '');
    } catch (error) {
      params = new URLSearchParams();
    }

    let stored = {};
    try {
      stored = JSON.parse(window.sessionStorage?.getItem('violeta.pendingCheckin') || '{}') || {};
    } catch (error) {
      stored = {};
    }

    const destinationLabel = String(params.get('destination') || stored.destinationLabel || '').trim();
    const etaRaw = Number(params.get('eta') || stored.etaMinutes || 0);
    const etaMinutes = Number.isFinite(etaRaw) && etaRaw > 0 ? clamp(Math.round(etaRaw), 5, 180) : null;
    const destinationPoint = Array.isArray(stored.destinationPoint) ? stored.destinationPoint : null;
    const destinationLat = toCoord(destinationPoint?.[0]);
    const destinationLng = toCoord(destinationPoint?.[1]);

    if (!destinationLabel && !etaMinutes && !hasValidCoords(destinationLat, destinationLng)) {
      return null;
    }

    return {
      destinationLabel,
      etaMinutes,
      destinationLat,
      destinationLng,
    };
  }

  function persistUiState(runtime) {
    const payload = {
      selectedIds: runtime.contacts.filter((contact) => contact.isSharing).map((contact) => String(contact.id)),
      noDestination: Boolean(runtime.noDestination),
    };
    safeStorage('set', runtime.storageKey, JSON.stringify(payload));
  }

  function chooseTone(index, preferred) {
    return preferred || AVATAR_TONES[index % AVATAR_TONES.length];
  }

  function cloneTrip(trip) {
    return Object.assign({}, trip || {});
  }

  function pickRouteStyle(index) {
    const keys = Object.keys(ROUTE_CONFIGS);
    return keys[index % keys.length];
  }

  function finishAnimation(animation) {
    if (!animation || !animation.finished) return Promise.resolve();
    return animation.finished.catch(() => undefined);
  }

  function animateNode(node, keyframes, options) {
    if (!node || typeof node.animate !== 'function') return null;
    try {
      if (typeof node.getAnimations === 'function') {
        node.getAnimations().forEach((animation) => animation.cancel());
      }
      return node.animate(keyframes, options);
    } catch (error) {
      return null;
    }
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function toCoord(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function hasValidCoords(lat, lng) {
    return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
  }

  function getDistanceBetweenCoords(a, b) {
    const latMeters = (b[0] - a[0]) * 111320;
    const avgLat = ((a[0] + b[0]) / 2) * (Math.PI / 180);
    const lngMeters = (b[1] - a[1]) * 111320 * Math.max(0.25, Math.cos(avgLat));
    return Math.sqrt((latMeters ** 2) + (lngMeters ** 2));
  }

  function hashString(value) {
    const source = String(value || '');
    let hash = 0;
    for (let index = 0; index < source.length; index += 1) {
      hash = ((hash << 5) - hash) + source.charCodeAt(index);
      hash |= 0;
    }
    return Math.abs(hash);
  }

  function metersToLatOffset(meters) {
    return meters / 111320;
  }

  function metersToLngOffset(meters, lat) {
    return meters / (111320 * Math.max(0.25, Math.cos((lat * Math.PI) / 180)));
  }

  function getCheckinStartCoords(checkin) {
    const lat = toCoord(checkin?.latitude);
    const lng = toCoord(checkin?.longitude);
    if (hasValidCoords(lat, lng)) {
      return [lat, lng];
    }
    return DEFAULT_SAFETY_CENTER.slice();
  }

  function buildSimulatedDestinationCoords(startCoords, checkin) {
    const seed = hashString(`${checkin?.id || 'trip'}:${checkin?.destination || checkin?.display_destination || 'destino'}`);
    const angle = ((seed % 360) * Math.PI) / 180;
    const etaMinutes = clamp(Number(checkin?.eta_minutes) || 30, 5, 180);
    const distanceMeters = clamp(etaMinutes * 85, 700, 5200);
    const latOffset = metersToLatOffset(Math.sin(angle) * distanceMeters);
    const lngOffset = metersToLngOffset(Math.cos(angle) * distanceMeters, startCoords[0]);
    return [startCoords[0] + latOffset, startCoords[1] + lngOffset];
  }

  function buildSimulatedRoute(startCoords, endCoords, seed) {
    const latDelta = endCoords[0] - startCoords[0];
    const lngDelta = endCoords[1] - startCoords[1];
    const midpoint = [
      (startCoords[0] + endCoords[0]) / 2,
      (startCoords[1] + endCoords[1]) / 2,
    ];
    const curveAmount = (((seed % 21) - 10) / 100) || 0.04;
    const controlPoint = [
      midpoint[0] + (lngDelta * curveAmount),
      midpoint[1] - (latDelta * curveAmount),
    ];
    const points = [];
    for (let step = 0; step <= 28; step += 1) {
      const progress = step / 28;
      const oneMinus = 1 - progress;
      const lat = (oneMinus * oneMinus * startCoords[0])
        + (2 * oneMinus * progress * controlPoint[0])
        + (progress * progress * endCoords[0]);
      const lng = (oneMinus * oneMinus * startCoords[1])
        + (2 * oneMinus * progress * controlPoint[1])
        + (progress * progress * endCoords[1]);
      points.push([lat, lng]);
    }
    return points;
  }

  function sendCheckinWithGeo(endpoint, payload) {
    const nativeBridge = window.VioletaNativeBridge || null;
    const send = (lat = null, lng = null) => fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify(Object.assign({}, payload, { lat, lng })),
    }).then(async (response) => ({
      ok: response.ok,
      data: await response.json(),
    }));

    if (nativeBridge && typeof nativeBridge.getCurrentPosition === 'function') {
      return nativeBridge.getCurrentPosition({
        enableHighAccuracy: true,
        timeout: 7000,
        maximumAge: 0,
      })
        .then((position) => send(position?.lat ?? null, position?.lng ?? null))
        .catch(() => send(null, null));
    }

    if (!navigator.geolocation) {
      return send(null, null);
    }

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        async (position) => resolve(await send(position.coords.latitude, position.coords.longitude)),
        async () => resolve(await send(null, null)),
        { enableHighAccuracy: true, timeout: 7000, maximumAge: 0 },
      );
    });
  }

  function initSafetyPage(root) {
    if (!root || root.dataset.enhanced === 'true') {
      return;
    }
    root.dataset.enhanced = 'true';

    const data = parseJSONScript(root, 'safetyPageData') || {};
    const uiState = loadUiState(data);
    const selectedIdsSet = new Set(uiState.selectedIds);
    const pendingHotspotsPlan = data.activeCheckin ? null : readPendingHotspotsPlan();

    const runtime = {
      storageKey: uiState.storageKey,
      currentState: '',
      previousState: data.initialState || (data.activeCheckin ? 'active' : 'idle'),
      currentContactFilter: 'all',
      destination: data.activeCheckin?.destination || pendingHotspotsPlan?.destinationLabel || '',
      noDestination: Boolean(uiState.noDestination && !data.activeCheckin?.destination && !pendingHotspotsPlan?.destinationLabel),
      destinationPlace: pendingHotspotsPlan?.destinationLabel && hasValidCoords(pendingHotspotsPlan.destinationLat, pendingHotspotsPlan.destinationLng)
        ? {
            display_name: pendingHotspotsPlan.destinationLabel,
            lat: pendingHotspotsPlan.destinationLat,
            lon: pendingHotspotsPlan.destinationLng,
            address: {},
          }
        : null,
      destinationSearchTimer: null,
      destinationSuggestionState: {
        items: [],
        activeIndex: -1,
        requestId: 0,
      },
      etaMinutes: Number(data.activeCheckin?.eta_minutes || pendingHotspotsPlan?.etaMinutes || 30),
      statusMessage: '',
      editingContactId: null,
      editingAvatarTone: 'violet',
      pendingDeleteContactId: null,
      timerId: null,
      summaryAnchorNode: null,
      routePoints: [],
      routePollTimer: null,
      routeWatchHandle: null,
      routeTrackingCheckinId: null,
      routeLastPersistedPoint: null,
      routeRequestToken: 0,
      activeDrag: null,
      stateTransitionTimer: null,
      mapState: null,
      summaryMapState: null,
      contacts: Array.isArray(data.contacts)
        ? data.contacts.map((contact, index) => ({
            id: String(contact.id),
            name: contact.name,
            phone: contact.phone,
            relationship: contact.relationship || '',
            isPrimary: Boolean(contact.is_primary),
            avatarTone: chooseTone(index, contact.avatar_tone),
            isSharing: selectedIdsSet.size
              ? selectedIdsSet.has(String(contact.id))
              : index < Math.min(2, data.contacts.length),
          }))
        : [],
      activeCheckin: data.activeCheckin ? Object.assign({}, data.activeCheckin) : null,
      tripItems: Array.isArray(data.tripItems) ? data.tripItems.map(cloneTrip) : [],
      endpoints: data.endpoints || {},
      dom: {
        mobileStates: Array.from(root.querySelectorAll('.mobile-state')),
        desktopStates: Array.from(root.querySelectorAll('.desktop-state')),
        previewLinks: Array.from(root.querySelectorAll('[data-preview-link]')),
        previewBackButtons: Array.from(root.querySelectorAll('[data-preview-back]')),
        statusNodes: Array.from(root.querySelectorAll('[data-safety-status]')),
        destinationInputs: Array.from(root.querySelectorAll('[data-destination-input]')),
        destinationToggleButtons: Array.from(root.querySelectorAll('[data-destination-toggle]')),
        destinationShells: Array.from(root.querySelectorAll('[data-destination-shell]')),
        destinationHelpers: Array.from(root.querySelectorAll('[data-destination-helper]')),
        destinationStatusBoxes: Array.from(root.querySelectorAll('[data-destination-status-box]')),
        desktopDestinationInput: root.querySelector('#desktopDestinationInput'),
        desktopDestinationResults: root.querySelector('#desktopDestinationResults'),
        desktopDestinationResultsList: root.querySelector('[data-destination-results-list]'),
        etaButtons: Array.from(root.querySelectorAll('[data-eta-value]')),
        startButtons: Array.from(root.querySelectorAll('[data-start-checkin]')),
        arriveButtons: Array.from(root.querySelectorAll('[data-arrive-safe]')),
        cancelButtons: Array.from(root.querySelectorAll('[data-cancel-trip]')),
        contactFilterButtons: Array.from(root.querySelectorAll('[data-contact-filter]')),
        createContactButtons: Array.from(root.querySelectorAll('[data-contact-create]')),
        contactListContainers: Array.from(root.querySelectorAll('[data-contact-list]')),
        historyListContainers: Array.from(root.querySelectorAll('[data-history-list]')),
        shareSummaryTitles: Array.from(root.querySelectorAll('[data-share-summary-title]')),
        shareSummaryCounts: Array.from(root.querySelectorAll('[data-share-summary-count]')),
        shareSummaryLists: Array.from(root.querySelectorAll('[data-share-summary-list]')),
        shareSummaryAvatars: Array.from(root.querySelectorAll('[data-share-summary-avatars]')),
        readyChipCopies: Array.from(root.querySelectorAll('[data-ready-chip-copy]')),
        activeShareCount: Array.from(root.querySelectorAll('[data-active-share-count]')),
        activeSupportCopy: Array.from(root.querySelectorAll('[data-active-support-copy]')),
        activeDestination: Array.from(root.querySelectorAll('[data-active-destination]')),
        activeDestinationInline: Array.from(root.querySelectorAll('[data-active-destination-inline]')),
        activeEtaBig: Array.from(root.querySelectorAll('[data-active-eta-big]')),
        activeEtaInline: Array.from(root.querySelectorAll('[data-active-eta-inline]')),
        activeElapsed: Array.from(root.querySelectorAll('[data-active-elapsed]')),
        activeTotal: Array.from(root.querySelectorAll('[data-active-total]')),
        activeLiveMap: root.querySelector('[data-active-live-map]'),
        draggableSheets: Array.from(root.querySelectorAll('[data-draggable-sheet]')),
        summaryModal: root.querySelector('#summaryModal'),
        summaryModalPanel: root.querySelector('#summaryModal .summary-modal'),
        summaryModalClose: root.querySelector('#summaryModalClose'),
        summaryModalBadge: root.querySelector('#summaryModalBadge'),
        summaryModalTitle: root.querySelector('#summaryModalTitle'),
        summaryModalMeta: root.querySelector('#summaryModalMeta'),
        summaryMetricTime: root.querySelector('#summaryMetricTime'),
        summaryMetricContacts: root.querySelector('#summaryMetricContacts'),
        summaryMetricExtra: root.querySelector('#summaryMetricExtra'),
        summaryModalBody: root.querySelector('#summaryModalBody'),
        summaryRouteLiveMap: root.querySelector('#summaryRouteLiveMap'),
        summaryRouteStatus: root.querySelector('#summaryRouteStatus'),
        contactEditorModal: root.querySelector('#contactEditorModal'),
        contactEditorClose: root.querySelector('#contactEditorClose'),
        contactEditorForm: root.querySelector('#contactEditorForm'),
        contactEditorEyebrow: root.querySelector('#contactEditorEyebrow'),
        contactEditorTitle: root.querySelector('#contactEditorTitle'),
        contactEditorDelete: root.querySelector('#contactEditorDelete'),
        contactNameInput: root.querySelector('#contactNameInput'),
        contactRelationInput: root.querySelector('#contactRelationInput'),
        contactPhoneInput: root.querySelector('#contactPhoneInput'),
        contactAvatarPicker: root.querySelector('#contactAvatarPicker'),
        contactDeleteModal: root.querySelector('#contactDeleteModal'),
        contactDeleteMeta: root.querySelector('#contactDeleteMeta'),
        contactDeleteCancel: root.querySelector('#contactDeleteCancel'),
        contactDeleteConfirm: root.querySelector('#contactDeleteConfirm'),
      },
    };

    function setStatus(message, tone) {
      runtime.statusMessage = String(message || '').trim();
      runtime.dom.statusNodes.forEach((node) => {
        node.textContent = runtime.statusMessage;
        node.dataset.tone = tone || '';
      });
    }

    function clearStatus() {
      setStatus('', '');
    }

    function normalizeLocationText(value) {
      return String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .trim();
    }

    function getDestinationCityName(address) {
      return address?.city
        || address?.town
        || address?.village
        || address?.municipality
        || address?.city_district
        || address?.county
        || '';
    }

    function getDestinationPrimaryLabel(item) {
      const firstChunk = String(item?.display_name || '').split(',')[0].trim();
      return firstChunk || getDestinationCityName(item?.address || {}) || 'Destino';
    }

    function isDestinationPlaceSelected() {
      return Boolean(
        runtime.destinationPlace
        && runtime.destination.trim()
        && normalizeLocationText(runtime.destinationPlace.display_name) === normalizeLocationText(runtime.destination.trim())
      );
    }

    function renderDestinationSupport() {
      const hasResolvedSelection = isDestinationPlaceSelected();
      const hasTypedDestination = Boolean(runtime.destination.trim());

      runtime.dom.destinationShells.forEach((shell) => {
        shell.classList.toggle('is-selected', hasResolvedSelection);
        shell.dataset.mode = runtime.noDestination ? 'no-destination' : (hasResolvedSelection ? 'selected' : 'default');
      });

      let helperMode = 'default';
      let helperTheme = 'default';
      let helperIcon = 'fa-solid fa-circle-info';
      let helperCopy = 'Escribe para buscar puntos de interés en la ciudad.';
      if (runtime.noDestination) {
        helperMode = 'no-destination';
        helperTheme = 'no-destination';
        helperIcon = 'fa-solid fa-route';
        helperCopy = 'Trayecto libre activo. Estás navegando sin un destino específico.';
      } else if (hasResolvedSelection) {
        helperMode = 'selected';
        helperTheme = 'selected';
        helperIcon = 'fa-solid fa-circle-info';
        helperCopy = `Destino fijado en ${getDestinationPrimaryLabel(runtime.destinationPlace)}.`;
      } else if (hasTypedDestination) {
        helperIcon = 'fa-solid fa-magnifying-glass';
        helperCopy = 'Sigue escribiendo o elige una sugerencia para usar el nombre correcto del lugar.';
      }

      runtime.dom.destinationStatusBoxes.forEach((node) => {
        node.dataset.theme = helperTheme;
      });

      runtime.dom.destinationHelpers.forEach((node) => {
        node.dataset.mode = helperMode;
        const iconNode = node.querySelector('i');
        const copyNode = node.querySelector('span') || node;
        if (iconNode) {
          iconNode.className = helperIcon;
        }
        copyNode.textContent = helperCopy;
      });
    }

    function isAllowedMetroDestination(item) {
      const address = item?.address || {};
      const cityCandidates = [
        address.city,
        address.town,
        address.village,
        address.municipality,
        address.city_district,
        address.county,
      ];
      const inAllowedCity = cityCandidates.some((candidate) => DESTINATION_ALLOWED_CITIES.has(normalizeLocationText(candidate)));
      const stateText = normalizeLocationText(address.state);
      return inAllowedCity && (!stateText || stateText.includes('nuevo leon'));
    }

    function setDestinationResultsExpanded(expanded) {
      runtime.dom.desktopDestinationInput?.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    function closeDestinationSuggestions() {
      if (runtime.destinationSearchTimer) {
        window.clearTimeout(runtime.destinationSearchTimer);
        runtime.destinationSearchTimer = null;
      }
      runtime.destinationSuggestionState.items = [];
      runtime.destinationSuggestionState.activeIndex = -1;
      if (runtime.dom.desktopDestinationResultsList) {
        runtime.dom.desktopDestinationResultsList.innerHTML = '';
      }
      if (runtime.dom.desktopDestinationResults) {
        runtime.dom.desktopDestinationResults.hidden = true;
      }
      setDestinationResultsExpanded(false);
    }

    function setActiveDestinationSuggestion(index) {
      const state = runtime.destinationSuggestionState;
      if (!state.items.length) {
        state.activeIndex = -1;
        return;
      }
      state.activeIndex = clamp(index, 0, state.items.length - 1);
      const optionNodes = runtime.dom.desktopDestinationResultsList?.querySelectorAll('[data-destination-option-index]') || [];
      optionNodes.forEach((node) => {
        const isActive = Number(node.dataset.destinationOptionIndex) === state.activeIndex;
        node.classList.toggle('is-active', isActive);
        node.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }

    function selectDestinationSuggestion(item) {
      if (!item) return;
      runtime.noDestination = false;
      runtime.destinationPlace = {
        display_name: String(item.display_name || '').trim(),
        lat: toCoord(item.lat),
        lon: toCoord(item.lon),
        address: item.address || {},
      };
      mirrorDestinationInputs(runtime.destinationPlace.display_name);
      renderDestinationInputs();
      persistUiState(runtime);
      clearStatus();
      closeDestinationSuggestions();
    }

    function renderDestinationSuggestions(items, emptyCopy) {
      const results = runtime.dom.desktopDestinationResults;
      const resultsList = runtime.dom.desktopDestinationResultsList;
      if (!results || !resultsList) return;
      runtime.destinationSuggestionState.items = Array.isArray(items) ? items : [];
      runtime.destinationSuggestionState.activeIndex = runtime.destinationSuggestionState.items.length ? 0 : -1;
      resultsList.innerHTML = '';

      if (!runtime.destinationSuggestionState.items.length) {
        const emptyNode = document.createElement('div');
        emptyNode.className = 'destination-search-empty';
        emptyNode.textContent = emptyCopy || 'No encontré coincidencias en Nuevo León.';
        resultsList.appendChild(emptyNode);
      } else {
        runtime.destinationSuggestionState.items.forEach((item, index) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'destination-search-item';
          button.dataset.destinationOptionIndex = String(index);
          button.setAttribute('role', 'option');
          button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
          if (index === 0) button.classList.add('is-active');

          const iconWrap = document.createElement('div');
          iconWrap.className = 'destination-search-item__icon';
          const icon = document.createElement('i');
          icon.className = 'fa-solid fa-location-crosshairs';
          iconWrap.appendChild(icon);

          const copy = document.createElement('div');
          copy.className = 'destination-search-item__copy';
          const title = document.createElement('div');
          title.className = 'destination-search-item__title';
          title.textContent = getDestinationPrimaryLabel(item);

          const meta = document.createElement('div');
          meta.className = 'destination-search-item__meta';
          meta.textContent = String(item.display_name || '').trim();

          copy.append(title, meta);
          button.append(iconWrap, copy);
          button.addEventListener('mousedown', (event) => {
            event.preventDefault();
          });
          button.addEventListener('mouseenter', () => {
            setActiveDestinationSuggestion(index);
          });
          button.addEventListener('click', () => {
            selectDestinationSuggestion(item);
          });
          resultsList.appendChild(button);
        });
      }

      results.hidden = false;
      setDestinationResultsExpanded(true);
    }

    async function fetchDestinationSuggestions(query, limit) {
      const trimmed = String(query || '').trim();
      if (!trimmed) return [];
      const normalizedLimit = Math.max(1, Math.min(10, Number(limit) || 8));
      const nominatimUrl = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&countrycodes=mx&accept-language=es&bounded=1&viewbox=${DESTINATION_METRO_BBOX}&q=${encodeURIComponent(trimmed)}&limit=${encodeURIComponent(normalizedLimit)}`;

      try {
        const response = await fetch(nominatimUrl, { headers: { Accept: 'application/json' } });
        const list = await response.json().catch(() => ([]));
        const filtered = (Array.isArray(list) ? list : []).filter(isAllowedMetroDestination);
        if (filtered.length) {
          return filtered.slice(0, normalizedLimit);
        }
      } catch (error) {
        // Fallback al backend si el proveedor directo falla o responde vacío.
      }

      const response = await fetch(`/api/safety/destination-search?q=${encodeURIComponent(trimmed)}&limit=${encodeURIComponent(normalizedLimit)}`, {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload?.ok) {
        throw new Error(payload?.error || 'No pude buscar destinos en este momento.');
      }
      return Array.isArray(payload.items) ? payload.items.slice(0, normalizedLimit) : [];
    }

    async function searchDesktopDestinations(query) {
      if (runtime.noDestination) {
        closeDestinationSuggestions();
        return;
      }

      const trimmed = String(query || '').trim();
      if (!trimmed) {
        closeDestinationSuggestions();
        return;
      }

      const requestId = runtime.destinationSuggestionState.requestId + 1;
      runtime.destinationSuggestionState.requestId = requestId;

      try {
        const items = await fetchDestinationSuggestions(trimmed, 8);
        if (requestId !== runtime.destinationSuggestionState.requestId) return;
        renderDestinationSuggestions(items, 'No encontré coincidencias en Nuevo León.');
      } catch (error) {
        if (requestId !== runtime.destinationSuggestionState.requestId) return;
        renderDestinationSuggestions([], 'No pude buscar destinos en este momento.');
      }
    }

    async function resolveDestinationFromInput() {
      const destinationValue = runtime.noDestination ? '' : runtime.destination.trim();
      if (!destinationValue) return '';
      if (
        runtime.destinationPlace
        && normalizeLocationText(runtime.destinationPlace.display_name) === normalizeLocationText(destinationValue)
      ) {
        return runtime.destinationPlace.display_name;
      }
      try {
        const items = await fetchDestinationSuggestions(destinationValue, 1);
        if (!items.length) return destinationValue;
        selectDestinationSuggestion(items[0]);
        return runtime.destinationPlace?.display_name || destinationValue;
      } catch (error) {
        return destinationValue;
      }
    }

    function getSelectedContacts() {
      return runtime.contacts.filter((contact) => contact.isSharing);
    }

    function getPrimaryContact() {
      return runtime.contacts.find((contact) => contact.isPrimary) || runtime.contacts[0] || null;
    }

    function mirrorDestinationInputs(originValue) {
      runtime.destination = originValue;
      runtime.dom.destinationInputs.forEach((input) => {
        if (input.value !== originValue) {
          input.value = originValue;
        }
      });
    }

    function setNoDestination(enabled) {
      runtime.noDestination = Boolean(enabled);
      if (runtime.noDestination) {
        runtime.destination = '';
        runtime.destinationPlace = null;
      }
      closeDestinationSuggestions();
      renderDestinationInputs();
      persistUiState(runtime);
      if (!runtime.noDestination) {
        const desktopInput = runtime.dom.destinationInputs.find((input) => input.dataset.destinationInput === 'desktop');
        desktopInput?.focus();
      }
    }

    function renderDestinationInputs() {
      const value = runtime.noDestination ? '' : runtime.destination;
      runtime.dom.destinationInputs.forEach((input) => {
        if (!input.dataset.defaultPlaceholder) {
          input.dataset.defaultPlaceholder = input.getAttribute('placeholder') || 'Buscar destino';
        }
        const defaultPlaceholder = input.dataset.defaultPlaceholder;
        input.disabled = runtime.noDestination;
        input.value = value;
        input.setAttribute('placeholder', runtime.noDestination ? 'Modo: Sin destino fijo' : defaultPlaceholder);
        input.setAttribute('aria-disabled', runtime.noDestination ? 'true' : 'false');
      });
      runtime.dom.destinationShells.forEach((shell) => {
        shell.classList.toggle('is-disabled', runtime.noDestination);
        const iconNode = shell.querySelector('i');
        if (iconNode) {
          iconNode.className = runtime.noDestination ? 'fa-solid fa-ban' : 'fa-solid fa-location-dot';
        }
      });
      runtime.dom.destinationToggleButtons.forEach((button) => {
        const iconNode = button.querySelector('i');
        button.setAttribute('aria-pressed', runtime.noDestination ? 'true' : 'false');
        button.setAttribute('aria-label', runtime.noDestination ? 'Volver a usar destino' : 'Sin destino');
        button.setAttribute('title', runtime.noDestination ? 'Volver a usar destino' : 'Sin destino');
        button.classList.toggle('is-active', runtime.noDestination);
        if (iconNode) {
          iconNode.className = runtime.noDestination ? 'fa-solid fa-route' : 'fa-solid fa-ban';
        }
      });
      renderDestinationSupport();
    }

    function renderEtaButtons() {
      runtime.dom.etaButtons.forEach((button) => {
        button.classList.toggle('is-active', Number(button.dataset.etaValue) === runtime.etaMinutes);
      });
    }

    function renderShareSummary() {
      const selectedContacts = getSelectedContacts();
      const labels = selectedContacts.map((contact) => contact.name);
      const label = formatContactList(labels);
      const count = selectedContacts.length;
      const countCopy = count
        ? `${count} contacto${count > 1 ? 's' : ''} seleccionado${count > 1 ? 's' : ''} para este trayecto.`
        : 'Agrega o selecciona contactos para este trayecto.';

      runtime.dom.shareSummaryTitles.forEach((node) => {
        node.textContent = label;
      });
      runtime.dom.shareSummaryCounts.forEach((node) => {
        node.textContent = countCopy;
      });
      runtime.dom.shareSummaryLists.forEach((node) => {
        node.innerHTML = labels.length ? labels.map((item) => `<span>${item}</span>`).join('') : '<span>Nadie</span>';
      });
      runtime.dom.shareSummaryAvatars.forEach((node) => {
        node.innerHTML = selectedContacts.map((contact) => (
          `<span class="avatar avatar--${contact.avatarTone}">${getContactInitials(contact.name)}</span>`
        )).join('');
      });
      runtime.dom.readyChipCopies.forEach((node) => {
        node.textContent = count ? `${count} contacto${count > 1 ? 's' : ''} listo${count > 1 ? 's' : ''}` : 'Sin contactos listos';
      });
      runtime.dom.activeShareCount.forEach((node) => {
        node.textContent = `${count} contacto${count === 1 ? '' : 's'} acompanando`;
      });
      runtime.dom.activeSupportCopy.forEach((node) => {
        node.textContent = count
          ? `${label} puede${count > 1 ? 'n' : ''} ver si sigues en ruta.`
          : 'Agrega contactos si quieres compartir este trayecto.';
      });

      persistUiState(runtime);
    }

    function renderContactFilters() {
      runtime.dom.contactFilterButtons.forEach((button) => {
        button.classList.toggle('is-active', button.dataset.contactFilter === runtime.currentContactFilter);
      });
    }

    function animateContainers(containers) {
      containers.forEach((container) => {
        if (!container) return;
        container.classList.remove('is-list-animating');
        void container.offsetWidth;
        container.classList.add('is-list-animating');
        const items = container.querySelectorAll('.history-card, .desktop-history-card, .contact-list-empty');
        items.forEach((item, index) => {
          animateNode(item, [
            { opacity: 0, transform: 'translateY(26px) scale(0.975)' },
            { opacity: 1, transform: 'translateY(0) scale(1)' },
          ], {
            duration: 420,
            delay: Math.min(index * 55, 220),
            easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
            fill: 'both',
          });
        });
        window.setTimeout(() => {
          container.classList.remove('is-list-animating');
        }, 430);
      });
    }

    function animateButtonPress(control) {
      if (!control) return;
      animateNode(control, [
        { transform: 'scale(1)', offset: 0 },
        { transform: 'translateY(1px) scale(0.945)', offset: 0.45 },
        { transform: 'scale(1)', offset: 1 },
      ], {
        duration: 220,
        easing: 'ease-out',
      });
    }

    function buildContactCard(contact) {
      const meta = [contact.relationship, contact.phone].filter(Boolean).join(' · ');
      const toggleCopy = contact.isSharing ? 'Compartir' : 'No compartir';
      return `
        <article class="history-card" data-contact-card="${contact.id}">
          <div class="history-card__top">
            <div class="contact-card-title">
              <button class="contact-avatar-btn" type="button" data-avatar-edit="${contact.id}" aria-label="Cambiar foto de perfil de ${contact.name}">
                <span class="avatar contact-avatar avatar--${contact.avatarTone}">${getContactInitials(contact.name)}</span>
              </button>
              <div class="contact-title-copy">
                <div class="history-card__title">${contact.name}</div>
                <div class="history-card__meta">${meta || 'Sin datos adicionales'}</div>
              </div>
            </div>
            <div class="contact-card-controls">
              <button class="favorite-btn ${contact.isPrimary ? 'is-favorite' : ''}" type="button" data-primary-contact="${contact.id}" aria-pressed="${contact.isPrimary ? 'true' : 'false'}" aria-label="${contact.isPrimary ? 'Contacto principal' : 'Marcar como contacto principal'}">
                <span class="favorite-btn__outline"><i class="fa-regular fa-star"></i></span>
                <span class="favorite-btn__fill"><i class="fa-solid fa-star"></i></span>
              </button>
              <button class="contact-toggle ${contact.isSharing ? 'is-on' : ''}" type="button" data-share-toggle="${contact.id}" aria-pressed="${contact.isSharing ? 'true' : 'false'}">${toggleCopy}</button>
            </div>
          </div>
          <div class="quick-actions">
            <button class="ghost-pill" type="button" data-edit-contact="${contact.id}">Editar</button>
            <button class="ghost-pill" type="button" data-delete-contact="${contact.id}">Eliminar</button>
          </div>
        </article>
      `;
    }

    function renderContacts(options) {
      const opts = Object.assign({ animate: false }, options || {});
      renderContactFilters();
      const visibleContacts = runtime.currentContactFilter === 'favorites'
        ? runtime.contacts.filter((contact) => contact.isPrimary)
        : runtime.contacts;

      runtime.dom.contactListContainers.forEach((container) => {
        if (!visibleContacts.length) {
          container.innerHTML = '<div class="contact-list-empty">Todavia no tienes contactos en esta categoria.</div>';
          return;
        }
        container.innerHTML = visibleContacts.map(buildContactCard).join('');
      });

      if (opts.animate) {
        animateContainers(runtime.dom.contactListContainers);
      }
    }

    function buildMiniMap(styleKey) {
      const route = ROUTE_CONFIGS[styleKey] || ROUTE_CONFIGS.office;
      return `
        <div class="desktop-mini-map desktop-mini-map--${styleKey}">
          <svg class="desktop-mini-map__route-svg" viewBox="0 0 184 124" preserveAspectRatio="none">
            <path class="desktop-mini-map__route-base" d="${route.miniPath}"></path>
            <path class="desktop-mini-map__route-path" d="${route.miniPath}"></path>
          </svg>
          <span class="desktop-mini-map__dot desktop-mini-map__dot--start"></span>
          <span class="desktop-mini-map__dot desktop-mini-map__dot--end"></span>
        </div>
      `;
    }

    function buildHistoryCardMobile(trip) {
      const badgeClass = trip.badge_variant === 'danger' ? 'badge badge--danger' : 'badge badge--live';
      const statusClass = trip.status_variant === 'danger' ? 'history-stat--danger' : 'history-stat--success';
      return `
        <article class="history-card">
          <div class="history-card__top">
            <div>
              <div class="history-card__title">${trip.display_title}</div>
              <div class="history-card__meta">${trip.when_label}</div>
            </div>
            <span class="${badgeClass}">${trip.badge_label}</span>
          </div>
          <div class="history-stats">
            <span>${trip.duration_label}</span>
            <span>${trip.destination || 'Sin destino claro'}</span>
            <span>${trip.contacts_label}</span>
            <span class="${statusClass}">${trip.status_label}</span>
          </div>
          <button class="neutral-btn" type="button" style="padding:13px 14px;" data-summary-open="${trip.id}">Abrir resumen</button>
        </article>
      `;
    }

    function buildHistoryCardDesktop(trip) {
      const badgeClass = trip.badge_variant === 'danger' ? 'badge badge--danger' : 'badge badge--live';
      const metricClass = trip.status_variant === 'danger'
        ? 'desktop-history-metric desktop-history-metric--danger'
        : 'desktop-history-metric desktop-history-metric--success';
      return `
        <article class="desktop-history-card">
          <div class="desktop-history-card__grid">
            <div class="desktop-history-copy">
              <div class="history-card__top">
                <div>
                  <div class="desktop-history-title-row">
                    <div class="history-card__title">${trip.display_title}</div>
                    <span class="${badgeClass}">${trip.badge_label}</span>
                  </div>
                  <div class="history-card__meta">${trip.when_label}</div>
                </div>
              </div>
              <div class="desktop-history-metrics">
                <span class="desktop-history-metric"><i class="fa-regular fa-clock"></i> ${trip.duration_label}</span>
                <span class="desktop-history-metric"><i class="fa-solid fa-route"></i> ${trip.destination || 'Sin destino claro'}</span>
                <span class="desktop-history-metric"><i class="fa-solid fa-user-group"></i> ${trip.contacts_label}</span>
                <span class="${metricClass}"><i class="fa-solid fa-check-circle"></i> ${trip.status_label}</span>
              </div>
              <div class="desktop-history-subline">Resumen rapido del trayecto guardado.</div>
              <div class="desktop-history-footer">
                <button class="neutral-btn history-open-btn" type="button" data-summary-open="${trip.id}">Abrir resumen</button>
                <div class="desktop-history-note">Ver recorrido, metricas y mapa del trayecto.</div>
              </div>
            </div>
            ${buildMiniMap(trip.route_style || 'office')}
          </div>
        </article>
      `;
    }

    function renderHistory(options) {
      const opts = Object.assign({ animate: false }, options || {});
      runtime.dom.historyListContainers.forEach((container) => {
        const mode = container.dataset.historyList;
        if (!runtime.tripItems.length) {
          container.innerHTML = '<div class="contact-list-empty">Todavia no has guardado trayectos.</div>';
          return;
        }
        container.innerHTML = runtime.tripItems.map((trip) => (
          mode === 'desktop' ? buildHistoryCardDesktop(trip) : buildHistoryCardMobile(trip)
        )).join('');
      });

      if (opts.animate) {
        animateContainers(runtime.dom.historyListContainers);
      }
    }

    function createLiveUserIcon() {
      if (!window.L) return null;
      return window.L.divIcon({
        className: 'safety-live-user-marker',
        html: '<span class="safety-live-user-marker__inner"><span class="safety-live-user-marker__pulse"></span><span class="safety-live-user-marker__dot"></span></span>',
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });
    }

    function createLiveDestinationIcon() {
      if (!window.L) return null;
      return window.L.divIcon({
        className: 'safety-live-destination-marker',
        html: '<span class="safety-live-destination-marker__inner"><span class="safety-live-destination-marker__dot"></span></span>',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });
    }

    function clearActiveLiveMapLayers() {
      const mapState = runtime.mapState;
      if (!mapState || !mapState.map) return;
      ['routeBase', 'routeLine', 'routeProgress', 'userMarker', 'destinationMarker'].forEach((key) => {
        if (mapState[key]) {
          mapState.map.removeLayer(mapState[key]);
          mapState[key] = null;
        }
      });
      mapState.routeKey = '';
      mapState.bounds = null;
      mapState.hasInitialFit = false;
    }

    function ensureActiveLiveMap() {
      if (!runtime.dom.activeLiveMap || !window.L) return null;
      if (runtime.mapState?.map) {
        return runtime.mapState;
      }

      const map = window.L.map(runtime.dom.activeLiveMap, {
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: false,
      });
      window.L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 19,
      }).addTo(map);
      map.setView(DEFAULT_SAFETY_CENTER, 13);

      runtime.mapState = {
        map,
        routeBase: null,
        routeLine: null,
        routeProgress: null,
        userMarker: null,
        destinationMarker: null,
        routeKey: '',
        bounds: null,
        hasInitialFit: false,
      };
      return runtime.mapState;
    }

    function getCheckinDestinationCoords(checkin) {
      const lat = toCoord(checkin?.destination_latitude);
      const lng = toCoord(checkin?.destination_longitude);
      if (!hasValidCoords(lat, lng)) {
        return null;
      }
      return [lat, lng];
    }

    function normalizeRoutePoint(point) {
      const lat = toCoord(point?.lat ?? point?.latitude);
      const lng = toCoord(point?.lng ?? point?.longitude);
      if (!hasValidCoords(lat, lng)) {
        return null;
      }
      const ts = Number(point?.ts_ms ?? point?.timestamp ?? Date.now());
      return {
        lat,
        lng,
        ts_ms: Number.isFinite(ts) ? ts : Date.now(),
        speed_kmh: Number.isFinite(Number(point?.speed_kmh)) ? Number(point.speed_kmh) : null,
        accuracy_m: Number.isFinite(Number(point?.accuracy_m ?? point?.accuracy)) ? Number(point.accuracy_m ?? point.accuracy) : null,
      };
    }

    function dedupeRoutePoints(points) {
      const normalized = (Array.isArray(points) ? points : [])
        .map(normalizeRoutePoint)
        .filter(Boolean)
        .sort((a, b) => (a.ts_ms || 0) - (b.ts_ms || 0));
      const deduped = [];
      normalized.forEach((point) => {
        const previous = deduped[deduped.length - 1];
        if (previous) {
          const distance = getDistanceBetweenCoords([previous.lat, previous.lng], [point.lat, point.lng]);
          const deltaMs = Math.abs((point.ts_ms || 0) - (previous.ts_ms || 0));
          if (distance < 1.5 && deltaMs < 2500) {
            return;
          }
        }
        deduped.push(point);
      });
      return deduped;
    }

    function buildActiveRouteLatLngs() {
      if (!runtime.activeCheckin) return [];
      const latLngs = [];
      const startCoords = getCheckinStartCoords(runtime.activeCheckin);
      if (Array.isArray(startCoords) && startCoords.length === 2) {
        latLngs.push(startCoords);
      }
      dedupeRoutePoints(runtime.routePoints).forEach((point) => {
        const nextCoords = [point.lat, point.lng];
        const previous = latLngs[latLngs.length - 1];
        if (!previous || getDistanceBetweenCoords(previous, nextCoords) >= 1.5) {
          latLngs.push(nextCoords);
        }
      });
      return latLngs;
    }

    function syncActiveCheckinMeta(payload) {
      if (!runtime.activeCheckin || !payload) return;
      if (typeof payload.destination === 'string') {
        runtime.activeCheckin.destination = payload.destination;
      }
      if (typeof payload.display_destination === 'string' && payload.display_destination.trim()) {
        runtime.activeCheckin.display_destination = payload.display_destination;
      }
      const lat = toCoord(payload.latitude);
      const lng = toCoord(payload.longitude);
      if (hasValidCoords(lat, lng)) {
        runtime.activeCheckin.latitude = lat;
        runtime.activeCheckin.longitude = lng;
      }
      const destinationLat = toCoord(payload.destination_latitude);
      const destinationLng = toCoord(payload.destination_longitude);
      if (hasValidCoords(destinationLat, destinationLng)) {
        runtime.activeCheckin.destination_latitude = destinationLat;
        runtime.activeCheckin.destination_longitude = destinationLng;
      }
    }

    async function fetchActiveRoutePoints(options) {
      const opts = Object.assign({ invalidateSize: false, refit: false }, options || {});
      if (!runtime.activeCheckin?.id) return;
      const requestToken = runtime.routeRequestToken + 1;
      runtime.routeRequestToken = requestToken;
      try {
        const response = await fetch(`/api/safety/checkin/${runtime.activeCheckin.id}/route/points`, {
          headers: { Accept: 'application/json' },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok) {
          return;
        }
        if (requestToken !== runtime.routeRequestToken || !runtime.activeCheckin || String(runtime.activeCheckin.id) !== String(payload?.checkin?.id || runtime.activeCheckin.id)) {
          return;
        }
        syncActiveCheckinMeta(payload.checkin);
        runtime.routePoints = dedupeRoutePoints(payload.points || []);
        renderActiveLiveMap({ invalidateSize: opts.invalidateSize, refit: opts.refit });
      } catch (error) {
        // No-op: el mapa sigue con los puntos locales si la sincronización falla.
      }
    }

    function shouldPersistRoutePoint(point) {
      if (!point) return false;
      if (point.accuracy_m != null && point.accuracy_m > 120) {
        return false;
      }
      const previous = runtime.routeLastPersistedPoint;
      if (!previous) return true;
      const distance = getDistanceBetweenCoords([previous.lat, previous.lng], [point.lat, point.lng]);
      const deltaMs = Math.max(0, (point.ts_ms || 0) - (previous.ts_ms || 0));
      return distance >= 8 || deltaMs >= 15000;
    }

    function appendLocalRoutePoint(point) {
      const normalized = normalizeRoutePoint(point);
      if (!normalized) return null;
      runtime.routePoints = dedupeRoutePoints(runtime.routePoints.concat(normalized));
      return normalized;
    }

    async function persistRoutePoint(point) {
      if (!runtime.activeCheckin?.id || !point) return;
      try {
        const response = await fetch(`/api/safety/checkin/${runtime.activeCheckin.id}/route/point`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            lat: point.lat,
            lng: point.lng,
            ts_ms: point.ts_ms,
            speed_kmh: point.speed_kmh,
            accuracy_m: point.accuracy_m,
          }),
        });
        const payload = await response.json().catch(() => ({}));
        if (response.ok && payload?.ok) {
          runtime.routeLastPersistedPoint = point;
        }
      } catch (error) {
        // No-op: el siguiente punto o el polling periódico volverán a sincronizar.
      }
    }

    function handleActiveRoutePosition(position) {
      if (!runtime.activeCheckin) return;
      const point = appendLocalRoutePoint({
        lat: position?.lat,
        lng: position?.lng,
        ts_ms: position?.timestamp || Date.now(),
        speed_kmh: Number.isFinite(Number(position?.speed)) ? Number(position.speed) * 3.6 : null,
        accuracy_m: position?.accuracy,
      });
      if (!point) return;
      runtime.activeCheckin.latitude = point.lat;
      runtime.activeCheckin.longitude = point.lng;
      renderActiveLiveMap();
      if (shouldPersistRoutePoint(point)) {
        persistRoutePoint(point);
      }
    }

    async function stopActiveRouteTracking() {
      if (runtime.routePollTimer) {
        clearInterval(runtime.routePollTimer);
        runtime.routePollTimer = null;
      }
      if (runtime.routeWatchHandle) {
        const bridge = window.VioletaNativeBridge || null;
        if (bridge && typeof bridge.clearPositionWatch === 'function') {
          await bridge.clearPositionWatch(runtime.routeWatchHandle);
        } else if (runtime.routeWatchHandle.source === 'browser' && navigator.geolocation?.clearWatch) {
          navigator.geolocation.clearWatch(runtime.routeWatchHandle.id);
        }
        runtime.routeWatchHandle = null;
      }
      runtime.routeTrackingCheckinId = null;
      runtime.routeRequestToken += 1;
      runtime.routeLastPersistedPoint = null;
      runtime.routePoints = [];
    }

    function startActiveRouteTracking() {
      if (!runtime.activeCheckin?.id) {
        stopActiveRouteTracking();
        return;
      }
      const trackingKey = String(runtime.activeCheckin.id);
      if (runtime.routeTrackingCheckinId === trackingKey) {
        return;
      }
      stopActiveRouteTracking();
      runtime.routeTrackingCheckinId = trackingKey;
      fetchActiveRoutePoints({ invalidateSize: true, refit: true });

      const bridge = window.VioletaNativeBridge || null;
      const watchOptions = { enableHighAccuracy: true, timeout: 12000, maximumAge: 2000 };
      const onPosition = (position) => {
        handleActiveRoutePosition(position);
      };

      if (bridge && typeof bridge.watchPosition === 'function') {
        Promise.resolve(bridge.watchPosition(watchOptions, onPosition, () => {}))
          .then((handle) => {
            if (runtime.routeTrackingCheckinId === trackingKey) {
              runtime.routeWatchHandle = handle;
            } else if (handle && bridge.clearPositionWatch) {
              bridge.clearPositionWatch(handle);
            }
          })
          .catch(() => {});
      } else if (navigator.geolocation?.watchPosition) {
        const watchId = navigator.geolocation.watchPosition(
          (position) => onPosition({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracy: position.coords.accuracy || null,
            timestamp: position.timestamp || Date.now(),
            speed: position.coords.speed ?? null,
          }),
          () => {},
          watchOptions,
        );
        runtime.routeWatchHandle = { id: watchId, source: 'browser' };
      }

      runtime.routePollTimer = setInterval(() => {
        if (!runtime.activeCheckin || runtime.routeTrackingCheckinId !== trackingKey) return;
        fetchActiveRoutePoints();
      }, 15000);
    }

    function renderActiveLiveMap(options) {
      const opts = Object.assign({ invalidateSize: false, refit: false }, options || {});
      const mapState = runtime.mapState?.map ? runtime.mapState : (runtime.activeCheckin ? ensureActiveLiveMap() : null);
      if (!mapState) return;

      if (!runtime.activeCheckin) {
        clearActiveLiveMapLayers();
        if (opts.invalidateSize) {
          window.setTimeout(() => mapState.map.invalidateSize(false), 40);
        }
        return;
      }

      const routeLatLngs = buildActiveRouteLatLngs();
      const destinationCoords = getCheckinDestinationCoords(runtime.activeCheckin);
      const currentPoint = routeLatLngs[routeLatLngs.length - 1] || getCheckinStartCoords(runtime.activeCheckin);
      const routeKey = [
        runtime.activeCheckin.id || 'active',
        routeLatLngs.length,
        currentPoint?.[0]?.toFixed?.(5) || '0',
        currentPoint?.[1]?.toFixed?.(5) || '0',
        destinationCoords ? `${destinationCoords[0].toFixed(5)}:${destinationCoords[1].toFixed(5)}` : 'no-destination',
      ].join(':');

      if (routeKey !== mapState.routeKey) {
        clearActiveLiveMapLayers();

        if (routeLatLngs.length > 1) {
          mapState.routeBase = window.L.polyline(routeLatLngs, {
            color: '#cbd5e1',
            weight: 10,
            opacity: 0.62,
            lineCap: 'round',
            lineJoin: 'round',
          }).addTo(mapState.map);
          mapState.routeLine = window.L.polyline(routeLatLngs, {
            color: '#7c3aed',
            weight: 5,
            opacity: 0.92,
            lineCap: 'round',
            lineJoin: 'round',
          }).addTo(mapState.map);
          mapState.routeProgress = window.L.polyline(routeLatLngs, {
            color: '#10b981',
            weight: 6,
            opacity: 0.95,
            lineCap: 'round',
            lineJoin: 'round',
          }).addTo(mapState.map);
        }

        mapState.userMarker = window.L.marker(currentPoint, {
          icon: createLiveUserIcon(),
          interactive: false,
          zIndexOffset: 700,
        }).addTo(mapState.map);

        if (destinationCoords) {
          mapState.destinationMarker = window.L.marker(destinationCoords, {
            icon: createLiveDestinationIcon(),
            interactive: false,
            zIndexOffset: 650,
          }).addTo(mapState.map);
        }

        const bounds = window.L.latLngBounds([currentPoint]);
        if (routeLatLngs.length > 1) {
          routeLatLngs.forEach((coords) => bounds.extend(coords));
        }
        if (destinationCoords) {
          bounds.extend(destinationCoords);
        }
        mapState.bounds = bounds.isValid() ? bounds : null;
        mapState.routeKey = routeKey;
      } else {
        if (mapState.routeBase && routeLatLngs.length > 1) {
          mapState.routeBase.setLatLngs(routeLatLngs);
        }
        if (mapState.routeLine && routeLatLngs.length > 1) {
          mapState.routeLine.setLatLngs(routeLatLngs);
        }
        if (mapState.routeProgress && routeLatLngs.length > 1) {
          mapState.routeProgress.setLatLngs(routeLatLngs);
        }
        if (mapState.userMarker) {
          mapState.userMarker.setLatLng(currentPoint);
        }
        if (mapState.destinationMarker && destinationCoords) {
          mapState.destinationMarker.setLatLng(destinationCoords);
        }
      }

      const shouldFit = !mapState.hasInitialFit || opts.invalidateSize || opts.refit;
      if (shouldFit) {
        window.setTimeout(() => {
          mapState.map.invalidateSize(false);
          if (mapState.bounds && routeLatLngs.length > 1) {
            mapState.map.fitBounds(mapState.bounds, { padding: [36, 36] });
          } else {
            mapState.map.setView(currentPoint, Math.max(mapState.map.getZoom(), 15));
          }
          mapState.hasInitialFit = true;
        }, 50);
      }
    }

    function updateActiveTripMetrics() {
      if (!runtime.activeCheckin) {
        if (runtime.timerId) {
          clearInterval(runtime.timerId);
          runtime.timerId = null;
        }
        runtime.dom.activeDestination.forEach((node) => { node.textContent = 'tu destino'; });
        runtime.dom.activeDestinationInline.forEach((node) => { node.textContent = 'tu destino'; });
        runtime.dom.activeEtaBig.forEach((node) => { node.textContent = '--'; });
        runtime.dom.activeEtaInline.forEach((node) => { node.textContent = '--'; });
        runtime.dom.activeElapsed.forEach((node) => { node.textContent = '--'; });
        runtime.dom.activeTotal.forEach((node) => { node.textContent = '--'; });
        renderActiveLiveMap();
        return;
      }

      const startedAt = runtime.activeCheckin.started_at_iso ? new Date(runtime.activeCheckin.started_at_iso) : new Date();
      const expiresAt = runtime.activeCheckin.expires_at_iso ? new Date(runtime.activeCheckin.expires_at_iso) : new Date();
      const destination = runtime.activeCheckin.display_destination || runtime.activeCheckin.destination || 'tu destino';
      const etaCopy = formatCountdown((expiresAt.getTime() - Date.now()) / 1000);
      const elapsedCopy = formatDurationFromSeconds((Date.now() - startedAt.getTime()) / 1000);
      const totalCopy = formatMinutesLabel(runtime.activeCheckin.eta_minutes || runtime.etaMinutes || 30);

      runtime.dom.activeDestination.forEach((node) => { node.textContent = destination; });
      runtime.dom.activeDestinationInline.forEach((node) => { node.textContent = destination; });
      runtime.dom.activeEtaBig.forEach((node) => { node.textContent = etaCopy; });
      runtime.dom.activeEtaInline.forEach((node) => { node.textContent = etaCopy; });
      runtime.dom.activeElapsed.forEach((node) => { node.textContent = elapsedCopy; });
      runtime.dom.activeTotal.forEach((node) => { node.textContent = totalCopy; });
      renderActiveLiveMap();
    }

    function startActiveTripTimer() {
      updateActiveTripMetrics();
      if (runtime.timerId) {
        clearInterval(runtime.timerId);
      }
      if (!runtime.activeCheckin) {
        stopActiveRouteTracking();
        return;
      }
      startActiveRouteTracking();
      runtime.timerId = setInterval(updateActiveTripMetrics, 1000);
    }

    function resetActiveSheetPosition() {
      runtime.dom.draggableSheets.forEach((sheet) => {
        sheet.classList.remove('is-collapsed');
        sheet.style.transform = '';
      });
    }

    function animateSectionIn(section) {
      if (!section) return;
      animateNode(section, [
        { opacity: 0, transform: 'translateY(30px) scale(0.985)' },
        { opacity: 1, transform: 'translateY(-2px) scale(1.004)', offset: 0.72 },
        { opacity: 1, transform: 'translateY(0)' },
      ], {
        duration: 460,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
      });

      const children = section.querySelectorAll('.desktop-header, .panel, .history-card, .desktop-history-card, .input-card, .support-row, .status-card, .ghost-banner');
      children.forEach((node, index) => {
        animateNode(node, [
          { opacity: 0, transform: 'translateY(24px) scale(0.98)' },
          { opacity: 1, transform: 'translateY(0) scale(1)' },
        ], {
          duration: 440,
          delay: Math.min(index * 50, 260),
          easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
          fill: 'both',
        });
      });
    }

    function animateSectionOut(section) {
      if (!section) return Promise.resolve();
      section.classList.add('is-leaving');
      return finishAnimation(animateNode(section, [
        { opacity: 1, transform: 'translateY(0) scale(1)' },
        { opacity: 0, transform: 'translateY(-20px) scale(0.985)' },
      ], {
        duration: 240,
        easing: 'ease-in',
        fill: 'forwards',
      }));
    }

    function applyVisibleState(nextState) {
      runtime.dom.mobileStates.forEach((section) => {
        if (typeof section.getAnimations === 'function') {
          section.getAnimations().forEach((animation) => animation.cancel());
        }
        section.classList.remove('is-leaving');
        section.classList.toggle('is-visible', section.dataset.state === nextState);
      });
      runtime.dom.desktopStates.forEach((section) => {
        if (typeof section.getAnimations === 'function') {
          section.getAnimations().forEach((animation) => animation.cancel());
        }
        section.classList.remove('is-leaving');
        section.classList.toggle('is-visible', section.dataset.state === nextState);
      });
      root.querySelectorAll('.desktop-header, .panel, .history-card, .desktop-history-card, .input-card, .support-row, .status-card, .ghost-banner').forEach((node) => {
        if (typeof node.getAnimations === 'function') {
          node.getAnimations().forEach((animation) => animation.cancel());
        }
      });
      if (nextState === 'active' || nextState === 'idle') {
        resetActiveSheetPosition();
      }
    }

    function resolveFallbackState() {
      return runtime.activeCheckin ? 'active' : 'idle';
    }

    function normalizeState(nextState) {
      if (!SAFETY_VIEW_STATES.has(nextState)) {
        return resolveFallbackState();
      }
      if (nextState === 'active' && !runtime.activeCheckin) {
        return 'idle';
      }
      return nextState;
    }

    function resolveBackState() {
      const nextState = normalizeState(runtime.previousState);
      if (nextState === runtime.currentState && (nextState === 'contacts' || nextState === 'history')) {
        return resolveFallbackState();
      }
      return nextState;
    }

    function setState(nextState, options) {
      const opts = Object.assign({ remember: true, animate: true }, options || {});
      nextState = normalizeState(nextState);
      if (runtime.currentState === nextState) {
        applyVisibleState(nextState);
        return;
      }
      if (opts.remember && runtime.currentState) {
        runtime.previousState = runtime.currentState;
      }

      if (runtime.stateTransitionTimer) {
        clearTimeout(runtime.stateTransitionTimer);
        runtime.stateTransitionTimer = null;
      }

      const visibleSections = runtime.dom.mobileStates
        .concat(runtime.dom.desktopStates)
        .filter((section) => section.classList.contains('is-visible'));

      runtime.currentState = nextState;

      if (!opts.animate || !visibleSections.length) {
        applyVisibleState(nextState);
        const nextSections = runtime.dom.mobileStates
          .concat(runtime.dom.desktopStates)
          .filter((section) => section.dataset.state === nextState);
        nextSections.forEach(animateSectionIn);
        if (nextState === 'active') {
          renderActiveLiveMap({ invalidateSize: true });
        }
        return;
      }

      Promise.all(visibleSections.map(animateSectionOut)).then(() => {
        applyVisibleState(nextState);
        const nextSections = runtime.dom.mobileStates
          .concat(runtime.dom.desktopStates)
          .filter((section) => section.dataset.state === nextState);
        nextSections.forEach(animateSectionIn);
        if (nextState === 'active') {
          renderActiveLiveMap({ invalidateSize: true });
        }
        runtime.stateTransitionTimer = null;
      });
    }

    function renderAll(options) {
      const opts = Object.assign({ animateLists: false }, options || {});
      renderDestinationInputs();
      renderEtaButtons();
      renderShareSummary();
      renderContacts({ animate: opts.animateLists });
      renderHistory({ animate: opts.animateLists });
      updateActiveTripMetrics();
    }

    function syncCustomBackdropViewportState() {
      const hasOpenBackdrop = [
        runtime.dom.summaryModal,
        runtime.dom.contactEditorModal,
        runtime.dom.contactDeleteModal,
      ].some((node) => node && (node.classList.contains('is-visible') || node.classList.contains('is-closing')));
      document.body.classList.toggle('violeta-backdrop-open', hasOpenBackdrop);
    }

    function showBackdropModal(backdrop) {
      if (!backdrop) return;
      if (backdrop._hideTimer) {
        window.clearTimeout(backdrop._hideTimer);
        backdrop._hideTimer = null;
      }
      backdrop.classList.remove('is-closing');
      backdrop.setAttribute('aria-hidden', 'false');
      syncCustomBackdropViewportState();
      void backdrop.offsetWidth;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          backdrop.classList.add('is-visible');
          syncCustomBackdropViewportState();
        });
      });
    }

    function clearSummaryModalPosition() {
      if (!runtime.dom.summaryModal) return;
      runtime.summaryAnchorNode = null;
      runtime.dom.summaryModal.classList.remove('is-anchored');
      runtime.dom.summaryModal.style.removeProperty('--summary-modal-top');
      runtime.dom.summaryModal.style.removeProperty('--summary-modal-left');
      runtime.dom.summaryModal.style.removeProperty('--summary-modal-width');
    }

    function positionSummaryModal(triggerNode) {
      if (!triggerNode) {
        clearSummaryModalPosition();
        return;
      }
      const rect = triggerNode.getBoundingClientRect();
      const modal = runtime.dom.summaryModal;
      const modalWidth = 560; // approximate width
      const left = Math.max(24, Math.min(window.innerWidth - modalWidth - 24, rect.left + rect.width / 2));
      const top = rect.bottom + 10;
      modal.style.setProperty('--summary-modal-top', `${top}px`);
      modal.style.setProperty('--summary-modal-left', `${left}px`);
      modal.classList.add('is-anchored');
    }

    function hideBackdropModal(backdrop, callback) {
      if (!backdrop) {
        if (typeof callback === 'function') callback();
        return;
      }
      if (!backdrop.classList.contains('is-visible')) {
        backdrop.classList.remove('is-closing');
        backdrop.setAttribute('aria-hidden', 'true');
        syncCustomBackdropViewportState();
        if (typeof callback === 'function') callback();
        return;
      }
      backdrop.classList.add('is-closing');
      backdrop.setAttribute('aria-hidden', 'true');
      backdrop.classList.remove('is-visible');
      syncCustomBackdropViewportState();
      backdrop._hideTimer = window.setTimeout(() => {
        backdrop.classList.remove('is-visible', 'is-closing');
        backdrop._hideTimer = null;
        syncCustomBackdropViewportState();
        if (typeof callback === 'function') callback();
      }, 420);
    }

    function animatePageOutAndNavigate(url) {
      const area = document.querySelector('.main-content');
      if (!area) {
        window.location.href = url;
        return;
      }
      area.classList.remove('page-anim-in');
      area.classList.add('page-anim-out');
      animateNode(area, [
        { opacity: 1, transform: 'translateY(0)' },
        { opacity: 0, transform: 'translateY(-24px) scale(0.99)' },
      ], {
        duration: 320,
        easing: 'ease-in',
        fill: 'forwards',
      });
      window.setTimeout(() => {
        window.location.href = url;
      }, 250);
    }

    function setSummaryRouteStatus(copy, tone) {
      if (!runtime.dom.summaryRouteStatus) return;
      runtime.dom.summaryRouteStatus.textContent = copy;
      if (tone) {
        runtime.dom.summaryRouteStatus.dataset.tone = tone;
      } else {
        runtime.dom.summaryRouteStatus.removeAttribute('data-tone');
      }
    }

    function ensureSummaryRouteMap() {
      if (!runtime.dom.summaryRouteLiveMap || !window.L) return null;
      if (runtime.summaryMapState?.map) {
        return runtime.summaryMapState;
      }

      const map = window.L.map(runtime.dom.summaryRouteLiveMap, {
        zoomControl: false,
        attributionControl: false,
        dragging: true,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: true,
      });
      window.L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 19,
      }).addTo(map);
      map.setView(DEFAULT_SAFETY_CENTER, 13);

      runtime.summaryMapState = {
        map,
        layers: [],
      };
      return runtime.summaryMapState;
    }

    function clearSummaryRouteLayers() {
      const mapState = runtime.summaryMapState;
      if (!mapState?.map) return;
      mapState.layers.forEach((layer) => {
        try { mapState.map.removeLayer(layer); } catch (error) { /* no-op */ }
      });
      mapState.layers = [];
    }

    function addSummaryRouteLayer(layer) {
      if (!runtime.summaryMapState?.map || !layer) return;
      layer.addTo(runtime.summaryMapState.map);
      runtime.summaryMapState.layers.push(layer);
    }

    function buildSummaryRouteLatLngs(trip, payload) {
      const checkin = Object.assign({
        id: trip.id,
        destination: trip.destination,
        display_destination: trip.display_title,
        eta_minutes: trip.eta_minutes || 30,
      }, payload?.checkin || {});
      const routePoints = dedupeRoutePoints(payload?.points || []);
      const startCoords = getCheckinStartCoords(checkin);
      const destinationCoords = getCheckinDestinationCoords(checkin)
        || buildSimulatedDestinationCoords(startCoords, checkin);

      if (routePoints.length >= 2) {
        return {
          latLngs: routePoints.map((point) => [point.lat, point.lng]),
          startCoords: [routePoints[0].lat, routePoints[0].lng],
          destinationCoords,
          realPointCount: routePoints.length,
        };
      }

      if (routePoints.length === 1) {
        const onlyPoint = [routePoints[0].lat, routePoints[0].lng];
        return {
          latLngs: destinationCoords ? [onlyPoint, destinationCoords] : [startCoords, onlyPoint],
          startCoords: onlyPoint,
          destinationCoords,
          realPointCount: 1,
        };
      }

      return {
        latLngs: buildSimulatedRoute(startCoords, destinationCoords, hashString(`${trip.id}:${trip.destination || trip.display_title || 'trayecto'}`)),
        startCoords,
        destinationCoords,
        realPointCount: 0,
      };
    }

    async function renderSummaryRouteReport(trip) {
      const mapState = ensureSummaryRouteMap();
      if (!mapState?.map) {
        setSummaryRouteStatus('Mapa no disponible en este navegador.', 'warning');
        return;
      }

      clearSummaryRouteLayers();
      setSummaryRouteStatus('Cargando recorrido real...', null);

      let payload = null;
      if (trip.route_points_url) {
        try {
          const response = await fetch(trip.route_points_url, { headers: { Accept: 'application/json' } });
          payload = await response.json().catch(() => ({}));
          if (!response.ok || !payload?.ok) {
            payload = null;
          }
        } catch (error) {
          payload = null;
        }
      }

      const routeData = buildSummaryRouteLatLngs(trip, payload);
      const latLngs = routeData.latLngs.filter((coords) => Array.isArray(coords) && hasValidCoords(coords[0], coords[1]));

      window.setTimeout(() => mapState.map.invalidateSize(false), 40);

      if (!latLngs.length) {
        mapState.map.setView(DEFAULT_SAFETY_CENTER, 13);
        setSummaryRouteStatus('No hay datos de recorrido para este trayecto.', 'warning');
        return;
      }

      if (latLngs.length > 1) {
        addSummaryRouteLayer(window.L.polyline(latLngs, {
          color: '#cbd5e1',
          weight: 10,
          opacity: 0.62,
          lineCap: 'round',
          lineJoin: 'round',
        }));
        addSummaryRouteLayer(window.L.polyline(latLngs, {
          color: '#7c3aed',
          weight: 5,
          opacity: 0.92,
          lineCap: 'round',
          lineJoin: 'round',
        }));
      }

      const start = latLngs[0];
      const end = routeData.destinationCoords || latLngs[latLngs.length - 1];
      addSummaryRouteLayer(window.L.marker(start, {
        icon: createLiveUserIcon(),
        interactive: false,
        zIndexOffset: 700,
      }));
      if (end && hasValidCoords(end[0], end[1])) {
        addSummaryRouteLayer(window.L.marker(end, {
          icon: createLiveDestinationIcon(),
          interactive: false,
          zIndexOffset: 650,
        }));
      }

      const bounds = window.L.latLngBounds(latLngs);
      if (end && hasValidCoords(end[0], end[1])) {
        bounds.extend(end);
      }
      window.setTimeout(() => {
        mapState.map.invalidateSize(false);
        if (bounds.isValid() && latLngs.length > 1) {
          mapState.map.fitBounds(bounds, { padding: [32, 32] });
        } else {
          mapState.map.setView(start, 15);
        }
      }, 70);

      if (routeData.realPointCount >= 2) {
        setSummaryRouteStatus(`Recorrido real: ${routeData.realPointCount} puntos registrados.`, 'success');
      } else if (routeData.realPointCount === 1) {
        setSummaryRouteStatus('Recorrido con 1 punto registrado; destino estimado.', 'warning');
      } else {
        setSummaryRouteStatus('Sin puntos reales suficientes; se muestra ruta estimada.', 'warning');
      }
    }

    function closeSummary(callback) {
      hideBackdropModal(runtime.dom.summaryModal, () => {
        clearSummaryRouteLayers();
        setSummaryRouteStatus('Cargando recorrido real...', null);
        clearSummaryModalPosition();
        if (typeof callback === 'function') callback();
      });
    }

    function openSummary(tripId, triggerNode) {
      const trip = runtime.tripItems.find((item) => String(item.id) === String(tripId));
      if (!trip || !runtime.dom.summaryModal) return;
      runtime.dom.summaryModalBadge.textContent = trip.badge_label || 'Resumen';
      runtime.dom.summaryModalTitle.textContent = trip.display_title || 'Trayecto';
      runtime.dom.summaryModalMeta.textContent = trip.when_label || '';
      runtime.dom.summaryMetricTime.textContent = trip.duration_label || '--';
      if (runtime.dom.summaryMetricContacts) {
        runtime.dom.summaryMetricContacts.textContent = trip.contacts_label || 'Sin contacto';
      }
      runtime.dom.summaryMetricExtra.textContent = trip.status_label || '--';
      runtime.dom.summaryModalBody.textContent = trip.destination
        ? `Trayecto guardado hacia ${trip.destination}. Puedes abrir el detalle completo cuando lo necesites.`
        : 'Trayecto guardado sin destino claro. Puedes abrir el detalle completo cuando lo necesites.';
      positionSummaryModal(triggerNode);
      showBackdropModal(runtime.dom.summaryModal);
      requestAnimationFrame(() => {
        positionSummaryModal(triggerNode);
        renderSummaryRouteReport(trip);
      });
    }

    function renderAvatarPicker() {
      const previewName = runtime.dom.contactNameInput?.value?.trim() || 'Contacto';
      const initials = getContactInitials(previewName);
      if (!runtime.dom.contactAvatarPicker) return;
      runtime.dom.contactAvatarPicker.innerHTML = AVATAR_TONES.map((tone) => `
        <button class="avatar-picker__option avatar--${tone} ${runtime.editingAvatarTone === tone ? 'is-active' : ''}" type="button" data-avatar-preset="${tone}" aria-pressed="${runtime.editingAvatarTone === tone ? 'true' : 'false'}">
          ${initials}
        </button>
      `).join('');
    }

    function closeContactEditor(callback) {
      runtime.editingContactId = null;
      hideBackdropModal(runtime.dom.contactEditorModal, callback);
    }

    function openContactEditor(contactId) {
      runtime.editingContactId = contactId ? String(contactId) : null;
      const contact = runtime.contacts.find((item) => item.id === runtime.editingContactId) || null;
      if (runtime.dom.contactEditorEyebrow) {
        runtime.dom.contactEditorEyebrow.textContent = contact ? 'Editar contacto' : 'Agregar contacto';
      }
      if (runtime.dom.contactEditorTitle) {
        runtime.dom.contactEditorTitle.textContent = contact ? contact.name : 'Nuevo contacto';
      }
      if (runtime.dom.contactNameInput) runtime.dom.contactNameInput.value = contact ? contact.name : '';
      if (runtime.dom.contactRelationInput) runtime.dom.contactRelationInput.value = contact ? contact.relationship : '';
      if (runtime.dom.contactPhoneInput) runtime.dom.contactPhoneInput.value = contact ? contact.phone : '';
      runtime.editingAvatarTone = contact ? contact.avatarTone : 'violet';
      if (runtime.dom.contactEditorDelete) {
        runtime.dom.contactEditorDelete.style.display = contact ? 'inline-flex' : 'none';
      }
      renderAvatarPicker();
      showBackdropModal(runtime.dom.contactEditorModal);
      runtime.dom.contactNameInput?.focus();
    }

    function closeDeleteModal(callback) {
      runtime.pendingDeleteContactId = null;
      hideBackdropModal(runtime.dom.contactDeleteModal, callback);
    }

    function openDeleteModal(contactId) {
      const contact = runtime.contacts.find((item) => item.id === String(contactId));
      if (!contact) return;
      runtime.pendingDeleteContactId = String(contactId);
      if (runtime.dom.contactDeleteMeta) {
        runtime.dom.contactDeleteMeta.textContent = `${contact.name} dejara de aparecer en tu lista y tambien se quitara del trayecto actual si estaba compartiendo.`;
      }
      showBackdropModal(runtime.dom.contactDeleteModal);
    }

    async function handleCreateOrUpdateContact() {
      const name = runtime.dom.contactNameInput?.value?.trim() || '';
      const relationship = runtime.dom.contactRelationInput?.value?.trim() || '';
      const phone = (runtime.dom.contactPhoneInput?.value || '').replace(/\D/g, '');

      if (!name || !phone) {
        setStatus('Completa nombre y telefono para guardar el contacto.', 'error');
        return;
      }

      const isEditing = Boolean(runtime.editingContactId);
      const endpoint = isEditing
        ? `/api/safety/contact/${runtime.editingContactId}/update`
        : runtime.endpoints.createContact;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ name, relationship, phone }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setStatus(payload.error || 'No se pudo guardar el contacto.', 'error');
        return;
      }

      if (isEditing) {
        runtime.contacts = runtime.contacts.map((contact) => (
          contact.id === runtime.editingContactId
            ? Object.assign({}, contact, { name, relationship, phone, avatarTone: runtime.editingAvatarTone })
            : contact
        ));
      } else {
        runtime.contacts.push({
          id: String(payload.contact_id),
          name,
          relationship,
          phone,
          avatarTone: runtime.editingAvatarTone,
          isPrimary: runtime.contacts.length === 0,
          isSharing: runtime.contacts.length < 2,
        });
      }

      closeContactEditor();
      clearStatus();
      renderAll({ animateLists: true });
    }

    async function setPrimaryContact(contactId) {
      const response = await fetch(`/api/safety/contact/${contactId}/primary`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setStatus(payload.error || 'No se pudo actualizar el contacto principal.', 'error');
        return;
      }
      runtime.contacts = runtime.contacts.map((contact) => Object.assign({}, contact, {
        isPrimary: contact.id === String(contactId),
      }));
      clearStatus();
      renderContacts({ animate: true });
    }

    async function deleteContact(contactId) {
      const response = await fetch(`/api/safety/contact/${contactId}/delete`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setStatus(payload.error || 'No se pudo eliminar el contacto.', 'error');
        return;
      }

      runtime.contacts = runtime.contacts.filter((contact) => contact.id !== String(contactId));
      if (!runtime.contacts.some((contact) => contact.isPrimary) && runtime.contacts[0]) {
        runtime.contacts[0].isPrimary = true;
      }
      closeDeleteModal();
      closeContactEditor();
      clearStatus();
      renderAll({ animateLists: true });
    }

    function prependHistory(status) {
      if (!runtime.activeCheckin) return;
      const nowLabel = formatNowLabel();
      const statusLabel = status === 'cancelled' ? 'Cancelada' : 'Finalizada';
      const statusVariant = status === 'cancelled' ? 'danger' : 'success';
      runtime.tripItems.unshift({
        id: `local-${Date.now()}`,
        display_title: runtime.activeCheckin.display_destination || runtime.activeCheckin.destination || 'Trayecto',
        destination: runtime.activeCheckin.destination || '',
        when_label: nowLabel,
        route_style: pickRouteStyle(runtime.tripItems.length),
        badge_label: runtime.activeCheckin.destination ? 'Con destino' : 'Sin destino claro',
        badge_variant: runtime.activeCheckin.destination ? 'live' : 'danger',
        duration_label: formatMinutesLabel(runtime.activeCheckin.eta_minutes || runtime.etaMinutes || 30),
        contacts_label: getSelectedContacts().length ? `${getSelectedContacts().length} contactos` : 'Sin contacto',
        status_label: statusLabel,
        status_variant: statusVariant,
      });
      runtime.tripItems = runtime.tripItems.slice(0, 6);
      renderHistory({ animate: true });
    }

    async function handleStartCheckin() {
      const destinationValue = runtime.noDestination ? '' : await resolveDestinationFromInput();
      if (!runtime.noDestination && !destinationValue) {
        setStatus('Escribe tu destino para iniciar el trayecto.', 'error');
        return;
      }

      runtime.dom.startButtons.forEach((button) => { button.disabled = true; });
      const result = await sendCheckinWithGeo(runtime.endpoints.startCheckin, {
        destination: destinationValue,
        destination_latitude: runtime.destinationPlace?.lat ?? null,
        destination_longitude: runtime.destinationPlace?.lon ?? null,
        eta_minutes: runtime.etaMinutes,
        note: '',
      });
      runtime.dom.startButtons.forEach((button) => { button.disabled = false; });

      if (!result.ok || !result.data.ok) {
        setStatus(result.data.error || 'No se pudo iniciar el trayecto.', 'error');
        return;
      }

      const primary = getPrimaryContact() || getSelectedContacts()[0] || null;
      runtime.activeCheckin = {
        id: result.data.checkin_id,
        destination: result.data.destination || destinationValue,
        display_destination: result.data.destination || destinationValue || 'Destino en progreso',
        started_at_iso: result.data.started_at || nowIso(),
        expires_at_iso: result.data.expires_at || nowIso(),
        eta_minutes: Number(result.data.eta_minutes || runtime.etaMinutes),
        contact_name: primary?.name || '',
        contact_phone: primary?.phone || '',
        latitude: toCoord(result.data.latitude),
        longitude: toCoord(result.data.longitude),
        destination_latitude: toCoord(result.data.destination_latitude),
        destination_longitude: toCoord(result.data.destination_longitude),
      };
      runtime.routePoints = [];
      runtime.routeLastPersistedPoint = null;
      setState('active');
      startActiveTripTimer();
      clearStatus();
    }

    async function handleArrive() {
      const response = await fetch(runtime.endpoints.arriveCheckin, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setStatus(payload.error || 'No se pudo cerrar el trayecto.', 'error');
        return;
      }
      const nextUrl = payload.redirect_url || '/safety';
      animatePageOutAndNavigate(nextUrl);
    }

    async function handleCancel() {
      const confirmed = window.confirm('Si cancelas este trayecto, tus contactos dejaran de ver tu ubicacion y Violeta dejara de acompanarte en esta ruta. ¿Seguro que quieres cancelarlo?');
      if (!confirmed) return;

      const response = await fetch(runtime.endpoints.cancelCheckin, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setStatus(payload.error || 'No se pudo cancelar el trayecto.', 'error');
        return;
      }

      prependHistory('cancelled');
      runtime.activeCheckin = null;
      setState('idle', { remember: false });
      startActiveTripTimer();
      clearStatus();
    }

    function bindSheetDrag() {
      runtime.dom.draggableSheets.forEach((sheet) => {
        const toggles = Array.from(sheet.querySelectorAll('[data-sheet-toggle]'));
        toggles.forEach((toggle) => {
          toggle.addEventListener('pointerdown', (event) => {
            const host = sheet.closest('.mobile-state--active, .mobile-state--idle') || sheet;
            const peek = parseFloat(getComputedStyle(host).getPropertyValue('--active-sheet-peek')) || 42;
            const collapsedOffset = Math.max(0, sheet.offsetHeight - peek);
            runtime.activeDrag = {
              sheet,
              startY: event.clientY,
              startOffset: sheet.classList.contains('is-collapsed') ? collapsedOffset : 0,
              collapsedOffset,
              moved: false,
            };
            toggle.setPointerCapture(event.pointerId);
            sheet.style.transition = 'none';
          });
        });
      });

      window.addEventListener('pointermove', (event) => {
        if (!runtime.activeDrag) return;
        const delta = event.clientY - runtime.activeDrag.startY;
        if (Math.abs(delta) > 6) {
          runtime.activeDrag.moved = true;
        }
        const nextOffset = Math.max(0, Math.min(runtime.activeDrag.collapsedOffset, runtime.activeDrag.startOffset + delta));
        runtime.activeDrag.sheet.style.transform = `translateY(${nextOffset}px)`;
      });

      window.addEventListener('pointerup', () => {
        if (!runtime.activeDrag) return;
        const match = runtime.activeDrag.sheet.style.transform.match(/translateY\(([\d.]+)px\)/);
        const offset = match ? parseFloat(match[1]) : runtime.activeDrag.startOffset;
        runtime.activeDrag.sheet.style.transition = '';
        runtime.activeDrag.sheet.style.transform = '';
        if (!runtime.activeDrag.moved) {
          runtime.activeDrag.sheet.classList.toggle('is-collapsed');
        } else {
          runtime.activeDrag.sheet.classList.toggle('is-collapsed', offset > runtime.activeDrag.collapsedOffset / 2);
        }
        runtime.activeDrag = null;
      });
    }

    root.addEventListener('click', (event) => {
      const pressedButton = event.target.closest('button');
      if (pressedButton) {
        animateButtonPress(pressedButton);
      }

      const link = event.target.closest('[data-preview-link]');
      if (link) {
        setState(link.dataset.previewLink);
        return;
      }

      const back = event.target.closest('[data-preview-back]');
      if (back) {
        setState(resolveBackState(), { remember: false, animate: false });
        return;
      }

      const eta = event.target.closest('[data-eta-value]');
      if (eta) {
        runtime.etaMinutes = Number(eta.dataset.etaValue);
        renderEtaButtons();
        if (runtime.activeCheckin) {
          runtime.activeCheckin.eta_minutes = runtime.etaMinutes;
        }
        return;
      }

      const destinationToggle = event.target.closest('[data-destination-toggle]');
      if (destinationToggle) {
        setNoDestination(!runtime.noDestination);
        clearStatus();
        return;
      }

      if (event.target.closest('[data-start-checkin]')) {
        handleStartCheckin();
        return;
      }

      if (event.target.closest('[data-arrive-safe]')) {
        handleArrive();
        return;
      }

      if (event.target.closest('[data-cancel-trip]')) {
        handleCancel();
        return;
      }

      const filterButton = event.target.closest('[data-contact-filter]');
      if (filterButton) {
        runtime.currentContactFilter = filterButton.dataset.contactFilter;
        renderContacts({ animate: true });
        return;
      }

      if (event.target.closest('[data-contact-create]')) {
        openContactEditor();
        return;
      }

      const shareToggle = event.target.closest('[data-share-toggle]');
      if (shareToggle) {
        runtime.contacts = runtime.contacts.map((contact) => (
          contact.id === String(shareToggle.dataset.shareToggle)
            ? Object.assign({}, contact, { isSharing: !contact.isSharing })
            : contact
        ));
        renderShareSummary();
        renderContacts({ animate: true });
        return;
      }

      const primaryButton = event.target.closest('[data-primary-contact]');
      if (primaryButton) {
        setPrimaryContact(primaryButton.dataset.primaryContact);
        return;
      }

      const editButton = event.target.closest('[data-edit-contact], [data-avatar-edit]');
      if (editButton) {
        openContactEditor(editButton.dataset.editContact || editButton.dataset.avatarEdit);
        return;
      }

      const deleteButton = event.target.closest('[data-delete-contact]');
      if (deleteButton) {
        openDeleteModal(deleteButton.dataset.deleteContact);
        return;
      }

      const avatarPreset = event.target.closest('[data-avatar-preset]');
      if (avatarPreset) {
        runtime.editingAvatarTone = avatarPreset.dataset.avatarPreset;
        renderAvatarPicker();
        return;
      }

      const summaryButton = event.target.closest('[data-summary-open]');
      if (summaryButton) {
        openSummary(summaryButton.dataset.summaryOpen, summaryButton);
      }
    });

    root.addEventListener('input', (event) => {
      const destinationInput = event.target.closest('[data-destination-input]');
      if (destinationInput) {
        if (runtime.noDestination) {
          destinationInput.value = '';
          return;
        }
        runtime.destinationPlace = null;
        mirrorDestinationInputs(destinationInput.value);
        if (destinationInput === runtime.dom.desktopDestinationInput) {
          if (runtime.destinationSearchTimer) {
            window.clearTimeout(runtime.destinationSearchTimer);
          }
          runtime.destinationSearchTimer = window.setTimeout(() => {
            searchDesktopDestinations(destinationInput.value);
          }, destinationInput.value.trim() ? 140 : 0);
        }
      }
    });

    runtime.dom.desktopDestinationInput?.addEventListener('focus', () => {
      if (runtime.noDestination) return;
      searchDesktopDestinations(runtime.dom.desktopDestinationInput.value);
    });

    runtime.dom.desktopDestinationInput?.addEventListener('blur', () => {
      window.setTimeout(() => {
        closeDestinationSuggestions();
      }, 160);
    });

    runtime.dom.desktopDestinationInput?.addEventListener('keydown', (event) => {
      if (runtime.noDestination) return;
      const items = runtime.destinationSuggestionState.items;
      if (!items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
        event.preventDefault();
        searchDesktopDestinations(runtime.dom.desktopDestinationInput.value);
        return;
      }
      if (!items.length) {
        if (event.key === 'Escape') closeDestinationSuggestions();
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveDestinationSuggestion(runtime.destinationSuggestionState.activeIndex + 1);
        return;
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveDestinationSuggestion(runtime.destinationSuggestionState.activeIndex - 1);
        return;
      }

      if (event.key === 'Enter') {
        const activeItem = items[runtime.destinationSuggestionState.activeIndex] || items[0];
        if (activeItem) {
          event.preventDefault();
          selectDestinationSuggestion(activeItem);
        }
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        closeDestinationSuggestions();
      }
    });

    runtime.dom.contactNameInput?.addEventListener('input', renderAvatarPicker);
    runtime.dom.contactPhoneInput?.addEventListener('input', () => {
      runtime.dom.contactPhoneInput.value = runtime.dom.contactPhoneInput.value.replace(/\D/g, '');
    });
    runtime.dom.contactEditorClose?.addEventListener('click', closeContactEditor);
    runtime.dom.contactEditorModal?.addEventListener('click', (event) => {
      if (event.target === runtime.dom.contactEditorModal) closeContactEditor();
    });
    runtime.dom.contactEditorDelete?.addEventListener('click', () => {
      if (runtime.editingContactId) openDeleteModal(runtime.editingContactId);
    });
    runtime.dom.contactEditorForm?.addEventListener('submit', (event) => {
      event.preventDefault();
      handleCreateOrUpdateContact();
    });
    runtime.dom.contactDeleteCancel?.addEventListener('click', closeDeleteModal);
    runtime.dom.contactDeleteModal?.addEventListener('click', (event) => {
      if (event.target === runtime.dom.contactDeleteModal) closeDeleteModal();
    });
    runtime.dom.contactDeleteConfirm?.addEventListener('click', () => {
      if (runtime.pendingDeleteContactId) deleteContact(runtime.pendingDeleteContactId);
    });
    runtime.dom.summaryModalClose?.addEventListener('click', closeSummary);
    runtime.dom.summaryModal?.addEventListener('click', (event) => {
      if (event.target === runtime.dom.summaryModal) closeSummary();
    });
    window.addEventListener('resize', () => {
      if (!runtime.dom.summaryModal?.classList.contains('is-visible')) return;
      positionSummaryModal(runtime.summaryAnchorNode);
    });

    bindSheetDrag();
    renderAvatarPicker();
    renderAll();
    startActiveTripTimer();
    setState(data.initialState || (runtime.activeCheckin ? 'active' : 'idle'), { remember: false, animate: false });
  }

  function initSafetyPageEnhancements(mountOrMounts) {
    if (Array.isArray(mountOrMounts)) {
      mountOrMounts.forEach((mount) => {
        const root = mount?.querySelector?.('#safetyRedesignPage');
        if (root) initSafetyPage(root);
      });
      return;
    }

    const root = mountOrMounts?.querySelector?.('#safetyRedesignPage')
      || document.getElementById('safetyRedesignPage');
    if (root) {
      initSafetyPage(root);
    }
  }

  window.initSafetyPageEnhancements = initSafetyPageEnhancements;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initSafetyPageEnhancements(document), { once: true });
  } else {
    initSafetyPageEnhancements(document);
  }
})();
