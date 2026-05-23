(function () {
    const currentUser = window.CURRENT_USER || {};
    if (!currentUser.is_authenticated || currentUser.can_override_content_controls) {
        return;
    }

    const policy = window.VIOLETA_SAFETY_PUBLISH_POLICY || {
        min_delay_minutes: 15,
        distance_meters: 200,
        fallback_minutes: 60
    };
    const nativeBridge = window.VioletaNativeBridge || null;

    let nextTimer = null;
    let requestInFlight = false;
    let geolocationCooldownUntil = 0;
    let lastKnownPendingCount = null;
    let overlayTicker = null;

    function scheduleNext(ms) {
        if (nextTimer) {
            window.clearTimeout(nextTimer);
        }
        nextTimer = window.setTimeout(runCycle, Math.max(5000, ms || 60000));
    }

    function formatDuration(ms) {
        const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    function updatePendingOverlays() {
        const overlays = document.querySelectorAll('[data-pending-post]');
        const now = Date.now();
        overlays.forEach((overlay) => {
            const minReadyAtRaw = overlay.getAttribute('data-min-ready-at') || '';
            const fallbackAtRaw = overlay.getAttribute('data-fallback-at') || '';
            const minReadyAt = minReadyAtRaw ? Date.parse(minReadyAtRaw) : NaN;
            const fallbackAt = fallbackAtRaw ? Date.parse(fallbackAtRaw) : NaN;
            const statusEl = overlay.querySelector('.grid-pending-overlay__status');
            const metaEl = overlay.querySelector('.grid-pending-overlay__meta');
            if (!statusEl || !metaEl) {
                return;
            }

            if (Number.isFinite(minReadyAt) && now < minReadyAt) {
                statusEl.textContent = `Faltan ${formatDuration(minReadyAt - now)} para activar la regla de salida`;
                metaEl.textContent = `Después se publicará al alejarte ${policy.distance_meters} m`;
                return;
            }

            if (Number.isFinite(fallbackAt) && now < fallbackAt) {
                statusEl.textContent = `Ya pasaron ${policy.min_delay_minutes} min. Falta alejarte ${policy.distance_meters} m`;
                metaEl.textContent = `Si no, se publicará en máximo ${formatDuration(fallbackAt - now)}`;
                return;
            }

            statusEl.textContent = 'Lista para publicarse';
            metaEl.textContent = 'Estamos liberando tu reporte...';
        });
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error('No se pudo completar la operación.');
        }
        return response.json();
    }

    function getCurrentLocation() {
        if (nativeBridge && typeof nativeBridge.getCurrentPosition === 'function') {
            return nativeBridge.getCurrentPosition({
                enableHighAccuracy: true,
                timeout: 12000,
                maximumAge: 30000,
            });
        }
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error('Geolocalizacion no disponible.'));
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    resolve({
                        lat: position.coords.latitude,
                        lng: position.coords.longitude,
                    });
                },
                (error) => reject(error),
                {
                    enableHighAccuracy: true,
                    timeout: 12000,
                    maximumAge: 30000,
                }
            );
        });
    }

    function shouldReloadForCurrentPage() {
        const path = window.location.pathname || '';
        return path === '/' || path === '/profile' || path === `/user/${encodeURIComponent(currentUser.username)}`;
    }

    async function postReleaseCheck(payload) {
        const data = await fetchJson('/api/posts/pending-safety/release', {
            method: 'POST',
            headers: buildHeaders('application/json'),
            body: JSON.stringify(payload || {}),
        });

        if (typeof data.pending_count === 'number') {
            lastKnownPendingCount = data.pending_count;
        }

        if (data.released_count > 0) {
            const msg = data.released_count === 1
                ? 'Tu reporte ya se hizo visible.'
                : `${data.released_count} reportes ya se hicieron visibles.`;
            if (typeof showVioletNotification === 'function') {
                showVioletNotification(msg, 'success', 7000);
            } else if (typeof showAlert === 'function') {
                showAlert(msg, 'success');
            }
            if (shouldReloadForCurrentPage()) {
                window.setTimeout(() => window.location.reload(), 1200);
                return;
            }
        }

        if (typeof data.next_check_in_sec === 'number') {
            scheduleNext(Math.min(data.next_check_in_sec * 1000, 120000));
            return;
        }

        scheduleNext(data.pending_count > 0 ? 60000 : 300000);
    }

    async function runCycle(force) {
        if (requestInFlight || document.hidden) {
            return;
        }
        requestInFlight = true;

        try {
            const status = await fetchJson('/api/posts/pending-safety/status', {
                headers: buildHeaders(),
            });

            if (typeof status.pending_count === 'number') {
                lastKnownPendingCount = status.pending_count;
            }

            if (!status.pending_count) {
                scheduleNext(force ? 30000 : 300000);
                return;
            }

            if (status.fallback_due_count > 0) {
                await postReleaseCheck({});
                return;
            }

            if (!status.needs_location_check) {
                if (typeof status.next_check_in_sec === 'number') {
                    scheduleNext(Math.min(status.next_check_in_sec * 1000, 120000));
                } else {
                    scheduleNext(60000);
                }
                return;
            }

            if (Date.now() < geolocationCooldownUntil) {
                scheduleNext(120000);
                return;
            }

            try {
                const coords = await getCurrentLocation();
                await postReleaseCheck(coords);
            } catch (error) {
                geolocationCooldownUntil = Date.now() + 5 * 60 * 1000;
                if (typeof status.next_check_in_sec === 'number') {
                    scheduleNext(Math.max(status.next_check_in_sec * 1000, 120000));
                } else {
                    scheduleNext(120000);
                }
            }
        } catch (error) {
            scheduleNext(120000);
        } finally {
            requestInFlight = false;
        }
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && lastKnownPendingCount !== 0) {
            runCycle(true);
        }
    });

    window.addEventListener('focus', () => {
        if (lastKnownPendingCount !== 0) {
            runCycle(true);
        }
    });

    window.addEventListener('violeta:safety-publish-created', () => {
        geolocationCooldownUntil = 0;
        updatePendingOverlays();
        runCycle(true);
    });

    window.refreshPendingPostReleaseUI = function refreshPendingPostReleaseUI(force) {
        updatePendingOverlays();
        if (force) {
            runCycle(true);
        } else if (lastKnownPendingCount !== 0) {
            runCycle(false);
        }
    };

    updatePendingOverlays();
    overlayTicker = window.setInterval(updatePendingOverlays, 1000);
    runCycle(true);
})();
