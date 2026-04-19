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

function inviteBetaFormatMessage(code) {
    return `Te invito a Violeta Beta, una comunidad privada para mujeres. Usa este código al registrarte: ${code}`;
}

function copyInviteText(text, statusEl) {
    const value = String(text || '').trim();
    if (!value) return Promise.resolve(false);
    const done = () => {
        if (statusEl) statusEl.textContent = 'Código copiado.';
        return true;
    };
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(value).then(done).catch(() => false);
    }
    const area = document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try {
        document.execCommand('copy');
        return Promise.resolve(done());
    } catch (error) {
        return Promise.resolve(false);
    } finally {
        area.remove();
    }
}

function appendInviteCode(card, invite) {
    const list = card.querySelector('[data-invite-code-list]');
    if (!list || !invite || !invite.code) return;
    const item = document.createElement('article');
    item.className = 'invite-beta-code';
    item.setAttribute('data-invite-code-item', '');
    item.innerHTML = `
      <div>
        <span class="invite-beta-code__label">Código activo</span>
        <strong class="invite-code-dots" data-invite-code-value>•••••••••••••••••</strong>
      </div>
      <button type="button" class="invite-beta-code__copy" data-copy-invite="">Copiar</button>
    `;
    item.querySelector('[data-copy-invite]').setAttribute('data-copy-invite', invite.code);
    list.prepend(item);
}

function initInviteBetaCards(root) {
    const scope = root || document;
    const cards = Array.from(scope.querySelectorAll('[data-invite-beta-card]'));
    cards.forEach((card) => {
        if (card.dataset.inviteReady === '1') return;
        card.dataset.inviteReady = '1';
        const statusEl = card.querySelector('[data-invite-status]');
        const remainingEl = card.querySelector('[data-invite-remaining]');
        const modalEl = document.getElementById('inviteBetaModal');
        if (modalEl && modalEl.parentNode !== document.body) {
            document.body.appendChild(modalEl);
        }
        const listEl = modalEl ? modalEl.querySelector('[data-invite-code-list]') : null;
        const createBtn = modalEl ? modalEl.querySelector('[data-invite-create]') : null;
        const modalCode = modalEl ? modalEl.querySelector('[data-invite-modal-code]') : null;
        const modalCopyBtn = modalEl ? modalEl.querySelector('[data-copy-modal-invite]') : null;
        const modal = modalEl && window.bootstrap ? new bootstrap.Modal(modalEl) : null;
        let latestCode = '';

        card.addEventListener('click', (event) => {
            const copyBtn = event.target.closest('[data-copy-invite]');
            if (!copyBtn) return;
            copyInviteText(copyBtn.getAttribute('data-copy-invite'), statusEl);
        });

        if (modalEl && modalEl.dataset.inviteCopyReady !== '1') {
            modalEl.dataset.inviteCopyReady = '1';
            modalEl.addEventListener('click', (event) => {
                const copyBtn = event.target.closest('[data-copy-invite]');
                if (!copyBtn) return;
                copyInviteText(copyBtn.getAttribute('data-copy-invite'), statusEl);
            });
        }

        if (!createBtn) return;
        createBtn.addEventListener('click', async () => {
            if (createBtn.disabled) return;
            createBtn.disabled = true;
            const original = createBtn.innerHTML;
            createBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Generando...</span>';
            if (statusEl) statusEl.textContent = '';

            try {
                const response = await fetch('/api/invitations/create', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
                    },
                    body: JSON.stringify({}),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    const reason = Array.isArray(data.reasons) && data.reasons.length ? ` ${data.reasons.join(' ')}` : '';
                    throw new Error((data.error || 'No se pudo generar la invitación.') + reason);
                }

                latestCode = data.invite.code;
                if (listEl) appendInviteCode(modalEl, data.invite);
                if (remainingEl) remainingEl.textContent = String(data.remaining ?? '0');
                if (Number(data.remaining || 0) <= 0) {
                    createBtn.disabled = true;
                    createBtn.innerHTML = original;
                } else {
                    createBtn.disabled = false;
                    createBtn.innerHTML = original;
                }
                if (statusEl) statusEl.textContent = data.message || 'Invitación creada.';
            } catch (error) {
                createBtn.disabled = false;
                createBtn.innerHTML = original;
                if (statusEl) statusEl.textContent = error.message || 'No se pudo generar la invitación.';
            }
        });
    });
}

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
    initInviteBetaCards(document);
    initProfileDeleteConfirm(document);
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initInviteBetaCards(document);
        initProfileDeleteConfirm(document);
    }, { once: true });
} else {
    initInviteBetaCards(document);
    initProfileDeleteConfirm(document);
}
