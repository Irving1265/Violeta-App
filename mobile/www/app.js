const status = document.getElementById('backendStatus');
const urlNode = document.getElementById('backendUrl');

async function boot() {
  try {
    const response = await fetch('./runtime-config.json', { cache: 'no-store' });
    if (!response.ok) {
      return;
    }
    const config = await response.json();
    if (!config.serverUrl) {
      return;
    }
    status.textContent = 'Configurado';
    urlNode.textContent = config.serverUrl;
  } catch {
    // Keep static fallback copy if runtime config is unavailable.
  }
}

boot();
