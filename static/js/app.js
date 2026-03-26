// CSRF helpers --------------------------------------------------------------
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

let currentReportPostId = null;
let currentReportCommentId = null;
let currentReportCommentPostId = null;
const commentLoadPromises = new Map();

function extractRemainingSeconds(text) {
    const msg = String(text || '');
    const m = msg.match(/([0-9]+)\s*segundos?/i);
    return m ? Number(m[1]) : null;
}

function openReportModal(postId) {
    if (typeof isUserVerified === 'function' && !isUserVerified()) {
        showVerifyGate();
        return;
    }
    currentReportPostId = postId;
    const modalEl = document.getElementById('reportPostModal');
    const errorEl = document.getElementById('reportPostError');
    const detailsEl = document.getElementById('reportDetails');

    if (!modalEl) {
        return;
    }

    // Reset form state
    const radios = modalEl.querySelectorAll('input[name="report_reason"]');
    radios.forEach(r => { r.checked = false; });
    if (detailsEl) {
        detailsEl.value = '';
    }
    if (errorEl) {
        errorEl.classList.add('d-none');
        errorEl.textContent = '';
    }

    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

async function submitReport(event) {
    event.preventDefault();
    const modalEl = document.getElementById('reportPostModal');
    const errorEl = document.getElementById('reportPostError');
    const form = event.target;
    const submitBtn = form ? form.querySelector('button[type="submit"]') : null;
    if (!modalEl || !currentReportPostId) {
        return;
    }

    const selected = modalEl.querySelector('input[name="report_reason"]:checked');
    const detailsEl = document.getElementById('reportDetails');
    const details = detailsEl ? detailsEl.value.trim() : '';

    if (!selected) {
        if (errorEl) {
            errorEl.textContent = 'Selecciona una categoría para continuar.';
            errorEl.classList.remove('d-none');
        }
        return;
    }

    const postId = Number(currentReportPostId);
    const postCard = document.querySelector(`[data-post-id="${postId}"]`);
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.dataset.originalText = submitBtn.textContent || 'Enviar reporte';
        submitBtn.textContent = 'Enviando...';
    }

    const modal = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.hide();
    if (postCard) {
        postCard.dataset.reportPending = 'true';
        postCard.style.opacity = '0.42';
        postCard.style.pointerEvents = 'none';
    }

    try {
        const response = await fetch(`/report_post/${postId}`, {
            method: 'POST',
            headers: buildHeaders('application/json'),
            body: JSON.stringify({
                reason: selected.value,
                details
            })
        });

        if (handleAuthRedirect(response)) {
            return;
        }

        const data = await response.json();
        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'No se pudo enviar el reporte.');
        }

        if (postCard) {
            postCard.remove();
        }

        const caseLabel = data.report_id ? ` Folio #${data.report_id}.` : '';
        showAlert(`Gracias. Tu reporte fue enviado.${caseLabel}`, 'success');
        currentReportPostId = null;
    } catch (error) {
        console.error('Error submitting report:', error);
        if (postCard) {
            delete postCard.dataset.reportPending;
            postCard.style.opacity = '';
            postCard.style.pointerEvents = '';
        }
        if (errorEl) {
            errorEl.textContent = error.message || 'Ocurrió un error al enviar el reporte.';
            errorEl.classList.remove('d-none');
        }
        showAlert(error.message || 'Ocurrió un error al enviar el reporte.', 'danger');
        modal.show();
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = submitBtn.dataset.originalText || 'Enviar reporte';
        }
    }
}

// Funcionalidad para dar like a publicaciones
async function toggleLike(postId) {
    if (typeof isUserVerified === 'function' && !isUserVerified()) {
        showVerifyGate();
        return;
    }
    try {
        const response = await fetch(`/like/${postId}`, {
            method: 'POST',
            headers: buildHeaders('application/json'),
            body: JSON.stringify({})
        });

        if (handleAuthRedirect(response)) {
            return;
        }

        const data = await response.json();
        if (!response.ok) {
            console.error('Error toggling like:', data);
            showAlert(data.error || 'No se pudo actualizar el like', 'danger');
            if (data && data.error && data.error.toLowerCase().includes('restricción temporal')) {
                const secs = extractRemainingSeconds(data.error);
                if (secs !== null) {
                    showAlert(`Tiempo restante aproximado: ${secs} segundos.`, 'warning');
                }
            }
            return;
        }

        const postCard = document.querySelector(`[data-post-id="${postId}"]`);
        if (!postCard) {
            return;
        }

        const likeBtn = postCard.querySelector('.like-btn');
        const likesCount = postCard.querySelector('.likes-count');
        if (!likeBtn || !likesCount) {
            return;
        }

        if (data.liked) {
            likeBtn.classList.add('active');
        } else {
            likeBtn.classList.remove('active');
        }

        likesCount.textContent = data.likes_count;

        // Animación
        likeBtn.style.transform = 'scale(1.15)';
        setTimeout(() => {
            likeBtn.style.transform = '';
        }, 150);
    } catch (error) {
        console.error('Error toggling like:', error);
        showAlert('Ocurrió un error al procesar tu like.', 'danger');
    }
}

