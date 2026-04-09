    const ADMIN_PAGE_CONFIG = window.ADMIN_PAGE_CONFIG || {};
    const ADMIN_CSRF_TOKEN = ADMIN_PAGE_CONFIG.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '';
    const ADMIN_BADGE_URL = ADMIN_PAGE_CONFIG.adminBadgeUrl || '/static/images/admin_badge.svg';
    let currentUserId = null;
    let currentCoordsPostId = null;
    let currentCoordsButton = null;
    let changePhotoCropFile = null;
    let changePhotoCropper = null;
    let changePhotoCropModal = null;
    let changePhotoCropUrl = null;
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
                        location.reload();
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
                        location.reload();
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
                        location.reload();
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
            bioInput.value = userBio || '';
        }
        new bootstrap.Modal(document.getElementById('changePhotoModal')).show();
    }

    function savePhoto() {
        const fileInput = document.getElementById('photoFile');
        const fileToSend = changePhotoCropFile || fileInput.files[0];
        const bioInput = document.getElementById('changePhotoBio');
        const bioValue = bioInput ? bioInput.value.trim() : '';
        if (!fileToSend && !bioValue) {
            alert('Selecciona una imagen o agrega una descripción.');
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
                    location.reload();
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
                    location.reload();
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
                const quality = outputType === 'image/jpeg' ? 0.92 : undefined;
                canvas.toBlob((blob) => {
                    if (!blob) return;
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
        const { confirmMessage, actionLabel, successFallback } = options;
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
                location.reload();
            })
            .catch(() => alert('Error al completar la acción.'));
    }

    function restorePostReport(reportId) {
        runReportAction(`/admin/report/${reportId}/restore`, {
            confirmMessage: '¿Restaurar esta publicación para que vuelva a mostrarse?',
            actionLabel: 'restaurar la publicación',
            successFallback: 'La publicación fue restaurada.'
        });
    }

    function strikePostReport(reportId) {
        runReportAction(`/admin/report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de esta publicación?',
            actionLabel: 'mandar el strike a la usuaria por esta publicación',
            successFallback: 'La publicación quedó sancionada.'
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
            successFallback: 'El mensaje fue restaurado.'
        });
    }

    function strikeChatMessageReport(reportId) {
        runReportAction(`/admin/chat_report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de este mensaje?',
            actionLabel: 'mandar el strike a la usuaria por este mensaje',
            successFallback: 'El mensaje quedó sancionado.'
        });
    }

    function restoreCommentReport(reportId) {
        runReportAction(`/admin/comment_report/${reportId}/restore`, {
            confirmMessage: '¿Restaurar este comentario para que vuelva a mostrarse?',
            actionLabel: 'restaurar el comentario',
            successFallback: 'El comentario fue restaurado.'
        });
    }

    function strikeCommentReport(reportId) {
        runReportAction(`/admin/comment_report/${reportId}/strike`, {
            confirmMessage: '¿Mandar un strike a la usuaria responsable de este comentario?',
            actionLabel: 'mandar el strike a la usuaria por este comentario',
            successFallback: 'El comentario quedó sancionado.'
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
        const items = document.querySelectorAll('.user-item');

        items.forEach(item => {
            const username = (item.querySelector('.user-username')?.textContent || '').toLowerCase();
            const email = (item.querySelector('.user-email')?.textContent || '').toLowerCase();

            if (username.includes(searchTerm) || email.includes(searchTerm)) {
                item.classList.remove('d-none');
            } else {
                item.classList.add('d-none');
            }
        });
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
            countEl.textContent = `${checkedCount} seleccionados`;
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

        if (!window.__adminVisibilityBound) {
            window.__adminVisibilityBound = true;
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    if (ADMIN_ACTIVITY_STATE.timer) {
                        clearInterval(ADMIN_ACTIVITY_STATE.timer);
                        ADMIN_ACTIVITY_STATE.timer = null;
                    }
                } else {
                    fetchAdminActivity(ADMIN_ACTIVITY_STATE.days, { animate: false, silent: true });
                    startAdminActivityAutoRefresh();
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
            });
        }
    }

    function bindAdminPageDom() {
        bindAdminEditButtons();
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
            location.reload();
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
            location.reload();
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
            location.reload();
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

    function openReportDetails(event, postId) {
        if (event && event.target.closest('input,button,a,label')) return;
        fetch(`/admin/report_details/${postId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                const post = data.post || {};
                document.getElementById('reportDetailsImage').src = post.image_url || '';
                document.getElementById('reportDetailsAuthorPic').src = post.author?.profile_pic || '';
                const authorName = post.author?.username || 'unknown';
                const authorEl = document.getElementById('reportDetailsAuthor');
                authorEl.textContent = authorName;
                if (authorName === 'admin') {
                    const badge = document.createElement('span');
                    badge.className = 'admin-badge admin-badge--xs';
                    badge.title = 'Admin verificada';
                    badge.setAttribute('aria-label', 'Admin verificada');
                    badge.innerHTML = `<img src="${ADMIN_BADGE_URL}" alt="Admin">`;
                    authorEl.appendChild(badge);
                }
                document.getElementById('reportDetailsCreated').textContent = post.created_at ? new Date(post.created_at).toLocaleString() : '';
                const loc = post.location || {};
                const locText = [loc.name, loc.city, loc.country].filter(Boolean).join(' · ');
                document.getElementById('reportDetailsLocation').textContent = locText || 'Sin ubicación';
                document.getElementById('reportDetailsCaption').textContent = post.caption || 'Sin descripción';
                document.getElementById('reportDetailsLikes').textContent = post.likes_count ?? '0';
                document.getElementById('reportDetailsCommentsCount').textContent = post.comments_count ?? '0';

                const reportsEl = document.getElementById('reportDetailsReports');
                const commentsEl = document.getElementById('reportDetailsComments');
                reportsEl.innerHTML = '';
                commentsEl.innerHTML = '';

                if (data.reports && data.reports.length) {
                    data.reports.forEach(r => {
                        const item = document.createElement('div');
                        item.className = 'report-detail-item';
                        const reporterBadge = r.reporter === 'admin'
                            ? `<span class="admin-badge admin-badge--xs" title="Admin verificada" aria-label="Admin verificada"><img src="${ADMIN_BADGE_URL}" alt="Admin"></span>`
                            : '';
                        const statusMap = {
                            pending: { label: 'Pendiente', cls: 'bg-warning text-dark' },
                            restored: { label: 'Restaurada', cls: 'bg-success text-white' },
                            struck: { label: 'Strike aplicado', cls: 'bg-danger text-white' },
                            dismissed: { label: 'Descartado', cls: 'bg-secondary text-white' },
                        };
                        const statusInfo = statusMap[r.status] || statusMap.pending;
                        const resolutionText = r.resolved_at
                            ? `<div class="small text-secondary mt-1">${r.resolved_by ? `Revisado por ${r.resolved_by}` : 'Revisado'} · ${formatRelativeTime(r.resolved_at)}</div>`
                            : '';
                        item.innerHTML = `
                            <div class="d-flex align-items-center justify-content-between gap-2">
                                <div class="fw-bold text-white">${r.reason}</div>
                                <span class="badge ${statusInfo.cls}">${statusInfo.label}</span>
                            </div>
                            <div class="small text-secondary">Reportado por ${r.reporter}${reporterBadge} · ${formatRelativeTime(r.created_at)}</div>
                            ${r.details ? `<div class="small text-white mt-1">${r.details}</div>` : ''}
                            ${r.admin_note ? `<div class="small text-info mt-1"><strong>Nota admin:</strong> ${r.admin_note}</div>` : ''}
                            ${resolutionText}
                            <div class="d-flex flex-wrap gap-2 mt-2">
                                <button class="btn btn-sm btn-outline-success" onclick="restorePostReport('${r.id}')">Restaurar</button>
                                <button class="btn btn-sm btn-outline-danger" onclick="strikePostReport('${r.id}')">Mandar un strike</button>
                            </div>
                        `;
                        reportsEl.appendChild(item);
                    });
                } else {
                    reportsEl.innerHTML = '<div class="text-muted small">Sin reportes.</div>';
                }

                if (data.comments && data.comments.length) {
                    data.comments.forEach(c => {
                        const item = document.createElement('div');
                        item.className = 'report-detail-item';
                        const badge = c.username === 'admin'
                            ? `<span class="admin-badge admin-badge--xs" title="Admin verificada" aria-label="Admin verificada"><img src="${ADMIN_BADGE_URL}" alt="Admin"></span>`
                            : '';
                        item.innerHTML = `
                            <div class="fw-bold text-white">${c.username}${badge}</div>
                            <div class="small text-secondary">${formatRelativeTime(c.created_at)}</div>
                            <div class="small text-white mt-1">${c.content}</div>
                        `;
                        commentsEl.appendChild(item);
                    });
                } else {
                    commentsEl.innerHTML = '<div class="text-muted small">Sin comentarios.</div>';
                }

                new bootstrap.Modal(document.getElementById('reportDetailsModal')).show();
            })
            .catch(() => alert('Error al cargar el detalle'));
    }

    window.initAdminPageEnhancements = initAdminPageEnhancements;

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
                    location.reload();
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
                    location.reload();
                } else {
                    alert(data.error || 'No se pudo rechazar');
                }
            })
            .catch(() => alert('Error al rechazar'));
    }
