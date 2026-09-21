// Configuración para JS
    // Public beta notice shown only on the home feed.
    (function () {
        const modal = document.getElementById('betaPublicModal');
        if (!modal) return;
        if (document.body.classList.contains('has-limited-access-popup')) return;

        const rawKey = modal.dataset.betaKey || 'Beta v1.1';
        const storageKey = `violeta.betaPublicModal.dismissed.${rawKey}`;
        const dismissButtons = modal.querySelectorAll('[data-beta-public-dismiss]');
        const learnMoreLink = modal.querySelector('.beta-public-modal__link');
        let storageAvailable = true;

        function isDismissed() {
            if (!storageAvailable) return false;
            try {
                return window.localStorage.getItem(storageKey) === '1';
            } catch (error) {
                storageAvailable = false;
                return false;
            }
        }

        function rememberDismissal() {
            if (!storageAvailable) return;
            try {
                window.localStorage.setItem(storageKey, '1');
            } catch (error) {
                storageAvailable = false;
            }
        }

        function openModal() {
            modal.classList.remove('is-hidden');
            modal.setAttribute('aria-hidden', 'false');
            document.body.classList.add('has-beta-public-modal');
            const closeButton = modal.querySelector('.beta-public-modal__close');
            if (closeButton) closeButton.focus({ preventScroll: true });
        }

        function closeModal() {
            rememberDismissal();
            modal.classList.add('is-hidden');
            modal.setAttribute('aria-hidden', 'true');
            document.body.classList.remove('has-beta-public-modal');
        }

        dismissButtons.forEach((button) => {
            button.addEventListener('click', closeModal);
        });
        if (learnMoreLink) {
            learnMoreLink.addEventListener('click', rememberDismissal);
        }

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !modal.classList.contains('is-hidden')) {
                closeModal();
            }
        });

        if (!isDismissed()) {
            window.requestAnimationFrame(openModal);
        }
    })();

    // Mini Map Initialization
    (function () {
        const mapEl = document.getElementById('miniMap');
        const loadingEl = document.getElementById('miniMapLoading');
        const countEl = document.getElementById('nearbyCount');
        if (!mapEl) return;

        const defaultLat = 25.6866, defaultLng = -100.3161;

        function init(lat, lng, currentLocation = true) {
            const map = L.map('miniMap', {
                zoomControl: false, dragging: false, scrollWheelZoom: false,
                doubleClickZoom: false, touchZoom: false
            }).setView([lat, lng], 14);

            L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
                attribution: '© OSM'
            }).addTo(map);

            // User marker
            if (currentLocation) L.marker([lat, lng], {
                icon: L.divIcon({
                    html: '<div class="mini-map-marker mini-map-marker--user"></div>',
                    className: 'mini-map-marker-host',
                    iconSize: [18, 18],
                    iconAnchor: [9, 9]
                })
            }).addTo(map);
            if (!currentLocation) {
                const locationLabel = document.querySelector('.mini-map-widget__current');
                if (locationLabel) locationLabel.textContent = 'Vista de Monterrey';
            }

            // Fetch hotspots already filtered near the current location.
            fetch(`/api/hotspots?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}&radius_km=8&limit=30`).then(r => r.json()).then(data => {
                let count = 0;
                (data.hotspots || []).forEach(h => {
                    // Distancia aproximada (km) para radios cortos.
                    const dx = (h.lng - lng) * Math.cos(((h.lat + lat) / 2) * Math.PI / 180) * 111.32;
                    const dy = (h.lat - lat) * 110.57;
                    const d = Math.sqrt(dx * dx + dy * dy);
                    const hotspotCount = h.count || 1;
                    const distanceClass = d <= 0.5 ? 'near' : d < 1 ? 'medium' : 'far';
                    const sizeClass = hotspotCount >= 6 ? 'large' : hotspotCount >= 3 ? 'regular' : 'small';
                    const markerSize = sizeClass === 'large' ? 14 : sizeClass === 'regular' ? 11 : 8;
                    count += hotspotCount;

                    L.marker([h.lat, h.lng], {
                        icon: L.divIcon({
                            html: `<div class="mini-map-marker mini-map-marker--hotspot mini-map-marker--${distanceClass} mini-map-marker--${sizeClass}"></div>`,
                            className: 'mini-map-marker-host',
                            iconSize: [markerSize, markerSize],
                            iconAnchor: [markerSize / 2, markerSize / 2]
                        })
                    }).addTo(map);
                });
                if (countEl) countEl.textContent = count;
            }).catch(e => console.warn('Mini map hotspots unavailable:', e));

            if (loadingEl) loadingEl.hidden = true;
            mapEl.onclick = () => window.location.href = (window.INDEX_PAGE_CONFIG && window.INDEX_PAGE_CONFIG.hotspotsUrl) || '/hotspots';
        }

        // Request user's CURRENT location with high accuracy
        if (navigator.geolocation) {
            // Show "Buscando ubicación..." while getting location
            const loadingText = document.querySelector('#miniMapLoading .mini-map-widget__loading-copy');
            if (loadingText) {
                loadingText.innerHTML = '<i class="fas fa-location-arrow fa-spin mini-map-widget__loading-icon" aria-hidden="true"></i><div class="mini-map-widget__loading-text">Obteniendo tu ubicación...</div>';
            }

            navigator.geolocation.getCurrentPosition(
                function (position) {
                    // SUCCESS: Center map on USER's actual location
                    init(position.coords.latitude, position.coords.longitude);
                },
                function (error) {
                    // ERROR: Fall back to Monterrey center
                    console.warn('Geolocation error:', error.message);
                    init(defaultLat, defaultLng, false);
                },
                {
                    enableHighAccuracy: true,  // Request GPS accuracy
                    timeout: 10000,            // Wait up to 10 seconds
                    maximumAge: 0              // Don't use cached location
                }
            );
        } else {
            init(defaultLat, defaultLng, false);
        }
    })();

    // Weather widget
    (function () {
        const tempEl = document.getElementById('weatherTemp');
        const minEl = document.getElementById('weatherMin');
        const maxEl = document.getElementById('weatherMax');
        const statusEl = document.getElementById('weatherStatus');
        const metaEl = document.getElementById('weatherMeta');

        if (!tempEl || !minEl || !maxEl || !statusEl) return;

        function setFallback(message) {
            statusEl.textContent = message || 'Clima no disponible';
        }

        function mapWeatherCode(code) {
            const map = {
                0: 'Despejado',
                1: 'Mayormente despejado',
                2: 'Parcialmente nublado',
                3: 'Nublado',
                45: 'Niebla',
                48: 'Niebla',
                51: 'Llovizna',
                53: 'Llovizna',
                55: 'Llovizna',
                61: 'Lluvia ligera',
                63: 'Lluvia',
                65: 'Lluvia fuerte',
                71: 'Nieve ligera',
                73: 'Nieve',
                75: 'Nieve fuerte',
                80: 'Chubascos',
                81: 'Chubascos',
                82: 'Chubascos fuertes',
                95: 'Tormenta',
                96: 'Tormenta',
                99: 'Tormenta'
            };
            return map[code] || 'Clima';
        }

        function fetchWeather(lat, lng) {
            const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min&timezone=auto`;
            fetch(url)
                .then(r => r.json())
                .then(data => {
                    const current = data.current || {};
                    const daily = data.daily || {};
                    const temp = Math.round(current.temperature_2m ?? 0);
                    const min = Math.round((daily.temperature_2m_min || [])[0] ?? 0);
                    const max = Math.round((daily.temperature_2m_max || [])[0] ?? 0);
                    tempEl.textContent = `${temp}°`;
                    minEl.textContent = `L:${min}°`;
                    maxEl.textContent = `H:${max}°`;
                    const label = mapWeatherCode(current.weather_code);
                    statusEl.textContent = label;
                    if (metaEl) metaEl.textContent = 'Actualizado hace un momento';

                    const iconEl = document.getElementById('weatherIcon');
                    if (iconEl) {
                        const isDay = current.is_day === 1;
                        let icon = 'fa-cloud';
                        if ([0].includes(current.weather_code)) icon = isDay ? 'fa-sun' : 'fa-moon';
                        if ([1, 2].includes(current.weather_code)) icon = isDay ? 'fa-cloud-sun' : 'fa-cloud-moon';
                        if ([3].includes(current.weather_code)) icon = 'fa-cloud';
                        if ([45, 48].includes(current.weather_code)) icon = 'fa-smog';
                        if ([51, 53, 55].includes(current.weather_code)) icon = 'fa-cloud-rain';
                        if ([61, 63, 65, 80, 81, 82].includes(current.weather_code)) icon = 'fa-cloud-showers-heavy';
                        if ([71, 73, 75].includes(current.weather_code)) icon = 'fa-snowflake';
                        if ([95, 96, 99].includes(current.weather_code)) icon = 'fa-bolt';
                        iconEl.className = `fas ${icon}`;
                    }
                })
                .catch(() => setFallback('Clima no disponible'));
        }

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                pos => {
                    const { latitude, longitude } = pos.coords;
                    fetchWeather(latitude, longitude);
                },
                () => setFallback('Activa tu ubicación para el clima'),
                { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
            );
        } else {
            setFallback('Navegador sin ubicación');
        }
    })();

    // Page transition for smoother navigation
    (function () {
        const layout = document.getElementById('feedLayout');
        if (!layout) return;

        // Enter animation
        requestAnimationFrame(() => {
            layout.classList.remove('page-enter');
        });

        window.__smoothNavigate = function (url) {
            window.location.href = url;
        };
    })();

    // Compact explore header while scrolling.
    (function () {
        const header = document.querySelector('.violeta-header');
        if (!header) return;

        let ticking = false;

        function syncHeaderState() {
            ticking = false;
            header.classList.toggle('header-scrolled', window.scrollY > 50);
        }

        window.addEventListener('scroll', () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(syncHeaderState);
        }, { passive: true });

        syncHeaderState();
    })();

    // Advanced feed filters
    (function () {
        const modal = document.getElementById('advancedModal');
        const openBtn = document.getElementById('openAdvancedFilters');
        const closeBtn = document.getElementById('closeModal');
        const applyBtn = document.getElementById('applyFilters');
        const resetBtn = document.getElementById('resetFilters');
        if (!modal || !openBtn || !closeBtn || !applyBtn || !resetBtn) return;

        const optionCards = modal.querySelectorAll('.v-option-card');

        function openModal() {
            modal.classList.add('active');
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeModal() {
            modal.classList.remove('active');
            modal.setAttribute('aria-hidden', 'true');
        }

        function setApplyLoading(isLoading) {
            applyBtn.disabled = Boolean(isLoading);
            applyBtn.innerHTML = isLoading
                ? '<i class="fas fa-circle-notch fa-spin"></i> Aplicando...'
                : 'Aplicar Filtros';
        }

        function goWithFilters(latLng) {
            const url = new URL(window.location.href);
            const selectedCategories = Array.from(modal.querySelectorAll('.v-option-card.active[data-filter="category"]'))
                .map(card => card.dataset.val)
                .filter(Boolean);
            const nearActive = Boolean(modal.querySelector('.v-option-card.active[data-filter="near"]'));
            const todayActive = Boolean(modal.querySelector('.v-option-card.active[data-filter="today"]'));

            if (selectedCategories.length) {
                url.searchParams.set('categories', selectedCategories.join(','));
            } else {
                url.searchParams.delete('categories');
                url.searchParams.delete('category');
            }

            if (todayActive) {
                url.searchParams.set('today', '1');
            } else {
                url.searchParams.delete('today');
            }

            if (nearActive && latLng) {
                url.searchParams.set('near', '1');
                url.searchParams.set('lat', String(latLng.lat));
                url.searchParams.set('lng', String(latLng.lng));
            } else if (!nearActive) {
                url.searchParams.delete('near');
                url.searchParams.delete('lat');
                url.searchParams.delete('lng');
            }

            url.searchParams.delete('page');
            const nav = window.__smoothNavigate || function (u) { window.location.href = u; };
            nav(url.toString());
        }

        openBtn.addEventListener('click', openModal);
        closeBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (event) => {
            if (event.target === modal) closeModal();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && modal.classList.contains('active')) closeModal();
        });

        optionCards.forEach(card => {
            card.addEventListener('click', () => {
                card.classList.toggle('active');
            });
        });

        resetBtn.addEventListener('click', () => {
            optionCards.forEach(card => card.classList.remove('active'));
        });

        applyBtn.addEventListener('click', () => {
            const nearActive = Boolean(modal.querySelector('.v-option-card.active[data-filter="near"]'));
            setApplyLoading(true);
            if (!nearActive) {
                goWithFilters(null);
                return;
            }
            if (!navigator.geolocation) {
                setApplyLoading(false);
                window.alert('Tu navegador no permite obtener tu ubicación para filtrar por mi zona.');
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    goWithFilters({
                        lat: Number(position.coords.latitude).toFixed(6),
                        lng: Number(position.coords.longitude).toFixed(6)
                    });
                },
                () => {
                    setApplyLoading(false);
                    window.alert('No pudimos obtener tu ubicación. Activa permisos para usar "Por mi zona".');
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
            );
        });
    })();

    // City Filter
    (function () {
        const chips = document.querySelectorAll('.violeta-chip[data-city]');
        if (!chips.length) return;
        const urlCity = (new URLSearchParams(window.location.search).get('city') || '').toLowerCase();
        const currentCity = urlCity || ((window.INDEX_PAGE_CONFIG && window.INDEX_PAGE_CONFIG.selectedCity) || 'all');

        chips.forEach(c => c.classList.toggle('active', c.dataset.city === currentCity));

        function goToCity(city, btn) {
            chips.forEach(c => c.classList.toggle('active', c === btn || c.dataset.city === city));
            const url = new URL(window.location.href);
            if (city === 'all') {
                url.searchParams.delete('city');
            } else {
                url.searchParams.set('city', city);
            }
            url.searchParams.delete('page'); // Reinicia a la primera página al cambiar de ciudad
            const nav = window.__smoothNavigate || function (u) { window.location.href = u; };
            nav(url.toString());
        }

        chips.forEach(c => c.addEventListener('click', () => {
            goToCity(c.dataset.city, c);
        }));
    })();

    (function () {
        const postsContainer = document.getElementById('posts-container');
        const loading = document.getElementById('loading');
        const sentinel = document.getElementById('feedScrollSentinel');
        if (!postsContainer || !loading || !sentinel) return;

        let currentPage = Number(postsContainer.dataset.feedPage || '1');
        let hasNext = postsContainer.dataset.feedHasNext === 'true';
        const selectedCity = postsContainer.dataset.feedCity || 'all';
        let isLoading = false;

        function syncSentinel() {
            sentinel.hidden = !hasNext;
        }

        async function loadMorePosts() {
            if (isLoading || !hasNext) return;
            isLoading = true;
            loading.style.display = 'block';

            try {
                const nextPage = currentPage + 1;
                const url = new URL('/feed', window.location.origin);
                const currentParams = new URLSearchParams(window.location.search);
                currentParams.forEach((value, key) => url.searchParams.set(key, value));
                url.searchParams.set('page', String(nextPage));
                if (!url.searchParams.get('city')) {
                    url.searchParams.set('city', selectedCity);
                }
                const response = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
                if (!response.ok) {
                    throw new Error('feed-load-failed');
                }

                const payload = await response.json();
                const html = (payload && payload.html) || '';
                const trimmedHtml = html.trim();
                currentPage = Number(payload?.page || nextPage);
                hasNext = Boolean(payload?.has_next);

                if (trimmedHtml) {
                    const fragment = document.createRange().createContextualFragment(trimmedHtml);
                    postsContainer.appendChild(fragment);
                }
            } catch (error) {
                console.error('No se pudieron cargar más publicaciones.', error);
            } finally {
                isLoading = false;
                loading.style.display = 'none';
                postsContainer.dataset.feedPage = String(currentPage);
                postsContainer.dataset.feedHasNext = hasNext ? 'true' : 'false';
                syncSentinel();
            }
        }

        syncSentinel();

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    loadMorePosts();
                }
            });
        }, {
            rootMargin: '240px 0px'
        });

        observer.observe(sentinel);
    })();

    // Reportes generados: toggle "por categoria" <-> "hoy"
    (function () {
        const btn = document.getElementById('reportsToggleBtn');
        const icon = document.getElementById('reportsToggleIcon');
        const title = document.getElementById('reportsWidgetTitle');
        const byCategory = document.getElementById('reportsByCategory');
        const today = document.getElementById('reportsToday');
        const byCategoryList = document.getElementById('reportsByCategoryList');
        const todayList = document.getElementById('reportsTodayList');
        const postsContainer = document.getElementById('posts-container');
        if (!btn || !icon || !title || !byCategory || !today || !byCategoryList || !todayList) return;

        let mode = 'category';
        let todayEmptyState = document.getElementById('feedTodayEmptyState');
        const widgetCard = btn.closest('.trends-widget');
        const cardAnimationTimers = new WeakMap();
        const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        function restartAnimation(element, className, duration = 420) {
            if (!element || prefersReducedMotion) return;
            element.classList.remove(className);
            void element.offsetWidth;
            element.classList.add(className);
            window.setTimeout(() => element.classList.remove(className), duration);
        }

        function animateModeChange(activePanel) {
            restartAnimation(btn, 'is-toggling', 520);
            restartAnimation(widgetCard, 'is-filtering-reports', 520);
            restartAnimation(activePanel, 'reports-panel-enter', 360);
        }

        function clearCardAnimation(card) {
            const timer = cardAnimationTimers.get(card);
            if (timer) {
                window.clearTimeout(timer);
                cardAnimationTimers.delete(card);
            }
        }

        function showCard(card, animate) {
            clearCardAnimation(card);
            card.classList.remove('report-filter-exit', 'd-none');
            if (animate) {
                restartAnimation(card, 'report-filter-enter', 460);
            } else {
                card.classList.remove('report-filter-enter');
            }
        }

        function hideCard(card, animate) {
            clearCardAnimation(card);
            card.classList.remove('report-filter-enter');
            if (!animate || card.classList.contains('d-none') || prefersReducedMotion) {
                card.classList.add('d-none');
                card.classList.remove('report-filter-exit');
                return;
            }

            card.classList.add('report-filter-exit');
            const timer = window.setTimeout(() => {
                card.classList.add('d-none');
                card.classList.remove('report-filter-exit');
                cardAnimationTimers.delete(card);
            }, 240);
            cardAnimationTimers.set(card, timer);
        }

        function renderList(listEl, items, emptyTitle, emptyText) {
            if (!listEl) return;
            if (!Array.isArray(items) || items.length === 0) {
                listEl.innerHTML = `
                    <li>
                        <div class="trend-info">
                            <h4 class="trend-title">${emptyTitle}</h4>
                            <span class="trend-stats">${emptyText}</span>
                        </div>
                    </li>
                `;
                return;
            }
            const categoryStyles = {
                'Alumbrado deficiente': ['lighting', 'fa-lightbulb'],
                'Poca iluminación': ['lighting', 'fa-lightbulb'],
                'Terrenos baldíos': ['vacant', 'fa-tree'],
                'Zona insegura': ['unsafe', 'fa-triangle-exclamation'],
                'Banquetas en mal estado': ['sidewalk', 'fa-shoe-prints']
            };
            listEl.innerHTML = items.map((item) => {
                const [tone, icon] = categoryStyles[item.category] || ['other', 'fa-location-dot'];
                return `
                <li>
                    <div class="trend-info">
                        <h4 class="trend-title activity-name--${tone}"><i class="fas ${icon}" aria-hidden="true"></i>${escapeHtml(item.category || 'Sin categoría')}</h4>
                        <span class="trend-stats activity-count" aria-label="${Number(item.count || 0)} reportes">${Number(item.count || 0)}</span>
                    </div>
                </li>
            `;
            }).join('');
        }

        function loadSidebarSummary() {
            const selectedCity = (window.INDEX_PAGE_CONFIG && window.INDEX_PAGE_CONFIG.selectedCity) || 'all';
            const url = `/api/feed/sidebar-summary?city=${encodeURIComponent(selectedCity)}`;
            fetch(url, { headers: { Accept: 'application/json' } })
                .then((response) => response.ok ? response.json() : Promise.reject(new Error('sidebar-summary')))
                .then((data) => {
                    renderList(byCategoryList, data.report_counts || [], 'Sin reportes', 'Aún no hay reportes generados.');
                    renderList(todayList, data.report_counts_today || [], 'Hoy', 'Aún no se han generado reportes el día de hoy');
                })
                .catch(() => {
                    renderList(byCategoryList, [], 'Sin reportes', 'No se pudo cargar el resumen.');
                    renderList(todayList, [], 'Hoy', 'No se pudo cargar el resumen.');
                });
        }

        function getLocalTodayYmd() {
            const now = new Date();
            const y = now.getFullYear();
            const m = String(now.getMonth() + 1).padStart(2, '0');
            const d = String(now.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        }

        function ensureTodayEmptyState() {
            if (todayEmptyState || !postsContainer || !postsContainer.parentElement) return;
            const block = document.createElement('div');
            block.id = 'feedTodayEmptyState';
            block.className = 'no-posts-message';
            block.style.cssText = 'display:none; text-align:center; padding: 28px 20px; color: var(--text-muted);';
            block.innerHTML = `
                <i class="fas fa-calendar-day" style="font-size: 2.2rem; margin-bottom: 12px; opacity: 0.55;"></i>
                <h3 style="margin-bottom:8px;">Sin publicaciones de hoy</h3>
                <p style="margin:0;">No se han publicado reportes en el feed el día de hoy.</p>
            `;
            postsContainer.insertAdjacentElement('afterend', block);
            todayEmptyState = block;
        }

        function applyFeedTodayFilter(onlyToday, { animate = false } = {}) {
            if (!postsContainer) return;
            ensureTodayEmptyState();

            const cards = postsContainer.querySelectorAll('.post-card[data-post-id]');
            const todayYmd = getLocalTodayYmd();
            let visibleCount = 0;

            cards.forEach(card => {
                if (!onlyToday) {
                    showCard(card, animate);
                    visibleCount += 1;
                    return;
                }
                const postYmd = (card.dataset.postDate || '').trim();
                const shouldShow = postYmd === todayYmd;
                if (shouldShow) {
                    showCard(card, animate);
                    visibleCount += 1;
                } else {
                    hideCard(card, animate);
                }
            });

            if (todayEmptyState) {
                todayEmptyState.style.display = onlyToday && cards.length > 0 && visibleCount === 0 ? 'block' : 'none';
                if (onlyToday && cards.length > 0 && visibleCount === 0 && animate) {
                    restartAnimation(todayEmptyState, 'report-filter-enter', 460);
                }
            }
        }

        const setMode = (nextMode, { animate = false } = {}) => {
            mode = nextMode;
            const isToday = mode === 'today';
            byCategory.style.display = isToday ? 'none' : 'block';
            today.style.display = isToday ? 'block' : 'none';
            title.textContent = isToday ? 'Reportes de hoy' : 'Actividad en tu comunidad';
            btn.setAttribute('aria-pressed', isToday ? 'true' : 'false');
            btn.title = isToday ? 'Ver por categoria' : 'Ver reportes de hoy';
            btn.setAttribute('aria-label', btn.title);
            const toggleLabel = document.getElementById('reportsToggleLabel');
            if (toggleLabel) toggleLabel.textContent = btn.title;
            icon.className = isToday ? 'fa-solid fa-list' : 'fa-solid fa-calendar-day';
            if (animate) {
                animateModeChange(isToday ? today : byCategory);
            }
            applyFeedTodayFilter(isToday, { animate });
        };

        btn.addEventListener('click', () => {
            setMode(mode === 'category' ? 'today' : 'category', { animate: true });
        });

        if (typeof window.requestIdleCallback === 'function') {
            window.requestIdleCallback(loadSidebarSummary, { timeout: 700 });
        } else {
            window.setTimeout(loadSidebarSummary, 120);
        }

        if (postsContainer) {
            const observer = new MutationObserver(() => {
                if (mode === 'today') {
                    applyFeedTodayFilter(true);
                }
            });
            observer.observe(postsContainer, { childList: true });
        }
    })();

    // Sidebar derecha: follow-scroll con limite al ultimo widget
    (function () {
        const sidebar = document.querySelector('.sidebar-right');
        const feedColumn = document.querySelector('.feed-column');
        if (!sidebar || !feedColumn) return;

        let rafId = null;
        const desktopQuery = window.matchMedia('(min-width: 1024px)');

        function requestSync() {
            if (rafId !== null) return;
            rafId = window.requestAnimationFrame(syncSidebarScroll);
        }

        function syncSidebarScroll() {
            rafId = null;

            if (!desktopQuery.matches) {
                sidebar.scrollTop = 0;
                return;
            }

            const maxInternalScroll = Math.max(0, sidebar.scrollHeight - sidebar.clientHeight);
            if (maxInternalScroll <= 0) {
                sidebar.scrollTop = 0;
                return;
            }

            const feedRect = feedColumn.getBoundingClientRect();
            const feedTop = feedRect.top + window.scrollY;
            const feedBottom = feedTop + feedColumn.offsetHeight;
            const scrollRange = Math.max(1, feedBottom - feedTop - window.innerHeight);
            const progress = Math.min(1, Math.max(0, (window.scrollY - feedTop) / scrollRange));

            sidebar.scrollTop = maxInternalScroll * progress;
        }

        window.addEventListener('scroll', requestSync, { passive: true });
        window.addEventListener('resize', requestSync);
        if (desktopQuery.addEventListener) {
            desktopQuery.addEventListener('change', requestSync);
        }

        requestSync();
    })();