// Función para mostrar/ocultar comentarios
function toggleComments(postId) {
    if (typeof isUserVerified === 'function' && !isUserVerified()) {
        showVerifyGate();
        return;
    }
    const commentsSection = document.getElementById(`comments-${postId}`);
    const postCard = document.querySelector(`[data-post-id="${postId}"]`);
    if (!commentsSection || !postCard) {
        return;
    }

    const commentBtn = postCard.querySelector('.comment-btn');
    const isHidden = commentsSection.classList.contains('d-none');

    commentsSection.classList.toggle('d-none', !isHidden);
    if (commentBtn) {
        commentBtn.classList.toggle('active', isHidden);
    }

    if (isHidden) {
        loadComments(postId);
    }
}

// Cargar comentarios de una publicación
function canReportComment(comment) {
    if (!comment || !window.CURRENT_USER || !window.CURRENT_USER.is_authenticated) return false;
    if (String(window.CURRENT_USER.username || '').toLowerCase() === 'admin') return true;
    return Number(window.CURRENT_USER.id) !== Number(comment.user_id);
}

function renderModerationBadge(level) {
    const numeric = Number(level || 0);
    if (!Number.isFinite(numeric) || numeric <= 0) return '';
    const tone = numeric >= 2 ? 'red' : 'yellow';
    const title = numeric >= 2 ? 'Usuaria con dos strikes o más' : 'Usuaria con un strike';
    return `<span class="moderation-strike-badge moderation-strike-badge--${tone}" title="${title}" aria-label="${title}"><i class="fas fa-triangle-exclamation"></i></span>`;
}

function buildCommentMarkup(comment, postId, options = {}) {
    const hidden = !!options.hidden;
    const timeLabel = typeof getRelativeTime === 'function'
        ? getRelativeTime(comment.created_at)
        : new Date(comment.created_at).toLocaleString();
    const avatarSrc = comment.profile_pic || `https://ui-avatars.com/api/?name=${encodeURIComponent(comment.username)}&background=b565a7&color=fff&rounded=true&size=32`;
    const reportBtnClass = String(window.CURRENT_USER?.username || '').toLowerCase() === 'admin'
        ? 'comment-report-btn comment-report-btn--always-visible'
        : 'comment-report-btn';
    const reportBtn = (!hidden && canReportComment(comment))
        ? `<button class="${reportBtnClass}" type="button" onclick="openCommentReportModal(${comment.id}, ${postId})" title="Reportar comentario"><i class="fas fa-flag"></i></button>`
        : '';
    const hiddenClass = hidden ? ' violet-comment--hidden' : '';
    const textClass = hidden ? ' violet-comment-text--hidden' : '';
    const bodyText = hidden ? 'Este comentario fue ocultado por moderación.' : escapeHtml(comment.content);
    return `
        <div class="violet-comment${hiddenClass}" data-comment-id="${comment.id}">
            <img class="violet-comment-avatar" src="${avatarSrc}" alt="avatar" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='/static/images/default_avatar.jpg';">
            <div class="violet-comment-content">
                <div class="violet-comment-header">
                    <div class="violet-comment-identity">
                        <div class="violet-comment-name-row">
                            <span class="violet-comment-username">${escapeHtml(comment.username)}${renderModerationBadge(comment.moderation_level)}${renderAdminBadge(comment.username)}</span>
                            ${reportBtn}
                        </div>
                    </div>
                    <div class="violet-comment-header-actions">
                        <span class="violet-comment-time">${timeLabel}</span>
                    </div>
                </div>
                <div class="violet-comment-text${textClass}">${bodyText}</div>
            </div>
        </div>
    `;
}

function ensureCommentsStructure(postId) {
    const commentsSection = document.getElementById(`comments-${postId}`);
    const root = commentsSection ? commentsSection.querySelector('.violet-comments-list') : null;
    if (!root) return null;

    let visibleWrap = root.querySelector('.violet-comments-visible');
    if (!visibleWrap) {
        visibleWrap = document.createElement('div');
        visibleWrap.className = 'violet-comments-visible';
        root.appendChild(visibleWrap);
    }

    let hiddenWrap = root.querySelector('.violet-comments-hidden-wrap');
    if (!hiddenWrap) {
        hiddenWrap = document.createElement('div');
        hiddenWrap.className = 'violet-comments-hidden-wrap d-none';
        hiddenWrap.innerHTML = `
            <div class="violet-comments-hidden-title">Comentarios ocultos</div>
            <div class="violet-comments-hidden-list"></div>
        `;
        root.appendChild(hiddenWrap);
    }

    let hiddenList = hiddenWrap.querySelector('.violet-comments-hidden-list');
    if (!hiddenList) {
        hiddenList = document.createElement('div');
        hiddenList.className = 'violet-comments-hidden-list';
        hiddenWrap.appendChild(hiddenList);
    }

    return { root, visibleWrap, hiddenWrap, hiddenList };
}

function updateCommentsCount(postId, total) {
    const postCard = document.querySelector(`[data-post-id="${postId}"]`);
    const commentsCount = postCard ? postCard.querySelector('.comments-count') : null;
    if (commentsCount) {
        commentsCount.textContent = String(total);
    }
}

