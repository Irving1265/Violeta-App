function toggleBlockUser(userId, block) {
    const url = block ? `/api/user/block/${userId}` : `/api/user/unblock/${userId}`;
    return fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
    }).then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'No se pudo actualizar el bloqueo');
        }
        window.location.reload();
    }).catch((error) => {
        alert(error.message || 'No se pudo actualizar el bloqueo');
    });
}

function toggleMuteUser(userId, mute) {
    const url = mute ? `/api/user/mute/${userId}` : `/api/user/unmute/${userId}`;
    return fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
    }).then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'No se pudo actualizar el silencio');
        }
        window.location.reload();
    }).catch((error) => {
        alert(error.message || 'No se pudo actualizar el silencio');
    });
}

window.toggleBlockUser = toggleBlockUser;
window.toggleMuteUser = toggleMuteUser;
window.initUserProfileEnhancements = function initUserProfileEnhancements() {
    if (typeof window.refreshPendingPostReleaseUI === 'function') {
        window.refreshPendingPostReleaseUI(true);
    }
};
