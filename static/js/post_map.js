// Map management for posts
const postMaps = {};

function getPostMapCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function notifyPostMap(message, type = 'info') {
    if (typeof showVioletNotification === 'function') {
        showVioletNotification(message, type, 5000);
    } else if (message) {
        alert(message);
    }
}

function protectedLocationLabel(payload) {
    if (!payload) return '';
    return payload.location_name || payload.location_label || payload.city || 'Ubicación revelada';
}

async function revealProtectedLocation(postId, btn) {
    if (!postId || !btn) return;
    const originalTitle = btn.title;
    btn.disabled = true;
    btn.classList.add('is-loading');

    try {
        const headers = { Accept: 'application/json' };
        const csrfToken = getPostMapCsrfToken();
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }
        const response = await fetch(`/api/posts/${postId}/reveal-location`, {
            method: 'POST',
            headers
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok || !payload.ok) {
            const label = protectedLocationLabel(payload);
            const labelEl = document.querySelector(`[data-post-location-label="${postId}"]`);
            if (labelEl && label) {
                labelEl.textContent = label;
            }
            notifyPostMap(payload.error || 'No se pudo revelar la ubicación.', 'warning');
            return;
        }

        const lat = Number(payload.latitude);
        const lng = Number(payload.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            notifyPostMap('La ubicación exacta no está disponible para este reporte.', 'warning');
            return;
        }

        const labelEl = document.querySelector(`[data-post-location-label="${postId}"]`);
        if (labelEl) {
            labelEl.textContent = protectedLocationLabel(payload);
        }

        btn.classList.remove('post-map-reveal');
        btn.title = 'Ver mapa';
        btn.setAttribute('aria-label', 'Ver mapa');
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = 'fas fa-map-marked-alt';
        }
        btn.onclick = function () {
            toggleMap(postId, lat, lng, btn);
        };

        notifyPostMap('Ubicación revelada. Esta vista cuenta como una de tus ubicaciones de prueba.', 'success');
        toggleMap(postId, lat, lng, btn);
    } catch (error) {
        console.error('revealProtectedLocation error:', error);
        notifyPostMap('No se pudo revelar la ubicación. Inténtalo de nuevo.', 'danger');
    } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        if (originalTitle && btn.title === '') {
            btn.title = originalTitle;
        }
    }
}

function toggleMap(postId, lat, lng, btn) {
    const flipContainer = document.getElementById(`flip-${postId}`);
    const mapContainer = document.getElementById(`map-${postId}`);

    if (!flipContainer || !mapContainer) return;

    // Toggle flip class
    flipContainer.classList.toggle('flipped');
    const isFlipped = flipContainer.classList.contains('flipped');

    // Update button icon
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = isFlipped ? 'fas fa-image' : 'fas fa-map-marked-alt';
        }
        const label = isFlipped ? 'Ver imagen' : 'Ver mapa';
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.setAttribute('aria-pressed', String(isFlipped));
        const visibleLabel = btn.querySelector('[data-post-map-label]');
        if (visibleLabel) visibleLabel.textContent = label;
    }

    // Initialize map if flipping to back and not already initialized
    if (isFlipped) {
        if (!postMaps[postId]) {
            // Check for valid coordinates
            if (lat === null || lng === null || isNaN(lat) || isNaN(lng)) {
                mapContainer.innerHTML = '<div class="d-flex align-items-center justify-content-center h-100 text-muted">Ubicación no disponible</div>';
                return;
            }

            // Initialize map
            const map = L.map(`map-${postId}`, {
                zoomControl: false,
                attributionControl: false
            }).setView([lat, lng], 15);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
            }).addTo(map);

            L.marker([lat, lng]).addTo(map);

            postMaps[postId] = map;
        }

        // Refresh map size after transition
        setTimeout(() => {
            if (postMaps[postId]) {
                postMaps[postId].invalidateSize();
            }
        }, 600); // Wait for flip animation to finish (approx 0.6s usually)
    }
}

window.revealProtectedLocation = revealProtectedLocation;