function renderCommentsState(postId, data) {
    const structure = ensureCommentsStructure(postId);
    if (!structure) return;
    const commentsSection = document.getElementById(`comments-${postId}`);

    const comments = Array.isArray(data.comments) ? data.comments : [];
    const hiddenComments = Array.isArray(data.hidden_comments) ? data.hidden_comments : [];
    structure.visibleWrap.innerHTML = comments.map(comment => buildCommentMarkup(comment, postId)).join('');
    structure.hiddenList.innerHTML = hiddenComments.map(comment => buildCommentMarkup(comment, postId, { hidden: true })).join('');
    structure.hiddenWrap.classList.toggle('d-none', hiddenComments.length === 0);
    structure.root.dataset.loaded = 'true';
    if (commentsSection) {
        commentsSection.dataset.commentsLoaded = 'true';
    }
    updateCommentsCount(postId, comments.length + hiddenComments.length);
}

async function loadComments(postId, force = false) {
    const commentsSection = document.getElementById(`comments-${postId}`);
    if (!force && commentsSection && commentsSection.dataset.commentsLoaded === 'true') {
        return;
    }
    const requestKey = String(postId);
    if (!force && commentLoadPromises.has(requestKey)) {
        return commentLoadPromises.get(requestKey);
    }
    const loader = (async () => {
        try {
            const response = await fetch(`/comments/${postId}`, {
                headers: { Accept: 'application/json' }
            });

            if (!response.ok) {
                console.error('Error loading comments: ', await response.text());
                return;
            }

            const data = await response.json();
            renderCommentsState(postId, data);
        } catch (error) {
            console.error('Error loading comments:', error);
        } finally {
            commentLoadPromises.delete(requestKey);
        }
    })();
    commentLoadPromises.set(requestKey, loader);
    return loader;
}

// Función para enviar comentarios
async function submitComment(event, postId) {
    if (typeof isUserVerified === 'function' && !isUserVerified()) {
        showVerifyGate();
        return;
    }
    event.preventDefault();

    const form = event.target;
    const contentInput = form.querySelector('[name="content"]');
    const content = contentInput ? contentInput.value.trim() : '';
    if (!content) return;

    const formData = new FormData(form);
    formData.set('content', content);
    const csrfToken = getCsrfToken();
    if (csrfToken) {
        formData.set('csrf_token', csrfToken);
    }

    try {
        const response = await fetch(`/comment/${postId}`, {
            method: 'POST',
            headers: buildHeaders(),
            body: formData
        });

        if (handleAuthRedirect(response)) {
            return;
        }

        const data = await response.json();
        if (!response.ok || !data.ok) {
            showAlert(data.error || 'No se pudo enviar el comentario.', 'danger');
            if (data && data.error && data.error.toLowerCase().includes('restricción temporal')) {
                const secs = extractRemainingSeconds(data.error);
                if (secs !== null) {
                    showAlert(`Tiempo restante aproximado: ${secs} segundos.`, 'warning');
                }
            }
            return;
        }

        if (contentInput) {
            contentInput.value = '';
        }
        await loadComments(postId, true);
    } catch (error) {
        console.error('Error submitting comment:', error);
        showAlert('Ocurrió un error al enviar tu comentario.', 'danger');
    }
}

function openCommentReportModal(commentId, postId) {
    currentReportCommentId = Number(commentId);
    currentReportCommentPostId = Number(postId);
    const modalEl = document.getElementById('reportCommentModal');
    const form = document.getElementById('reportCommentForm');
    const errorEl = document.getElementById('reportCommentError');
    const detailsEl = document.getElementById('reportCommentDetails');
    if (form) form.reset();
    if (detailsEl) detailsEl.value = '';
    if (errorEl) {
        errorEl.textContent = '';
        errorEl.classList.add('d-none');
    }
    if (!modalEl || typeof bootstrap === 'undefined') return;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function optimisticallyHideReportedComment(postId, commentId) {
    const structure = ensureCommentsStructure(postId);
    if (!structure) return;

    const commentEl = structure.visibleWrap.querySelector(`.violet-comment[data-comment-id="${commentId}"]`);
    if (!commentEl) return;

    const reportBtn = commentEl.querySelector('.comment-report-btn');
    if (reportBtn) {
        reportBtn.remove();
    }

    commentEl.classList.add('violet-comment--hidden');
    const textEl = commentEl.querySelector('.violet-comment-text');
    if (textEl) {
        textEl.textContent = 'Este comentario ha sido reportado';
        textEl.classList.add('violet-comment-text--hidden');
    }

    structure.hiddenWrap.classList.remove('d-none');
    structure.hiddenList.appendChild(commentEl);
}

async function submitCommentReport(event) {
    event.preventDefault();
    const errorEl = document.getElementById('reportCommentError');
    const selectedReason = document.querySelector('input[name="comment_report_reason"]:checked');
    const detailsEl = document.getElementById('reportCommentDetails');
    const modalEl = document.getElementById('reportCommentModal');
    const form = event.target;
    const submitBtn = form ? form.querySelector('button[type="submit"]') : null;

    if (!currentReportCommentId || !currentReportCommentPostId) {
        if (errorEl) {
            errorEl.textContent = 'No se encontró el comentario a reportar.';
            errorEl.classList.remove('d-none');
        }
        return;
    }

    if (!selectedReason) {
        if (errorEl) {
            errorEl.textContent = 'Selecciona una clasificación antes de continuar.';
            errorEl.classList.remove('d-none');
        }
        return;
    }

    const commentId = currentReportCommentId;
    const postId = currentReportCommentPostId;
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.dataset.originalText = submitBtn.textContent || 'Enviar reporte';
        submitBtn.textContent = 'Enviando...';
    }

    if (modalEl && typeof bootstrap !== 'undefined') {
        const instance = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
        instance.hide();
    }
    optimisticallyHideReportedComment(postId, commentId);

    try {
        const response = await fetch(`/api/comment/${commentId}/report`, {
            method: 'POST',
            headers: buildHeaders('application/json'),
            body: JSON.stringify({
                reason: selectedReason.value,
                details: detailsEl ? detailsEl.value.trim() : ''
            })
        });

        if (handleAuthRedirect(response)) {
            return;
        }

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'No se pudo enviar el reporte');
        }

        currentReportCommentId = null;
        currentReportCommentPostId = null;
        loadComments(postId, true);
        notifyCommentAction(data.message || 'El comentario fue reportado correctamente.', 'success');
    } catch (error) {
        if (errorEl) {
            errorEl.textContent = error.message || 'No se pudo enviar el reporte.';
            errorEl.classList.remove('d-none');
        }
        await loadComments(postId, true);
        if (typeof showAlert === 'function') {
            showAlert(error.message || 'No se pudo enviar el reporte.', 'danger');
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = submitBtn.dataset.originalText || 'Enviar reporte';
        }
    }
}

