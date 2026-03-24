const mexicoBounds = L.latLngBounds([14.3, -118.8], [32.9, -86.5]);

function applyMapLimits(map) {
    const sz = map.getSize ? map.getSize() : null;
    if (!sz || sz.x < 120 || sz.y < 120) return false;
    const fitZoom = map.getBoundsZoom(mexicoBounds, false, L.point(10, 10));
    const minZoom = Math.max(4, Number.isFinite(fitZoom) ? Math.floor(fitZoom) : 4);
    map.setMinZoom(minZoom);
    map.options.minZoom = minZoom;
    if (map.getZoom() < minZoom) {
        map.setZoom(minZoom, { animate: false });
    }
    map.setMaxBounds(mexicoBounds.pad(0.02));
    map.options.maxBoundsViscosity = 1.0;
    return true;
}

// Inicializa el mapa
const map = L.map('map').setView([23.6345, -102.5528], 5);
map.whenReady(() => {
    let retries = 0;
    const applyWithRetry = () => {
        if (!applyMapLimits(map) && retries < 20) {
            retries += 1;
            setTimeout(applyWithRetry, 120);
        }
    };
    applyWithRetry();
});
map.on('resize', () => applyMapLimits(map));

// Carga el mapa base
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
}).addTo(map);

// Función para actualizar el mapa con coordenadas
function updateMap(lat, lng) {
    // Centra el mapa en las coordenadas
    map.setView([lat, lng], 13); // Ajusta el zoom según sea necesario

    // Agrega un marcador en las coordenadas
    L.marker([lat, lng]).addTo(map)
        .bindPopup('Ubicación: ' + lat + ', ' + lng)
        .openPopup();
}

// Supongamos que tienes las coordenadas disponibles en el HTML
// Puedes pasarlas desde el backend al renderizar la página
const latitude = parseFloat(document.getElementById('latitude').value); // Asegúrate de tener un input oculto o similar
const longitude = parseFloat(document.getElementById('longitude').value);

// Llama a la función updateMap con las coordenadas
if (!isNaN(latitude) && !isNaN(longitude)) {
    updateMap(latitude, longitude);
}
