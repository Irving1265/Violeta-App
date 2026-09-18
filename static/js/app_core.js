(function () {
    if (window.VioletaAppCoreLoaded) {
        return;
    }
    window.VioletaAppCoreLoaded = true;

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function buildHeaders(contentType) {
        const headers = { Accept: 'application/json' };
        const csrfToken = getCsrfToken();
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }
        if (contentType) {
            headers['Content-Type'] = contentType;
        }
        return headers;
    }

    function handleAuthRedirect(response) {
        if (response.redirected && response.url && response.url.includes('/login')) {
            window.location.href = response.url;
            return true;
        }
        if (response.status === 401) {
            window.location.href = '/login';
            return true;
        }
        if (response.status === 403) {
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                window.location.href = '/login';
                return true;
            }
        }
        return false;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function getRelativeTime(dateInput) {
        const date = new Date(dateInput);
        if (Number.isNaN(date.getTime())) {
            return '';
        }

        const diffMs = Date.now() - date.getTime();
        const diffSeconds = Math.max(0, Math.floor(diffMs / 1000));
        if (diffSeconds < 60) return 'Hace un momento';

        const diffMinutes = Math.floor(diffSeconds / 60);
        if (diffMinutes < 60) return `Hace ${diffMinutes} min`;

        const diffHours = Math.floor(diffMinutes / 60);
        if (diffHours < 24) return `Hace ${diffHours} hora${diffHours === 1 ? '' : 's'}`;

        return 'Hace tiempo';
    }

    function showVioletNotification(message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `violet-notification violet-notification-${type}`;
        notification.innerHTML = `
            <div class="violet-notification-content">
                <span class="violet-notification-message">${message}</span>
                <button class="violet-notification-close" onclick="this.parentElement.parentElement.remove()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;

        Object.assign(notification.style, {
            position: 'fixed',
            top: '20px',
            right: '20px',
            backgroundColor: type === 'error' || type === 'danger' ? '#ff4757' : type === 'success' ? '#2ed573' : '#b565a7',
            color: '#ffffff',
            padding: '16px 20px',
            borderRadius: '12px',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
            zIndex: '10000',
            transform: 'translateX(400px)',
            transition: 'transform 0.3s ease',
            minWidth: '300px',
            maxWidth: '400px'
        });

        document.body.appendChild(notification);

        window.setTimeout(() => {
            notification.style.transform = 'translateX(0)';
        }, 100);

        window.setTimeout(() => {
            notification.style.transform = 'translateX(400px)';
            window.setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, 300);
        }, duration);
    }

    function showAlert(message, type = 'info') {
        showVioletNotification(message, type);
    }

    function isUserVerified() {
        return window.USER_IS_VERIFIED !== false;
    }

    function showVerifyGate() {
        const msg = window.VERIFY_REQUIRED_MSG || 'Para poder ver el contenido tenemos que verificar tu identidad';
        showVioletNotification(msg, 'info', 5000);
    }

    function initVioletFormValidation() {
        document.querySelectorAll('.violet-input').forEach((input) => {
            if (input.closest('[data-validation="native"]')) return;
            input.addEventListener('blur', function () {
                validateInput(this);
            });
            input.addEventListener('input', function () {
                this.classList.remove('error');
                const errorElement = this.parentNode.querySelector('.violet-error');
                if (errorElement) {
                    errorElement.style.display = 'none';
                }
            });
        });
    }

    function validateInput(input) {
        const value = input.value.trim();
        let isValid = true;
        let errorMessage = '';

        switch (input.type) {
            case 'email':
                if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
                    isValid = false;
                    errorMessage = 'Please enter a valid email address';
                }
                break;
            case 'password':
                if (value.length < 8) {
                    isValid = false;
                    errorMessage = 'This field is required';
                }
                break;
            default:
                if (value === '') {
                    isValid = false;
                    errorMessage = 'This field is required';
                }
        }

        if (input.id === 'username' && value !== '' && !/^[a-zA-Z0-9._]+$/.test(value)) {
            isValid = false;
            errorMessage = 'Username can only contain letters, numbers, periods, and underscores';
        }

        if (!isValid) {
            input.classList.add('error');
            showInputError(input, errorMessage);
        } else {
            input.classList.remove('error');
            hideInputError(input);
        }

        return isValid;
    }

    function showInputError(input, message) {
        let errorElement = input.parentNode.querySelector('.violet-error');
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.className = 'violet-error';
            input.parentNode.appendChild(errorElement);
        }
        errorElement.textContent = message;
        errorElement.style.display = 'block';
    }

    function hideInputError(input) {
        const errorElement = input.parentNode.querySelector('.violet-error');
        if (errorElement) {
            errorElement.style.display = 'none';
        }
    }

    function initVioletButtonAnimations() {
        document.querySelectorAll('.violet-btn-primary, .violet-btn-secondary').forEach((button) => {
            button.addEventListener('mousedown', function () {
                this.style.transform = 'translateY(1px) scale(0.98)';
            });
            button.addEventListener('mouseup', function () {
                this.style.transform = 'translateY(-2px) scale(1)';
            });
            button.addEventListener('mouseleave', function () {
                this.style.transform = '';
            });
        });
    }

    function initVioletInputEffects() {
        document.querySelectorAll('.violet-input').forEach((input) => {
            input.addEventListener('focus', function () {
                this.parentNode.classList.add('focused');
            });
            input.addEventListener('blur', function () {
                this.parentNode.classList.remove('focused');
            });
        });
    }

    function installVerifiedActionGate() {
        document.addEventListener('click', function (event) {
            if (isUserVerified()) return;
            const target = event.target.closest('[data-require-verified]');
            if (target) {
                event.preventDefault();
                event.stopPropagation();
                showVerifyGate();
            }
        }, true);
    }

    function installNavigationEnhancements() {
        function isModifiedEvent(e) { return e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0; }
        function isSameOrigin(href) { try { return new URL(href, window.location.href).origin === window.location.origin; } catch (_) { return false; } }
        const prefetchedUrls = new Set();
        let navServiceWorkerReady = null;

        function normalizeSameOriginUrl(href) {
            const url = new URL(href, window.location.href);
            url.hash = '';
            return url.toString();
        }

        function isSafetyNavigationPath(pathname) {
            return pathname === '/safety' || pathname.startsWith('/safety/');
        }

        function shouldPrefetchLink(link) {
            if (!link || !link.href) return false;
            if (link.dataset && link.dataset.noPrefetch === '1') return false;
            const href = link.getAttribute('href') || '';
            if (!href || href.startsWith('#') || href.startsWith('tel:') || href.startsWith('mailto:')) return false;
            if (!isSameOrigin(href)) return false;
            try {
                const url = new URL(href, window.location.href);
                if (url.pathname === '/logout' || isSafetyNavigationPath(url.pathname)) return false;
            } catch (_) {
                return false;
            }
            return true;
        }

        function prefetchDocument(href) {
            if (!href || !isSameOrigin(href)) return;
            const normalized = normalizeSameOriginUrl(href);
            if (prefetchedUrls.has(normalized)) return;
            const link = document.createElement('link');
            link.rel = 'prefetch';
            link.as = 'document';
            link.href = normalized;
            document.head.appendChild(link);
            prefetchedUrls.add(normalized);
        }

        function sendServiceWorkerMessage(payload) {
            if (!('serviceWorker' in navigator)) return;
            const postToWorker = (worker) => {
                if (worker) worker.postMessage(payload);
            };
            if (navigator.serviceWorker.controller) {
                postToWorker(navigator.serviceWorker.controller);
                return;
            }
            if (navServiceWorkerReady) {
                navServiceWorkerReady.then((registration) => postToWorker(registration.active || registration.waiting || registration.installing)).catch(() => null);
            }
        }

        function installSpeculationRules(urls) {
            if (!Array.isArray(urls) || !urls.length) return;
            if (typeof HTMLScriptElement === 'undefined' || typeof HTMLScriptElement.supports !== 'function') return;
            if (!HTMLScriptElement.supports('speculationrules')) return;
            const existing = document.getElementById('violeta-speculation-rules');
            if (existing) existing.remove();
            const script = document.createElement('script');
            script.type = 'speculationrules';
            script.id = 'violeta-speculation-rules';
            script.textContent = JSON.stringify({
                prerender: [{ urls: urls.slice(0, 4) }],
                prefetch: [{ urls: urls.slice(0, 8) }],
            });
            document.head.appendChild(script);
        }

        function warmNavigationTarget(href) {
            if (!href || !isSameOrigin(href)) return;
            const normalized = normalizeSameOriginUrl(href);
            prefetchDocument(normalized);
            sendServiceWorkerMessage({ type: 'VIOLETA_PREFETCH_NAV', urls: [normalized] });
            installSpeculationRules([normalized]);
        }

        function registerNavigationServiceWorker() {
            if (!('serviceWorker' in navigator)) return Promise.resolve(null);
            if (!(window.isSecureContext || window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost')) {
                return Promise.resolve(null);
            }
            navServiceWorkerReady = navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
                .then(() => navigator.serviceWorker.ready)
                .catch(() => null);
            return navServiceWorkerReady;
        }

        function getNavigationCandidates() {
            return Array.from(document.querySelectorAll('.sidebar-link, .bottom-nav .nav-item, .widget-card a, .brand-logo a'))
                .filter(shouldPrefetchLink)
                .map((link) => normalizeSameOriginUrl(link.href))
                .filter((href, index, arr) => arr.indexOf(href) === index);
        }

        const area = document.querySelector('.main-content');
        if (area) {
            requestAnimationFrame(() => { area.classList.add('page-anim-in'); });
        }

        const navigationCandidates = getNavigationCandidates();
        navigationCandidates.forEach((href) => prefetchDocument(href));
        installSpeculationRules(navigationCandidates);

        registerNavigationServiceWorker().then(() => {
            if (window.CURRENT_USER && window.CURRENT_USER.is_authenticated && navigationCandidates.length) {
                sendServiceWorkerMessage({ type: 'VIOLETA_PREFETCH_NAV', urls: navigationCandidates });
                window.setTimeout(() => sendServiceWorkerMessage({ type: 'VIOLETA_PREFETCH_NAV', urls: navigationCandidates }), 1500);
            } else {
                sendServiceWorkerMessage({ type: 'VIOLETA_CLEAR_NAV_CACHE' });
            }
        });

        document.addEventListener('click', function (e) {
            if (!(e.target instanceof Element)) return;
            const target = e.target.closest('a, button');
            if (!target || target.dataset?.noAnim === '1') return;
            if (target.tagName !== 'A') return;
            const href = target.getAttribute('href') || '';
            if (!href || href.startsWith('#') || href.startsWith('tel:') || href.startsWith('mailto:')) return;
            if (isModifiedEvent(e) || !isSameOrigin(href)) return;
            if (target.dataset?.noPrefetch === '1') {
                sendServiceWorkerMessage({ type: 'VIOLETA_CLEAR_NAV_CACHE' });
            } else {
                warmNavigationTarget(href);
            }
            e.preventDefault();
            window.location.href = normalizeSameOriginUrl(href);
        }, true);

        ['pointerenter', 'focusin', 'touchstart'].forEach((eventName) => {
            document.addEventListener(eventName, function (event) {
                // Captured pointer events may target Document rather than an element.
                if (!(event.target instanceof Element)) return;
                const link = event.target.closest('a[href]');
                if (!shouldPrefetchLink(link)) return;
                warmNavigationTarget(link.href);
            }, eventName === 'touchstart' ? { passive: true, capture: true } : true);
        });
    }

    window.getCsrfToken = getCsrfToken;
    window.buildHeaders = buildHeaders;
    window.handleAuthRedirect = handleAuthRedirect;
    window.escapeHtml = escapeHtml;
    window.getRelativeTime = getRelativeTime;
    window.showVioletNotification = showVioletNotification;
    window.showAlert = showAlert;
    window.isUserVerified = isUserVerified;
    window.showVerifyGate = showVerifyGate;

    installVerifiedActionGate();

    document.addEventListener('DOMContentLoaded', function () {
        initVioletFormValidation();
        initVioletButtonAnimations();
        initVioletInputEffects();
        installNavigationEnhancements();

        document.addEventListener('keydown', function (event) {
            if (event.target.name === 'content' && event.target.closest('.comments-section')) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    const form = event.target.closest('form');
                    if (form) {
                        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                    }
                }
            }
        });
    });
})();