function notifyCommentAction(message, type = 'info') {
    if (typeof showAlert === 'function') {
        showAlert(message, type);
    } else {
        alert(message);
    }
}

function prefetchPostDetailComments() {
    const targets = document.querySelectorAll('.comments-section[data-prefetch-comments="true"][data-comments-loaded="false"]');
    if (!targets.length) return;
    const runner = () => {
        targets.forEach((section) => {
            const postCard = section.closest('[data-post-id]');
            const postId = postCard ? Number(postCard.dataset.postId) : NaN;
            if (Number.isFinite(postId)) {
                loadComments(postId);
            }
        });
    };
    if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(runner, { timeout: 600 });
    } else {
        window.setTimeout(runner, 120);
    }
}

document.addEventListener('DOMContentLoaded', prefetchPostDetailComments);

function renderAdminBadge(username, sizeClass = 'admin-badge--xs') {
    if (username !== 'admin') return '';
    const cls = sizeClass ? ` ${sizeClass}` : '';
    return `<span class="admin-badge${cls}" title="Admin verificado" aria-label="Admin verificado"><img src="/static/images/admin_badge.svg" alt="Admin"></span>`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
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

// Función para abrir modal de compartir
function openShareModal(postId) {
    const modal = document.getElementById('shareModal');
    const postIdInput = document.getElementById('sharePostId');
    const shareForm = document.getElementById('shareForm');

    if (!modal || !postIdInput || !shareForm) {
        return;
    }

    postIdInput.value = postId;
    shareForm.reset();

    const bootstrapModal = new bootstrap.Modal(modal);
    bootstrapModal.show();
}

// Manejar envío del formulario de compartir
document.addEventListener('DOMContentLoaded', function () {
    const shareSubmitBtn = document.getElementById('shareSubmit');

    if (shareSubmitBtn) {
        shareSubmitBtn.addEventListener('click', async function () {
            const form = document.getElementById('shareForm');
            const postId = document.getElementById('sharePostId').value;
            if (!form || !postId) {
                return;
            }

            const formData = new FormData(form);
            const csrfToken = getCsrfToken();
            if (csrfToken) {
                formData.set('csrf_token', csrfToken);
            }

            try {
                const response = await fetch(`/share/${postId}`, {
                    method: 'POST',
                    headers: buildHeaders(),
                    body: formData
                });

                if (handleAuthRedirect(response)) {
                    return;
                }

                const data = await response.json();
                if (!response.ok || !data.ok) {
                    showAlert(data.error || 'No se pudo compartir la publicación.', 'danger');
                    return;
                }

                const modal = bootstrap.Modal.getInstance(document.getElementById('shareModal'));
                if (modal) {
                    modal.hide();
                }
                showAlert('Publicación compartida exitosamente', 'success');
            } catch (error) {
                console.error('Error sharing post:', error);
                showAlert('Ocurrió un error al compartir la publicación.', 'danger');
            }
        });
    }
});

// Función para mostrar alertas temporales
function showAlert(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    alertDiv.style.top = '20px';
    alertDiv.style.right = '20px';
    alertDiv.style.zIndex = '9999';
    alertDiv.style.minWidth = '300px';

    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    document.body.appendChild(alertDiv);

    // Auto-remover después de 5 segundos
    setTimeout(() => {
        if (alertDiv.parentElement) {
            alertDiv.remove();
        }
    }, 5000);
}

// Funcionalidad de scroll infinito (ya implementada en index.html)
// Aquí podríamos agregar más funciones auxiliares si fuera necesario

// --------------------------------------------------------------
// Búsqueda: conecta inputs de búsqueda a /api/search
// --------------------------------------------------------------
(function () {
    const BASE_MIN = 2; // mínimo de caracteres para buscar

    function debounce(fn, wait) {
        let t; return function (...args) { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), wait); };
    }

    function ensureResultsContainer(input) {
        let box = input._resultsBox;
        if (box && document.body.contains(box)) return box;
        box = document.createElement('div');
        box.className = 'violet-search-results';
        Object.assign(box.style, {
            position: 'absolute', zIndex: '2000', left: '0', right: '0', top: '100%',
            background: '#fff', borderRadius: '12px', boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
            padding: '8px', marginTop: '6px', maxHeight: '320px', overflowY: 'auto'
        });
        // Insertar bajo el contenedor visual del input
        const parent = input.closest('.search-container') || input.parentNode;
        parent.style.position = parent.style.position || 'relative';
        parent.appendChild(box);
        input._resultsBox = box;
        return box;
    }

    function clearResults(input) {
        const box = input._resultsBox; if (!box) return; box.innerHTML = ''; box.style.display = 'none';
    }

    function renderResults(input, data) {
        const box = ensureResultsContainer(input);
        box.innerHTML = '';
        const hasUsers = Array.isArray(data.users) && data.users.length;
        const hasPosts = Array.isArray(data.posts) && data.posts.length;
        if (!hasUsers && !hasPosts) { clearResults(input); return; }

        function sectionTitle(text) {
            const t = document.createElement('div');
            t.textContent = text; t.style.fontWeight = '600'; t.style.fontSize = '0.85rem'; t.style.margin = '6px 8px'; t.style.color = '#6c757d';
            return t;
        }
        function itemUser(u) {
            const a = document.createElement('a'); a.href = `/user/${encodeURIComponent(u.username)}`; a.style.textDecoration = 'none'; a.style.color = 'inherit';
            const row = document.createElement('div'); row.style.display = 'flex'; row.style.alignItems = 'center'; row.style.gap = '10px'; row.style.padding = '8px'; row.style.borderRadius = '8px';
            row.addEventListener('mouseenter', () => row.style.background = '#f8f9fa');
            row.addEventListener('mouseleave', () => row.style.background = 'transparent');
            const img = document.createElement('img'); img.alt = 'avatar'; img.src = u.profile_pic || `https://ui-avatars.com/api/?name=${encodeURIComponent(u.username)}&background=b565a7&color=fff&rounded=true&size=48`; img.style.width = '32px'; img.style.height = '32px'; img.style.borderRadius = '50%'; img.style.objectFit = 'cover';
            const col = document.createElement('div');
            const u1 = document.createElement('div'); u1.textContent = `@${u.username}`; u1.style.fontWeight = '600';
            const u2 = document.createElement('div'); u2.textContent = `${u.posts_count} reportes`; u2.style.fontSize = '0.8rem'; u2.style.color = '#6c757d';
            col.appendChild(u1); col.appendChild(u2);
            row.appendChild(img); row.appendChild(col); a.appendChild(row); return a;
        }
        function itemPost(p) {
            const a = document.createElement('a'); a.href = `/post/${p.id}`; a.style.textDecoration = 'none'; a.style.color = 'inherit';
            const row = document.createElement('div'); row.style.display = 'flex'; row.style.alignItems = 'center'; row.style.gap = '10px'; row.style.padding = '8px'; row.style.borderRadius = '8px';
            row.addEventListener('mouseenter', () => row.style.background = '#f8f9fa');
            row.addEventListener('mouseleave', () => row.style.background = 'transparent');
            const img = document.createElement('img'); img.alt = 'post'; img.src = p.image_url; img.style.width = '44px'; img.style.height = '44px'; img.style.objectFit = 'cover'; img.style.borderRadius = '8px';
            const col = document.createElement('div');
            const t1 = document.createElement('div'); t1.textContent = p.caption || '(Sin descripción)'; t1.style.fontSize = '0.9rem'; t1.style.whiteSpace = 'nowrap'; t1.style.overflow = 'hidden'; t1.style.textOverflow = 'ellipsis'; t1.style.maxWidth = '220px';
            const t2 = document.createElement('div'); t2.textContent = `@${p.username}`; t2.style.fontSize = '0.8rem'; t2.style.color = '#6c757d';
            col.appendChild(t1); col.appendChild(t2);
            row.appendChild(img); row.appendChild(col); a.appendChild(row); return a;
        }

        if (hasUsers) { box.appendChild(sectionTitle('Usuarios')); data.users.forEach(u => box.appendChild(itemUser(u))); }
        if (hasPosts) { box.appendChild(sectionTitle('Reportes')); data.posts.forEach(p => box.appendChild(itemPost(p))); }
        box.style.display = 'block';
    }

    async function doSearch(input) {
        const q = (input.value || '').trim();
        if (q.length < BASE_MIN) { clearResults(input); return; }
        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&type=both`, { headers: { Accept: 'application/json' } });
            if (!res.ok) return;
            const data = await res.json();
            renderResults(input, data);
        } catch (e) { console.error('search error', e); }
    }

    function bindSearch(input) {
        if (!input) return;
        const handler = debounce(() => doSearch(input), 200);
        input.addEventListener('input', handler);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { clearResults(input); }
            if (e.key === 'Enter') { e.preventDefault(); doSearch(input); }
        });
        document.addEventListener('click', (e) => {
            const box = input._resultsBox; if (!box) return;
            if (!box.contains(e.target) && e.target !== input) { clearResults(input); }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        bindSearch(document.querySelector('.search-input'));
        bindSearch(document.querySelector('.violet-search-input'));

        // Enlazar icono "compass" a página de hotspots sin alterar la UI
        const compassIcon = document.querySelector('.bottom-nav i.fa-compass');
        if (compassIcon && compassIcon.parentElement && compassIcon.parentElement.tagName === 'A') {
            compassIcon.parentElement.setAttribute('href', '/hotspots');
        }
    });
})();

// Manejar preview de imagen antes de subir
document.addEventListener('DOMContentLoaded', function () {
    const imageInput = document.querySelector('input[type="file"][name="image"]');

    if (imageInput) {
        imageInput.addEventListener('change', function (event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    // Crear preview si no existe
                    let preview = document.getElementById('image-preview');
                    if (!preview) {
                        preview = document.createElement('div');
                        preview.id = 'image-preview';
                        preview.className = 'mt-2';
                        imageInput.parentNode.appendChild(preview);
                    }

                    preview.innerHTML = `
                        <img src="${e.target.result}" class="img-fluid rounded" style="max-height: 200px;">
                        <small class="text-muted d-block mt-1">${file.name}</small>
                    `;
                };
                reader.readAsDataURL(file);
            }
        });
    }
});

// Añadir funcionalidad de doble click para dar like
document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('dblclick', function (event) {
        const postImage = event.target.closest('.violet-post-image');
        if (!postImage) {
            return;
        }

        const postCard = postImage.closest('.violet-post-card');
        if (!postCard) {
            return;
        }

        const postId = postCard.dataset.postId;
        const likeBtn = postCard.querySelector('.like-btn');

        // Solo si el usuario está autenticado
        if (!likeBtn) {
            return;
        }

        toggleLike(postId);

        // Crear animación de corazón
        const heart = document.createElement('div');
        heart.innerHTML = '❤️';
        heart.style.position = 'absolute';
        heart.style.fontSize = '50px';
        heart.style.color = '#e1306c';
        heart.style.zIndex = '1000';
        heart.style.pointerEvents = 'none';
        heart.style.left = event.clientX - 25 + 'px';
        heart.style.top = event.clientY - 25 + 'px';
        heart.style.transform = 'scale(0)';
        heart.style.transition = 'all 0.5s ease';

        document.body.appendChild(heart);

        setTimeout(() => {
            heart.style.transform = 'scale(1.5)';
            heart.style.opacity = '0';
        }, 50);

        setTimeout(() => {
            heart.remove();
        }, 600);
    });
});

// VIOLETA Specific Functions
// Funciones para la nueva interfaz de VIOLETA

// Validación de formularios en tiempo real
function initVioletFormValidation() {
    const inputs = document.querySelectorAll('.violet-input');

    inputs.forEach(input => {
        input.addEventListener('blur', function () {
            validateInput(this);
        });

        input.addEventListener('input', function () {
            // Remover error al escribir
            this.classList.remove('error');
            const errorElement = this.parentNode.querySelector('.violet-error');
            if (errorElement) {
                errorElement.style.display = 'none';
            }
        });
    });
}

// Función para validar un input individual
function validateInput(input) {
    const value = input.value.trim();
    let isValid = true;
    let errorMessage = '';

    // Validación por tipo
    switch (input.type) {
        case 'email':
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
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

    // Username específico
    if (input.id === 'username' && value !== '') {
        const usernameRegex = /^[a-zA-Z0-9._]+$/;
        if (!usernameRegex.test(value)) {
            isValid = false;
            errorMessage = 'Username can only contain letters, numbers, periods, and underscores';
        }
    }

    // Mostrar/ocultar error
    if (!isValid) {
        input.classList.add('error');
        showInputError(input, errorMessage);
    } else {
        input.classList.remove('error');
        hideInputError(input);
    }

    return isValid;
}

// Mostrar error en input
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

// Ocultar error en input
function hideInputError(input) {
    const errorElement = input.parentNode.querySelector('.violet-error');
    if (errorElement) {
        errorElement.style.display = 'none';
    }
}

// Animaciones de botones
function initVioletButtonAnimations() {
    const buttons = document.querySelectorAll('.violet-btn-primary, .violet-btn-secondary');

    buttons.forEach(button => {
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

// Efectos de focus para inputs
function initVioletInputEffects() {
    const inputs = document.querySelectorAll('.violet-input');

    inputs.forEach(input => {
        input.addEventListener('focus', function () {
            this.parentNode.classList.add('focused');
        });

        input.addEventListener('blur', function () {
            this.parentNode.classList.remove('focused');
        });
    });
}

// Función para mostrar notificaciones estilo VIOLETA
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

    // Estilos en línea para la notificación
    Object.assign(notification.style, {
        position: 'fixed',
        top: '20px',
        right: '20px',
        backgroundColor: type === 'error' ? '#ff4757' : type === 'success' ? '#2ed573' : '#b565a7',
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

    // Animación de entrada
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 100);

    // Auto-remover
    setTimeout(() => {
        notification.style.transform = 'translateX(400px)';
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 300);
    }, duration);
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
                <img class="violet-chat-toast__avatar" src="${escapeHtml(roomImageUrl)}" alt="${escapeHtml(roomName)}">
                <div class="violet-chat-toast__body">
                    <div class="violet-chat-toast__title">${escapeHtml(roomName)}</div>
                    <div class="violet-chat-toast__message"><span class="violet-chat-toast__user">${escapeHtml(username)}</span>: ${escapeHtml(messageText)}</div>
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

            // If we're already in /chat and the function exists, switch rooms without navigating.
            if (window.location && window.location.pathname === '/chat' && typeof window.selectRoom === 'function') {
                try {
                    window.selectRoom(Number(rid));
                    return;
                } catch (err) {}
            }

            window.location.href = `/chat?room=${encodeURIComponent(rid)}`;
        });

        flash.appendChild(toast);

        // Limit stacked toasts to avoid flooding the UI.
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
        // Never throw from a notification helper.
    }
}

// Poll chat rooms for new unread messages and show a toast.
(function initChatRoomToasts() {
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
            const res = await fetch('/api/chat/rooms', { headers: { 'Accept': 'application/json' } });
            if (!res.ok) return;
            const data = await res.json();
            const rooms = Array.isArray(data.rooms) ? data.rooms : [];

            if (!initialized || initial) {
                rooms.forEach(r => {
                    const key = msgKey(r.last_unread_message);
                    lastUnreadKeyByRoom.set(String(r.id), key || '');
                });
                initialized = true;
                return;
            }

            const activeRoomId = (window.__CHAT_CURRENT_ROOM_ID != null) ? Number(window.__CHAT_CURRENT_ROOM_ID) : null;

            rooms.forEach(r => {
                const roomIdStr = String(r.id);
                const unread = r.last_unread_message || null;
                const key = msgKey(unread);
                const prevKey = lastUnreadKeyByRoom.get(roomIdStr) || '';

                // If user read the room, reset baseline.
                if (!unread || !key || Number(r.unread_count || 0) <= 0) {
                    lastUnreadKeyByRoom.set(roomIdStr, '');
                    return;
                }

                if (key === prevKey) return;
                lastUnreadKeyByRoom.set(roomIdStr, key);

                // If the user is actively viewing this room, don't show a toast.
                if (activeRoomId && Number.isFinite(activeRoomId) && Number(r.id) === activeRoomId) return;

                const preview = formatChatToastPreview(unread);
                if (!preview) return;

                showChatMessageToast({
                    room_id: r.id,
                    room_name: r.name,
                    room_image_url: r.image_url,
                    username: unread.username,
                    message: preview,
                });
            });
        } catch (e) {
            // ignore
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
})();

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

        // Avoid showing the toast if user is already viewing this report.
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
        const timeLabel = publishedAt ? getRelativeTime(publishedAt) : '';

        const toast = document.createElement('div');
        toast.className = 'alert violet-nearby-toast alert-dismissible fade show popup-alert';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        toast.setAttribute('aria-atomic', 'true');
        toast.setAttribute('data-post-id', String(postId));
        toast.innerHTML = `
            <div class="violet-nearby-toast__content">
                <div class="violet-nearby-toast__thumb-wrap" aria-hidden="true">
                    ${imageUrl ? `<img class="violet-nearby-toast__thumb" src="${escapeHtml(imageUrl)}" alt="">` : `<div class="violet-nearby-toast__thumb violet-nearby-toast__thumb--fallback"><i class="fa-solid fa-location-dot" aria-hidden="true"></i></div>`}
                </div>
                <div class="violet-nearby-toast__body">
                    <div class="violet-nearby-toast__title">Reporte cerca de ti</div>
                    <div class="violet-nearby-toast__meta">
                        ${distLabel ? `<span class="violet-nearby-toast__chip">${escapeHtml(distLabel)}</span>` : ''}
                        <span class="violet-nearby-toast__chip violet-nearby-toast__chip--cat">${escapeHtml(primaryCategory)}</span>
                        ${timeLabel ? `<span class="violet-nearby-toast__time">${escapeHtml(timeLabel)}</span>` : ''}
                    </div>
                    <div class="violet-nearby-toast__message"><span class="violet-nearby-toast__user">${escapeHtml(username)}</span>: ${escapeHtml(messageText)}</div>
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

        // Limit stacked toasts to avoid flooding the UI.
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
        // Never throw from a notification helper.
    }
}

