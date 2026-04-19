  (function () {
    // --- Helpers visuales ---
    function colorForCount(c) {
      if (c >= 10) return '#ef4444';
      if (c >= 5) return '#f97316';
      if (c >= 2) return '#facc15';
      return '#8b5cf6';
    }
    function sizeForCount(c) {
      return Math.min(60, 12 + c * 6);
    }

    // Color consistente por ruta (según ref/name)
    function hashStr(s) {
      let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0; }
      return Math.abs(h);
    }
    function colorForRouteKey(key) {
      const h = hashStr(key);
      const hue = h % 360; // 0-359
      return `hsl(${hue}, 70%, 55%)`;
    }
    function escapeHtml(s) { return (s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', '\'': '&#39;' }[c])); }

	    let currentCategory = '';
	    let mapRef = null; // referencia global segura al mapa
	    let hotspotsLayer = null; // solo hotspots (no tocar transporte)
	    let transitStopsLayer = null;
	    let transitRoutesLayer = null;
	    let transitIndex = null; // [{ id_ruta, nombre, linea, paradas }]
	    let transitWalkLayer = null; // walking legs to/from stops
    let userLocationMarker = null;
    let userLocationAccuracyCircle = null;
    let userCurrentPoint = null;
    const applyMexicoLimits = function () { /* límite de zoom desactivado temporalmente */ };
    function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
    function rememberBaseStyle(layer) {
      if (!layer || layer.__violetaBaseReady) return;
      const opt = layer.options || {};
      layer.__violetaBaseOpacity = (typeof opt.opacity === 'number') ? opt.opacity : 1;
      layer.__violetaBaseFillOpacity = (typeof opt.fillOpacity === 'number') ? opt.fillOpacity : null;
      layer.__violetaBaseReady = true;
    }
    function applyLayerOpacity(layer, alpha) {
      if (!layer) return;
      if (typeof layer.eachLayer === 'function') {
        layer.eachLayer(child => applyLayerOpacity(child, alpha));
      }
      rememberBaseStyle(layer);
      if (typeof layer.setStyle === 'function') {
        const style = { opacity: (layer.__violetaBaseOpacity ?? 1) * alpha };
        if (layer.__violetaBaseFillOpacity != null) {
          style.fillOpacity = layer.__violetaBaseFillOpacity * alpha;
        }
        try { layer.setStyle(style); } catch (_) { }
      } else if (typeof layer.setOpacity === 'function') {
        try { layer.setOpacity(alpha); } catch (_) { }
      } else if (typeof layer.getElement === 'function') {
        const el = layer.getElement();
        if (el) el.style.opacity = String(alpha);
      }
    }
    function animateLayerGroupVisibility(layerGroup, shouldShow, duration = 260) {
      const m = mapRef;
      if (!m || !layerGroup) return;
      if (layerGroup.__violetaAnimFrame) {
        cancelAnimationFrame(layerGroup.__violetaAnimFrame);
        layerGroup.__violetaAnimFrame = null;
      }
      if (shouldShow && !m.hasLayer(layerGroup)) m.addLayer(layerGroup);
      const start = performance.now();
      const from = shouldShow ? 0 : 1;
      const to = shouldShow ? 1 : 0;
      const tick = (now) => {
        const p = Math.min(1, (now - start) / duration);
        const eased = easeOutCubic(p);
        const alpha = from + ((to - from) * eased);
        applyLayerOpacity(layerGroup, alpha);
        if (p < 1) {
          layerGroup.__violetaAnimFrame = requestAnimationFrame(tick);
          return;
        }
        layerGroup.__violetaAnimFrame = null;
        if (!shouldShow && m.hasLayer(layerGroup)) m.removeLayer(layerGroup);
        applyLayerOpacity(layerGroup, 1);
      };
      layerGroup.__violetaAnimFrame = requestAnimationFrame(tick);
    }
    function animateLeafletLayerIn(layer, duration = 280) {
      if (!layer) return;
      if (layer.__violetaAnimFrame) {
        cancelAnimationFrame(layer.__violetaAnimFrame);
        layer.__violetaAnimFrame = null;
      }
      const start = performance.now();
      const tick = (now) => {
        const p = Math.min(1, (now - start) / duration);
        const eased = easeOutCubic(p);
        applyLayerOpacity(layer, eased);
        if (p < 1) {
          layer.__violetaAnimFrame = requestAnimationFrame(tick);
          return;
        }
        layer.__violetaAnimFrame = null;
        applyLayerOpacity(layer, 1);
      };
      applyLayerOpacity(layer, 0);
      layer.__violetaAnimFrame = requestAnimationFrame(tick);
    }
    function createUserLocationIcon() {
      return L.divIcon({
        className: '',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        html: '<div class="user-location-marker"><span class="user-location-marker__pulse"></span><span class="user-location-marker__dot"></span></div>'
      });
    }
    function updateUserLocationMarker(lat, lng, accuracyMeters = 24) {
      const m = mapRef || window.hotspotMap;
      if (!m || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const latlng = [lat, lng];
      userCurrentPoint = latlng;
      if (!userLocationMarker) {
        userLocationMarker = L.marker(latlng, {
          icon: createUserLocationIcon(),
          zIndexOffset: 1200,
          keyboard: false
        }).addTo(m);
        userLocationMarker.bindTooltip('Tu ubicación actual', { direction: 'top', offset: [0, -10], opacity: 0.9 });
      } else {
        userLocationMarker.setLatLng(latlng);
      }
      const r = Math.min(Math.max(Number(accuracyMeters) || 24, 12), 120);
      if (!userLocationAccuracyCircle) {
        userLocationAccuracyCircle = L.circle(latlng, {
          radius: r,
          color: '#60a5fa',
          weight: 1,
          fillColor: '#60a5fa',
          fillOpacity: 0.15,
          interactive: false
        }).addTo(m);
      } else {
        userLocationAccuracyCircle.setLatLng(latlng);
        userLocationAccuracyCircle.setRadius(r);
      }
    }
    function setRouteLegend(info) {
      const host = document.getElementById('hotspotMap');
      if (!host) return;
      let box = document.getElementById('routeLegend');
      if (!box) { box = document.createElement('div'); box.id = 'routeLegend'; box.className = 'route-legend'; host.appendChild(box); }
      const title = escapeHtml(info.title || 'Ruta');
      const sub = info.subtitle ? `<div class="legend-sub">${escapeHtml(info.subtitle)}</div>` : '';
      box.innerHTML = `<div class="swatch" style="background:${info.color}"></div><div class="legend-text"><div class="legend-title">${title}</div>${sub}</div>`;
      requestAnimationFrame(() => box.classList.add('is-visible'));
    }
    function clearRouteLegend() { const box = document.getElementById('routeLegend'); if (box) box.classList.remove('is-visible'); }
    function updateStopLabels() {
      if (!mapRef || !transitStopsLayer) return;
      const show = mapRef.getZoom() >= 15;
      transitStopsLayer.eachLayer(l => {
        try {
          const el = l.getElement && l.getElement();
          if (!el) return;
          const lab = el.querySelector && el.querySelector('.bus-stop-label');
          if (lab) lab.style.display = show ? 'block' : 'none';
        } catch (_) { }
      });
    }

	    function initMap(center) {
	      const map = L.map('hotspotMap', {
	        attributionControl: true,
	        zoomControl: false,
	        zoomAnimation: true,
        fadeAnimation: true,
        markerZoomAnimation: true,
        preferCanvas: true
      })
        .setView(center || [25.6866, -100.3161], 12);

      L.control.zoom({ position: 'bottomleft' }).addTo(map);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        detectRetina: false
      }).addTo(map);

	      window.hotspotMap = map; // disponible global
	      mapRef = map;            // referencia local del módulo
	      transitStopsLayer = L.layerGroup().addTo(map);
	      transitRoutesLayer = L.layerGroup().addTo(map);
	      transitWalkLayer = L.layerGroup().addTo(map);
	      hotspotsLayer = L.layerGroup().addTo(map);
	      map.on('zoomend', updateStopLabels);

      const recenterBtn = document.getElementById('mapRecenterBtn');
      if (recenterBtn) {
        recenterBtn.addEventListener('click', function () {
          if (!navigator.geolocation) {
            map.flyTo([25.6866, -100.3161], 13, { duration: 0.45 });
            return;
          }
          navigator.geolocation.getCurrentPosition(
            function (pos) {
              updateUserLocationMarker(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy);
              map.flyTo([pos.coords.latitude, pos.coords.longitude], Math.max(map.getZoom(), 13), { duration: 0.45 });
            },
            function () {
              map.flyTo([25.6866, -100.3161], 13, { duration: 0.45 });
            },
            { enableHighAccuracy: true, timeout: 5000, maximumAge: 120000 }
          );
        });
      }

      const reportsCloseBtn = document.getElementById('hotspotReportsClose');
      if (reportsCloseBtn) {
        reportsCloseBtn.addEventListener('click', closeReportsPanel);
      }

      const legendEl = document.getElementById('hotspotsLegend');
      const legendBtn = document.getElementById('legendToggleBtn');
      if (legendBtn && legendEl) {
        legendBtn.classList.toggle('is-active', !legendEl.classList.contains('is-hidden'));
        legendBtn.addEventListener('click', function () {
          const hidden = legendEl.classList.toggle('is-hidden');
          legendBtn.classList.toggle('is-active', !hidden);
        });
      }

      if (map.hasLayer(transitRoutesLayer)) map.removeLayer(transitRoutesLayer);
      if (map.hasLayer(transitStopsLayer)) map.removeLayer(transitStopsLayer);

      let transportVisible = false;
      const transportBtn = document.getElementById('transportToggleBtn');
      if (transportBtn) {
        transportBtn.classList.toggle('is-active', transportVisible);
        transportBtn.addEventListener('click', function () {
          transportVisible = !transportVisible;
          if (transportVisible) {
            animateLayerGroupVisibility(transitRoutesLayer, true, 300);
            animateLayerGroupVisibility(transitStopsLayer, true, 300);
          } else {
            animateLayerGroupVisibility(transitRoutesLayer, false, 240);
            animateLayerGroupVisibility(transitStopsLayer, false, 240);
          }
          transportBtn.classList.toggle('is-active', transportVisible);
        });
      }

      let hotspotsVisible = true;
      const hotspotsBtn = document.getElementById('hotspotsToggleBtn');
      if (hotspotsBtn) {
        if (!map.hasLayer(hotspotsLayer)) {
          map.addLayer(hotspotsLayer);
        }
        hotspotsBtn.classList.toggle('is-active', hotspotsVisible);
        hotspotsBtn.addEventListener('click', function () {
          hotspotsVisible = !hotspotsVisible;
          if (hotspotsVisible) {
            animateLayerGroupVisibility(hotspotsLayer, true, 300);
          } else {
            animateLayerGroupVisibility(hotspotsLayer, false, 240);
          }
          hotspotsBtn.classList.toggle('is-active', hotspotsVisible);
        });
      }

      if (Array.isArray(center) && center.length === 2) {
        updateUserLocationMarker(center[0], center[1], 24);
      }

      fetchHotspots(center, map);
      loadTransitOffline();

	      // Filtros por categoría
	      document.querySelectorAll('.violet-chips-container [data-cat]').forEach(btn => {
	        btn.addEventListener('click', function () {
          document.querySelectorAll('.violet-chips-container [data-cat]').forEach(b => b.classList.remove('active'));
          this.classList.add('active');
          currentCategory = this.dataset.cat || '';

	          // Limpiar sólo los hotspots (no tocar rutas/paradas/route planner)
	          if (hotspotsLayer) hotspotsLayer.clearLayers();

          // Recargar hotspots con la categoría activa
          const lat0 = center ? center[0] : 25.6866;
          const lng0 = center ? center[1] : -100.3161;
          const params =
            `?precision=3` +
            (currentCategory ? `&category=${encodeURIComponent(currentCategory)}` : '');

	          fetch('/api/hotspots' + params)
	            .then(r => r.json())
	            .then(data => {
	              (data.hotspots || []).forEach(h => {
                const radius = sizeForCount(h.count);
                const color = colorForCount(h.count);
	                const circle = L.circleMarker([h.lat, h.lng], {
	                  radius: radius / 3,
	                  color,
	                  weight: 2,
	                  fillColor: color,
	                  fillOpacity: .25
	                }).addTo(hotspotsLayer || map);
                animateLeafletLayerIn(circle, 260);

                circle.bindPopup(`<b>${h.count} reportes</b>`);

                circle.on('click', function () {
                  const c = circle.getLatLng();
                  const url =
                    `/api/posts-in-radius?lat=${c.lat}&lng=${c.lng}&radius_km=0.2` +
                    (currentCategory ? `&category=${encodeURIComponent(currentCategory)}` : '');
                  fetch(url).then(r => r.json()).then(d => renderReports(d.posts || [], { open: true }));
	            });
              });
            });

          // Recargar lista de reportes debajo del mapa con posts cercanos de esta categoría
          const mapCenter = map.getCenter();
          const postsUrl = `/api/posts-in-radius?lat=${mapCenter.lat}&lng=${mapCenter.lng}&radius_km=8` +
            (currentCategory ? `&category=${encodeURIComponent(currentCategory)}` : '');
          fetch(postsUrl)
            .then(r => r.json())
            .then(d => renderReports(d.posts || [], { open: false }))
            .catch(() => renderReports([], { open: false }));
        });
      });
    }

    function normalizeTransitRoute(route, defaultType = 'bus') {
      const tipo = (route && route.tipo ? String(route.tipo).toLowerCase() : defaultType).trim();
      const linea = Array.isArray(route?.linea) ? route.linea
        .filter(p => Array.isArray(p) && p.length >= 2 && Number.isFinite(Number(p[0])) && Number.isFinite(Number(p[1])))
        .map(p => [Number(p[0]), Number(p[1])]) : [];
      const paradas = Array.isArray(route?.paradas) ? route.paradas
        .filter(p => Number.isFinite(Number(p?.lat)) && Number.isFinite(Number(p?.lng)))
        .map((p, idx) => ({
          nombre: p.nombre || `Parada ${idx + 1}`,
          lat: Number(p.lat),
          lng: Number(p.lng),
          orden: Number.isFinite(Number(p.orden)) ? Number(p.orden) : idx + 1
        })) : [];
      return {
        ...route,
        tipo,
        nombre: route?.nombre || (tipo === 'metro' ? 'Línea Metro' : 'Ruta'),
        id_ruta: route?.id_ruta || route?.nombre || `${tipo}_${Math.random().toString(36).slice(2, 8)}`,
        linea,
        paradas
      };
    }

    function routeStrokeColor(route) {
      if (route?.color) return route.color;
      return colorForRouteKey(route?.id_ruta || route?.nombre || '');
    }

    function isBusRouteOne(route) {
      if (!route || route.tipo === 'metro') return false;
      const name = String(route.nombre || '').toLowerCase();
      const id = String(route.id_ruta || '').toLowerCase();
      return name.includes('ruta 1 - tecnológico') || id.includes('ruta_1_tecnologico');
    }

    function loadTransitOffline() {
      if (!transitRoutesLayer || !transitStopsLayer) return;

      Promise.all([
        fetch('/static/data/base_datos_rutas_mty.json')
          .then(r => r.ok ? r.json() : [])
          .catch(() => []),
        fetch('/static/data/metro_monterrey.json')
          .then(r => r.ok ? r.json() : [])
          .catch(() => [])
      ])
        .then(([busData, metroData]) => {
          const merged = []
            .concat(Array.isArray(busData) ? busData.map(r => normalizeTransitRoute(r, 'bus')) : [])
            .concat(Array.isArray(metroData) ? metroData.map(r => normalizeTransitRoute(r, 'metro')) : []);

          if (!merged.length) return;
          const visibleRoutes = merged.filter(r => !isBusRouteOne(r));
          transitIndex = visibleRoutes;

          // Limpiar cualquier remanente visual previo
          transitRoutesLayer.clearLayers();
          transitStopsLayer.clearLayers();

          // Dibujar de fondo todas las rutas visibles (incluye Metro)
          visibleRoutes.forEach(route => {
            if (Array.isArray(route.linea) && route.linea.length > 1) {
              const color = routeStrokeColor(route);
              const isMetro = route.tipo === 'metro';
              const poly = L.polyline(route.linea, {
                color,
                weight: isMetro ? 6 : 3,
                opacity: isMetro ? 0.95 : 0.75
              });
              const typeLabel = isMetro ? 'Metro' : 'Ruta';
              poly.bindTooltip(`${typeLabel}: ${route.nombre || 'Sin nombre'}`, { sticky: true });
              transitRoutesLayer.addLayer(poly);
            }

            if (Array.isArray(route.paradas)) {
              route.paradas.forEach(p => {
                const isMetro = route.tipo === 'metro';
                const marker = L.circleMarker([p.lat, p.lng], {
                  radius: isMetro ? 3.8 : 2.8,
                  color: isMetro ? '#ffffff' : '#a78bfa',
                  weight: 1,
                  fillColor: isMetro ? routeStrokeColor(route) : '#a78bfa',
                  fillOpacity: 0.9
                });
                marker.bindTooltip(`${isMetro ? 'Estación' : 'Parada'}: ${p.nombre || 'Sin nombre'}`, { direction: 'top' });
                transitStopsLayer.addLayer(marker);
              });
            }
          });
          updateStopLabels();
        })
        .catch(() => { /* silent */ });
    }

	    function fetchHotspots(center, map) {
	      let params = `?precision=3` + (currentCategory ? `&category=${encodeURIComponent(currentCategory)}` : '');

	      // Evitar duplicados al recargar
	      if (hotspotsLayer) hotspotsLayer.clearLayers();

	      fetch('/api/hotspots' + params)
	        .then(r => r.json())
	        .then(data => {
	          (data.hotspots || []).forEach(h => {
            const radius = sizeForCount(h.count);
            const color = colorForCount(h.count);
	            const circle = L.circleMarker([h.lat, h.lng], {
	              radius: radius / 3,
	              color: color,
	              weight: 2,
	              fillColor: color,
	              fillOpacity: 0.25
	            }).addTo(hotspotsLayer || map);
            animateLeafletLayerIn(circle, 260);

            const topTags = (h.top_tags || []).map(t => `#${t[0]} (${t[1]})`).join(', ');
            circle.bindPopup(
              `<b>${h.count} reportes</b><br>Likes: ${h.likes}<br>${topTags ? 'Etiquetas: ' + topTags : ''}`
            );

            // Click: cargar reportes cercanos (radio ~0.2 km)
            circle.on('click', function () {
              const c = circle.getLatLng();
              const url =
                `/api/posts-in-radius?lat=${c.lat}&lng=${c.lng}&radius_km=0.2` +
                (currentCategory ? `&category=${encodeURIComponent(currentCategory)}` : '');
              fetch(url)
                .then(r => r.json())
                .then(d => renderReports(d.posts || [], { open: true }))
                .catch(err => console.error('posts-in-radius error', err));
            });
          });
        })
        .catch(err => console.error('Hotspots error', err));
    }

    function reportsBadgeClass(category) {
      const c = canonicalCategory(category) || category || 'Otros';
      if (c === 'Poca iluminación') return 'badge-lighting';
      if (c === 'Banquetas en mal estado') return 'badge-sidewalk';
      if (c === 'Zona insegura') return 'badge-unsafe';
      if (c === 'Terrenos baldíos') return 'badge-baldios';
      return 'badge-other';
    }

    function formatDistance(meters) {
      if (!Number.isFinite(meters)) return 'Distancia no disponible';
      if (meters < 1000) return `A ${Math.max(1, Math.round(meters))} m de ti`;
      return `A ${(meters / 1000).toFixed(1)} km de ti`;
    }

    function formatRelativeTime(iso) {
      if (!iso) return 'Hace un momento';
      const date = new Date(iso);
      if (!Number.isFinite(date.getTime())) return 'Hace un momento';
      const diffMs = Math.max(0, Date.now() - date.getTime());
      const min = Math.floor(diffMs / 60000);
      if (min < 1) return 'Hace unos segundos';
      if (min < 60) return `Hace ${min} min`;
      const hrs = Math.floor(min / 60);
      if (hrs < 24) return `Hace ${hrs} h`;
      const days = Math.floor(hrs / 24);
      if (days < 30) return `Hace ${days} d`;
      const months = Math.floor(days / 30);
      if (months < 12) return `Hace ${months} mes${months === 1 ? '' : 'es'}`;
      const years = Math.floor(months / 12);
      return `Hace ${years} año${years === 1 ? '' : 's'}`;
    }

    function openReportsPanel() {
      const panel = document.getElementById('hotspotReports');
      if (!panel) return;
      panel.classList.remove('is-hidden');
      panel.setAttribute('aria-hidden', 'false');
    }

    function closeReportsPanel() {
      const panel = document.getElementById('hotspotReports');
      if (!panel) return;
      panel.classList.add('is-hidden');
      panel.setAttribute('aria-hidden', 'true');
    }

    function renderReports(posts, opts = {}) {
      const panel = document.getElementById('hotspotReports');
      const list = document.getElementById('hotspotReportsList');
      const title = document.getElementById('hotspotReportsTitle');
      const sub = document.getElementById('hotspotReportsSub');
      if (!panel || !list) return;
      const shouldOpen = opts.open !== false;

      const fallbackPoint = mapRef ? [mapRef.getCenter().lat, mapRef.getCenter().lng] : null;
      const userPoint = userCurrentPoint || fallbackPoint;
      const enriched = (posts || []).map((p) => {
        const plat = Number(p?.latitude);
        const plng = Number(p?.longitude);
        let distanceMeters = Infinity;
        if (userPoint && Number.isFinite(plat) && Number.isFinite(plng)) {
          distanceMeters = haversine(userPoint[0], userPoint[1], plat, plng);
        }
        const categories = Array.isArray(p?.categories) && p.categories.length
          ? p.categories.map(c => canonicalCategory(c) || c)
          : ['Otros'];
        return {
          ...p,
          __distanceMeters: distanceMeters,
          __categories: categories
        };
      }).sort((a, b) => (a.__distanceMeters - b.__distanceMeters));

      list.innerHTML = '';

      if (title) title.textContent = 'Alertas en esta zona';
      if (sub) {
        const count = enriched.length;
        sub.textContent = count
          ? `${count} alerta${count === 1 ? '' : 's'} · ordenadas de más cercana a más lejana`
          : 'No hay alertas en este punto';
      }

      if (!enriched.length) {
        list.innerHTML = '<div class="hotspots-report-empty">Aún no hay alertas cercanas en este círculo.</div>';
        if (shouldOpen || !panel.classList.contains('is-hidden')) openReportsPanel();
        return;
      }

      enriched.forEach((p, index) => {
        const item = document.createElement('article');
        item.className = 'hotspots-report-item';
        item.style.setProperty('--delay', `${Math.min(index * 45, 260)}ms`);
        const primaryCat = p.__categories[0] || 'Otros';
        const badgeClass = reportsBadgeClass(primaryCat);
        const safeCaption = escapeHtml(p.caption || 'Sin descripción');
        const safeUser = escapeHtml(p.username || 'Usuaria');
        const safeTime = escapeHtml(formatRelativeTime(p.created_at));
        const safeDistance = escapeHtml(formatDistance(p.__distanceMeters));
        const imageHtml = p.image_url
          ? `<a class="hotspots-report-item__image" href="/post/${p.id}"><img src="${p.image_url}" alt="Reporte ${safeUser}"></a>`
          : '';

        item.innerHTML = `
          <div class="hotspots-report-item__head">
            <div class="hotspots-report-item__meta">
              <div class="hotspots-report-item__user">@${safeUser}</div>
              <div class="hotspots-report-item__time">${safeTime}</div>
            </div>
            <div class="hotspots-report-item__distance">${safeDistance}</div>
          </div>
          <div class="hotspots-report-item__badge ${badgeClass}">
            <i class="fas fa-triangle-exclamation"></i>
            <span>${escapeHtml(primaryCat)}</span>
          </div>
          <p class="hotspots-report-item__caption">${safeCaption}</p>
          ${imageHtml}
        `;
        list.appendChild(item);
      });

      if (shouldOpen || !panel.classList.contains('is-hidden')) openReportsPanel();
    }

    // Inicialización con geolocalización
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function (pos) { initMap([pos.coords.latitude, pos.coords.longitude]); },
        function () { initMap(); },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 300000 }
      );
    } else {
      initMap();
    }

    // ------- Ruta segura (si el usuario inició sesión) -------
    const originInput = document.getElementById('originInput');
    const originResults = document.getElementById('originResults');
    const destInput = document.getElementById('destInput');
    const destResults = document.getElementById('destResults');
    const routeSwitchBtn = document.querySelector('.route-switch-pill');
    const routeBtn = document.getElementById('routeBtn');
    const routeCard = document.getElementById('routeCard');
    const routeCardHeader = document.getElementById('routeCardHeader');
    const routeCardSummary = document.getElementById('routeCardSummary');
    const routeCardScorePreview = document.getElementById('routeCardScorePreview');
    const speedReadout = document.getElementById('speedReadout');
    const routeSafetyScoreEl = document.getElementById('routeSafetyScore');
    const routeSafetyLevelEl = document.getElementById('routeSafetyLevel');
    const routeSafetyMetaEl = document.getElementById('routeSafetyMeta');
    const routeFeedbackEl = document.getElementById('routeFeedback');
    const routeLaunchActionsEl = document.getElementById('routeLaunchActions');
    const startSafeTripBtn = document.getElementById('startSafeTripBtn');
    const routeLaunchMetaEl = document.getElementById('routeLaunchMeta');
    const transitBtn = document.getElementById('transitBtn');
    const toggleStops = document.getElementById('toggleTransitStops');
    const routeSearch = document.getElementById('routeSearch');
    const routeResults = document.getElementById('routeResults');
    const clearRoutes = document.getElementById('clearRoutes');
    const waitStartSel = document.getElementById('waitStartSel');
    const waitXferSel = document.getElementById('waitXferSel');

    let destPoint = null;
    let startPoint = null;
    let routeLine = null;
    let startMarker = null;
    let destMarker = null;
    let liveSpeedMps = null; // velocidad estimada en m/s
    let speedWatchId = null;
    let lastFix = null; // {lat,lng,time}
    let speedWindow = []; // muestras recientes para suavizar
    let lastRouteMeters = null;
    let lastHazText = '';
    let activeRouteMode = 'walk';
    let lastPlannedTrip = null;
    const norm = s => (s || '').toString().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const allowedCities = new Set([
      'monterrey',
      'san pedro garza garcia', 'san pedro',
      'san nicolas de los garza',
      'guadalupe',
      'apodaca',
      'general escobedo', 'escobedo',
      'pesqueria',
      'santa catarina', 'sta catarina',
      'garcia',
      'juarez', 'ciudad benito juarez', 'benito juarez', 'cd benito juarez'
    ]);
    const metroBbox = '-100.80,26.10,-99.90,25.30';

    function fmtLatLngLabel(point) {
      if (!Array.isArray(point) || point.length < 2) return '';
      return `${Number(point[0]).toFixed(5)}, ${Number(point[1]).toFixed(5)}`;
    }

    function syncRouteCardSummary() {
      if (!routeCardSummary) return;
      const originText = (originInput?.value || 'Mi ubicación actual').trim() || 'Mi ubicación actual';
      const destText = (destInput?.value || '').trim();
      routeCardSummary.textContent = destText
        ? `${originText} hacia ${destText}`
        : `${originText} hacia tu destino`;
    }

    function syncRouteCardState() {
      if (!routeCard || !routeCardHeader) return;
      const isExpanded = routeCard.classList.contains('is-sheet-expanded')
        || routeCard.classList.contains('expanded')
        || routeCard.classList.contains('has-route-output');
      routeCardHeader.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    }

    function setSheetExpanded(shouldExpand) {
      if (!routeCard) return;
      routeCard.classList.toggle('is-sheet-expanded', !!shouldExpand);
      syncRouteCardState();
    }

    async function useCurrentLocationAsOrigin() {
      if (!navigator.geolocation) return false;
      return new Promise(resolve => {
        navigator.geolocation.getCurrentPosition(pos => {
          startPoint = [pos.coords.latitude, pos.coords.longitude];
          if (originInput) originInput.value = 'Mi ubicación actual';
          updateUserLocationMarker(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy);
          syncRouteCardSummary();
          resolve(true);
        }, () => resolve(false), { enableHighAccuracy: true, timeout: 8000, maximumAge: 20000 });
      });
    }

    function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }
    function setRouteMode(mode) {
      activeRouteMode = mode === 'transit' ? 'transit' : 'walk';
      if (routeBtn) routeBtn.classList.toggle('is-active', activeRouteMode === 'walk');
      if (transitBtn) transitBtn.classList.toggle('is-active', activeRouteMode === 'transit');
    }
    function updateRouteFeedbackVisibility() {
      if (!routeFeedbackEl) return;
      const alertEl = document.getElementById('routeAlert');
      const instrEl = document.getElementById('transitInstructions');
      const showAlert = !!(alertEl && alertEl.style.display !== 'none' && alertEl.innerHTML.trim());
      const showInstr = !!(instrEl && instrEl.style.display !== 'none');
      const hasOutput = showAlert || showInstr;
      routeFeedbackEl.classList.toggle('is-visible', hasOutput);
      if (routeCard) routeCard.classList.toggle('has-route-output', hasOutput);
      if (hasOutput) routeCard?.classList.add('is-sheet-expanded');
      syncRouteCardState();
    }
    function setTripLaunchState(plan) {
      lastPlannedTrip = plan || null;
      if (!routeLaunchActionsEl || !routeLaunchMetaEl || !startSafeTripBtn) return;
      if (!plan) {
        routeLaunchActionsEl.style.display = 'none';
        routeLaunchMetaEl.textContent = '';
        startSafeTripBtn.disabled = false;
        startSafeTripBtn.innerHTML = '<i class="fas fa-location-arrow"></i><span>Iniciar trayecto seguro</span>';
        return;
      }
      routeLaunchActionsEl.style.display = 'grid';
      const etaLabel = Number.isFinite(plan.etaMinutes) ? `${plan.etaMinutes} min` : 'ETA estimada';
      const distanceLabel = Number.isFinite(plan.distanceMeters)
        ? (plan.distanceMeters < 1000 ? `${Math.round(plan.distanceMeters)} m` : `${(plan.distanceMeters / 1000).toFixed(1)} km`)
        : 'distancia estimada';
      const modeLabel = plan.mode === 'transit' ? 'transporte público' : 'ruta peatonal';
      routeLaunchMetaEl.textContent = `Se activará tu seguimiento en vivo con ${modeLabel} · ${distanceLabel} · ${etaLabel}.`;
      startSafeTripBtn.disabled = false;
      startSafeTripBtn.innerHTML = '<i class="fas fa-location-arrow"></i><span>Iniciar trayecto seguro</span>';
    }
    function pickEtaOption(totalMinutes) {
      const options = [15, 30, 45, 60, 90];
      const target = clamp(Math.round(Number(totalMinutes) || 30), 5, 180);
      let best = options[0];
      let bestDiff = Math.abs(best - target);
      options.forEach(opt => {
        const diff = Math.abs(opt - target);
        if (diff < bestDiff) {
          best = opt;
          bestDiff = diff;
        }
      });
      return best;
    }
    function persistPendingTripPlan(extra = {}) {
      if (!lastPlannedTrip) return null;
      const payload = {
        ...lastPlannedTrip,
        source: 'hotspots',
        destinationLabel: (destInput?.value || lastPlannedTrip.destinationLabel || '').trim(),
        destinationPoint: Array.isArray(destPoint) ? [...destPoint] : (lastPlannedTrip.destinationPoint || null),
        originPoint: Array.isArray(startPoint) ? [...startPoint] : (lastPlannedTrip.originPoint || null),
        etaMinutes: pickEtaOption(lastPlannedTrip.etaMinutes),
        savedAt: Date.now(),
        ...extra
      };
      try {
        sessionStorage.setItem('violeta.pendingCheckin', JSON.stringify(payload));
      } catch (_) { }
      return payload;
    }
    function redirectToSafetyWithPlan(extra = {}) {
      const payload = persistPendingTripPlan(extra);
      const params = new URLSearchParams();
      if (payload?.destinationLabel) params.set('destination', payload.destinationLabel);
      if (payload?.etaMinutes) params.set('eta', String(payload.etaMinutes));
      if (payload?.mode) params.set('mode', payload.mode);
      Object.entries(extra || {}).forEach(([key, value]) => {
        if (value == null || value === false || value === '') return;
        params.set(key, String(value));
      });
      const query = params.toString();
      window.location.href = `/safety${query ? `?${query}` : ''}`;
    }
    async function startCheckinFromHotspots() {
      if (!lastPlannedTrip) {
        if (activeRouteMode === 'transit') await drawRouteTransit();
        else await drawRouteSafe();
        if (!lastPlannedTrip) return;
      }
      const payload = persistPendingTripPlan();
      if (!payload) return;

      startSafeTripBtn.disabled = true;
      startSafeTripBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Iniciando...</span>';

      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
      const noteParts = [
        payload.mode === 'transit' ? 'Ruta desde Hotspots · Transporte' : 'Ruta desde Hotspots · Caminando'
      ];
      if (Number.isFinite(payload.safetyScore)) noteParts.push(`Safety ${payload.safetyScore}/100`);
      if (payload.summaryText) noteParts.push(payload.summaryText);
      const note = noteParts.join(' · ').slice(0, 255);

      const send = (lat = null, lng = null) => fetch('/api/safety/checkin/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf
        },
        body: JSON.stringify({
          destination: payload.destinationLabel || '',
          eta_minutes: payload.etaMinutes || 30,
          note,
          lat,
          lng
        })
      }).then(async (response) => ({
        ok: response.ok,
        status: response.status,
        data: await response.json().catch(() => ({}))
      }));

      let result = null;
      if (navigator.geolocation) {
        result = await new Promise(resolve => {
          navigator.geolocation.getCurrentPosition(
            async (pos) => resolve(await send(pos.coords.latitude, pos.coords.longitude)),
            async () => resolve(await send(null, null)),
            { enableHighAccuracy: true, timeout: 7000, maximumAge: 0 }
          );
        });
      } else {
        result = await send(null, null);
      }

      startSafeTripBtn.disabled = false;
      startSafeTripBtn.innerHTML = '<i class="fas fa-location-arrow"></i><span>Iniciar trayecto seguro</span>';

      if (result?.ok && result.data?.ok) {
        redirectToSafetyWithPlan({ started: 1 });
        return;
      }

      if (result?.data?.error && /contacto de confianza/i.test(result.data.error)) {
        redirectToSafetyWithPlan({ missing_contact: 1 });
        return;
      }

      if (result?.status === 403) {
        redirectToSafetyWithPlan({ verify_required: 1 });
        return;
      }

      const alertBox = document.getElementById('routeAlert');
      if (alertBox) {
        alertBox.style.display = 'block';
        alertBox.textContent = result?.data?.error || 'No se pudo iniciar el trayecto.';
        updateRouteFeedbackVisibility();
      }
    }
    function haversine(lat1, lng1, lat2, lng2) {
      const R = 6371000; const toRad = x => x * Math.PI / 180;
      const dLat = toRad(lat2 - lat1), dLng = toRad(lng2 - lng1);
      const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(a));
    }
    function updateSpeedReadout() {
      if (!speedReadout) return;
      if (liveSpeedMps) {
        speedReadout.textContent = `Velocidad actual: ${(liveSpeedMps * 3.6).toFixed(1)} km/h`;
      } else {
        speedReadout.textContent = 'Velocidad actual: -- km/h';
      }
    }
    function startSpeedWatch() {
      if (!navigator.geolocation) return;
      if (speedWatchId) return;
      speedWatchId = navigator.geolocation.watchPosition(pos => {
        try {
          const { latitude: lat, longitude: lng, speed } = pos.coords;
          updateUserLocationMarker(lat, lng, pos.coords.accuracy);
          const ts = pos.timestamp ? pos.timestamp : Date.now();
          let v = null;
          if (typeof speed === 'number' && isFinite(speed) && speed >= 0) {
            v = speed; // m/s
          } else if (lastFix) {
            const dt = (ts - lastFix.time) / 1000; // s
            if (dt > 0.5) {
              const d = haversine(lastFix.lat, lastFix.lng, lat, lng); // m
              v = d / dt;
            }
          }
          lastFix = { lat, lng, time: ts };
          if (v != null && isFinite(v)) {
            // filtrar velocidades no plausibles para caminata
            if (v < 0.2 || v > 2.8) { updateSpeedReadout(); return; }
            speedWindow.push(v);
            if (speedWindow.length > 5) speedWindow.shift();
            const avg = speedWindow.reduce((a, b) => a + b, 0) / speedWindow.length;
            liveSpeedMps = clamp(avg, 0.2, 2.8);
            updateSpeedReadout();
            // actualizar ETA si ya hay ruta
            if (routeLine && lastRouteMeters != null) updateRouteAlert();
          } else {
            updateSpeedReadout();
          }
        } catch (_) { updateSpeedReadout(); }
      }, _ => { }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 });
    }
    function stopSpeedWatch() {
      if (speedWatchId) { navigator.geolocation.clearWatch(speedWatchId); speedWatchId = null; }
      lastFix = null; speedWindow = []; liveSpeedMps = null; updateSpeedReadout();
    }

    // Punto de inicio por geolocalización (si está disponible)
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(function (pos) {
        startPoint = [pos.coords.latitude, pos.coords.longitude];
        if (originInput) originInput.value = 'Mi ubicación actual';
        try { if (destPoint) { } } catch (_) { }
      });
    }

    function searchOrigin(query) {
      if (!originResults) return;
      originResults.innerHTML = '';

      const wrap = document.createElement('div');
      wrap.className = 'route-search-dropdown';

      const currentBtn = document.createElement('button');
      currentBtn.type = 'button';
      currentBtn.className = 'route-search-item route-search-item--current';
      currentBtn.innerHTML = `
        <span class="route-search-item__icon"><i class="fas fa-location-crosshairs"></i></span>
        <span class="route-search-item__content">
          <span class="route-search-item__title">Mi ubicación actual</span>
          <span class="route-search-item__sub">Usar GPS del dispositivo</span>
        </span>
      `;
      currentBtn.addEventListener('click', async () => {
        await useCurrentLocationAsOrigin();
        originResults.innerHTML = '';
        if (routeCard) routeCard.classList.remove('expanded');
        syncRouteCardSummary();
      });
      wrap.appendChild(currentBtn);

      const trimmed = (query || '').trim();
      if (!trimmed || trimmed.length < 2) {
        originResults.appendChild(wrap);
        return;
      }

      const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&countrycodes=mx&accept-language=es&bounded=1&viewbox=${metroBbox}&q=${encodeURIComponent(trimmed)}&limit=8`;
      fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(r => r.json())
        .then(list => {
          const filtered = (list || []).filter(item => {
            const a = item.address || {};
            const cityCandidates = [a.city, a.town, a.village, a.municipality, a.city_district, a.county];
            const inAllowedCity = cityCandidates.some(c => allowedCities.has(norm(c)));
            const inNuevoLeon = a.state ? norm(a.state).includes('nuevo leon') : true;
            return inAllowedCity && inNuevoLeon;
          });

          (filtered || []).forEach(item => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'route-search-item';

            const a = item.address || {};
            const cityName = a.city || a.town || a.village || a.municipality || a.city_district || a.county || '';
            const icon = document.createElement('span');
            icon.className = 'route-search-item__icon';
            icon.innerHTML = '<i class="fas fa-location-dot"></i>';

            const content = document.createElement('span');
            content.className = 'route-search-item__content';

            const title = document.createElement('span');
            title.className = 'route-search-item__title';
            title.textContent = cityName || 'Dirección';
            const sub = document.createElement('span');
            sub.className = 'route-search-item__sub';
            sub.textContent = item.display_name;
            content.appendChild(title);
            content.appendChild(sub);
            btn.appendChild(icon);
            btn.appendChild(content);

            btn.addEventListener('click', () => {
              startPoint = [parseFloat(item.lat), parseFloat(item.lon)];
              if (originInput) originInput.value = item.display_name;
              originResults.innerHTML = '';
              if (routeCard) routeCard.classList.remove('expanded');
              syncRouteCardSummary();
            });
            wrap.appendChild(btn);
          });

          originResults.innerHTML = '';
          originResults.appendChild(wrap);
        })
        .catch(() => {
          originResults.innerHTML = '';
          originResults.appendChild(wrap);
        });
    }

    function searchDest(query) {
      if (!query || query.length < 1) { destResults.innerHTML = ''; return; }
      // Restringir a municipios del AMG de Nuevo León
      const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&countrycodes=mx&accept-language=es&bounded=1&viewbox=${metroBbox}&q=${encodeURIComponent(query)}&limit=10`;
      fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(r => r.json())
        .then(list => {
          destResults.innerHTML = '';
          const wrap = document.createElement('div');
          wrap.className = 'route-search-dropdown';
          wrap.style.maxHeight = '65vh';

          const filtered = (list || []).filter(item => {
            const a = item.address || {};
            const cityCandidates = [a.city, a.town, a.village, a.municipality, a.city_district, a.county];
            const inAllowedCity = cityCandidates.some(c => allowedCities.has(norm(c)));
            const inNuevoLeon = a.state ? norm(a.state).includes('nuevo leon') : true;
            return inAllowedCity && inNuevoLeon;
          });

          (filtered || []).forEach(item => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'route-search-item';

            // Título con ciudad en negritas y descripción debajo
            const a = item.address || {};
            const cityName = a.city || a.town || a.village || a.municipality || a.city_district || a.county || '';
            const icon = document.createElement('span');
            icon.className = 'route-search-item__icon';
            icon.innerHTML = '<i class="fas fa-location-dot"></i>';

            const content = document.createElement('span');
            content.className = 'route-search-item__content';

            const title = document.createElement('span');
            title.className = 'route-search-item__title';
            title.textContent = cityName || 'Dirección';
            const sub = document.createElement('span');
            sub.className = 'route-search-item__sub';
            sub.textContent = item.display_name;
            content.appendChild(title);
            content.appendChild(sub);
            btn.appendChild(icon);
            btn.appendChild(content);

            btn.addEventListener('click', function () {
              destInput.value = item.display_name;
              destPoint = [parseFloat(item.lat), parseFloat(item.lon)];
              destResults.innerHTML = '';
              if (routeCard) routeCard.classList.remove('expanded');
              syncRouteCardSummary();
              setSheetExpanded(true);
              try {
                if (activeRouteMode === 'transit') drawRouteTransit();
                else drawRouteSafe();
              } catch (_) { }
            });
            wrap.appendChild(btn);
          });

          destResults.appendChild(wrap);
        })
        .catch(() => { });
    }

    async function geocodeDest(query) {
      if (!query) return null;
      const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&countrycodes=mx&accept-language=es&bounded=1&viewbox=${metroBbox}&q=${encodeURIComponent(query)}&limit=5`;
      try {
        const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
        const list = await res.json();
        const filtered = (list || []).filter(item => {
          const a = item.address || {};
          const cityCandidates = [a.city, a.town, a.village, a.municipality, a.city_district, a.county];
          const inAllowedCity = cityCandidates.some(c => allowedCities.has(norm(c)));
          const inNuevoLeon = a.state ? norm(a.state).includes('nuevo leon') : true;
          return inAllowedCity && inNuevoLeon;
        });
        const item = filtered[0] || list[0];
        if (!item) return null;
        return [parseFloat(item.lat), parseFloat(item.lon)];
      } catch (_) {
        return null;
      }
    }

    if (destInput) {
      let t = null;
      destInput.addEventListener('input', function () {
        clearTimeout(t);
        // Expandir el card mientras hay texto
        if (routeCard) routeCard.classList.toggle('expanded', this.value.trim().length > 0);
        syncRouteCardSummary();
        setSheetExpanded(true);
        t = setTimeout(() => searchDest(this.value.trim()), 150);
      });
      destInput.addEventListener('focus', function () {
        if (routeCard) routeCard.classList.toggle('expanded', this.value.trim().length > 0);
        setSheetExpanded(true);
        const v = this.value.trim();
        if (v.length >= 1) {
          clearTimeout(t);
          t = setTimeout(() => searchDest(v), 0);
        }
      });
      destInput.addEventListener('blur', function () {
        setTimeout(() => {
          destResults.innerHTML = '';
          if (routeCard && !(originInput && document.activeElement === originInput)) routeCard.classList.remove('expanded');
          syncRouteCardState();
        }, 200);
      });
      destInput.addEventListener('keydown', async function (event) {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        const raw = this.value.trim();
        if (!raw) return;
        if (!destPoint) {
          const resolved = await geocodeDest(raw);
          if (resolved) destPoint = resolved;
        }
        if (activeRouteMode === 'transit') drawRouteTransit();
        else drawRouteSafe();
      });
    }

    if (originInput) {
      let tOrigin = null;
      originInput.addEventListener('input', function () {
        clearTimeout(tOrigin);
        if (routeCard) routeCard.classList.toggle('expanded', this.value.trim().length > 0);
        syncRouteCardSummary();
        setSheetExpanded(true);
        tOrigin = setTimeout(() => searchOrigin(this.value.trim()), 150);
      });
      originInput.addEventListener('focus', function () {
        if (routeCard) routeCard.classList.add('expanded');
        setSheetExpanded(true);
        clearTimeout(tOrigin);
        tOrigin = setTimeout(() => searchOrigin(this.value.trim()), 0);
      });
      originInput.addEventListener('blur', function () {
        setTimeout(() => {
          if (originResults) originResults.innerHTML = '';
          if (routeCard && !(destInput && document.activeElement === destInput)) routeCard.classList.remove('expanded');
          syncRouteCardState();
        }, 220);
      });
    }

    function swapRouteEndpoints() {
      const oldStart = Array.isArray(startPoint) ? [...startPoint] : null;
      const oldDest = Array.isArray(destPoint) ? [...destPoint] : null;
      const oldOriginText = (originInput?.value || 'Mi ubicación actual').trim();
      const oldDestText = (destInput?.value || '').trim();

      if (!oldStart && !oldDest && !oldDestText) return;

      startPoint = oldDest ? [...oldDest] : null;
      destPoint = oldStart ? [...oldStart] : null;

      if (originInput) {
        originInput.value = oldDestText || (oldDest ? fmtLatLngLabel(oldDest) : 'Mi ubicación actual');
      }
      if (destInput) {
        destInput.value = oldOriginText || (oldStart ? fmtLatLngLabel(oldStart) : '');
      }

      if (originResults) originResults.innerHTML = '';
      if (destResults) destResults.innerHTML = '';
      syncRouteCardSummary();
      setSheetExpanded(true);

      if (startPoint && destPoint) {
        if (activeRouteMode === 'transit') drawRouteTransit();
        else drawRouteSafe();
      }
    }

    if (routeSwitchBtn) {
      routeSwitchBtn.addEventListener('click', swapRouteEndpoints);
    }
    if (startSafeTripBtn) {
      startSafeTripBtn.addEventListener('click', startCheckinFromHotspots);
    }

    // Iniciar cálculo automático de velocidad
    startSpeedWatch();
    updateSpeedReadout();
    setRouteMode('walk');
    syncRouteCardSummary();
    updateRouteFeedbackVisibility();
    syncRouteCardState();

    if (routeCardHeader) {
      const toggleSheet = () => {
        if (!routeCard) return;
        const next = !(routeCard.classList.contains('is-sheet-expanded')
          || routeCard.classList.contains('expanded')
          || routeCard.classList.contains('has-route-output'));
        setSheetExpanded(next);
      };
      routeCardHeader.addEventListener('click', toggleSheet);
      routeCardHeader.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        toggleSheet();
      });
    }

    const activeMap = window.hotspotMap || mapRef;
    if (activeMap) {
      activeMap.on('click', () => {
        if (destResults) destResults.innerHTML = '';
        if (originResults) originResults.innerHTML = '';
        if (routeCard) routeCard.classList.remove('expanded');
        if (routeCard && !routeCard.classList.contains('has-route-output')) {
          routeCard.classList.remove('is-sheet-expanded');
        }
        syncRouteCardState();
      });
    }



    function polylineMeters(points) {
      if (!Array.isArray(points) || points.length < 2) return 0;
      let total = 0;
      for (let i = 1; i < points.length; i++) {
        total += haversine(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1]);
      }
      return total;
    }

    function latLngToXYMeters(point, refLat) {
      const latFactor = 110540;
      const lngFactor = 111320 * Math.cos(refLat * Math.PI / 180);
      return [point[1] * lngFactor, point[0] * latFactor];
    }

    function pointToSegmentDistanceMeters(p, a, b, refLat) {
      const [px, py] = latLngToXYMeters(p, refLat);
      const [ax, ay] = latLngToXYMeters(a, refLat);
      const [bx, by] = latLngToXYMeters(b, refLat);
      const abx = bx - ax;
      const aby = by - ay;
      const ab2 = (abx * abx) + (aby * aby);
      if (ab2 <= 1e-6) return Math.hypot(px - ax, py - ay);
      let t = ((px - ax) * abx + (py - ay) * aby) / ab2;
      t = clamp(t, 0, 1);
      const cx = ax + (abx * t);
      const cy = ay + (aby * t);
      return Math.hypot(px - cx, py - cy);
    }

    function pointToPolylineDistanceMeters(point, coords) {
      if (!Array.isArray(coords) || coords.length < 2) return Infinity;
      const refLat = coords.reduce((s, c) => s + c[0], 0) / coords.length;
      let best = Infinity;
      for (let i = 1; i < coords.length; i++) {
        const d = pointToSegmentDistanceMeters(point, coords[i - 1], coords[i], refLat);
        if (d < best) best = d;
      }
      return best;
    }

    function canonicalCategory(raw) {
      const t = norm(raw);
      if (!t) return null;
      if (t.includes('ilumin') || t.includes('oscuro') || t.includes('alumbrado') || t.includes('luz')) return 'Poca iluminación';
      if (t.includes('banqueta') || t.includes('acera') || t.includes('bache') || t.includes('pavimento')) return 'Banquetas en mal estado';
      if (t.includes('insegur') || t.includes('asalto') || t.includes('robo') || t.includes('violencia') || t.includes('acoso') || t.includes('peligro')) return 'Zona insegura';
      if (t.includes('punto ciego') || t.includes('ciego') || t.includes('baldio') || t.includes('baldío') || t.includes('lote') || t.includes('abandon')) return 'Terrenos baldíos';
      return null;
    }

    function extractPostCategories(post) {
      const set = new Set();
      if (Array.isArray(post?.categories)) {
        post.categories.forEach(c => {
          const canon = canonicalCategory(c);
          if (canon) set.add(canon);
        });
      }
      const cap = norm(post?.caption || '');
      [
        'iluminacion', 'iluminación', 'oscuro', 'alumbrado', 'luz',
        'banqueta', 'acera', 'bache', 'pavimento',
        'inseguro', 'insegura', 'asalto', 'robo', 'violencia', 'acoso', 'peligro',
        'baldio', 'baldío', 'lote', 'abandonado'
      ].forEach(k => {
        if (cap.includes(k)) {
          const canon = canonicalCategory(k);
          if (canon) set.add(canon);
        }
      });
      if (!set.size) set.add('Otros');
      return Array.from(set);
    }

    function recencyFactor(createdAt) {
      if (!createdAt) return 0.85;
      const dt = new Date(createdAt);
      if (!Number.isFinite(dt.getTime())) return 0.85;
      const ageHours = Math.max(0, (Date.now() - dt.getTime()) / 3600000);
      if (ageHours <= 6) return 1.35;
      if (ageHours <= 24) return 1.2;
      if (ageHours <= 72) return 1.0;
      if (ageHours <= 168) return 0.82;
      if (ageHours <= 720) return 0.65;
      return 0.48;
    }

    function timeRiskInfo() {
      const h = new Date().getHours();
      if (h >= 22 || h < 5) return { label: 'Noche', factor: 1.32, isNight: true };
      if ((h >= 19 && h < 22) || (h >= 5 && h < 7)) return { label: 'Atardecer/madrugada', factor: 1.16, isNight: true };
      return { label: 'Día', factor: 1.0, isNight: false };
    }

    function categorySeverity(category) {
      const map = {
        'Zona insegura': 1.0,
        'Poca iluminación': 0.9,
        'Terrenos baldíos': 0.8,
        'Banquetas en mal estado': 0.45,
        'Otros': 0.3
      };
      return map[category] || 0.3;
    }

    function distanceBand(distanceM) {
      if (distanceM <= 35) return { factor: 1.65, mandatory: true };
      if (distanceM <= 70) return { factor: 1.3, mandatory: true };
      if (distanceM <= 130) return { factor: 0.95, mandatory: false };
      if (distanceM <= 220) return { factor: 0.55, mandatory: false };
      return null;
    }

    function classifySafety(score) {
      if (score >= 82) return { label: 'Alta', cls: 'score-high' };
      if (score >= 64) return { label: 'Media', cls: 'score-medium' };
      if (score >= 45) return { label: 'Baja', cls: 'score-low' };
      return { label: 'Crítica', cls: 'score-low' };
    }

    function setSafetyScoreUI(result) {
      if (!routeSafetyScoreEl || !routeSafetyLevelEl || !routeSafetyMetaEl) return;
      routeSafetyLevelEl.classList.remove('score-high', 'score-medium', 'score-low');
      if (!result) {
        routeSafetyScoreEl.textContent = '--/100';
        routeSafetyLevelEl.textContent = '--';
        routeSafetyMetaEl.textContent = 'Calcula una ruta para evaluar riesgos reales.';
        if (routeCardScorePreview) routeCardScorePreview.textContent = '--';
        return;
      }
      const cls = classifySafety(result.score);
      routeSafetyScoreEl.textContent = `${result.score}/100`;
      routeSafetyLevelEl.textContent = cls.label;
      routeSafetyLevelEl.classList.add(cls.cls);
      routeSafetyMetaEl.textContent = `${result.totalReports} reportes en corredor · ${result.mandatoryReports} obligatorios · ${result.timeLabel}`;
      if (routeCardScorePreview) routeCardScorePreview.textContent = String(result.score);
    }

    async function fetchPostsInRadius(lat, lng, radiusKm) {
      const url = `/api/posts-in-radius?lat=${lat}&lng=${lng}&radius_km=${radiusKm.toFixed(2)}&_ts=${Date.now()}`;
      try {
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) return [];
        const json = await res.json();
        return Array.isArray(json?.posts) ? json.posts : [];
      } catch (_) {
        return [];
      }
    }

    async function fetchWalkLegPath(fromPoint, toPoint) {
      const straightDistance = haversine(fromPoint[0], fromPoint[1], toPoint[0], toPoint[1]);
      const chain = `${fromPoint[1]},${fromPoint[0]};${toPoint[1]},${toPoint[0]}`;
      const footUrl = `https://routing.openstreetmap.de/routed-foot/route/v1/foot/${chain}?overview=full&geometries=geojson&alternatives=false`;
      const fallbackUrl = `https://router.project-osrm.org/route/v1/walking/${chain}?overview=full&geometries=geojson&alternatives=false`;
      try {
        let res = await fetch(footUrl);
        if (!res.ok) res = await fetch(fallbackUrl);
        if (!res.ok) throw new Error('walk-leg-unavailable');
        const json = await res.json();
        const route = json?.routes?.[0];
        if (!route?.geometry?.coordinates?.length) throw new Error('walk-leg-empty');
        const coords = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
        return {
          coords,
          distance: Number(route.distance || 0) || polylineMeters(coords),
          routed: true
        };
      } catch (_) {
        return {
          coords: [fromPoint, toPoint],
          distance: straightDistance,
          routed: false
        };
      }
    }

    async function fetchRoutePosts(routeCoords) {
      if (!Array.isArray(routeCoords) || routeCoords.length < 2) return [];
      let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
      routeCoords.forEach(([lat, lng]) => {
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLng = Math.min(minLng, lng);
        maxLng = Math.max(maxLng, lng);
      });
      const center = [(minLat + maxLat) / 2, (minLng + maxLng) / 2];
      const maxDist = routeCoords.reduce((best, [lat, lng]) => Math.max(best, haversine(center[0], center[1], lat, lng)), 0);
      const radiusKm = clamp((maxDist / 1000) + 0.35, 0.5, 8.0);
      return fetchPostsInRadius(center[0], center[1], radiusKm);
    }

    function computeRouteSafety(routeCoords, posts) {
      const riskByCategory = {};
      const timeInfo = timeRiskInfo();
      const corridor = [];
      const routeKm = polylineMeters(routeCoords) / 1000;
      const BASE_RISK = 4.8;
      const lengthFactor = clamp(0.88 + (Math.min(routeKm, 10) * 0.05), 0.88, 1.35);

      (posts || []).forEach(post => {
        const lat = Number(post?.latitude);
        const lng = Number(post?.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

        const distanceM = pointToPolylineDistanceMeters([lat, lng], routeCoords);
        const band = distanceBand(distanceM);
        if (!band) return;

        const categories = extractPostCategories(post);
        const categoryMaxSeverity = Math.max(...categories.map(categorySeverity), 0.3);
        const categoryCountFactor = 1 + Math.min((categories.length - 1) * 0.16, 0.48);
        const recency = recencyFactor(post.created_at);
        const reactions = Math.max(0, Number(post.likes_count || 0) + Number(post.comments_count || 0));
        const social = 1 + Math.min(Math.log1p(reactions) / 3, 0.55);
        let categoryNightFactor = 1.0;
        if (timeInfo.isNight) {
          if (categories.includes('Poca iluminación')) categoryNightFactor *= 1.25;
          if (categories.includes('Terrenos baldíos')) categoryNightFactor *= 1.15;
          if (categories.includes('Zona insegura')) categoryNightFactor *= 1.12;
        }

        corridor.push({
          id: post.id,
          lat,
          lng,
          categories,
          distanceM,
          mandatory: band.mandatory,
          baseRisk: BASE_RISK * categoryMaxSeverity * categoryCountFactor * recency * social * timeInfo.factor * categoryNightFactor * band.factor
        });
      });

      // Densidad por zona: si hay varios reportes cercanos entre sí, sube riesgo.
      for (let i = 0; i < corridor.length; i++) {
        let neighbors = 0;
        for (let j = 0; j < corridor.length; j++) {
          if (i === j) continue;
          if (haversine(corridor[i].lat, corridor[i].lng, corridor[j].lat, corridor[j].lng) <= 120) neighbors += 1;
        }
        const zoneFactor = 1 + Math.min(neighbors * 0.12, 0.45);
        corridor[i].risk = corridor[i].baseRisk * zoneFactor;
      }

      let totalRisk = corridor.reduce((s, it) => s + (it.risk || 0), 0) * lengthFactor;
      const mandatoryReports = corridor.filter(it => it.mandatory).length;
      totalRisk += mandatoryReports * 2.5; // penalización explícita por reportes inevitables

      corridor.forEach(it => {
        it.categories.forEach(cat => {
          riskByCategory[cat] = (riskByCategory[cat] || 0) + (it.risk || 0);
        });
      });

      const score = Math.round(clamp(100 - totalRisk, 5, 100));
      const categorySummary = Object.entries(riskByCategory)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([cat]) => cat)
        .join(', ');
      const hint = corridor.length
        ? `Riesgo ${classifySafety(score).label.toLowerCase()}: ${corridor.length} reportes en corredor${mandatoryReports ? ` · ${mandatoryReports} obligatorios` : ''}${categorySummary ? ` · ${categorySummary}` : ''}`
        : 'Sin reportes cercanos en el corredor trazado';

      return {
        score,
        totalReports: corridor.length,
        mandatoryReports,
        timeLabel: timeInfo.label,
        hint
      };
    }

    async function evaluateRouteSafety(routeCoords, options = { updateUI: true, posts: null }) {
      if (!Array.isArray(routeCoords) || routeCoords.length < 2) {
        if (options.updateUI) setSafetyScoreUI(null);
        return null;
      }
      const posts = Array.isArray(options.posts) ? options.posts : await fetchRoutePosts(routeCoords);
      const result = computeRouteSafety(routeCoords, posts);
      if (options.updateUI) setSafetyScoreUI(result);
      return result;
    }

    async function drawRouteSafe() {
      const alertBox = document.getElementById('routeAlert');
      const instructionsPanel = document.getElementById('transitInstructions');
      setRouteMode('walk');
      setTripLaunchState(null);
      if (alertBox) { alertBox.style.display = 'none'; alertBox.innerHTML = ''; }
      if (instructionsPanel) instructionsPanel.style.display = 'none';
      updateRouteFeedbackVisibility();

      if (!startPoint) {
        try {
          const pos = await new Promise((res, rej) =>
            navigator.geolocation.getCurrentPosition(res, rej, { enableHighAccuracy: true, timeout: 8000 })
          );
          startPoint = [pos.coords.latitude, pos.coords.longitude];
        } catch (e) { }
      }

      if (!destPoint && destInput && destInput.value.trim()) {
        const resolved = await geocodeDest(destInput.value.trim());
        if (resolved) destPoint = resolved;
      }

      if (!startPoint || !destPoint) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'Define tu destino y habilita la ubicación.';
          updateRouteFeedbackVisibility();
        }
        return;
      }

      const m = window.hotspotMap || mapRef;
      if (!m) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'El mapa no está listo aún.';
          updateRouteFeedbackVisibility();
        }
        return;
      }

      function fmtKm(m) { if (m < 1000) return Math.round(m) + ' m'; const v = m / 1000; return (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + ' km'; }
      function fmtTime(s) { const min = Math.round(s / 60); if (min < 60) return `${min} min`; const h = Math.floor(min / 60), mm = min % 60; return `${h} h ${mm} min`; }
      function currentMps() { return liveSpeedMps || 1.33; }
      function routeStatusMsg(safety) {
        const secs = lastRouteMeters > 0 ? lastRouteMeters / currentMps() : 0;
        const safetyPart = safety ? ` · Safety ${safety.score}/100 (${classifySafety(safety.score).label})` : '';
        const hazardPart = safety?.hint ? ` · ${safety.hint}` : '';
        return `Ruta peatonal: ${fmtKm(lastRouteMeters)} · ${fmtTime(secs)}${safetyPart}${hazardPart}`;
      }

      function buildDetourMidpoints(a, b) {
        const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        const dLat = b[0] - a[0];
        const dLng = b[1] - a[1];
        const len = Math.hypot(dLat, dLng) || 1;
        const offset = 0.0055; // ~600m
        const nLat = (-dLng / len) * offset;
        const nLng = (dLat / len) * offset;
        return [
          [mid[0] + nLat, mid[1] + nLng],
          [mid[0] - nLat, mid[1] - nLng]
        ];
      }

      async function fetchWalkingRoute(points) {
        const chain = points.map(([lat, lng]) => `${lng},${lat}`).join(';');
        const footUrl = `https://routing.openstreetmap.de/routed-foot/route/v1/foot/${chain}?overview=full&geometries=geojson&alternatives=false`;
        const fallbackUrl = `https://router.project-osrm.org/route/v1/walking/${chain}?overview=full&geometries=geojson&alternatives=false`;
        let res = await fetch(footUrl);
        if (!res.ok) res = await fetch(fallbackUrl);
        if (!res.ok) return null;
        const json = await res.json();
        if (!json?.routes?.length) return null;
        return json.routes[0];
      }

      try {
        const tripCenter = [(startPoint[0] + destPoint[0]) / 2, (startPoint[1] + destPoint[1]) / 2];
        const tripRadiusKm = clamp((haversine(startPoint[0], startPoint[1], destPoint[0], destPoint[1]) / 2000) + 1.4, 0.8, 8.0);
        const envelopePosts = await fetchPostsInRadius(tripCenter[0], tripCenter[1], tripRadiusKm);

        const candidates = [];
        const directRoute = await fetchWalkingRoute([startPoint, destPoint]);
        if (directRoute) candidates.push({ route: directRoute, kind: 'directa' });

        const detours = buildDetourMidpoints(startPoint, destPoint);
        for (const mid of detours) {
          const alt = await fetchWalkingRoute([startPoint, mid, destPoint]);
          if (alt) candidates.push({ route: alt, kind: 'desvío' });
        }

        // Fallback opcional (si los motores OSM fallan)
        if (!candidates.length) {
          try {
            const ghUrl = `https://graphhopper.com/api/1/route?point=${startPoint[0]},${startPoint[1]}&point=${destPoint[0]},${destPoint[1]}&profile=foot&locale=es&points_encoded=false&key=demo`;
            const ghRes = await fetch(ghUrl);
            if (ghRes.ok) {
              const ghData = await ghRes.json();
              const path = ghData?.paths?.[0];
              if (path?.points?.coordinates?.length) {
                candidates.push({
                  kind: 'fallback',
                  route: {
                    distance: path.distance || 0,
                    geometry: { coordinates: path.points.coordinates }
                  }
                });
              }
            }
          } catch (_) { }
        }

        if (!candidates.length) throw new Error('No se pudo encontrar una ruta peatonal.');

        const scored = [];
        for (const candidate of candidates) {
          const coords = (candidate.route?.geometry?.coordinates || []).map(([lng, lat]) => [lat, lng]);
          if (!coords.length) continue;
          const safety = await evaluateRouteSafety(coords, { updateUI: false, posts: envelopePosts });
          scored.push({ ...candidate, coords, safety });
        }
        if (!scored.length) throw new Error('No se pudo evaluar ninguna ruta.');

        scored.sort((a, b) => {
          const as = a.safety?.score ?? 0;
          const bs = b.safety?.score ?? 0;
          if (bs !== as) return bs - as; // prioriza más segura
          const ad = Number(a.route?.distance || polylineMeters(a.coords));
          const bd = Number(b.route?.distance || polylineMeters(b.coords));
          return ad - bd; // empate: más corta
        });

        const best = scored[0];
        const route = best.route;
        const coords = best.coords;
        const safety = best.safety;

        // Limpiar ruta/markers anteriores
        if (routeLine) { routeLine.remove(); routeLine = null; }
        if (startMarker) { startMarker.remove(); startMarker = null; }
        if (destMarker) { destMarker.remove(); destMarker = null; }

        // Dibujar ruta peatonal con estilo legible
        routeLine = L.polyline(coords, { color: '#1e90ff', weight: 6, opacity: 0.95, dashArray: '6 6' }).addTo(m);
        // Marcadores de inicio/destino
        startMarker = L.circleMarker(startPoint, { radius: 6, color: '#00c853', fillColor: '#00c853', fillOpacity: 0.9, weight: 2 }).addTo(m);
        destMarker = L.circleMarker(destPoint, { radius: 6, color: '#b565a7', fillColor: '#b565a7', fillOpacity: 0.9, weight: 2 }).addTo(m);
        animateLeafletLayerIn(routeLine, 340);
        animateLeafletLayerIn(startMarker, 300);
        animateLeafletLayerIn(destMarker, 300);
        m.fitBounds(routeLine.getBounds(), { padding: [30, 30] });

        // Distancia total de la ruta
        lastRouteMeters = Number(route.distance || 0) || polylineMeters(coords);
        if (safety) setSafetyScoreUI(safety);
        lastHazText = safety?.hint || '';
        setTripLaunchState({
          mode: 'walk',
          destinationLabel: (destInput?.value || '').trim(),
          destinationPoint: Array.isArray(destPoint) ? [...destPoint] : null,
          originPoint: Array.isArray(startPoint) ? [...startPoint] : null,
          distanceMeters: lastRouteMeters,
          etaMinutes: Math.max(5, Math.round((lastRouteMeters / currentMps()) / 60)),
          safetyScore: safety?.score ?? null,
          summaryText: 'Ruta segura a pie'
        });

        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.innerHTML = routeStatusMsg(safety);
          updateRouteFeedbackVisibility();
        }
      } catch (e) {
        console.error('Route error:', e);
        setSafetyScoreUI(null);
        setTripLaunchState(null);
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'No se pudo trazar la ruta. Verifica tu conexión a internet o intenta con otro destino.';
          updateRouteFeedbackVisibility();
        }
      }
    }

    if (routeBtn) {
      routeBtn.addEventListener('click', () => {
        setSheetExpanded(true);
        drawRouteSafe();
      });
    }

    // Transit routing layers
    let transitLayers = [];

    // Draw transit route using Local Routing Engine + Metro data
    async function drawRouteTransit() {
      console.log('Transit button clicked - calling Local Engine');
      const alertBox = document.getElementById('routeAlert');
      const instructionsPanel = document.getElementById('transitInstructions');
      const stepsContainer = document.getElementById('transitSteps');
      setRouteMode('transit');
      setTripLaunchState(null);

      if (alertBox) {
        alertBox.style.display = 'none';
        alertBox.innerHTML = '';
        alertBox.style.background = 'rgba(99, 102, 241, 0.12)';
        alertBox.style.color = '#3730a3';
      }
      if (instructionsPanel) instructionsPanel.style.display = 'none';
      if (stepsContainer) stepsContainer.innerHTML = '';
      clearRouteLegend();
      updateRouteFeedbackVisibility();

      transitLayers.forEach(layer => {
        try { if (layer && layer.remove) layer.remove(); } catch (_) { }
      });
      transitLayers = [];

      if (!destInput || !destInput.value.trim()) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'Escribe un destino para calcular la ruta.';
          updateRouteFeedbackVisibility();
        }
        return;
      }

      if (!startPoint) {
        try {
          const pos = await new Promise((res, rej) =>
            navigator.geolocation.getCurrentPosition(res, rej, { enableHighAccuracy: true, timeout: 8000 })
          );
          startPoint = [pos.coords.latitude, pos.coords.longitude];
        } catch (_) { }
      }

      if (!destPoint && destInput && destInput.value.trim()) {
        const resolved = await geocodeDest(destInput.value.trim());
        if (resolved) destPoint = resolved;
      }

      if (!startPoint || !destPoint) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'Define tu destino y habilita la ubicación.';
          updateRouteFeedbackVisibility();
        }
        return;
      }

      const m = window.hotspotMap || mapRef;
      if (!m) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.textContent = 'El mapa no está listo aún.';
          updateRouteFeedbackVisibility();
        }
        return;
      }

      if (alertBox) {
        alertBox.style.display = 'block';
        alertBox.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div> Buscando ruta de transporte...';
        updateRouteFeedbackVisibility();
      }

      try {
        if (!Array.isArray(transitIndex) || !transitIndex.length) {
          throw new Error('No hay rutas locales cargadas.');
        }

        const BUS_MAX_WALK = 600;
        const METRO_MAX_WALK = 1500;
        const METRO_TRANSFER_MAX = 450;

        function haversineMeters(a, b) {
          const R = 6371000;
          const toRad = x => x * Math.PI / 180;
          const dLat = toRad(b[0] - a[0]);
          const dLng = toRad(b[1] - a[1]);
          const s = Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
          return 2 * R * Math.asin(Math.sqrt(s));
        }

        function polylineMeters(points) {
          if (!Array.isArray(points) || points.length < 2) return 0;
          let d = 0;
          for (let i = 1; i < points.length; i++) d += haversineMeters(points[i - 1], points[i]);
          return d;
        }

        function closestIndex(point, line) {
          let bestIdx = 0;
          let bestDist = Infinity;
          for (let i = 0; i < line.length; i++) {
            const d = haversineMeters(point, line[i]);
            if (d < bestDist) {
              bestDist = d;
              bestIdx = i;
            }
          }
          return { idx: bestIdx, dist: bestDist };
        }

        function segmentBetween(line, fromIdx, toIdx) {
          if (!Array.isArray(line) || !line.length) return [];
          if (fromIdx <= toIdx) return line.slice(fromIdx, toIdx + 1);
          return line.slice(toIdx, fromIdx + 1).reverse();
        }

        function routeMaxWalk(route) {
          return (route?.tipo === 'metro') ? METRO_MAX_WALK : BUS_MAX_WALK;
        }

        function findBestSingleRoute() {
          let best = null;
          transitIndex.forEach(route => {
            if (!Array.isArray(route?.linea) || route.linea.length < 2) return;
            const s = closestIndex(startPoint, route.linea);
            const d = closestIndex(destPoint, route.linea);
            const maxWalk = routeMaxWalk(route);
            if (s.dist > maxWalk || d.dist > maxWalk) return;

            const seg = segmentBetween(route.linea, s.idx, d.idx);
            const rideMeters = polylineMeters(seg);
            const score = s.dist + d.dist + (rideMeters * 0.03);
            if (!best || score < best.score) {
              best = { mode: 'single', route, score, sIdx: s.idx, dIdx: d.idx, sDist: s.dist, dDist: d.dist, rideMeters, seg };
            }
          });
          return best;
        }

        function bestTransferBetween(routeA, routeB) {
          if (!Array.isArray(routeA?.linea) || !Array.isArray(routeB?.linea)) return null;
          let best = null;
          for (let i = 0; i < routeA.linea.length; i++) {
            for (let j = 0; j < routeB.linea.length; j++) {
              const d = haversineMeters(routeA.linea[i], routeB.linea[j]);
              if (d <= METRO_TRANSFER_MAX && (!best || d < best.dist)) {
                best = { aIdx: i, bIdx: j, dist: d, aPoint: routeA.linea[i], bPoint: routeB.linea[j] };
              }
            }
          }
          return best;
        }

        function findBestMetroTransfer() {
          const metros = transitIndex.filter(r => r?.tipo === 'metro' && Array.isArray(r?.linea) && r.linea.length > 1);
          if (metros.length < 2) return null;
          let best = null;
          metros.forEach(routeA => {
            metros.forEach(routeB => {
              if (routeA.id_ruta === routeB.id_ruta) return;
              const s = closestIndex(startPoint, routeA.linea);
              const d = closestIndex(destPoint, routeB.linea);
              if (s.dist > METRO_MAX_WALK || d.dist > METRO_MAX_WALK) return;

              const xfer = bestTransferBetween(routeA, routeB);
              if (!xfer) return;

              const segA = segmentBetween(routeA.linea, s.idx, xfer.aIdx);
              const segB = segmentBetween(routeB.linea, xfer.bIdx, d.idx);
              const rideA = polylineMeters(segA);
              const rideB = polylineMeters(segB);
              const score = s.dist + d.dist + xfer.dist + ((rideA + rideB) * 0.03) + 250;
              if (!best || score < best.score) {
                best = {
                  mode: 'metro_transfer',
                  score,
                  routeA, routeB,
                  sIdx: s.idx,
                  dIdx: d.idx,
                  sDist: s.dist,
                  dDist: d.dist,
                  xfer,
                  segA,
                  segB,
                  rideA,
                  rideB
                };
              }
            });
          });
          return best;
        }

        const bestSingle = findBestSingleRoute();
        const bestTransfer = !bestSingle ? findBestMetroTransfer() : null;
        const plan = bestSingle || bestTransfer;

        if (!plan) {
          throw new Error('No se encontró una ruta de transporte cercana. Intenta con otro destino dentro del área metropolitana.');
        }

        const walkColor = '#3b82f6';
        const startM = L.circleMarker(startPoint, { radius: 6, color: walkColor, fillColor: walkColor, fillOpacity: 1 }).addTo(m);
        const destM = L.circleMarker(destPoint, { radius: 8, color: '#ef4444', fillColor: '#ef4444', fillOpacity: 1 }).addTo(m);
        transitLayers.push(startM, destM);

        let allPoints = [startPoint, destPoint];
        let summaryText = '';
        const walkMins = (meters) => Math.max(1, Math.round((Number(meters) || 0) / 80));
        const rideMins = (meters, type = 'bus') => Math.max(2, Math.round((Number(meters) || 0) / (type === 'metro' ? 520 : 420)));

        if (plan.mode === 'single') {
          const route = plan.route;
          const rideColor = routeStrokeColor(route);
          const routeIconClass = route.tipo === 'metro' ? 'fa-train-subway' : 'fa-bus';
          const routeLabel = route.tipo === 'metro' ? 'Metro' : 'Ruta';

          const rideStart = plan.seg[0];
          const rideEnd = plan.seg[plan.seg.length - 1];
          const walkLeg1 = await fetchWalkLegPath(startPoint, rideStart);
          const walkLeg2 = await fetchWalkLegPath(rideEnd, destPoint);

          const polyWalk1 = L.polyline(walkLeg1.coords, { color: walkColor, weight: 4, dashArray: '6 6', opacity: 0.85 }).addTo(m);
          const polyRide = L.polyline(plan.seg, { color: rideColor, weight: route.tipo === 'metro' ? 7 : 6, opacity: 0.95 }).addTo(m);
          const polyWalk2 = L.polyline(walkLeg2.coords, { color: walkColor, weight: 4, dashArray: '6 6', opacity: 0.85 }).addTo(m);
          transitLayers.push(polyWalk1, polyRide, polyWalk2);

          const stop1M = L.circleMarker(rideStart, { radius: 6, color: rideColor, fillColor: '#fff', weight: 2 }).addTo(m);
          const stop2M = L.circleMarker(rideEnd, { radius: 6, color: rideColor, fillColor: '#fff', weight: 2 }).addTo(m);
          transitLayers.push(stop1M, stop2M);

          allPoints = allPoints.concat(walkLeg1.coords, plan.seg, walkLeg2.coords);
          setRouteLegend({ color: rideColor, title: `${routeLabel}: ${route.nombre}` });

          if (stepsContainer) {
            stepsContainer.innerHTML = `
              <div class="route-steps-timeline">
                <article class="route-step-item route-step-item--walk">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title">Camina al ${route.tipo === 'metro' ? 'acceso de estación' : 'punto de abordaje'}</div>
                      <span class="route-step-pill">${walkMins(walkLeg1.distance)}m</span>
                    </div>
                    <div class="route-step-sub">${Math.round(walkLeg1.distance)} metros</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--ride" style="--step-color:${rideColor};">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title"><i class="fas ${routeIconClass} me-1"></i> Toma ${route.nombre}</div>
                      <span class="route-step-pill">${rideMins(plan.rideMeters, route.tipo)}m</span>
                    </div>
                    <div class="route-step-sub">Recorrido aproximado: ${(plan.rideMeters / 1000).toFixed(1)} km</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--walk">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title">Camina a tu destino</div>
                      <span class="route-step-pill">${walkMins(walkLeg2.distance)}m</span>
                    </div>
                    <div class="route-step-sub">${Math.round(walkLeg2.distance)} metros</div>
                  </div>
                </article>
              </div>
            `;
          }

          summaryText = `${routeLabel}: ${route.nombre}`;
          setTripLaunchState({
            mode: 'transit',
            destinationLabel: (destInput?.value || '').trim(),
            destinationPoint: Array.isArray(destPoint) ? [...destPoint] : null,
            originPoint: Array.isArray(startPoint) ? [...startPoint] : null,
            distanceMeters: Number(walkLeg1.distance || 0) + Number(plan.rideMeters || 0) + Number(walkLeg2.distance || 0),
            etaMinutes: walkMins(walkLeg1.distance) + rideMins(plan.rideMeters, route.tipo) + walkMins(walkLeg2.distance),
            summaryText,
            safetyScore: null
          });
        } else {
          const colorA = routeStrokeColor(plan.routeA);
          const colorB = routeStrokeColor(plan.routeB);
          const walkLeg1 = await fetchWalkLegPath(startPoint, plan.segA[0]);
          const walkLegTransfer = await fetchWalkLegPath(plan.xfer.aPoint, plan.xfer.bPoint);
          const walkLegEnd = await fetchWalkLegPath(plan.segB[plan.segB.length - 1], destPoint);

          const polyWalk1 = L.polyline(walkLeg1.coords, { color: walkColor, weight: 4, dashArray: '6 6', opacity: 0.85 }).addTo(m);
          const polyA = L.polyline(plan.segA, { color: colorA, weight: 7, opacity: 0.95 }).addTo(m);
          const polyTransfer = L.polyline(walkLegTransfer.coords, { color: '#f59e0b', weight: 4, dashArray: '4 6', opacity: 0.9 }).addTo(m);
          const polyB = L.polyline(plan.segB, { color: colorB, weight: 7, opacity: 0.95 }).addTo(m);
          const polyWalkEnd = L.polyline(walkLegEnd.coords, { color: walkColor, weight: 4, dashArray: '6 6', opacity: 0.85 }).addTo(m);
          transitLayers.push(polyWalk1, polyA, polyTransfer, polyB, polyWalkEnd);

          const boardM = L.circleMarker(plan.segA[0], { radius: 6, color: colorA, fillColor: '#fff', weight: 2 }).addTo(m);
          const xA = L.circleMarker(plan.xfer.aPoint, { radius: 6, color: colorA, fillColor: '#fff', weight: 2 }).addTo(m);
          const xB = L.circleMarker(plan.xfer.bPoint, { radius: 6, color: colorB, fillColor: '#fff', weight: 2 }).addTo(m);
          const alightM = L.circleMarker(plan.segB[plan.segB.length - 1], { radius: 6, color: colorB, fillColor: '#fff', weight: 2 }).addTo(m);
          transitLayers.push(boardM, xA, xB, alightM);

          allPoints = allPoints.concat(walkLeg1.coords, plan.segA, walkLegTransfer.coords, plan.segB, walkLegEnd.coords);
          setRouteLegend({
            color: colorA,
            title: `Metro: ${plan.routeA.nombre}`,
            subtitle: `Transbordo a ${plan.routeB.nombre}`
          });

          if (stepsContainer) {
            stepsContainer.innerHTML = `
              <div class="route-steps-timeline">
                <article class="route-step-item route-step-item--walk">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title">Camina a la estación</div>
                      <span class="route-step-pill">${walkMins(walkLeg1.distance)}m</span>
                    </div>
                    <div class="route-step-sub">${Math.round(walkLeg1.distance)} metros</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--ride" style="--step-color:${colorA};">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title"><i class="fas fa-train-subway me-1"></i> Toma ${plan.routeA.nombre}</div>
                      <span class="route-step-pill">${rideMins(plan.rideA, 'metro')}m</span>
                    </div>
                    <div class="route-step-sub">Recorrido aproximado: ${(plan.rideA / 1000).toFixed(1)} km</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--transfer">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title"><i class="fas fa-right-left me-1"></i> Haz transbordo</div>
                      <span class="route-step-pill">${walkMins(walkLegTransfer.distance)}m</span>
                    </div>
                    <div class="route-step-sub">${Math.round(walkLegTransfer.distance)} metros entre andenes/estaciones</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--ride" style="--step-color:${colorB};">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title"><i class="fas fa-train-subway me-1"></i> Continúa por ${plan.routeB.nombre}</div>
                      <span class="route-step-pill">${rideMins(plan.rideB, 'metro')}m</span>
                    </div>
                    <div class="route-step-sub">Recorrido aproximado: ${(plan.rideB / 1000).toFixed(1)} km</div>
                  </div>
                </article>
                <article class="route-step-item route-step-item--walk">
                  <div class="route-step-marker"></div>
                  <div class="route-step-card">
                    <div class="route-step-head">
                      <div class="route-step-title">Camina a tu destino</div>
                      <span class="route-step-pill">${walkMins(walkLegEnd.distance)}m</span>
                    </div>
                    <div class="route-step-sub">${Math.round(walkLegEnd.distance)} metros</div>
                  </div>
                </article>
              </div>
            `;
          }

          summaryText = `Metro con transbordo: ${plan.routeA.nombre} → ${plan.routeB.nombre}`;
          setTripLaunchState({
            mode: 'transit',
            destinationLabel: (destInput?.value || '').trim(),
            destinationPoint: Array.isArray(destPoint) ? [...destPoint] : null,
            originPoint: Array.isArray(startPoint) ? [...startPoint] : null,
            distanceMeters: Number(walkLeg1.distance || 0) + Number(plan.rideA || 0) + Number(walkLegTransfer.distance || 0) + Number(plan.rideB || 0) + Number(walkLegEnd.distance || 0),
            etaMinutes: walkMins(walkLeg1.distance) + rideMins(plan.rideA, 'metro') + walkMins(walkLegTransfer.distance) + rideMins(plan.rideB, 'metro') + walkMins(walkLegEnd.distance),
            summaryText,
            safetyScore: null
          });
        }

        transitLayers.forEach(layer => animateLeafletLayerIn(layer, 320));

        if (allPoints.length > 1) {
          m.fitBounds(allPoints, { padding: [50, 50] });
        }

        const transitSafety = await evaluateRouteSafety(allPoints, { updateUI: true });
        lastHazText = transitSafety?.hint || '';
        if (lastPlannedTrip) {
          lastPlannedTrip.safetyScore = transitSafety?.score ?? null;
        }

        if (instructionsPanel) instructionsPanel.style.display = 'block';
        if (alertBox) {
          alertBox.style.background = 'rgba(16, 185, 129, 0.14)';
          alertBox.style.color = '#065f46';
          alertBox.innerHTML = `<i class="fas fa-circle-check me-1"></i> Ruta encontrada: ${summaryText}` +
            (transitSafety ? `<br><span class="small">Safety ${transitSafety.score}/100 (${classifySafety(transitSafety.score).label}) · ${transitSafety.hint}</span>` : '');
        }
        updateRouteFeedbackVisibility();
      } catch (e) {
        console.error('Transit routing error:', e);
        clearRouteLegend();
        setSafetyScoreUI(null);
        setTripLaunchState(null);
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.14)';
          alertBox.style.color = '#991b1b';
          alertBox.innerHTML = `<i class="fas fa-triangle-exclamation me-1"></i> ${e.message || 'No se pudo calcular la ruta de transporte.'}`;
        }
        updateRouteFeedbackVisibility();
      }
    }

    // Transit button listener
    if (transitBtn) {
      transitBtn.addEventListener('click', () => {
        console.log('Transit Button Clicked (Event Fired)');
        setSheetExpanded(true);
        drawRouteTransit();
      });
    } else {
      console.error('Transit Button not found in DOM');
    }

    // Expose for debugging in console
    window.drawRouteTransit = drawRouteTransit;

    // Actualiza el mensaje de ruta si cambia la velocidad en modo automático
    function updateRouteAlert() {
      const alertBox = document.getElementById('routeAlert');
      if (!alertBox || lastRouteMeters == null) return;
      function fmtTime(s) { const min = Math.round(s / 60); if (min < 60) return `${min} min`; const h = Math.floor(min / 60), m = min % 60; return `${h} h ${m} min`; }
      function fmtKm(m) { if (m < 1000) return Math.round(m) + ' m'; const v = m / 1000; return (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + ' km'; }
      const mps = liveSpeedMps || 1.33;
      const secs = lastRouteMeters > 0 ? lastRouteMeters / mps : 0;
      const msg = `Ruta peatonal: ${fmtKm(lastRouteMeters)} · ${fmtTime(secs)}` + (lastHazText ? ` · ${lastHazText}` : '');
      alertBox.style.display = 'block';
      alertBox.innerHTML = msg;
      updateRouteFeedbackVisibility();
    }
  })();
