(function () {
    if (window.VioletaRealtimeLoaded) {
        return;
    }
    window.VioletaRealtimeLoaded = true;

    function safeEscape(value) {
        if (typeof window.escapeHtml === 'function') {
            return window.escapeHtml(value);
        }
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    }

    function relativeTime(value) {
        if (typeof window.getRelativeTime === 'function') {
            return window.getRelativeTime(value);
        }
        return '';
    }

    function formatChatToastPreview(message) {
        if (!message) return '';
        if (message.is_deleted) return 'Mensaje eliminado';
        const type = String(message.message_type || '').toLowerCase();
        const content = String(message.content || '').trim();
        const attachmentName = String(message.attachment_name || '').trim();

        if (type === 'image') {
            if (content) return content;
            return attachmentName ? `Imagen: ${attachmentName}` : 'Imagen';
        }

        if (type === 'file') {
            if (content) return content;
            return attachmentName ? `Archivo: ${attachmentName}` : 'Archivo adjunto';
        }

        if (content) return content;
        if (attachmentName) return `Archivo: ${attachmentName}`;
        return '';
    }

    function showChatMessageToast(options) {
        try {
            const roomId = options && options.room_id != null ? Number(options.room_id) : null;
            if (!roomId) return;

            const flash = document.getElementById('flashPopups');
            if (!flash) return;

            const roomName = String(options.room_name || 'Chat');
            const roomImageUrl = String(options.room_image_url || '/static/images/favicon.png');
            const username = String(options.username || '');
            const messageText = String(options.message || '').trim();
            if (!username || !messageText) return;

            const toast = document.createElement('div');
            toast.className = 'alert violet-chat-toast alert-dismissible fade show popup-alert';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            toast.setAttribute('data-room-id', String(roomId));
            toast.innerHTML = `
                <div class="violet-chat-toast__content">
                    <img class="violet-chat-toast__avatar" src="${safeEscape(roomImageUrl)}" alt="${safeEscape(roomName)}">
                    <div class="violet-chat-toast__body">
                        <div class="violet-chat-toast__title">${safeEscape(roomName)}</div>
                        <div class="violet-chat-toast__message"><span class="violet-chat-toast__user">${safeEscape(username)}</span>: ${safeEscape(messageText)}</div>
                    </div>
                    <button type="button" class="violet-chat-toast__close" data-bs-dismiss="alert" aria-label="Cerrar">
                        <i class="fas fa-times" aria-hidden="true"></i>
                    </button>
                </div>
            `;

            toast.addEventListener('click', (e) => {
                if (e.target && e.target.closest && e.target.closest('[data-bs-dismiss="alert"]')) return;
                const rid = toast.getAttribute('data-room-id');
                if (!rid) return;

                if (window.location && window.location.pathname === '/chat' && typeof window.selectRoom === 'function') {
                    try {
                        window.selectRoom(Number(rid));
                        return;
                    } catch (err) {}
                }

                window.location.href = `/chat?room=${encodeURIComponent(rid)}`;
            });

            flash.appendChild(toast);

            try {
                const all = flash.querySelectorAll('.violet-chat-toast');
                const maxToasts = 3;
                if (all.length > maxToasts) {
                    for (let i = 0; i < all.length - maxToasts; i++) {
                        try { bootstrap.Alert.getOrCreateInstance(all[i]).close(); } catch (e) { all[i].remove(); }
                    }
                }
            } catch (e) {}

            const duration = Number(options.duration_ms || 6500);
            window.setTimeout(() => {
                try {
                    bootstrap.Alert.getOrCreateInstance(toast).close();
                } catch (e) {
                    try { toast.remove(); } catch (e2) {}
                }
            }, Number.isFinite(duration) ? duration : 6500);
        } catch (e) {
            // Notification helpers should never break the page.
        }
    }

    function initChatRoomToasts() {
        const IS_CHAT_PAGE = window.location && window.location.pathname === '/chat';
        const POLL_MS = IS_CHAT_PAGE ? 8000 : 20000;
        const INITIAL_DELAY_MS = IS_CHAT_PAGE ? 0 : 2500;
        let initialized = false;
        const lastUnreadKeyByRoom = new Map();
        let pollTimer = null;

        function msgKey(msg) {
            if (!msg) return '';
            if (msg.id != null) return String(msg.id);
            if (msg.created_at) return String(msg.created_at);
            return '';
        }

        async function poll(initial = false) {
            if (!window.CURRENT_USER || !window.CURRENT_USER.is_authenticated) return;
            if (window.USER_IS_VERIFIED === false) return;
            if (document.hidden) return;
            try {
                const res = await fetch('/api/chat/rooms', { headers: { Accept: 'application/json' } });
                if (!res.ok) return;
                const data = await res.json();
                const rooms = Array.isArray(data.rooms) ? data.rooms : [];

                if (!initialized || initial) {
                    rooms.forEach((room) => {
                        lastUnreadKeyByRoom.set(String(room.id), msgKey(room.last_unread_message) || '');
                    });
                    initialized = true;
                    return;
                }

                const activeRoomId = (window.__CHAT_CURRENT_ROOM_ID != null) ? Number(window.__CHAT_CURRENT_ROOM_ID) : null;

                rooms.forEach((room) => {
                    const roomIdStr = String(room.id);
                    const unread = room.last_unread_message || null;
                    const key = msgKey(unread);
                    const prevKey = lastUnreadKeyByRoom.get(roomIdStr) || '';

                    if (!unread || !key || Number(room.unread_count || 0) <= 0) {
                        lastUnreadKeyByRoom.set(roomIdStr, '');
                        return;
                    }

                    if (key === prevKey) return;
                    lastUnreadKeyByRoom.set(roomIdStr, key);
                    if (activeRoomId && Number.isFinite(activeRoomId) && Number(room.id) === activeRoomId) return;

                    const preview = formatChatToastPreview(unread);
                    if (!preview) return;

                    showChatMessageToast({
                        room_id: room.id,
                        room_name: room.name,
                        room_image_url: room.image_url,
                        username: unread.username,
                        message: preview,
                    });
                });
            } catch (e) {
                // ignore transient polling failures
            }
        }

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) return;
            poll(false);
        });

        document.addEventListener('DOMContentLoaded', () => {
            if (pollTimer) return;
            window.setTimeout(() => {
                poll(true);
                pollTimer = window.setInterval(() => poll(false), POLL_MS);
            }, INITIAL_DELAY_MS);
        });
    }

    function formatNearbyReportToastPreview(report) {
        if (!report) return '';
        const caption = String(report.caption || '').trim();
        if (caption) return caption;
        const categories = Array.isArray(report.categories) ? report.categories.filter(Boolean) : [];
        if (categories.length) return categories.join(' · ');
        return 'Nuevo reporte';
    }

    function showNearbyReportToast(options) {
        try {
            const postId = options && options.post_id != null ? Number(options.post_id) : null;
            if (!postId) return;

            try {
                if (window.location && window.location.pathname === `/post/${postId}`) return;
            } catch (_) {}

            const flash = document.getElementById('flashPopups');
            if (!flash) return;

            const categories = Array.isArray(options.categories) ? options.categories.filter(Boolean) : [];
            const primaryCategory = categories.length ? String(categories[0]) : 'Reporte';
            const imageUrl = String(options.image_url || '');
            const username = String(options.username || '');
            const messageText = String(options.message || '').trim();
            const distanceKm = Number(options.distance_km);
            const publishedAt = options.published_at || null;

            function fmtKm(km) {
                if (!Number.isFinite(km) || km < 0) return '';
                if (km < 0.1) return '<0.1 km';
                return `${km.toFixed(1)} km`;
            }

            const distLabel = fmtKm(distanceKm);
            const timeLabel = publishedAt ? relativeTime(publishedAt) : '';

            const toast = document.createElement('div');
            toast.className = 'alert violet-nearby-toast alert-dismissible fade show popup-alert';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            toast.setAttribute('aria-atomic', 'true');
            toast.setAttribute('data-post-id', String(postId));
            toast.innerHTML = `
                <div class="violet-nearby-toast__content">
                    <div class="violet-nearby-toast__thumb-wrap" aria-hidden="true">
                        ${imageUrl ? `<img class="violet-nearby-toast__thumb" src="${safeEscape(imageUrl)}" alt="">` : `<div class="violet-nearby-toast__thumb violet-nearby-toast__thumb--fallback"><i class="fa-solid fa-location-dot" aria-hidden="true"></i></div>`}
                    </div>
                    <div class="violet-nearby-toast__body">
                        <div class="violet-nearby-toast__title">Reporte cerca de ti</div>
                        <div class="violet-nearby-toast__meta">
                            ${distLabel ? `<span class="violet-nearby-toast__chip">${safeEscape(distLabel)}</span>` : ''}
                            <span class="violet-nearby-toast__chip violet-nearby-toast__chip--cat">${safeEscape(primaryCategory)}</span>
                            ${timeLabel ? `<span class="violet-nearby-toast__time">${safeEscape(timeLabel)}</span>` : ''}
                        </div>
                        <div class="violet-nearby-toast__message"><span class="violet-nearby-toast__user">${safeEscape(username)}</span>: ${safeEscape(messageText)}</div>
                    </div>
                    <button type="button" class="violet-nearby-toast__close" data-bs-dismiss="alert" aria-label="Cerrar">
                        <i class="fas fa-times" aria-hidden="true"></i>
                    </button>
                </div>
            `;

            toast.addEventListener('click', (e) => {
                if (e.target && e.target.closest && e.target.closest('[data-bs-dismiss="alert"]')) return;
                window.location.href = `/post/${encodeURIComponent(String(postId))}`;
            });

            flash.appendChild(toast);

            try {
                const all = flash.querySelectorAll('.violet-nearby-toast');
                const maxToasts = 1;
                if (all.length > maxToasts) {
                    for (let i = 0; i < all.length - maxToasts; i++) {
                        try { bootstrap.Alert.getOrCreateInstance(all[i]).close(); } catch (e) { all[i].remove(); }
                    }
                }
            } catch (e) {}

            if (typeof options.on_closed === 'function') {
                toast.addEventListener('closed.bs.alert', () => {
                    try { options.on_closed(); } catch (_) {}
                }, { once: true });
            }

            const duration = Number(options.duration_ms || 8000);
            window.setTimeout(() => {
                try {
                    bootstrap.Alert.getOrCreateInstance(toast).close();
                } catch (e) {
                    try { toast.remove(); } catch (e2) {}
                }
            }, Number.isFinite(duration) ? duration : 8000);
        } catch (e) {
            // Notification helpers should never break the page.
        }
    }

    function initNearbyReportToasts() {
        const POLL_MS = 15000;
        const INITIAL_DELAY_MS = 3000;
        const RADIUS_KM = 1;
        const GEO_TTL_MS = 25000;

        let lastSinceMs = null;
        let lastGeo = null;
        let pollTimer = null;
        const shownIds = new Set();
        const toastQueue = [];
        let toastShowing = false;
        let geoRequestReady = false;
        let geoPermissionDenied = false;

        function enqueueToast(payload) {
            toastQueue.push(payload);
            drainToastQueue();
        }

        function drainToastQueue() {
            if (toastShowing) return;
            const next = toastQueue.shift();
            if (!next) return;
            toastShowing = true;
            showNearbyReportToast({
                ...next,
                on_closed: () => {
                    toastShowing = false;
                    drainToastQueue();
                }
            });
        }

        function canRun() {
            if (!window.CURRENT_USER || !window.CURRENT_USER.is_authenticated) return false;
            if (window.USER_IS_VERIFIED === false) return false;
            if (!navigator.geolocation) return false;
            if (geoPermissionDenied) return false;
            return true;
        }

        function getGeo() {
            return new Promise((resolve) => {
                if (!geoRequestReady) {
                    resolve(null);
                    return;
                }
                if (lastGeo && (Date.now() - lastGeo.ts) < GEO_TTL_MS) {
                    resolve(lastGeo);
                    return;
                }

                navigator.geolocation.getCurrentPosition(
                    (pos) => {
                        try {
                            const lat = Number(pos.coords && pos.coords.latitude);
                            const lng = Number(pos.coords && pos.coords.longitude);
                            if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
                                resolve(null);
                                return;
                            }
                            lastGeo = { lat, lng, ts: Date.now() };
                            resolve(lastGeo);
                        } catch (e) {
                            resolve(null);
                        }
                    },
                    (err) => {
                        try {
                            if (err && err.code === 1) {
                                geoPermissionDenied = true;
                            }
                        } catch (_) {}
                        resolve(null);
                    },
                    {
                        enableHighAccuracy: false,
                        timeout: 8000,
                        maximumAge: 60000
                    }
                );
            });
        }

        async function poll(initial = false) {
            if (!canRun()) return;
            if (document.hidden) return;

            const geo = await getGeo();
            if (!geo) return;

            if (lastSinceMs == null) {
                lastSinceMs = Date.now();
                return;
            }

            try {
                let since = lastSinceMs;
                const maxLookbackMs = 2 * 60 * 1000;
                if (Number.isFinite(since) && (Date.now() - since) > maxLookbackMs) {
                    since = Date.now() - maxLookbackMs;
                }
                const url = `/api/reports/nearby?lat=${encodeURIComponent(String(geo.lat))}&lng=${encodeURIComponent(String(geo.lng))}&radius_km=${encodeURIComponent(String(RADIUS_KM))}&since=${encodeURIComponent(String(since))}`;
                const res = await fetch(url, { headers: { Accept: 'application/json' } });
                if (!res.ok) return;
                const data = await res.json();
                const reports = Array.isArray(data.reports) ? data.reports : [];

                lastSinceMs = Date.now();
                if (initial) return;

                reports.forEach((report) => {
                    if (!report || report.id == null) return;
                    const id = String(report.id);
                    if (shownIds.has(id)) return;
                    shownIds.add(id);

                    const msg = formatNearbyReportToastPreview(report);
                    if (!msg) return;

                    enqueueToast({
                        post_id: report.id,
                        image_url: report.image_url,
                        username: report.username,
                        message: msg,
                        categories: report.categories,
                        distance_km: report.distance_km,
                        published_at: report.published_at,
                    });
                });
            } catch (e) {
                // ignore transient polling failures
            }
        }

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) return;
            poll(false);
        });

        document.addEventListener('DOMContentLoaded', () => {
            if (pollTimer) return;

            const startPolling = () => {
                if (pollTimer) return;
                poll(true);
                pollTimer = window.setInterval(() => poll(false), POLL_MS);
            };

            try {
                if (navigator.permissions && typeof navigator.permissions.query === 'function') {
                    navigator.permissions.query({ name: 'geolocation' }).then((status) => {
                        const st = String(status && status.state || '');
                        if (st === 'granted') {
                            geoRequestReady = true;
                            window.setTimeout(startPolling, INITIAL_DELAY_MS);
                            return;
                        }
                        if (st === 'denied') {
                            geoPermissionDenied = true;
                            return;
                        }
                        const enable = () => {
                            geoRequestReady = true;
                            startPolling();
                        };
                        window.addEventListener('pointerdown', enable, { once: true, passive: true });
                        window.addEventListener('keydown', enable, { once: true });
                    }).catch(() => {
                        const enable = () => {
                            geoRequestReady = true;
                            startPolling();
                        };
                        window.addEventListener('pointerdown', enable, { once: true, passive: true });
                        window.addEventListener('keydown', enable, { once: true });
                    });
                } else {
                    const enable = () => {
                        geoRequestReady = true;
                        startPolling();
                    };
                    window.addEventListener('pointerdown', enable, { once: true, passive: true });
                    window.addEventListener('keydown', enable, { once: true });
                }
            } catch (_) {}
        });
    }

    window.showChatMessageToast = showChatMessageToast;
    window.showNearbyReportToast = showNearbyReportToast;

    initChatRoomToasts();
    initNearbyReportToasts();
})();