// Poll nearby reports (within 1km) and show a toast when a new report is published near the user.
(function initNearbyReportToasts() {
    const POLL_MS = 15000;
    const INITIAL_DELAY_MS = 3000;
    const RADIUS_KM = 1;
    const GEO_TTL_MS = 25000;

    let lastSinceMs = null;
    let lastGeo = null; // { lat, lng, ts }
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
                        if (err && err.code === 1) { // PERMISSION_DENIED
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

        // Baseline: don't show notifications for old reports when the page loads.
        if (lastSinceMs == null) {
            lastSinceMs = Date.now();
            return;
        }

        try {
            let since = lastSinceMs;
            // If the tab was inactive for a while, avoid flooding with old reports.
            const maxLookbackMs = 2 * 60 * 1000;
            if (Number.isFinite(since) && (Date.now() - since) > maxLookbackMs) {
                since = Date.now() - maxLookbackMs;
            }
            const url = `/api/reports/nearby?lat=${encodeURIComponent(String(geo.lat))}&lng=${encodeURIComponent(String(geo.lng))}&radius_km=${encodeURIComponent(String(RADIUS_KM))}&since=${encodeURIComponent(String(since))}`;
            const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!res.ok) return;
            const data = await res.json();
            const reports = Array.isArray(data.reports) ? data.reports : [];

            // Move cursor only after a successful fetch to reduce the chance of missing events on flaky networks.
            lastSinceMs = Date.now();

            if (initial) return;

            reports.forEach((r) => {
                if (!r || r.id == null) return;
                const id = String(r.id);
                if (shownIds.has(id)) return;
                shownIds.add(id);

                const msg = formatNearbyReportToastPreview(r);
                if (!msg) return;

                enqueueToast({
                    post_id: r.id,
                    image_url: r.image_url,
                    username: r.username,
                    message: msg,
                    categories: r.categories,
                    distance_km: r.distance_km,
                    published_at: r.published_at,
                });
            });
        } catch (e) {
            // ignore
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

        // Permission UX: avoid prompting for geolocation on page load if the browser would show a permission prompt.
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
                    // "prompt": wait for a user gesture before requesting location.
                    const enable = () => {
                        geoRequestReady = true;
                        startPolling();
                    };
                    window.addEventListener('pointerdown', enable, { once: true, passive: true });
                    window.addEventListener('keydown', enable, { once: true });
                }).catch(() => {
                    // Fallback: require user gesture before requesting location.
                    const enable = () => {
                        geoRequestReady = true;
                        startPolling();
                    };
                    window.addEventListener('pointerdown', enable, { once: true, passive: true });
                    window.addEventListener('keydown', enable, { once: true });
                });
            } else {
                // Fallback: require user gesture before requesting location.
                const enable = () => {
                    geoRequestReady = true;
                    startPolling();
                };
                window.addEventListener('pointerdown', enable, { once: true, passive: true });
                window.addEventListener('keydown', enable, { once: true });
            }
        } catch (_) {}
    });
})();

