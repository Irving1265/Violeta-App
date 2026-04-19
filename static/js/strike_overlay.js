(function () {
    'use strict';

    const WARNING_DURATION_SECONDS = 10;

    function getCsrfToken() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    function parseServerDate(raw) {
        if (!raw) return null;
        const normalized = /(?:z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`;
        const value = new Date(normalized);
        return Number.isNaN(value.getTime()) ? null : value;
    }

    function formatClock(seconds) {
        const safe = Math.max(0, Math.floor(seconds || 0));
        const days = Math.floor(safe / 86400);
        const hours = Math.floor((safe % 86400) / 3600);
        const minutes = Math.floor((safe % 3600) / 60);
        const secs = safe % 60;

        if (days > 0) {
            return `${days}d ${hours}h ${minutes}m`;
        }
        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        }
        return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }

    function setStatus(node, message, isError) {
        if (!node) return;
        node.textContent = message || '';
        node.classList.toggle('is-error', Boolean(isError));
    }

    function setDismissButton(button, state) {
        if (!button) return;
        button.classList.toggle('is-loading', state === 'loading');

        if (state === 'ready') {
            button.disabled = false;
            button.innerHTML = '<span>Entiendo, deseo continuar</span>';
        } else if (state === 'loading') {
            button.disabled = true;
            button.innerHTML = '<span class="strike-spinner" aria-hidden="true"></span><span>Procesando...</span>';
        } else {
            button.disabled = true;
            button.innerHTML = '<span>Espera 10 segundos...</span>';
        }
    }

    function setRestrictionDismissButton(button, state) {
        if (!button) return;
        button.classList.toggle('is-loading', state === 'loading');

        if (state === 'ready') {
            button.disabled = false;
            button.innerHTML = '<span>Entiendo, deseo continuar</span>';
        } else if (state === 'loading') {
            button.disabled = true;
            button.innerHTML = '<span class="strike-spinner" aria-hidden="true"></span><span>Procesando...</span>';
        } else {
            button.disabled = true;
            button.innerHTML = '<span>Disponible cuando termine la suspensión</span>';
        }
    }

    function safeStorageGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (error) {
            return null;
        }
    }

    function safeStorageSet(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (error) {
            // localStorage can be unavailable in private contexts.
        }
    }

    function safeStorageRemove(key) {
        try {
            window.localStorage.removeItem(key);
        } catch (error) {
            // localStorage can be unavailable in private contexts.
        }
    }

    function initWarningStrikeOverlay() {
        const overlay = document.querySelector('[data-strike-warning-overlay]');
        const config = window.VIOLETA_STRIKE_OVERLAY || null;
        if (!overlay || !config || !config.id) return;

        document.body.classList.add('strike-overlay-open', 'strike-warning-open');

        const countdown = overlay.querySelector('[data-strike-countdown]');
        const progress = overlay.querySelector('[data-strike-progress]');
        const button = overlay.querySelector('[data-strike-dismiss]');
        const status = overlay.querySelector('[data-strike-status]');
        const storageKey = `violeta_strike_unlock_at_${config.id}`;
        const initialRemaining = Math.max(0, Number(config.dismiss_remaining_seconds || WARNING_DURATION_SECONDS));
        const serverUnlockAt = Date.now() + initialRemaining * 1000;
        const storedUnlockAt = Number(safeStorageGet(storageKey) || 0);
        let unlockAt = storedUnlockAt > 0 ? Math.min(storedUnlockAt, serverUnlockAt) : serverUnlockAt;
        let intervalId = null;

        if (!storedUnlockAt || storedUnlockAt !== unlockAt) {
            safeStorageSet(storageKey, String(unlockAt));
        }

        function renderTimer() {
            const remainingMs = Math.max(0, unlockAt - Date.now());
            const remainingSeconds = Math.ceil(remainingMs / 1000);
            const elapsedSeconds = Math.min(WARNING_DURATION_SECONDS, WARNING_DURATION_SECONDS - Math.min(WARNING_DURATION_SECONDS, remainingSeconds));
            const progressPct = Math.max(0, Math.min(100, (elapsedSeconds / WARNING_DURATION_SECONDS) * 100));

            if (countdown) countdown.textContent = formatClock(remainingSeconds);
            if (progress) {
                if (progress.tagName && progress.tagName.toLowerCase() === 'circle') {
                    const length = Number(progress.getAttribute('data-progress-length') || 125.6);
                    progress.style.strokeDasharray = `${length} ${length}`;
                    progress.style.strokeDashoffset = `${(progressPct / 100) * length}`;
                } else {
                    progress.style.width = `${progressPct}%`;
                }
            }

            if (remainingSeconds <= 0) {
                setDismissButton(button, 'ready');
                if (intervalId) {
                    window.clearInterval(intervalId);
                    intervalId = null;
                }
            } else {
                setDismissButton(button, 'waiting');
            }
        }

        function restartTimer(remainingSeconds) {
            unlockAt = Date.now() + Math.max(0, Number(remainingSeconds || 0)) * 1000;
            safeStorageSet(storageKey, String(unlockAt));
            if (intervalId) window.clearInterval(intervalId);
            renderTimer();
            intervalId = window.setInterval(renderTimer, 1000);
        }

        async function dismissStrike() {
            if (!button || button.disabled) return;
            setStatus(status, '', false);
            setDismissButton(button, 'loading');

            try {
                const response = await fetch('/api/safety/dismiss_strike', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                    body: '{}',
                });
                const payload = await response.json().catch(() => ({}));

                if (response.ok && (payload.ok || payload.success)) {
                    safeStorageRemove(storageKey);
                    overlay.classList.add('is-leaving');
                    window.setTimeout(() => {
                        overlay.remove();
                        document.body.classList.remove('strike-overlay-open', 'strike-warning-open');
                    }, 220);
                    return;
                }

                if (response.status === 409 && payload.remaining_seconds != null) {
                    setStatus(status, 'Aún falta tiempo. El contador se ajustó con el servidor.', true);
                    restartTimer(Number(payload.remaining_seconds));
                    return;
                }

                setStatus(status, payload.message || 'No se pudo cerrar la advertencia. Intenta de nuevo.', true);
                setDismissButton(button, 'ready');
            } catch (error) {
                setStatus(status, 'No se pudo conectar con el servidor. Intenta de nuevo.', true);
                setDismissButton(button, 'ready');
            }
        }

        button?.addEventListener('click', dismissStrike);
        renderTimer();
        if (unlockAt > Date.now()) {
            intervalId = window.setInterval(renderTimer, 1000);
        }
    }

    function initRestrictedOverlay() {
        const overlay = document.querySelector('[data-restricted-overlay]');
        if (!overlay) return;

        const strikeLevel = Number(overlay.getAttribute('data-strike-level') || 0);
        document.body.classList.add('strike-overlay-open', 'strike-restricted-lock');
        if (strikeLevel >= 3) {
            document.body.classList.add('strike-banned-lock');
        }

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
            }
        }, true);

        const timer = overlay.querySelector('[data-restriction-countdown]');
        const dismissButton = overlay.querySelector('[data-restriction-dismiss]');
        const status = overlay.querySelector('[data-restriction-status]');
        if (!timer) return;

        const value = overlay.querySelector('[data-restriction-countdown-value]');
        const progress = overlay.querySelector('[data-restriction-progress]');
        const until = parseServerDate(timer.getAttribute('data-restriction-until'));
        const initialTotal = Math.max(1, Number(timer.getAttribute('data-restriction-total') || 0));
        let restrictionIntervalId = null;
        if (!until) {
            if (value) value.textContent = 'Sin fecha';
            return;
        }

        function renderRestrictionTimer() {
            const diffSeconds = Math.max(0, Math.ceil((until.getTime() - Date.now()) / 1000));
            if (value) value.textContent = diffSeconds <= 0 ? 'Puedes volver a entrar ahora' : formatClock(diffSeconds);
            if (progress) {
                const pct = Math.max(0, Math.min(100, ((initialTotal - diffSeconds) / initialTotal) * 100));
                progress.style.width = `${pct}%`;
            }
            if (diffSeconds <= 0) {
                if (value) value.textContent = 'Suspensión cumplida';
                setRestrictionDismissButton(dismissButton, 'ready');
                if (restrictionIntervalId) {
                    window.clearInterval(restrictionIntervalId);
                    restrictionIntervalId = null;
                }
            } else {
                setRestrictionDismissButton(dismissButton, 'waiting');
            }
        }

        async function dismissRestriction() {
            if (!dismissButton || dismissButton.disabled) return;
            setStatus(status, '', false);
            setRestrictionDismissButton(dismissButton, 'loading');

            try {
                const response = await fetch('/api/safety/dismiss_strike', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                    body: '{}',
                });
                const payload = await response.json().catch(() => ({}));

                if (response.ok && (payload.ok || payload.success)) {
                    window.location.href = payload.redirect || '/';
                    return;
                }

                if (response.status === 409 && payload.remaining_seconds != null) {
                    setStatus(status, 'La suspensión todavía no ha terminado. El contador se actualizó con el servidor.', true);
                    setRestrictionDismissButton(dismissButton, 'waiting');
                    return;
                }

                setStatus(status, payload.message || 'No se pudo cerrar la suspensión. Intenta de nuevo.', true);
                setRestrictionDismissButton(dismissButton, 'ready');
            } catch (error) {
                setStatus(status, 'No se pudo conectar con el servidor. Intenta de nuevo.', true);
                setRestrictionDismissButton(dismissButton, 'ready');
            }
        }

        dismissButton?.addEventListener('click', dismissRestriction);
        renderRestrictionTimer();
        if (until.getTime() > Date.now()) {
            restrictionIntervalId = window.setInterval(renderRestrictionTimer, 1000);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        initWarningStrikeOverlay();
        initRestrictedOverlay();
    });
})();
