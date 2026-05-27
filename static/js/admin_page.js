    const ADMIN_PAGE_CONFIG = window.ADMIN_PAGE_CONFIG || {};
    const ADMIN_CSRF_TOKEN = ADMIN_PAGE_CONFIG.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '';
    let currentUserId = null;
    let currentCoordsPostId = null;
    let currentCoordsButton = null;
    let changePhotoCropFile = null;
    let changePhotoCropper = null;
    let changePhotoCropModal = null;
    let changePhotoCropUrl = null;
    const AVATAR_UPLOAD_MAX_BYTES = 8 * 1024 * 1024;
    let assistedPasswordResetModal = null;
    let currentRoleUserId = null;
    let userRolesModal = null;
    let verificationEvidenceModal = null;
    const ADMIN_REPORT_PALETTE = ['#8b5cf6', '#a78bfa', '#f43f5e', '#10b981', '#3b82f6', '#f59e0b', '#ec4899', '#14b8a6'];
    const ADMIN_REPORT_COLOR_BY_REASON = {
        'Poca iluminación': '#f59e0b',
        'Banquetas en mal estado': '#3b82f6',
        'Zona insegura': '#f43f5e',
        'Zonas inseguras': '#f43f5e',
        'Terrenos baldíos': '#10b981',
        'Baldíos': '#10b981',
        'Baldios': '#10b981',
        'Punto ciego': '#10b981',
    };
    const ADMIN_ACTIVITY_STATE = {
        days: 7,
        timer: null,
        requestId: 0,
    };
    const ADMIN_ATTENTION_INITIAL = ADMIN_PAGE_CONFIG.attentionState || {};
    const ADMIN_ATTENTION_STATE = {
        timer: null,
        requestId: 0,
        initialized: false,
        total: Number(ADMIN_ATTENTION_INITIAL.reportsTotal || 0),
        latest: ADMIN_ATTENTION_INITIAL.latestReportCreatedAt || '',
    };

    function getGlobalSearchTerm() {
        return (document.getElementById('adminGlobalFilter')?.value || '').trim().toLowerCase();
    }

    function normalizeRangeDays(val) {
        const parsed = Number.parseInt(String(val || ''), 10);
        if ([7, 15, 30].includes(parsed)) return parsed;
        return 7;
    }

    function getReportSeriesColor(name, idx = 0) {
        if (ADMIN_REPORT_COLOR_BY_REASON[name]) return ADMIN_REPORT_COLOR_BY_REASON[name];
        return ADMIN_REPORT_PALETTE[idx % ADMIN_REPORT_PALETTE.length];
    }

    function buildChartXTicks(labels) {
        if (!Array.isArray(labels) || labels.length === 0) return [];
        if (labels.length <= 7) return labels;
        const result = [];
        const maxIdx = labels.length - 1;
        for (let i = 0; i < 7; i++) {
            const idx = Math.round((maxIdx * i) / 6);
            if (!result.includes(labels[idx])) {
                result.push(labels[idx]);
            }
        }
        return result;
    }

    function animateSeriesPath(pathEl) {
        if (!pathEl || typeof pathEl.getTotalLength !== 'function') return;
        const total = pathEl.getTotalLength();
        pathEl.style.strokeDasharray = `${total}`;
        pathEl.style.strokeDashoffset = `${total}`;
        requestAnimationFrame(() => {
            pathEl.style.transition = 'stroke-dashoffset 460ms ease';
            pathEl.style.strokeDashoffset = '0';
        });
        setTimeout(() => {
            pathEl.style.strokeDasharray = '';
            pathEl.style.strokeDashoffset = '';
            pathEl.style.transition = '';
        }, 540);
    }

    let currentReportsSubtab = ADMIN_PAGE_CONFIG.activeReportsSubtab || 'reportados';

    function applyReportsSubtabFilter() {
        if (currentReportsSubtab === 'reportados') {
            filterReportedPosts();
        } else if (currentReportsSubtab === 'reportes-chat') {
            filterReportedChatMessages();
        } else if (currentReportsSubtab === 'reportes-comentarios') {
            filterReportedComments();
        }
    }

    function applyActiveTabFilter() {
        const activeTabId = document.querySelector('#adminTabs .tab-btn.active')?.id;
        if (activeTabId === 'tab-users') {
            filterUsers();
        } else if (activeTabId === 'tab-posts') {
            filterPosts();
        } else if (activeTabId === 'tab-reportes') {
            applyReportsSubtabFilter();
        }
    }

    function removeTabDot(buttonSelector) {
        document.querySelector(`${buttonSelector} .tab-dot`)?.remove();
    }

    function ensureTabDot(buttonSelector) {
        const button = document.querySelector(buttonSelector);
        if (!button || button.querySelector('.tab-dot')) return;
        const dot = document.createElement('span');
        dot.className = 'tab-dot';
        button.insertBefore(dot, button.firstChild);
    }

    function normalizeAdminAttentionPayload(payload) {
        return {
            total: Number(payload?.admin_reports_total_count || 0),
            postReports: Number(payload?.post_reports_count || 0),
            reportedPosts: Number(payload?.reported_posts_count || 0),
            chatReports: Number(payload?.chat_message_reports_count || 0),
            commentReports: Number(payload?.comment_reports_count || 0),
            pendingChats: Number(payload?.pending_chat_rooms_count || 0),
            pendingVerifications: Number(payload?.pending_verifications_count || 0),
            pendingRecoveries: Number(payload?.pending_password_recovery_count || 0),
            latest: String(payload?.latest_admin_report_created_at || ''),
        };
    }

    function syncAdminAttentionDots(state) {
        if (!state) return;

        if (state.pendingRecoveries > 0) ensureTabDot('#tab-users');
        else removeTabDot('#tab-users');

        if (state.total > 0) ensureTabDot('#tab-reportes');
        else removeTabDot('#tab-reportes');

        if (state.reportedPosts > 0) ensureTabDot('#report-subtab-reportados');
        else removeTabDot('#report-subtab-reportados');

        if (state.chatReports > 0) ensureTabDot('#report-subtab-reportes-chat');
        else removeTabDot('#report-subtab-reportes-chat');

        if (state.commentReports > 0) ensureTabDot('#report-subtab-reportes-comentarios');
        else removeTabDot('#report-subtab-reportes-comentarios');

        if (state.pendingChats > 0) ensureTabDot('#tab-chats');
        else removeTabDot('#tab-chats');

        if (state.pendingVerifications > 0) ensureTabDot('#tab-verificaciones');
        else removeTabDot('#tab-verificaciones');
    }

    function showAdminReportNotification(state, previousState) {
        if (!state || state.total <= 0) return;
        document.querySelectorAll('.admin-report-toast').forEach((toast) => toast.remove());

        const increasedBy = Math.max(1, state.total - Number(previousState?.total || 0));
        const detail = [
            state.postReports ? `${state.postReports} de publicación` : '',
            state.chatReports ? `${state.chatReports} de chat` : '',
            state.commentReports ? `${state.commentReports} de comentario` : '',
        ].filter(Boolean).join(' · ');

        const toast = document.createElement('div');
        toast.className = 'admin-report-toast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        toast.innerHTML = `
            <div class="admin-report-toast__icon"><i class="fas fa-flag"></i></div>
            <div class="admin-report-toast__body">
                <div class="admin-report-toast__title">${increasedBy === 1 ? 'Nuevo reporte pendiente' : `${increasedBy} reportes nuevos`}</div>
                <div class="admin-report-toast__copy">${detail || `${state.total} reportes activos`} esperan revisión.</div>
            </div>
            <button class="admin-report-toast__action" type="button">Ver reportes</button>
            <button class="admin-report-toast__close" type="button" aria-label="Cerrar"><i class="fas fa-times"></i></button>
        `;

        toast.querySelector('.admin-report-toast__action')?.addEventListener('click', () => {
            const url = new URL('/admin', window.location.origin);
            url.searchParams.set('tab', 'reportes');
            window.location.assign(url.toString());
        });
        toast.querySelector('.admin-report-toast__close')?.addEventListener('click', () => toast.remove());
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('is-visible'));
        setTimeout(() => {
            toast.classList.remove('is-visible');
            setTimeout(() => toast.remove(), 260);
        }, 9000);
    }

    function fetchAdminAttentionState(options = {}) {
        const silent = !!options.silent;
        const suppressToast = !!options.suppressToast;
        const reqId = ++ADMIN_ATTENTION_STATE.requestId;
        return fetch(`/admin/attention-state?_ts=${Date.now()}`, {
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        })
            .then((response) => {
                if (!response.ok) throw new Error('No se pudo cargar el estado de reportes.');
                return response.json();
            })
            .then((payload) => {
                if (reqId !== ADMIN_ATTENTION_STATE.requestId || !payload?.success) return;
                const nextState = normalizeAdminAttentionPayload(payload);
                const previousState = {
                    total: ADMIN_ATTENTION_STATE.total,
                    latest: ADMIN_ATTENTION_STATE.latest,
                };
                const hasNewReports = ADMIN_ATTENTION_STATE.initialized
                    && !suppressToast
                    && nextState.total > 0
                    && (
                        nextState.total > previousState.total
                        || (nextState.latest && previousState.latest && nextState.latest > previousState.latest)
                    );

                ADMIN_ATTENTION_STATE.initialized = true;
                ADMIN_ATTENTION_STATE.total = nextState.total;
                ADMIN_ATTENTION_STATE.latest = nextState.latest;
                syncAdminAttentionDots(nextState);

                if (hasNewReports) {
                    showAdminReportNotification(nextState, previousState);
                }
            })
            .catch((error) => {
                if (!silent) console.error('admin attention state error:', error);
            });
    }

    function startAdminAttentionPolling() {
        if (ADMIN_ATTENTION_STATE.timer) {
            clearInterval(ADMIN_ATTENTION_STATE.timer);
        }
        fetchAdminAttentionState({ silent: true, suppressToast: true });
        ADMIN_ATTENTION_STATE.timer = setInterval(() => {
            fetchAdminAttentionState({ silent: true });
        }, 30000);
    }

    function syncPostsViewState() {
        const grid = document.getElementById('postsGrid');
        if (!grid) return;
        if (grid.querySelector('.post-item')) return;
        grid.innerHTML = `
            <div class="col-12">
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-image fa-3x mb-3 opacity-50"></i>
                    <h4>No hay publicaciones</h4>
                    <p>Aún no se han creado publicaciones en la plataforma.</p>
                </div>
            </div>
        `;
    }

    function syncUsersViewState() {
        const list = document.getElementById('usersList');
        if (!list) return;
        if (list.querySelector('.user-item')) return;
        list.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-5 text-muted">
                    <i class="fas fa-users fa-2x mb-3 opacity-50 d-block"></i>
                    <div class="fw-semibold text-white">No hay usuarias</div>
                    <div class="small text-secondary">No quedan usuarias en esta vista.</div>
                </td>
            </tr>
        `;
    }

    function syncUsersAttentionState() {
        const pendingRecoveryCount = document.querySelectorAll('.user-item[data-password-recovery-pending="1"]').length;
        const chip = document.getElementById('pendingRecoveryChip');
        if (pendingRecoveryCount === 0) {
            chip?.remove();
            removeTabDot('#tab-users');
            return;
        }
        if (chip) {
            chip.innerHTML = `
                <i class="fas fa-key"></i>
                ${pendingRecoveryCount} solicitud${pendingRecoveryCount === 1 ? '' : 'es'} de recuperación pendiente${pendingRecoveryCount === 1 ? '' : 's'}
            `;
        }
    }

    function syncPendingChatRoomsState() {
        const pendingList = document.getElementById('pendingChatRoomsList');
        if (!pendingList) return;
        if (pendingList.querySelector('.pending-chat-room-item')) return;
        pendingList.innerHTML = '<div class="text-muted small">No hay solicitudes pendientes.</div>';
        removeTabDot('#tab-chats');
    }

    function syncAllChatRoomsState() {
        const allRoomsList = document.getElementById('allChatRoomsList');
        if (!allRoomsList) return;
        if (allRoomsList.querySelector('.admin-chat-room-item')) return;
        allRoomsList.innerHTML = '<div class="text-muted small">No hay salas creadas.</div>';
    }

    function syncVerificationState() {
        const list = document.getElementById('verificationList');
        const counter = document.getElementById('pendingVerificationsCountText');
        if (!list) return;
        const remainingPending = list.querySelectorAll('.verification-item[data-verification-status="pending"]').length;
        const remainingItems = list.querySelectorAll('.verification-item').length;
        if (counter) {
            counter.textContent = `Pendientes: ${remainingPending}`;
        }
        if (remainingPending === 0) {
            removeTabDot('#tab-verificaciones');
        }
        if (remainingItems === 0) {
            list.innerHTML = '<div class="col-12"><div class="text-secondary">No hay verificaciones pendientes.</div></div>';
        }
    }

    function syncReportAttentionState() {
        const reportedCount = document.querySelectorAll('#reportedGrid .reported-item').length;
        const reportedChatCount = document.querySelectorAll('#reportedChatGrid .reported-chat-item').length;
        const reportedCommentCount = document.querySelectorAll('#reportedCommentsGrid .reported-comment-item').length;

        if (reportedCount === 0) removeTabDot('#report-subtab-reportados');
        if (reportedChatCount === 0) removeTabDot('#report-subtab-reportes-chat');
        if (reportedCommentCount === 0) removeTabDot('#report-subtab-reportes-comentarios');
        if (reportedCount === 0 && reportedChatCount === 0 && reportedCommentCount === 0) {
            removeTabDot('#tab-reportes');
        }
        fetchAdminAttentionState({ silent: true, suppressToast: true });
    }

    function ensureReportedGridEmptyState(gridId, itemSelector, message) {
        const grid = document.getElementById(gridId);
        if (!grid) return;
        if (grid.querySelector(itemSelector)) return;
        grid.innerHTML = `
            <div class="col-12">
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-shield-alt fa-3x mb-3 opacity-50"></i>
                    <h4>No hay reportes pendientes</h4>
                    <p>${message}</p>
                </div>
            </div>
        `;
    }

    function switchReportsSubtab(tabName) {
        currentReportsSubtab = tabName;
        const nextUrl = new URL(window.location.href);
        nextUrl.searchParams.set('tab', 'reportes');
        nextUrl.searchParams.set('reports_subtab', tabName);
        nextUrl.searchParams.delete('page');
        window.location.assign(nextUrl.toString());
    }

    function switchTab(tabName) {
        const nextUrl = new URL(window.location.href);
        nextUrl.searchParams.set('tab', tabName);
        nextUrl.searchParams.delete('page');
        window.location.assign(nextUrl.toString());
    }

    function renderAdminActivityChart(payload, options = {}) {
        const animate = !!options.animate;
        const svg = document.getElementById('adminActivityChart');
        const seriesGroup = document.getElementById('adminActivitySeries');
        const dotsGroup = document.getElementById('adminActivityDots');
        const gridGroup = document.getElementById('adminActivityGrid');
        const labelsWrap = document.getElementById('adminActivityXLabels');
        const legendWrap = document.getElementById('adminActivityLegend');
        const subtitleEl = document.getElementById('adminActivitySubtitle');
        const updatedEl = document.getElementById('adminActivityUpdatedAt');
        const chartWrap = document.getElementById('adminActivityChartWrap');
        if (!svg || !seriesGroup || !dotsGroup || !gridGroup) return;

        const labels = Array.isArray(payload?.labels) ? payload.labels : [];
        const categories = Array.isArray(payload?.categories) ? payload.categories : [];
        const days = normalizeRangeDays(payload?.days || ADMIN_ACTIVITY_STATE.days);
        const totalPosts = Number(payload?.total_posts || payload?.total_reports || 0);
        const maxVal = Math.max(
            1,
            ...categories.flatMap((serie) => Array.isArray(serie.counts) ? serie.counts : [0]),
        );
        const width = 720;
        const height = 300;
        const left = 18;
        const right = 14;
        const top = 12;
        const bottom = 28;
        const innerW = width - left - right;
        const innerH = height - top - bottom;
        const pointCount = Math.max(labels.length, 2);
        const stepX = innerW / (pointCount - 1);

        if (chartWrap && animate) {
            chartWrap.classList.remove('is-updating');
            void chartWrap.offsetWidth;
            chartWrap.classList.add('is-updating');
            setTimeout(() => chartWrap.classList.remove('is-updating'), 400);
        }

        seriesGroup.innerHTML = '';
        dotsGroup.innerHTML = '';

        categories.forEach((serie, idx) => {
            const counts = Array.isArray(serie.counts) ? serie.counts : [];
            if (!counts.length) return;
            const color = serie.color || getReportSeriesColor(serie.name || '', idx);
            const points = counts.map((v, i) => {
                const x = left + stepX * i;
                const y = top + innerH - ((Number(v || 0) / maxVal) * innerH);
                return { x, y, value: Number(v || 0) };
            });
            const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
            const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            pathEl.setAttribute('d', d);
            pathEl.setAttribute('stroke', color);
            pathEl.setAttribute('data-series', serie.name || `Serie ${idx + 1}`);
            seriesGroup.appendChild(pathEl);
            if (animate) animateSeriesPath(pathEl);

            points.forEach((p) => {
                if (p.value <= 0) return;
                const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                dot.setAttribute('cx', p.x.toFixed(2));
                dot.setAttribute('cy', p.y.toFixed(2));
                dot.setAttribute('r', '3.6');
                dot.setAttribute('stroke', color);
                dotsGroup.appendChild(dot);
            });
        });

        gridGroup.innerHTML = Array.from({ length: 5 }).map((_, idx) => {
            const y = top + (innerH / 4) * idx;
            return `<line x1="${left}" y1="${y.toFixed(2)}" x2="${left + innerW}" y2="${y.toFixed(2)}"></line>`;
        }).join('');

        if (labelsWrap) {
            const ticks = buildChartXTicks(labels);
            labelsWrap.innerHTML = ticks.map((lab) => `<span>${lab}</span>`).join('');
        }

        if (subtitleEl) {
            subtitleEl.textContent = `${totalPosts} publicaciones categorizadas en los últimos ${days} días`;
        }

        if (legendWrap) {
            if (!categories.length) {
                legendWrap.innerHTML = `<span class="small text-secondary">Aún no hay publicaciones categorizadas en este rango.</span>`;
            } else {
                legendWrap.innerHTML = categories.map((serie, idx) => {
                    const color = serie.color || getReportSeriesColor(serie.name || '', idx);
                    return `
                        <div class="admin-legend-item">
                            <span class="admin-legend-swatch" style="background:${color}"></span>
                            <span class="admin-legend-name">${serie.name}</span>
                            <span class="admin-legend-total">${serie.total} pub.</span>
                        </div>
                    `;
                }).join('');
            }
        }

        if (updatedEl) {
            const now = new Date(payload?.updated_at || Date.now());
            updatedEl.textContent = `Actualizado: ${now.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
        }
    }

    function fetchAdminActivity(days, options = {}) {
        const requestedDays = normalizeRangeDays(days || ADMIN_ACTIVITY_STATE.days);
        const animate = !!options.animate;
        const silent = !!options.silent;
        ADMIN_ACTIVITY_STATE.days = requestedDays;
        const reqId = ++ADMIN_ACTIVITY_STATE.requestId;
        return fetch(`/admin/reports_timeseries?days=${requestedDays}&_ts=${Date.now()}`, { cache: 'no-store' })
            .then((res) => {
                if (!res.ok) throw new Error('No se pudo cargar la analítica');
                return res.json();
            })
            .then((data) => {
                if (reqId !== ADMIN_ACTIVITY_STATE.requestId) return;
                renderAdminActivityChart(data, { animate });
            })
            .catch((err) => {
                if (!silent) {
                    console.error('admin reports chart error:', err);
                }
            });
    }

    function wireAdminActivityControls() {
        const rangeSelect = document.getElementById('adminReportsRangeSelect');
        if (rangeSelect) {
            rangeSelect.addEventListener('change', () => {
                const days = normalizeRangeDays(rangeSelect.value);
                fetchAdminActivity(days, { animate: true });
            });
        }
    }

    function startAdminActivityAutoRefresh() {
        if (ADMIN_ACTIVITY_STATE.timer) {
            clearInterval(ADMIN_ACTIVITY_STATE.timer);
        }
        ADMIN_ACTIVITY_STATE.timer = setInterval(() => {
            fetchAdminActivity(ADMIN_ACTIVITY_STATE.days, { animate: false, silent: true });
        }, 45000);
    }

    function deleteUser(userId, username) {
        if (confirm(`¿Estás segura de que quieres eliminar a la usuaria "${username}"? Esta acción no se puede deshacer.`)) {
            fetch(`/admin/delete_user/${userId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': ADMIN_CSRF_TOKEN
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(data.message);
                        const item = document.querySelector(`.user-item[data-user-id="${userId}"]`);
                        item?.remove();
                        syncUsersViewState();
                        syncUsersAttentionState();
                        wireBulkSelection('selectAllUsers', '.user-select', 'usersSelectedCount');
                        if (!item) {
                            location.reload();
                        }
                    } else {
                        alert('Error: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('Error al eliminar usuaria');
                });
        }
    }

    function ensureAssistedPasswordResetModal() {
        if (assistedPasswordResetModal || !window.bootstrap) return assistedPasswordResetModal;
        const modalEl = document.getElementById('assistedPasswordResetModal');
        if (!modalEl) return null;
        assistedPasswordResetModal = new bootstrap.Modal(modalEl);
        return assistedPasswordResetModal;
    }

    function showAssistedPasswordResetModal(payload) {
        const usernameEl = document.getElementById('assistedResetUsername');
        const emailEl = document.getElementById('assistedResetEmail');
        const valueEl = document.getElementById('assistedResetPasswordValue');
        const copyBtn = document.getElementById('assistedResetCopyBtn');
        const modalEl = document.getElementById('assistedPasswordResetModal');
        if (!usernameEl || !emailEl || !valueEl) {
            alert(`Contraseña temporal para ${payload.username}: ${payload.temporaryPassword}`);
            return;
        }

        usernameEl.textContent = payload.username || 'la usuaria';
        emailEl.textContent = payload.email || '';
        valueEl.value = payload.temporaryPassword || '';
        if (copyBtn) {
            copyBtn.textContent = 'Copiar';
        }

        const modal = ensureAssistedPasswordResetModal();
        if (modal) {
            if (modalEl) {
                modalEl.addEventListener('hidden.bs.modal', () => {
                    window.location.reload();
                }, { once: true });
            }
            modal.show();
        } else {
            alert(`Contraseña temporal para ${payload.username}: ${payload.temporaryPassword}`);
        }
    }

    function issueAssistedPasswordReset(userId, username, email) {
        const confirmed = confirm(`Se generará una contraseña temporal para "${username}". La usuaria tendrá que cambiarla al iniciar sesión. ¿Continuar?`);
        if (!confirmed) return;

        fetch(`/admin/user/${userId}/assisted_password_reset`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo generar la contraseña temporal.');
                }
                return data;
            })
            .then((data) => {
                showAssistedPasswordResetModal({
                    username: data.username || username,
                    email: data.email || email,
                    temporaryPassword: data.temporary_password || '',
                });
            })
            .catch((error) => {
                console.error('assisted password reset error:', error);
                alert(error.message || 'No se pudo generar la contraseña temporal.');
            });
    }

    function deletePost(postId) {
        if (confirm('¿Estás seguro de que quieres eliminar esta publicación? Esta acción no se puede deshacer.')) {
            fetch(`/admin/delete_post/${postId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': ADMIN_CSRF_TOKEN
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(data.message);
                        const removed = document.querySelectorAll(`.post-item[data-post-id="${postId}"], .reported-item[data-post-id="${postId}"]`);
                        removed.forEach((item) => item.remove());
                        syncPostsViewState();
                        ensureReportedGridEmptyState('reportedGrid', '.reported-item', 'Todas las publicaciones reportadas ya fueron revisadas.');
                        syncReportAttentionState();
                        if (!removed.length) {
                            location.reload();
                        }
                    } else {
                        alert('Error: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('Error al eliminar publicación');
                });
        }
    }

    function restorePost(postId) {
        if (confirm('¿Quieres restaurar esta publicación para que vuelva a mostrarse?')) {
            fetch(`/admin/restore_post/${postId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': ADMIN_CSRF_TOKEN
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const removed = document.querySelectorAll(`.reported-item[data-post-id="${postId}"]`);
                        removed.forEach((item) => item.remove());
                        ensureReportedGridEmptyState('reportedGrid', '.reported-item', 'Todas las publicaciones reportadas ya fueron revisadas.');
                        syncReportAttentionState();
                        if (!removed.length) {
                            location.reload();
                        }
                    } else {
                        alert('Error: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('Error al restaurar publicación');
                });
        }
    }

    function editUsername(userId, currentUsername) {
        currentUserId = userId;
        document.getElementById('newUsername').value = currentUsername;
        new bootstrap.Modal(document.getElementById('editUsernameModal')).show();
    }

    function saveUsername() {
        const newUsername = document.getElementById('newUsername').value.trim();
        if (!newUsername) {
            alert('El username no puede estar vacío');
            return;
        }

        const formData = new FormData();
        formData.append('new_username', newUsername);

        fetch(`/admin/change_username/${currentUserId}`, {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error al cambiar username');
            });
    }

    function openUserRolesModal(userId, username, roles) {
        currentRoleUserId = userId;
        const modalEl = document.getElementById('userRolesModal');
        const subtitle = document.getElementById('userRolesSubtitle');
        const errorBox = document.getElementById('userRolesError');
        if (!modalEl) return;

        const selectedRoles = new Set(Array.isArray(roles) ? roles.map((role) => String(role || '').trim().toLowerCase()) : []);
        modalEl.querySelectorAll('.staff-role-checkbox').forEach((input) => {
            input.checked = selectedRoles.has(String(input.value || '').toLowerCase());
        });
        if (subtitle) {
            subtitle.textContent = `Roles de @${username || 'usuaria'}`;
        }
        if (errorBox) {
            errorBox.classList.add('d-none');
            errorBox.textContent = '';
        }

        userRolesModal = userRolesModal || new bootstrap.Modal(modalEl);
        userRolesModal.show();
    }

    async function saveUserRoles() {
        if (!currentRoleUserId) return;
        const modalEl = document.getElementById('userRolesModal');
        const errorBox = document.getElementById('userRolesError');
        const saveBtn = document.getElementById('saveUserRolesBtn');
        const roles = Array.from(modalEl?.querySelectorAll('.staff-role-checkbox:checked') || [])
            .map((input) => String(input.value || '').trim())
            .filter(Boolean);

        if (errorBox) {
            errorBox.classList.add('d-none');
            errorBox.textContent = '';
        }
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = 'Guardando...';
        }

        try {
            const response = await fetch(`/admin/user/${currentRoleUserId}/roles`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': ADMIN_CSRF_TOKEN,
                },
                body: JSON.stringify({ roles }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.success) {
                throw new Error(payload.error || 'No se pudieron guardar los roles.');
            }
            location.reload();
        } catch (error) {
            if (errorBox) {
                errorBox.textContent = error.message || 'No se pudieron guardar los roles.';
                errorBox.classList.remove('d-none');
            } else {
                alert(error.message || 'No se pudieron guardar los roles.');
            }
        } finally {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Guardar roles';
            }
        }
    }

    function resetVerificationEvidencePreview() {
        const video = document.getElementById('verificationEvidenceVideo');
        const source = document.getElementById('verificationEvidenceVideoSource');
        const image = document.getElementById('verificationEvidenceImage');
        const fallback = document.getElementById('verificationEvidenceFallback');
        if (video) {
            video.pause();
            video.classList.add('d-none');
            video.removeAttribute('src');
        }
        if (source) {
            source.src = '';
            source.type = '';
        }
        if (image) {
            image.classList.add('d-none');
            image.removeAttribute('src');
        }
        fallback?.classList.add('d-none');
    }

    function openVerificationEvidence(reqId, username, evidenceUrl, mimeType, evidenceType) {
        const modalEl = document.getElementById('verificationEvidenceModal');
        if (!modalEl || !evidenceUrl) return;

        resetVerificationEvidencePreview();

        const subtitle = document.getElementById('verificationEvidenceSubtitle');
        const openLink = document.getElementById('verificationEvidenceOpenLink');
        const fallbackLink = document.getElementById('verificationEvidenceFallbackLink');
        const video = document.getElementById('verificationEvidenceVideo');
        const source = document.getElementById('verificationEvidenceVideoSource');
        const image = document.getElementById('verificationEvidenceImage');
        const fallback = document.getElementById('verificationEvidenceFallback');

        if (subtitle) {
            subtitle.textContent = `Solicitud #${reqId} · @${username || 'usuaria'}`;
        }
        [openLink, fallbackLink].forEach((link) => {
            if (link) {
                link.href = evidenceUrl;
            }
        });

        const normalizedType = String(evidenceType || '').toLowerCase();
        const normalizedMime = String(mimeType || '').toLowerCase();
        if (normalizedType === 'video' || normalizedMime.startsWith('video/')) {
            if (source && video) {
                source.src = evidenceUrl;
                source.type = mimeType || 'video/webm';
                video.classList.remove('d-none');
                video.load();
            }
        } else if (normalizedType === 'image' || normalizedMime.startsWith('image/')) {
            if (image) {
                image.src = evidenceUrl;
                image.classList.remove('d-none');
            }
        } else {
            fallback?.classList.remove('d-none');
        }

        verificationEvidenceModal = verificationEvidenceModal || new bootstrap.Modal(modalEl);
        verificationEvidenceModal.show();
    }

    function bindVerificationEvidenceModal() {
        const modalEl = document.getElementById('verificationEvidenceModal');
        if (!modalEl || modalEl.dataset.evidenceResetBound === '1') return;
        modalEl.dataset.evidenceResetBound = '1';
        modalEl.addEventListener('hidden.bs.modal', resetVerificationEvidencePreview);
    }

    function changePhoto(userId, photoUrl, userBio) {
        currentUserId = userId;
        document.getElementById('photoFile').value = '';
        changePhotoCropFile = null;
        if (changePhotoCropUrl) {
            URL.revokeObjectURL(changePhotoCropUrl);
            changePhotoCropUrl = null;
        }
        const preview = document.getElementById('changePhotoPreview');
        const bioInput = document.getElementById('changePhotoBio');
        if (preview && photoUrl) {
            preview.src = photoUrl;
        }
        if (bioInput) {
            bioInput.value = (userBio || '').slice(0, 50);
        }
        new bootstrap.Modal(document.getElementById('changePhotoModal')).show();
    }

    function savePhoto() {
        const fileInput = document.getElementById('photoFile');
        const fileToSend = changePhotoCropFile || fileInput.files[0];
        const bioInput = document.getElementById('changePhotoBio');
        const bioValue = bioInput ? bioInput.value.trim() : '';
        if (bioValue.length > 50) {
            alert('La biografía debe tener máximo 50 caracteres.');
            return;
        }
        if (!fileToSend && !bioValue) {
            alert('Selecciona una imagen o agrega una descripción.');
            return;
        }
        if (fileToSend && fileToSend.size > AVATAR_UPLOAD_MAX_BYTES) {
            alert('La foto de perfil es demasiado grande. Usa una imagen de máximo 8 MB.');
            return;
        }

        const formData = new FormData();
        if (fileToSend) {
            formData.append('photo', fileToSend);
        }
        formData.append('bio', bioValue);

        fetch(`/admin/change_user_photo/${currentUserId}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            },
            body: formData
        })
            .then(async response => {
                const isJson = response.headers.get('content-type')?.includes('application/json');
                const data = isJson ? await response.json() : { success: false, error: 'Respuesta inválida' };
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo cambiar la foto');
                }
                return data;
            })
            .then(() => location.reload())
            .catch(error => {
                console.error('Error:', error);
                alert(error.message || 'Error al cambiar foto');
            });
    }

    function approveChatRoom(roomId) {
        fetch(`/admin/approve_chat_room/${roomId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const pendingItem = document.querySelector(`.pending-chat-room-item[data-room-id="${roomId}"]`);
                    pendingItem?.remove();
                    const roomRow = document.querySelector(`.admin-chat-room-item[data-room-id="${roomId}"]`);
                    const badge = roomRow?.querySelector('.chat-room-status-badge');
                    if (badge) {
                        badge.className = 'badge bg-success chat-room-status-badge';
                        badge.textContent = 'Activa';
                    }
                    syncPendingChatRoomsState();
                    if (!pendingItem && !roomRow) {
                        location.reload();
                    }
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error al aprobar sala');
            });
    }

    function deleteChatRoom(roomId) {
        if (!confirm('¿Eliminar esta sala? Esta acción no se puede deshacer.')) return;
        fetch(`/admin/delete_chat_room/${roomId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const pendingItem = document.querySelector(`.pending-chat-room-item[data-room-id="${roomId}"]`);
                    const roomRow = document.querySelector(`.admin-chat-room-item[data-room-id="${roomId}"]`);
                    pendingItem?.remove();
                    roomRow?.remove();
                    syncPendingChatRoomsState();
                    syncAllChatRoomsState();
                    if (!pendingItem && !roomRow) {
                        location.reload();
                    }
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error al eliminar sala');
            });
    }

    (function () {
        const fileInput = document.getElementById('photoFile');
        const pickBtn = document.getElementById('photoPickBtn');
        const preview = document.getElementById('changePhotoPreview');
        const changeModalEl = document.getElementById('changePhotoModal');
        const cropModalEl = document.getElementById('changePhotoCropperModal');
        const cropImage = document.getElementById('changePhotoCropperImage');
        const cropApplyBtn = document.getElementById('changePhotoApplyCropBtn');
        const cropChooseBtn = document.getElementById('changePhotoChooseCropBtn');
        let cropperReady = false;

        function ensureCropperModal() {
            if (cropperReady) return true;
            if (!cropModalEl || !window.bootstrap || typeof Cropper === 'undefined') {
                return false;
            }
            changePhotoCropModal = new bootstrap.Modal(cropModalEl, {
                backdrop: false,
                focus: false,
                keyboard: true
            });
            cropModalEl.addEventListener('shown.bs.modal', () => {
                if (!cropImage || typeof Cropper === 'undefined') return;
                if (changePhotoCropper) changePhotoCropper.destroy();
                changePhotoCropper = new Cropper(cropImage, {
                    aspectRatio: 1,
                    viewMode: 1,
                    dragMode: 'crop',
                    autoCropArea: 1,
                    restore: false,
                    guides: true,
                    center: true,
                    highlight: true,
                    cropBoxMovable: true,
                    cropBoxResizable: true,
                    zoomable: true,
                    zoomOnWheel: true,
                    zoomOnTouch: true,
                    toggleDragModeOnDblclick: false
                });
            });
            cropModalEl.addEventListener('hidden.bs.modal', () => {
                if (changePhotoCropper) {
                    changePhotoCropper.destroy();
                    changePhotoCropper = null;
                }
                if (changePhotoCropUrl) {
                    URL.revokeObjectURL(changePhotoCropUrl);
                    changePhotoCropUrl = null;
                }
                if (fileInput) fileInput.value = '';
                const changeModalOpen = changeModalEl && changeModalEl.classList.contains('show');
                const backdrops = document.querySelectorAll('.modal-backdrop');
                if (changeModalOpen) {
                    backdrops.forEach((bd, idx) => {
                        if (idx > 0) bd.remove();
                    });
                    document.body.classList.add('modal-open');
                } else {
                    backdrops.forEach((bd) => bd.remove());
                    document.body.classList.remove('modal-open');
                    document.body.classList.remove('change-photo-open');
                }
            });
            cropperReady = true;
            return true;
        }

        function openCropper(file) {
            if (!ensureCropperModal() || !cropImage) {
                changePhotoCropFile = file;
                if (preview) {
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                        preview.src = ev.target.result;
                    };
                    reader.readAsDataURL(file);
                }
                return;
            }

            changePhotoCropFile = file;
            if (changePhotoCropUrl) {
                URL.revokeObjectURL(changePhotoCropUrl);
            }
            changePhotoCropUrl = URL.createObjectURL(file);
            cropImage.src = changePhotoCropUrl;
            changePhotoCropModal.show();
        }

        if (cropApplyBtn) {
            cropApplyBtn.addEventListener('click', () => {
                if (!changePhotoCropper || !changePhotoCropFile) return;
                const outputType = changePhotoCropFile.type === 'image/png' ? 'image/png' : 'image/jpeg';
                const canvas = changePhotoCropper.getCroppedCanvas({
                    width: 512,
                    height: 512,
                    fillColor: '#000'
                });
                if (!canvas) return;
                const quality = outputType === 'image/jpeg' ? 0.86 : undefined;
                canvas.toBlob((blob) => {
                    if (!blob) return;
                    if (blob.size > AVATAR_UPLOAD_MAX_BYTES) {
                        alert('La foto de perfil es demasiado grande. Usa una imagen de máximo 8 MB.');
                        return;
                    }
                    changePhotoCropFile = new File([blob], changePhotoCropFile.name || `avatar-${Date.now()}.jpg`, { type: outputType });
                    if (preview) {
                        const url = URL.createObjectURL(blob);
                        preview.src = url;
                    }
                    if (changePhotoCropModal) changePhotoCropModal.hide();
                }, outputType, quality);
            });
        }

        if (cropChooseBtn) {
            cropChooseBtn.addEventListener('click', () => {
                if (changePhotoCropModal) changePhotoCropModal.hide();
                if (fileInput) fileInput.click();
            });
        }

        if (pickBtn && fileInput) {
            pickBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;
                openCropper(file);
            });
        }
        if (changeModalEl) {
            changeModalEl.addEventListener('show.bs.modal', () => {
                document.body.classList.add('change-photo-open');
            });
            changeModalEl.addEventListener('hidden.bs.modal', () => {
                document.body.classList.remove('change-photo-open');
                changePhotoCropFile = null;
                if (changePhotoCropUrl) {
                    URL.revokeObjectURL(changePhotoCropUrl);
                    changePhotoCropUrl = null;
                }
            });
        }
    })();

    function requestAdminModerationNote(actionLabel) {
        return (prompt(`Nota opcional para ${actionLabel}:`) || '').trim();
    }

    function runReportAction(url, options) {
        const { confirmMessage, actionLabel, successFallback, removeSelector, gridId, itemSelector, emptyMessage } = options;
        if (confirmMessage && !confirm(confirmMessage)) return;
        const adminNote = requestAdminModerationNote(actionLabel);
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            },
            body: JSON.stringify({ admin_note: adminNote })
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    alert('Error: ' + (data.error || 'No se pudo completar la acción.'));
                    return;
                }
                alert(data.message || successFallback);
                let removed = 0;
                if (removeSelector) {
                    const nodes = document.querySelectorAll(removeSelector);
                    removed = nodes.length;
                    nodes.forEach((node) => node.remove());
                }
                if (gridId && itemSelector && emptyMessage) {
                    ensureReportedGridEmptyState(gridId, itemSelector, emptyMessage);
                }
                syncReportAttentionState();
                if (!removed) {
                    location.reload();
                }
            })
            .catch(() => alert('Error al completar la acción.'));
    }

    function restorePostReport(reportId) {
        runReportAction(`/admin/report/${reportId}/restore`, {
            confirmMessage: '¿Restaurar esta publicación para que vuelva a mostrarse?',
            actionLabel: 'restaurar la publicación',
            successFallback: 'La publicación fue restaurada.',
            removeSelector: `.reported-item[data-report-id="${reportId}"]`,
            gridId: 'reportedGrid',
            itemSelector: '.reported-item',
            emptyMessage: 'Todas las publicaciones reportadas ya fueron revisadas.'
        });
    }

    function strikePostReport(reportId) {
        runReportAction(`/admin/report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de esta publicación?',
            actionLabel: 'mandar el strike a la usuaria por esta publicación',
            successFallback: 'La publicación quedó sancionada.',
            removeSelector: `.reported-item[data-report-id="${reportId}"]`,
            gridId: 'reportedGrid',
            itemSelector: '.reported-item',
            emptyMessage: 'Todas las publicaciones reportadas ya fueron revisadas.'
        });
    }

    function filterReportedChatMessages() {
        const term = getGlobalSearchTerm();
        const items = document.querySelectorAll('.reported-chat-item');
        items.forEach(item => {
            const haystack = ((item.getAttribute('data-search') || '') + ' ' + (item.textContent || '')).toLowerCase();
            item.classList.toggle('d-none', !!term && !haystack.includes(term));
        });
    }

    function filterReportedComments() {
        const term = getGlobalSearchTerm();
        const items = document.querySelectorAll('.reported-comment-item');
        items.forEach(item => {
            const haystack = ((item.getAttribute('data-search') || '') + ' ' + (item.textContent || '')).toLowerCase();
            item.classList.toggle('d-none', !!term && !haystack.includes(term));
        });
    }

    function restoreChatMessageReport(reportId) {
        runReportAction(`/admin/chat_report/${reportId}/restore`, {
            confirmMessage: '¿Restaurar este mensaje para que vuelva a verse en el chat?',
            actionLabel: 'restaurar el mensaje',
            successFallback: 'El mensaje fue restaurado.',
            removeSelector: `.reported-chat-item[data-report-id="${reportId}"]`,
            gridId: 'reportedChatGrid',
            itemSelector: '.reported-chat-item',
            emptyMessage: 'Todos los mensajes reportados ya fueron revisados.'
        });
    }

    function strikeChatMessageReport(reportId) {
        runReportAction(`/admin/chat_report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de este mensaje?',
            actionLabel: 'mandar el strike a la usuaria por este mensaje',
            successFallback: 'El mensaje quedó sancionado.',
            removeSelector: `.reported-chat-item[data-report-id="${reportId}"]`,
            gridId: 'reportedChatGrid',
            itemSelector: '.reported-chat-item',
            emptyMessage: 'Todos los mensajes reportados ya fueron revisados.'
        });
    }

    function restoreCommentReport(reportId) {
        runReportAction(`/admin/comment_report/${reportId}/restore`, {
            confirmMessage: '¿Restaurar este comentario para que vuelva a mostrarse?',
            actionLabel: 'restaurar el comentario',
            successFallback: 'El comentario fue restaurado.',
            removeSelector: `.reported-comment-item[data-report-id="${reportId}"]`,
            gridId: 'reportedCommentsGrid',
            itemSelector: '.reported-comment-item',
            emptyMessage: 'Todos los comentarios reportados ya fueron revisados.'
        });
    }

    function strikeCommentReport(reportId) {
        runReportAction(`/admin/comment_report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de este comentario?',
            actionLabel: 'mandar el strike a la usuaria por este comentario',
            successFallback: 'El comentario quedó sancionado.',
            removeSelector: `.reported-comment-item[data-report-id="${reportId}"]`,
            gridId: 'reportedCommentsGrid',
            itemSelector: '.reported-comment-item',
            emptyMessage: 'Todos los comentarios reportados ya fueron revisados.'
        });
    }

    function bindAdminEditButtons() {
        document.querySelectorAll('.edit-user-btn').forEach((btn) => {
            if (btn.dataset.adminEditBound === '1') {
                return;
            }
            btn.dataset.adminEditBound = '1';
            btn.addEventListener('click', () => {
                const userId = btn.getAttribute('data-user-id');
                const photoUrl = btn.getAttribute('data-photo-url');
                const bio = btn.getAttribute('data-bio') || '';
                changePhoto(userId, photoUrl, bio);
            });
        });
    }

    function updateLocationCardDisplay(triggerBtn) {
        if (!triggerBtn) return;
        const card = triggerBtn.closest('.flip-card');
        const back = card ? card.querySelector('.post-location-back') : null;
        if (!card || !back) return;

        const lat = (triggerBtn.getAttribute('data-lat') || '').trim();
        const lng = (triggerBtn.getAttribute('data-lng') || '').trim();
        const locationName = (triggerBtn.getAttribute('data-location-name') || '').trim();
        const city = (triggerBtn.getAttribute('data-city') || '').trim();
        const country = (triggerBtn.getAttribute('data-country') || '').trim();

        const nameEl = back.querySelector('.location-name-text');
        if (nameEl) nameEl.textContent = locationName || 'Sin ubicación asignada';

        const cityEl = back.querySelector('.location-city-text');
        if (cityEl) cityEl.textContent = city;

        const countryEl = back.querySelector('.location-country-text');
        if (countryEl) countryEl.textContent = country;

        const latEl = back.querySelector('.location-lat-text');
        if (latEl) latEl.textContent = lat || '—';

        const lngEl = back.querySelector('.location-lng-text');
        if (lngEl) lngEl.textContent = lng || '—';

        const mapLink = back.querySelector('.location-map-link');
        if (mapLink) {
            if (lat && lng) {
                mapLink.href = `https://www.google.com/maps?q=${lat},${lng}`;
                mapLink.classList.remove('disabled');
            } else {
                mapLink.href = '#';
                mapLink.classList.add('disabled');
            }
        }
    }

    function toggleLocationView(button) {
        const card = button.closest('.flip-card');
        if (!card) return;
        const triggerBtn = card.querySelector('.location-btn');
        if (!triggerBtn) return;

        const isFlipped = card.classList.toggle('is-flipped');
        if (isFlipped) {
            updateLocationCardDisplay(triggerBtn);
        }
    }

    function openCoordsModal(button) {
        // If button is passed directly (from onclick)
        if (button.tagName) {
            currentCoordsButton = button;
        } else {
            // Fallback if event delegation was used
            currentCoordsButton = button.target.closest('button');
        }

        currentCoordsPostId = currentCoordsButton.getAttribute('data-post-id');
        document.getElementById('coordsError').classList.add('d-none');

        document.getElementById('coordLat').value = currentCoordsButton.getAttribute('data-lat') || '';
        document.getElementById('coordLng').value = currentCoordsButton.getAttribute('data-lng') || '';
        document.getElementById('coordLocationName').value = currentCoordsButton.getAttribute('data-location-name') || '';
        document.getElementById('coordCity').value = currentCoordsButton.getAttribute('data-city') || '';
        document.getElementById('coordCountry').value = currentCoordsButton.getAttribute('data-country') || '';

        new bootstrap.Modal(document.getElementById('coordsModal')).show();
    }

    function saveCoords() {
        const lat = parseFloat(document.getElementById('coordLat').value);
        const lng = parseFloat(document.getElementById('coordLng').value);
        const locationName = document.getElementById('coordLocationName').value.trim();
        const city = document.getElementById('coordCity').value.trim();
        const country = document.getElementById('coordCountry').value.trim();
        const errorBox = document.getElementById('coordsError');

        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            errorBox.textContent = 'Debes ingresar coordenadas válidas.';
            errorBox.classList.remove('d-none');
            return;
        }
        errorBox.classList.add('d-none');

        fetch(`/admin/update_post_location/${currentCoordsPostId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            },
            body: JSON.stringify({
                latitude: lat,
                longitude: lng,
                location_name: locationName,
                city,
                country
            })
        })
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    errorBox.textContent = data.error || 'No se pudo actualizar la ubicación.';
                    errorBox.classList.remove('d-none');
                    return;
                }

                // Update data attributes on button
                if (currentCoordsButton) {
                    currentCoordsButton.setAttribute('data-lat', String(lat));
                    currentCoordsButton.setAttribute('data-lng', String(lng));
                    currentCoordsButton.setAttribute('data-location-name', locationName);
                    currentCoordsButton.setAttribute('data-city', city);
                    currentCoordsButton.setAttribute('data-country', country);
                    updateLocationCardDisplay(currentCoordsButton);
                }

                bootstrap.Modal.getInstance(document.getElementById('coordsModal')).hide();
                alert('Ubicación actualizada');
            })
            .catch(error => {
                console.error('Error:', error);
                errorBox.textContent = 'Ocurrió un error guardando la ubicación.';
                errorBox.classList.remove('d-none');
            });
    }

    function filterUsers() {
        const localTerm = (document.getElementById('userSearch')?.value || '').toLowerCase();
        const searchTerm = (localTerm || getGlobalSearchTerm()).toLowerCase();
        const statusFilter = document.getElementById('adminUserStatusFilter')?.value || 'all';
        const strikesFilter = document.getElementById('adminUserStrikesFilter')?.value || 'all';
        const reportsFilter = document.getElementById('adminUserReportsFilter')?.value || 'all';
        const items = Array.from(document.querySelectorAll('.user-item'));
        let visibleCount = 0;

        items.forEach(item => {
            const searchable = (item.dataset.userSearch || `${item.querySelector('.user-username')?.textContent || ''} ${item.querySelector('.user-email')?.textContent || ''}`).toLowerCase();
            const status = item.dataset.userStatus || 'offline';
            const verified = item.dataset.userVerified === '1';
            const postCount = Number(item.dataset.userPosts || 0);
            const strikeCount = Number(item.dataset.userStrikes || 0);
            const activeReports = Number(item.dataset.userReportsActive || 0);

            const matchesText = !searchTerm || searchable.includes(searchTerm);
            const matchesStatus = statusFilter === 'all'
                || (statusFilter === 'verified' && verified)
                || (statusFilter === 'unverified' && !verified)
                || (statusFilter === 'recovery' && status === 'recovery')
                || (statusFilter === 'with_posts' && postCount > 0)
                || (statusFilter === 'no_posts' && postCount === 0);
            const matchesStrikes = strikesFilter === 'all'
                || (strikesFilter === 'none' && strikeCount === 0)
                || (strikesFilter === 'one' && strikeCount === 1)
                || (strikesFilter === 'two_plus' && strikeCount >= 2);
            const matchesReports = reportsFilter === 'all'
                || (reportsFilter === 'with_reports' && activeReports > 0)
                || (reportsFilter === 'no_reports' && activeReports === 0);

            if (matchesText && matchesStatus && matchesStrikes && matchesReports) {
                item.classList.remove('d-none');
                visibleCount += 1;
            } else {
                item.classList.add('d-none');
            }
        });

        const summary = document.getElementById('adminUserFilterSummary');
        if (summary) {
            summary.textContent = `${visibleCount} visible${visibleCount === 1 ? '' : 's'} en esta página`;
        }
        syncBulkSelectionState(
            document.getElementById('selectAllUsers'),
            '.user-select',
            document.getElementById('usersSelectedCount')
        );
    }

    function filterPosts() {
        const localTerm = (document.getElementById('postSearch')?.value || '').toLowerCase();
        const searchTerm = (localTerm || getGlobalSearchTerm()).toLowerCase();
        const items = document.querySelectorAll('.post-item');

        items.forEach(item => {
            const author = (item.querySelector('.post-author')?.textContent || '').toLowerCase();
            const caption = item.querySelector('.post-caption')?.textContent.toLowerCase() || '';

            if (author.includes(searchTerm) || caption.includes(searchTerm)) {
                item.classList.remove('d-none');
            } else {
                item.classList.add('d-none');
            }
        });
    }

    function filterReportedPosts() {
        const searchTerm = getGlobalSearchTerm();
        const items = document.querySelectorAll('#reportedGrid .reported-item');

        items.forEach(item => {
            const haystack = ((item.getAttribute('data-search') || '') + ' ' + (item.textContent || '')).toLowerCase();
            item.classList.toggle('d-none', !!searchTerm && !haystack.includes(searchTerm));
        });
    }

    function getSelectedIds(selector) {
        return Array.from(document.querySelectorAll(selector + ':checked'))
            .map(el => el.getAttribute('data-id'))
            .filter(Boolean);
    }

    function getBulkSelectionItems(itemSelector) {
        return Array.from(document.querySelectorAll(itemSelector));
    }

    function updateBulkSelectionVisualState(inputEl) {
        if (!inputEl) {
            return;
        }

        const isSelected = !!inputEl.checked;
        const bulkCircle = inputEl.closest('.bulk-circle');
        if (bulkCircle) {
            bulkCircle.classList.toggle('is-selected', isSelected);
        }

        if (inputEl.classList.contains('post-select')) {
            const postItem = inputEl.closest('.post-item');
            if (postItem) {
                postItem.classList.toggle('is-bulk-selected', isSelected);
            }
        }
    }

    function syncBulkSelectionState(selectAll, itemSelector, countEl) {
        const items = getBulkSelectionItems(itemSelector);
        const selectableItems = items.filter((el) => !el.disabled);
        const checkedCount = items.filter((el) => el.checked).length;
        const checkedSelectableCount = selectableItems.filter((el) => el.checked).length;

        items.forEach((el) => updateBulkSelectionVisualState(el));

        if (countEl) {
            const selectedWord = countEl.id === 'usersSelectedCount' ? 'seleccionadas' : 'seleccionados';
            countEl.textContent = `${checkedCount} ${selectedWord}`;
        }

        if (!selectAll) {
            return;
        }

        if (!selectableItems.length) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
            return;
        }

        selectAll.checked = checkedSelectableCount === selectableItems.length;
        selectAll.indeterminate = checkedSelectableCount > 0 && checkedSelectableCount < selectableItems.length;
    }

    function wireBulkSelection(selectAllId, itemSelector, countId) {
        const selectAll = document.getElementById(selectAllId);
        const countEl = document.getElementById(countId);
        if (selectAll) {
            if (selectAll.dataset.bulkBound !== '1') {
                selectAll.dataset.bulkBound = '1';
                selectAll.addEventListener('change', () => {
                    getBulkSelectionItems(itemSelector).forEach((el) => {
                        if (!el.disabled) el.checked = selectAll.checked;
                    });
                    syncBulkSelectionState(selectAll, itemSelector, countEl);
                });
            }
        }
        getBulkSelectionItems(itemSelector).forEach((el) => {
            if (el.dataset.bulkBound === '1') {
                return;
            }
            el.dataset.bulkBound = '1';
            el.addEventListener('change', () => {
                syncBulkSelectionState(selectAll, itemSelector, countEl);
            });
        });
        syncBulkSelectionState(selectAll, itemSelector, countEl);
    }

    function bindAdminStaticControls() {
        const globalFilter = document.getElementById('adminGlobalFilter');
        if (globalFilter && globalFilter.dataset.adminBound !== '1') {
            globalFilter.dataset.adminBound = '1';
            globalFilter.addEventListener('input', () => {
                applyActiveTabFilter();
            });
        }
        ['adminUserStatusFilter', 'adminUserStrikesFilter', 'adminUserReportsFilter'].forEach((id) => {
            const control = document.getElementById(id);
            if (!control || control.dataset.adminBound === '1') return;
            control.dataset.adminBound = '1';
            control.addEventListener('change', filterUsers);
        });

        if (!window.__adminVisibilityBound) {
            window.__adminVisibilityBound = true;
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    if (ADMIN_ACTIVITY_STATE.timer) {
                        clearInterval(ADMIN_ACTIVITY_STATE.timer);
                        ADMIN_ACTIVITY_STATE.timer = null;
                    }
                    if (ADMIN_ATTENTION_STATE.timer) {
                        clearInterval(ADMIN_ATTENTION_STATE.timer);
                        ADMIN_ATTENTION_STATE.timer = null;
                    }
                } else {
                    fetchAdminActivity(ADMIN_ACTIVITY_STATE.days, { animate: false, silent: true });
                    startAdminActivityAutoRefresh();
                    startAdminAttentionPolling();
                }
            });
        }

        if (!window.__adminBeforeUnloadBound) {
            window.__adminBeforeUnloadBound = true;
            window.addEventListener('beforeunload', () => {
                if (ADMIN_ACTIVITY_STATE.timer) {
                    clearInterval(ADMIN_ACTIVITY_STATE.timer);
                    ADMIN_ACTIVITY_STATE.timer = null;
                }
                if (ADMIN_ATTENTION_STATE.timer) {
                    clearInterval(ADMIN_ATTENTION_STATE.timer);
                    ADMIN_ATTENTION_STATE.timer = null;
                }
            });
        }
    }

    function bindAdminPageDom() {
        bindAdminEditButtons();
        bindVerificationEvidenceModal();
        wireBulkSelection('selectAllUsers', '.user-select', 'usersSelectedCount');
        wireBulkSelection('selectAllPosts', '.post-select', 'postsSelectedCount');
        wireBulkSelection('selectAllChats', '.chat-select', 'chatsSelectedCount');
    }

    function initAdminPageEnhancements() {
        bindAdminPageDom();

        if (window.__adminPageEnhancementsInitialized) {
            return;
        }
        window.__adminPageEnhancementsInitialized = true;

        wireAdminActivityControls();
        bindAdminStaticControls();
        fetchAdminActivity(ADMIN_ACTIVITY_STATE.days, { animate: true });
        startAdminActivityAutoRefresh();
        startAdminAttentionPolling();
    }

    function bulkDeleteUsers() {
        const ids = getSelectedIds('.user-select');
        if (!ids.length) return alert('Selecciona usuarias para eliminar');
        if (!confirm('¿Eliminar las usuarias seleccionadas?')) return;
        fetch('/admin/bulk_delete_users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': ADMIN_CSRF_TOKEN },
            body: JSON.stringify({ ids })
        }).then(r => r.json()).then(data => {
            if (!data.success) return alert('Error: ' + data.error);
            let removed = 0;
            ids.forEach((id) => {
                const item = document.querySelector(`.user-item[data-user-id="${id}"]`);
                if (item) {
                    item.remove();
                    removed += 1;
                }
            });
            syncUsersViewState();
            syncUsersAttentionState();
            wireBulkSelection('selectAllUsers', '.user-select', 'usersSelectedCount');
            if (!removed) {
                location.reload();
            }
        }).catch(() => alert('Error al eliminar usuarias'));
    }

    function bulkDeletePosts() {
        const ids = getSelectedIds('.post-select');
        if (!ids.length) return alert('Selecciona publicaciones para eliminar');
        if (!confirm('¿Eliminar las publicaciones seleccionadas?')) return;
        fetch('/admin/bulk_delete_posts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': ADMIN_CSRF_TOKEN },
            body: JSON.stringify({ ids })
        }).then(r => r.json()).then(data => {
            if (!data.success) return alert('Error: ' + data.error);
            let removed = 0;
            ids.forEach((id) => {
                const nodes = document.querySelectorAll(`.post-item[data-post-id="${id}"], .reported-item[data-post-id="${id}"]`);
                removed += nodes.length;
                nodes.forEach((node) => node.remove());
            });
            syncPostsViewState();
            ensureReportedGridEmptyState('reportedGrid', '.reported-item', 'Todas las publicaciones reportadas ya fueron revisadas.');
            syncReportAttentionState();
            wireBulkSelection('selectAllPosts', '.post-select', 'postsSelectedCount');
            if (!removed) {
                location.reload();
            }
        }).catch(() => alert('Error al eliminar publicaciones'));
    }

    function bulkDeleteChats() {
        const ids = getSelectedIds('.chat-select');
        if (!ids.length) return alert('Selecciona chats para eliminar');
        if (!confirm('¿Eliminar los chats seleccionados?')) return;
        fetch('/admin/bulk_delete_chat_rooms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': ADMIN_CSRF_TOKEN },
            body: JSON.stringify({ ids })
        }).then(r => r.json()).then(data => {
            if (!data.success) return alert('Error: ' + data.error);
            let removed = 0;
            ids.forEach((id) => {
                const nodes = document.querySelectorAll(`.pending-chat-room-item[data-room-id="${id}"], .admin-chat-room-item[data-room-id="${id}"]`);
                removed += nodes.length;
                nodes.forEach((node) => node.remove());
            });
            syncPendingChatRoomsState();
            syncAllChatRoomsState();
            wireBulkSelection('selectAllChats', '.chat-select', 'chatsSelectedCount');
            if (!removed) {
                location.reload();
            }
        }).catch(() => alert('Error al eliminar chats'));
    }

    function formatRelativeTime(dateStr) {
        if (!dateStr) return '';
        const diff = Date.now() - new Date(dateStr).getTime();
        const minutes = Math.floor(diff / 60000);
        if (minutes < 1) return 'Hace un momento';
        if (minutes < 60) return `Hace ${minutes} min`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `Hace ${hours} hora${hours === 1 ? '' : 's'}`;
        return 'Hace tiempo';
    }

    function escapeAdminHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatAuditDate(dateStr) {
        if (!dateStr) return 'Sin fecha';
        const date = new Date(dateStr);
        if (Number.isNaN(date.getTime())) return 'Sin fecha';
        return date.toLocaleString('es-MX', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function renderAuditEmpty(message) {
        return `<div class="admin-user-audit-empty">${escapeAdminHtml(message)}</div>`;
    }

    function renderAuditSummary(data) {
        const user = data?.user || {};
        const summary = data?.summary || {};
        const roles = Array.isArray(user.roles) && user.roles.length ? user.roles.join(', ') : 'Sin roles staff';
        return `
            <article class="admin-user-audit-hero">
                <div class="admin-user-audit-hero__main">
                    <div class="admin-user-audit-avatar">${escapeAdminHtml((user.username || 'U').slice(0, 2).toUpperCase())}</div>
                    <div>
                        <h3>@${escapeAdminHtml(user.username || 'usuaria')}</h3>
                        <p>${escapeAdminHtml(user.email || '')}</p>
                        <div class="admin-user-audit-tags">
                            <span>${user.is_verified ? 'Verificada' : 'Sin verificar'}</span>
                            <span>${escapeAdminHtml(roles)}</span>
                            ${user.password_recovery_pending ? '<span class="is-warning">Recuperación pendiente</span>' : ''}
                        </div>
                    </div>
                </div>
                <div class="admin-user-audit-created">Alta: ${escapeAdminHtml(formatAuditDate(user.created_at))}</div>
            </article>
            <div class="admin-user-audit-kpis">
                <div><strong>${Number(summary.posts || 0)}</strong><span>Posts</span></div>
                <div><strong>${Number(summary.comments || 0)}</strong><span>Comentarios</span></div>
                <div><strong>${Number(summary.active_reports || 0)}</strong><span>Reportes activos</span></div>
                <div><strong>${Number(summary.strikes || 0)}</strong><span>Strikes</span></div>
            </div>
        `;
    }

    function renderStrikeList(strikes) {
        if (!Array.isArray(strikes) || !strikes.length) {
            return renderAuditEmpty('No hay strikes registrados.');
        }
        return strikes.map((strike) => `
            <div class="admin-user-audit-item">
                <div class="admin-user-audit-item__top">
                    <strong>Strike ${Number(strike.strike_number || 0)}</strong>
                    <span>${escapeAdminHtml(formatAuditDate(strike.created_at))}</span>
                </div>
                <div class="admin-user-audit-item__reason">${escapeAdminHtml(strike.reason || 'Incumplimiento')}</div>
                <p>${escapeAdminHtml(strike.content_excerpt || strike.details || strike.source_label || 'Sin detalle adicional')}</p>
                <div class="admin-user-audit-item__meta">
                    <span>${escapeAdminHtml(strike.source_type || 'fuente')}</span>
                    <span>${escapeAdminHtml(strike.consequence || 'warning')}</span>
                    <span>Por ${escapeAdminHtml(strike.issued_by || 'Sistema')}</span>
                </div>
            </div>
        `).join('');
    }

    function renderReportList(reports) {
        if (!Array.isArray(reports) || !reports.length) {
            return renderAuditEmpty('No hay reportes recibidos.');
        }
        const typeLabel = {
            post: 'Publicación',
            comment: 'Comentario',
            chat: 'Chat',
        };
        return reports.map((report) => `
            <div class="admin-user-audit-item">
                <div class="admin-user-audit-item__top">
                    <strong>${escapeAdminHtml(typeLabel[report.source_type] || 'Reporte')}</strong>
                    <span>${escapeAdminHtml(formatAuditDate(report.created_at))}</span>
                </div>
                <div class="admin-user-audit-item__reason">${escapeAdminHtml(report.reason || 'Sin motivo')}</div>
                <p>${escapeAdminHtml(report.content_excerpt || report.details || 'Sin detalle adicional')}</p>
                <div class="admin-user-audit-item__meta">
                    <span>Estado: ${escapeAdminHtml(report.status || 'pending')}</span>
                    <span>Reportó ${escapeAdminHtml(report.reporter || 'Usuaria')}</span>
                    ${report.resolver ? `<span>Resolvió ${escapeAdminHtml(report.resolver)}</span>` : ''}
                </div>
            </div>
        `).join('');
    }

    function renderAuditLogList(logs) {
        if (!Array.isArray(logs) || !logs.length) {
            return renderAuditEmpty('No hay acciones recientes registradas.');
        }
        return logs.map((log) => `
            <div class="admin-user-audit-timeline__item">
                <span class="admin-user-audit-timeline__dot"></span>
                <div>
                    <div class="admin-user-audit-item__top">
                        <strong>${escapeAdminHtml(log.summary || log.event_type || 'Acción')}</strong>
                        <span>${escapeAdminHtml(formatAuditDate(log.created_at))}</span>
                    </div>
                    <p>${escapeAdminHtml(log.event_type || '')}${log.workspace ? ` · ${escapeAdminHtml(log.workspace)}` : ''}</p>
                    <div class="admin-user-audit-item__meta">
                        <span>Actor: ${escapeAdminHtml(log.actor || 'Sistema')}</span>
                        ${log.resource_type ? `<span>${escapeAdminHtml(log.resource_type)} #${escapeAdminHtml(log.resource_id || '')}</span>` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    }

    function openUserAudit(userId) {
        const modalEl = document.getElementById('userAuditModal');
        if (!modalEl || !userId) return;
        const loading = document.getElementById('userAuditLoading');
        const errorBox = document.getElementById('userAuditError');
        const content = document.getElementById('userAuditContent');
        const title = document.getElementById('userAuditTitle');
        const subtitle = document.getElementById('userAuditSubtitle');
        const summary = document.getElementById('userAuditSummary');
        const strikes = document.getElementById('userAuditStrikes');
        const reports = document.getElementById('userAuditReports');
        const logs = document.getElementById('userAuditLogs');

        title.textContent = 'Historial de usuaria';
        subtitle.textContent = 'Cargando información...';
        loading?.classList.remove('d-none');
        errorBox?.classList.add('d-none');
        content?.classList.add('d-none');
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();

        fetch(`/admin/user/${userId}/audit_summary`, {
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo cargar el historial.');
                }
                return data;
            })
            .then((data) => {
                const user = data.user || {};
                title.textContent = `Historial de @${user.username || 'usuaria'}`;
                subtitle.textContent = `${Number(data.summary?.active_reports || 0)} reportes activos · ${Number(data.summary?.strikes || 0)} strikes · ${Number(data.summary?.reports_made || 0)} reportes enviados`;
                if (summary) summary.innerHTML = renderAuditSummary(data);
                if (strikes) strikes.innerHTML = renderStrikeList(data.strikes);
                if (reports) reports.innerHTML = renderReportList(data.reports);
                if (logs) logs.innerHTML = renderAuditLogList(data.audit_logs);
                const strikesCount = document.getElementById('userAuditStrikesCount');
                const reportsCount = document.getElementById('userAuditReportsCount');
                const logsCount = document.getElementById('userAuditLogsCount');
                if (strikesCount) strikesCount.textContent = String((data.strikes || []).length);
                if (reportsCount) reportsCount.textContent = String((data.reports || []).length);
                if (logsCount) logsCount.textContent = String((data.audit_logs || []).length);
                loading?.classList.add('d-none');
                content?.classList.remove('d-none');
            })
            .catch((error) => {
                loading?.classList.add('d-none');
                if (errorBox) {
                    errorBox.textContent = error.message || 'No se pudo cargar el historial.';
                    errorBox.classList.remove('d-none');
                }
            });
    }

    window.initAdminPageEnhancements = initAdminPageEnhancements;
    window.openUserRolesModal = openUserRolesModal;
    window.saveUserRoles = saveUserRoles;
    window.openVerificationEvidence = openVerificationEvidence;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminPageEnhancements, { once: true });
    } else {
        initAdminPageEnhancements();
    }

    function approveVerification(reqId) {
        if (!confirm('¿Aprobar esta verificación?')) return;
        fetch(`/admin/verify/${reqId}/approve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const item = document.querySelector(`.verification-item[data-verification-id="${reqId}"]`);
                    item?.remove();
                    syncVerificationState();
                    if (!item) {
                        location.reload();
                    }
                } else {
                    alert(data.error || 'No se pudo aprobar');
                }
            })
            .catch(() => alert('Error al aprobar'));
    }

    function rejectVerification(reqId) {
        if (!confirm('¿Rechazar esta verificación?')) return;
        fetch(`/admin/verify/${reqId}/reject`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const item = document.querySelector(`.verification-item[data-verification-id="${reqId}"]`);
                    item?.remove();
                    syncVerificationState();
                    if (!item) {
                        location.reload();
                    }
                } else {
                    alert(data.error || 'No se pudo rechazar');
                }
            })
            .catch(() => alert('Error al rechazar'));
    }

    function suspendVerification(reqId) {
        if (!confirm('¿Suspender esta cuenta?')) return;
        fetch(`/admin/verify/${reqId}/suspend`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': ADMIN_CSRF_TOKEN
            }
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const item = document.querySelector(`.verification-item[data-verification-id="${reqId}"]`);
                    item?.remove();
                    syncVerificationState();
                    if (!item) {
                        location.reload();
                    }
                } else {
                    alert(data.error || 'No se pudo suspender');
                }
            })
            .catch(() => alert('Error al suspender'));
    }

    window.approveVerification = approveVerification;
    window.rejectVerification = rejectVerification;
    window.suspendVerification = suspendVerification;

    document.addEventListener('DOMContentLoaded', () => {
        const copyBtn = document.getElementById('assistedResetCopyBtn');
        const valueEl = document.getElementById('assistedResetPasswordValue');
        if (!copyBtn || !valueEl) return;
        copyBtn.addEventListener('click', async () => {
            const value = (valueEl.value || '').trim();
            if (!value) return;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(value);
                } else {
                    valueEl.focus();
                    valueEl.select();
                    document.execCommand('copy');
                }
                copyBtn.textContent = 'Copiada';
            } catch (error) {
                console.error('copy temp password error:', error);
                valueEl.focus();
                valueEl.select();
            }
        });
    });