function isUserVerified() {
    return window.USER_IS_VERIFIED !== false;
}

function showVerifyGate() {
    const msg = window.VERIFY_REQUIRED_MSG || 'Para poder ver el contenido tenemos que verificar tu identidad';
    if (typeof showVioletNotification === 'function') {
        showVioletNotification(msg, 'info', 5000);
    } else {
        alert(msg);
    }
}

window.showVerifyGate = showVerifyGate;
window.isUserVerified = isUserVerified;

// Block actions that require verification
document.addEventListener('click', function (event) {
    if (isUserVerified()) return;
    const target = event.target.closest('[data-require-verified]');
    if (target) {
        event.preventDefault();
        event.stopPropagation();
        showVerifyGate();
    }
}, true);

// --------------------------------------------------------------
// Page transitions on button/link click
// --------------------------------------------------------------
(function () {
    function isModifiedEvent(e) { return e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0; }
    function isSameOrigin(href) { try { const u = new URL(href, window.location.href); return u.origin === window.location.origin; } catch (_) { return false; } }
    const prefetchedUrls = new Set();

    function prefetchDocument(href) {
        if (!href || href.startsWith('#') || href.startsWith('tel:') || href.startsWith('mailto:')) return;
        if (!isSameOrigin(href)) return;
        const normalized = new URL(href, window.location.href).toString();
        if (prefetchedUrls.has(normalized)) return;
        const link = document.createElement('link');
        link.rel = 'prefetch';
        link.as = 'document';
        link.href = normalized;
        document.head.appendChild(link);
        prefetchedUrls.add(normalized);
    }

    function shouldPrefetchLink(link) {
        if (!link || !link.href) return false;
        if (link.dataset && link.dataset.noPrefetch === '1') return false;
        const href = link.getAttribute('href') || '';
        if (!href || href.startsWith('#') || href.startsWith('tel:') || href.startsWith('mailto:')) return false;
        if (!isSameOrigin(href)) return false;
        try {
            const url = new URL(href, window.location.href);
            if (url.pathname === '/logout') return false;
        } catch (_) {
            return false;
        }
        return true;
    }

    function animateOutAndNavigate(href) {
        window.location.href = href;
    }
    document.addEventListener('DOMContentLoaded', function () {
        const area = document.querySelector('.main-content');
        if (area) {
            // animate entry
            requestAnimationFrame(() => { area.classList.add('page-anim-in'); });
        }

        document.querySelectorAll('.sidebar-link, .bottom-nav .nav-item, .widget-card a, .brand-logo a').forEach((link) => {
            if (shouldPrefetchLink(link)) prefetchDocument(link.href);
        });

        // Delegate clicks on nav and primary buttons/links
        document.addEventListener('click', function (e) {
            const target = e.target.closest('a, button');
            if (!target) return;
            if (target.dataset && target.dataset.noAnim === '1') return;

            // Links: same origin and not anchor/hash/tel/mailto
            if (target.tagName === 'A') {
                const href = target.getAttribute('href') || '';
                if (!href || href.startsWith('#') || href.startsWith('tel:') || href.startsWith('mailto:')) return;
                if (isModifiedEvent(e)) return;
                if (!isSameOrigin(href)) return;

                e.preventDefault();
                animateOutAndNavigate(href);
            }
        }, true);

        document.addEventListener('pointerenter', function (e) {
            const link = e.target.closest('a[href]');
            if (!shouldPrefetchLink(link)) return;
            prefetchDocument(link.href);
        }, true);

        document.addEventListener('focusin', function (e) {
            const link = e.target.closest('a[href]');
            if (!shouldPrefetchLink(link)) return;
            prefetchDocument(link.href);
        }, true);
    });
})();

// Inicializar todas las funciones cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', function () {
    initVioletFormValidation();
    initVioletButtonAnimations();
    initVioletInputEffects();

    // Sobrescribir la función showAlert para usar el nuevo estilo
    window.showAlert = function (message, type = 'info') {
        showVioletNotification(message, type);
    };

    // Explicitly handle Enter key for comment inputs
    document.addEventListener('keydown', function (event) {
        if (event.target.name === 'content' && event.target.closest('.comments-section')) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const form = event.target.closest('form');
                if (form) {
                    // Trigger the submit event handler programmatically
                    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                }
            }
        }
    });
});
