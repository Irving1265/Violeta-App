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

function initProfileDeleteConfirm(root) {
    const scope = root || document;
    const modal = document.getElementById('profileDeleteModal');
    if (!modal) return;

    const imageEl = modal.querySelector('#profileDeleteImage');
    const locationEl = modal.querySelector('#profileDeleteLocation');
    const captionEl = modal.querySelector('#profileDeleteCaption');
    const confirmBtn = modal.querySelector('#profileDeleteConfirm');
    let activeForm = null;

    const closeModal = () => {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        modal.hidden = true;
        document.body.classList.remove('profile-delete-modal-open');
        activeForm = null;
    };

    const openModal = (form) => {
        activeForm = form;
        if (imageEl) imageEl.src = form.dataset.deleteImage || '';
        if (locationEl) locationEl.textContent = form.dataset.deleteLocation || 'Sin ubicación registrada';
        if (captionEl) captionEl.textContent = form.dataset.deleteCaption || 'Sin descripción';
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.classList.add('is-open');
        document.body.classList.add('profile-delete-modal-open');
        if (confirmBtn) confirmBtn.focus();
    };

    Array.from(scope.querySelectorAll('[data-delete-post-form]')).forEach((form) => {
        if (form.dataset.deleteConfirmReady === '1') return;
        form.dataset.deleteConfirmReady = '1';
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            event.stopPropagation();
            openModal(form);
        });
    });

    if (modal.dataset.deleteModalReady === '1') return;
    modal.dataset.deleteModalReady = '1';

    modal.addEventListener('click', (event) => {
        if (event.target.closest('[data-delete-modal-close]')) {
            closeModal();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !modal.hidden) {
            closeModal();
        }
    });

    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            if (!activeForm) return;
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Borrando...';
            HTMLFormElement.prototype.submit.call(activeForm);
        });
    }
}

window.initUserProfileEnhancements = function initUserProfileEnhancements() {
    if (typeof window.refreshPendingPostReleaseUI === 'function') {
        window.refreshPendingPostReleaseUI(true);
    }
    initProfileDeleteConfirm(document);
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initProfileDeleteConfirm(document);
    }, { once: true });
} else {
    initProfileDeleteConfirm(document);
}
