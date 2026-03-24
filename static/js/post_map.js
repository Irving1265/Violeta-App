// Map management for posts
const postMaps = {};

function toggleMap(postId, lat, lng, btn) {
    const flipContainer = document.getElementById(`flip-${postId}`);
    const mapContainer = document.getElementById(`map-${postId}`);

    if (!flipContainer || !mapContainer) return;

    // Toggle flip class
    flipContainer.classList.toggle('flipped');
    const isFlipped = flipContainer.classList.contains('flipped');

    // Update button icon
    const icon = btn.querySelector('i');
    if (icon) {
        icon.className = isFlipped ? 'fas fa-image' : 'fas fa-map-marked-alt';
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
