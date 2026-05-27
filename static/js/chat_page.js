    // Chat functionality
    let currentRoomId = null;
    let currentRoomData = null;
    let roomIndex = {};
    let socket = null;
    const CHAT_PAGE_CONFIG = window.CHAT_PAGE_CONFIG || {};
    let currentUser = CHAT_PAGE_CONFIG.currentUser || '';
    let currentUserId = CHAT_PAGE_CONFIG.currentUserId ?? null;
    let currentIsAdmin = !!CHAT_PAGE_CONFIG.currentIsAdmin;
    let currentCanManageRooms = !!CHAT_PAGE_CONFIG.currentCanManageRooms || currentIsAdmin;
    let currentUserAvatar = CHAT_PAGE_CONFIG.currentUserAvatar || '/static/images/default_avatar.jpg';
    const CHAT_CSRF_TOKEN = CHAT_PAGE_CONFIG.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '';
    const CHAT_LOGOUT_URL = CHAT_PAGE_CONFIG.logoutUrl || '/logout';
    let roomCropFile = null;
    let roomCropper = null;
    let roomCropModal = null;
    let roomCropUrl = null;
    let pendingAttachmentFile = null;
    let autoOpenRoomId = null;
    let joinedSocketRooms = new Set();
    let currentReportMessageId = null;
    let chatRoomsLoadPromise = null;
    let lastChatRoomsLoadedAt = 0;
    const CHAT_ROOMS_REFRESH_DEBOUNCE_MS = 1200;
    const CHAT_ROOMS_CACHE_KEY = 'violeta_chat_rooms_cache_v1';
    const CHAT_ROOMS_CACHE_TTL_MS = 20000;

    function isMobileChatView() {
        return window.matchMedia('(max-width: 767.98px)').matches;
    }

    function syncChatViewportHeight() {
        if (!document.body.classList.contains('chat-page')) return;
        const height = window.visualViewport?.height || window.innerHeight;
        if (!height) return;
        document.documentElement.style.setProperty('--chat-viewport-height', `${Math.round(height)}px`);
    }

    syncChatViewportHeight();
    window.addEventListener('resize', syncChatViewportHeight, { passive: true });
    window.visualViewport?.addEventListener('resize', syncChatViewportHeight, { passive: true });
    try {
        const raw = new URLSearchParams(window.location.search).get('room');
        const parsed = raw ? Number(raw) : NaN;
        autoOpenRoomId = Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    } catch (e) {
        autoOpenRoomId = null;
    }

    document.addEventListener('DOMContentLoaded', function () {
        initializeChat();
    });

    function initializeChat() {
        // Initialize Socket.IO
        socket = io();

        // Load user's chat rooms
        loadChatRooms();

        // Setup event listeners
        setupEventListeners();
        setupAttachmentPicker();
        setInterval(refreshDeleteButtons, 30000);

        // Socket event handlers
			        socket.on('new_message', function (data) {
			            if (!data) return;
			            if (data.room_id == currentRoomId) {
			                const upgraded = upgradePendingMessage(buildPendingKey(data.content, data.attachment_name), data);
			                const existing = (data.id != null) ? document.querySelector(`.chat-message-row[data-message-id="${data.id}"]`) : null;
			                if (!upgraded && !existing) {
			                    appendMessage(data);
			                }
			                // We're viewing this room, so treat it as seen.
			                scheduleMarkRoomRead(currentRoomId);
			            }
			            // Update room list to show new message
			            updateRoomInList(data.room_id, data);
			        });

	        socket.on('room_cleared', function (data) {
	            if (data.room_id == currentRoomId) {
	                const container = document.querySelector('.chat-messages');
	                if (container) {
	                    container.innerHTML = '<div class="chat-placeholder"><p>El chat fue vaciado por una administradora.</p></div>';
	                }
	                if (currentRoomData) {
	                    currentRoomData.last_message = null;
	                }
	                updateRoomHeader();
	                updateSendState();
	            } else {
	                // Si el usuario está dentro de un chat, no reemplazar la vista actual.
	                if (!currentRoomId) {
	                    loadChatRooms({ force: true });
	                }
	            }
	        });

        socket.on('message_deleted', function (data) {
            if (!data || !data.message_id) return;
            const deletedReason = data.deleted_reason || 'deleted';
            applyMessageDeleted(data.message_id, deletedReason);
            if (data.room_id && roomIndex && roomIndex[data.room_id]) {
                const roomLastMessage = roomIndex[data.room_id].last_message;
                if (roomLastMessage && Number(roomLastMessage.id) === Number(data.message_id)) {
                    updateRoomInList(data.room_id, {
                        id: data.message_id,
                        room_id: data.room_id,
                        content: '',
                        username: data.username || roomLastMessage.username,
                        created_at: data.created_at || roomLastMessage.created_at,
                        message_type: data.message_type || roomLastMessage.message_type,
                        attachment_name: null,
                        attachment_url: null,
                        attachment_mime: null,
                        is_deleted: true,
                        deleted_reason: deletedReason,
                    });
                }
            }
        });

        socket.on('message_restored', function (data) {
            if (!data || !data.message) return;
            const payload = data.message;
            if (data.room_id == currentRoomId) {
                applyMessageRestored(payload);
            }
            if (payload.room_id) {
                updateRoomInList(payload.room_id, payload);
            }
        });

        socket.on('user_joined', function (data) {
            if (data && data.username === currentUser) return;
            if (data.room_id == currentRoomId) {
                showSystemMessage(`${data.username} se unió al chat`);
            }
        });

        socket.on('user_left', function (data) {
            if (data && data.username === currentUser) return;
            if (data.room_id == currentRoomId) {
                showSystemMessage(`${data.username} salió del chat`);
            }
        });
    }

    function setupEventListeners() {
        // Send message button
        const sendBtn = document.querySelector('.chat-send-btn');
        const input = document.querySelector('.chat-input');
        const inputArea = document.querySelector('.chat-input-area');
        const attachBtn = document.getElementById('chatAttachBtn');
        const messagesContainer = document.querySelector('.chat-messages');
        const createBtn = document.getElementById('createRoomBtnTop');

        if (sendBtn && input) {
            sendBtn.addEventListener('click', sendMessage);
            input.addEventListener('keypress', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
            // Toggle send button state on input changes
            input.addEventListener('input', updateSendState);
            // Initialize state
            updateSendState();
        }

        // Logout link: clear and disable input before navigating
        const logoutUrl = CHAT_LOGOUT_URL;
        document.querySelectorAll(`a[href='${logoutUrl}']`).forEach(el => {
            el.addEventListener('click', () => {
                const input = document.querySelector('.chat-input');
                if (input) input.value = '';
                updateSendState();
            });
        });

        const searchInput = document.getElementById('chatSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                filterChatRooms(e.target.value);
            });
        }

        if (createBtn) {
            createBtn.addEventListener('click', showCreateRoomModal);
        }

        const backBtn = document.getElementById('chatBackBtn');
        if (backBtn) {
            backBtn.addEventListener('click', () => {
                const leavingRoomId = currentRoomId;
                if (leavingRoomId) {
                    // Make sure the room is marked as read so the badge doesn't reappear for messages already seen.
                    markRoomRead(leavingRoomId, true);
                }
                currentRoomId = null;
                window.__CHAT_CURRENT_ROOM_ID = null;
                currentRoomData = null;
                document.querySelectorAll('.chat-room-item').forEach(item => item.classList.remove('active'));
                loadChatRooms({ force: true });
                const container = document.getElementById('chatMessages');
                if (container) {
                    container.innerHTML = `
                        <div class="chat-placeholder chat-main-empty">
                            <i class="fas fa-comments"></i>
                            <p>Selecciona una sala para ver los mensajes.</p>
                        </div>
                    `;
                }
                updateRoomHeader();
                updateSendState();
            });
        }

        // Edit room
        const editBtn = document.getElementById('editChatRoomBtn');
        if (editBtn) {
            editBtn.addEventListener('click', () => {
                if (!currentRoomData) return;
                const preview = document.getElementById('editRoomPreview');
                const descInput = document.getElementById('editRoomDescInput');
                const deleteBtn = document.getElementById('deleteRoomBtn');
                const clearBtn = document.getElementById('clearRoomBtn');
                const editFileInput = document.getElementById('editRoomFile');
                const modeAll = document.getElementById('editRoomModeAll');
                const modeRestricted = document.getElementById('editRoomModeRestricted');
                if (preview) preview.src = currentRoomData.image_url || '/static/images/favicon.png';
                if (descInput) descInput.value = currentRoomData.description || '';
                if (deleteBtn) {
                    deleteBtn.classList.toggle('d-none', !currentCanManageRooms);
                }
                if (clearBtn) {
                    clearBtn.classList.toggle('d-none', !currentCanManageRooms);
                }
                if (modeAll && modeRestricted) {
                    const open = currentRoomData.messages_open !== false;
                    modeAll.checked = open;
                    modeRestricted.checked = !open;
                }
                roomCropFile = null;
                if (editFileInput) editFileInput.value = '';
                const modal = new bootstrap.Modal(document.getElementById('editRoomModal'));
                modal.show();
            });
        }

        const editPickBtn = document.getElementById('editRoomPickBtn');
        const editFileInput = document.getElementById('editRoomFile');
        const editPreview = document.getElementById('editRoomPreview');
        const roomCropperModalEl = document.getElementById('chatCropperModal');
        const roomCropperImage = document.getElementById('chatCropperImage');
        const roomCropperApplyBtn = document.getElementById('chatApplyCropBtn');
        const roomCropperChooseBtn = document.getElementById('chatChooseCropFileBtn');

        function openRoomCropper(file) {
            if (!roomCropperModalEl || !roomCropperImage || typeof Cropper === 'undefined') {
                roomCropFile = file;
                if (editPreview) {
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                        editPreview.src = ev.target.result;
                    };
                    reader.readAsDataURL(file);
                }
                return;
            }
            roomCropFile = file;
            if (roomCropUrl) {
                URL.revokeObjectURL(roomCropUrl);
            }
            roomCropUrl = URL.createObjectURL(file);
            roomCropperImage.src = roomCropUrl;
            roomCropModal.show();
        }

        if (roomCropperModalEl && window.bootstrap) {
            roomCropModal = new bootstrap.Modal(roomCropperModalEl, {
                backdrop: false,
                focus: false,
                keyboard: true
            });
            roomCropperModalEl.addEventListener('shown.bs.modal', () => {
                if (roomCropper) roomCropper.destroy();
                if (!roomCropperImage || typeof Cropper === 'undefined') return;
                roomCropper = new Cropper(roomCropperImage, {
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
            roomCropperModalEl.addEventListener('hidden.bs.modal', () => {
                if (roomCropper) {
                    roomCropper.destroy();
                    roomCropper = null;
                }
                if (roomCropUrl) {
                    URL.revokeObjectURL(roomCropUrl);
                    roomCropUrl = null;
                }
                if (editFileInput) editFileInput.value = '';
                if (document.getElementById('editRoomModal')?.classList.contains('show')) {
                    document.body.classList.add('modal-open');
                }
            });
        }

        if (roomCropperApplyBtn) {
            roomCropperApplyBtn.addEventListener('click', () => {
                if (!roomCropper || !roomCropFile) return;
                const outputType = roomCropFile.type === 'image/png' ? 'image/png' : 'image/jpeg';
                const canvas = roomCropper.getCroppedCanvas({
                    width: 512,
                    height: 512,
                    fillColor: '#000'
                });
                if (!canvas) return;
                const quality = outputType === 'image/jpeg' ? 0.92 : undefined;
                canvas.toBlob((blob) => {
                    if (!blob) return;
                    roomCropFile = new File([blob], roomCropFile.name || `sala-${Date.now()}.jpg`, { type: outputType });
                    if (editPreview) {
                        const url = URL.createObjectURL(blob);
                        editPreview.src = url;
                    }
                    roomCropModal.hide();
                }, outputType, quality);
            });
        }

        if (roomCropperChooseBtn) {
            roomCropperChooseBtn.addEventListener('click', () => {
                if (roomCropModal) roomCropModal.hide();
                if (editFileInput) editFileInput.click();
            });
        }

        if (editPickBtn && editFileInput) {
            editPickBtn.addEventListener('click', () => editFileInput.click());
            editFileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;
                openRoomCropper(file);
            });
        }

        const saveRoomBtn = document.getElementById('saveRoomBtn');
        if (saveRoomBtn) {
            saveRoomBtn.addEventListener('click', () => {
                if (!currentRoomId) return;
                const formData = new FormData();
                const descInput = document.getElementById('editRoomDescInput');
                const modeAll = document.getElementById('editRoomModeAll');
                const modeRestricted = document.getElementById('editRoomModeRestricted');
                if (descInput) {
                    formData.append('description', descInput.value.trim());
                }
                if (modeAll && modeRestricted) {
                    const messagesOpen = modeAll.checked || !modeRestricted.checked;
                    formData.append('messages_open', messagesOpen ? 'true' : 'false');
                }
                if (roomCropFile) {
                    formData.append('photo', roomCropFile);
                } else if (editFileInput && editFileInput.files[0]) {
                    formData.append('photo', editFileInput.files[0]);
                }
                fetch(`/api/chat/room/${currentRoomId}/update`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': CHAT_CSRF_TOKEN },
                    body: formData
                })
                    .then(response => response.json())
                    .then(data => {
                        if (!data.success) {
                            alert('Error: ' + (data.error || 'No se pudo actualizar'));
                            return;
                        }
                        currentRoomData = {
                            ...currentRoomData,
                            description: data.room.description,
                            image_url: data.room.image_url,
                            created_by: data.room.created_by,
                            messages_open: data.room.messages_open,
                            can_post: data.room.messages_open ? true : (currentIsAdmin || data.room.created_by === currentUserId)
                        };
                        updateRoomHeader();
                        loadChatRooms({ force: true });
                        bootstrap.Modal.getInstance(document.getElementById('editRoomModal')).hide();
                    })
                    .catch(err => {
                        console.error(err);
                        alert('Error al actualizar la sala');
                    });
            });
        }

        function playWarningBeep() {
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.value = 880;
                gain.gain.value = 0.08;
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + 0.12);
            } catch (e) {
                // No audio available
            }
        }

        const deleteRoomBtn = document.getElementById('deleteRoomBtn');
        if (deleteRoomBtn) {
            deleteRoomBtn.addEventListener('click', () => {
                playWarningBeep();
                const existingModal = document.getElementById('deleteRoomConfirmModal');
                if (existingModal) existingModal.remove();

                const modalHtml = `
                    <div class="modal fade" id="deleteRoomConfirmModal" tabindex="-1">
                        <div class="modal-dialog modal-dialog-centered">
                            <div class="modal-content vio-card chat-delete-modal" style="background: #1f1b2d; color: #fff;">
                                <div class="modal-header violet-modal-header">
                                    <div class="chat-delete-title">
                                        <span class="delete-icon">
                                            <i class="fas fa-triangle-exclamation"></i>
                                        </span>
                                        <h5 class="modal-title">Eliminar chat</h5>
                                    </div>
                                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                                </div>
                                <div class="modal-body">
                                    <p class="mb-2">¿Estás segura de que quieres borrar este chat?</p>
                                    <p class="text-warning small mb-0">Todos los mensajes, imágenes y archivos serán eliminados y no podrán ser recuperados.</p>
                                </div>
                                <div class="modal-footer">
                                    <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Cancelar</button>
                                    <button type="button" class="btn btn-danger" id="confirmDeleteRoomBtn">Sí, eliminar</button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                document.body.insertAdjacentHTML('beforeend', modalHtml);
                const modalElement = document.getElementById('deleteRoomConfirmModal');
                const modal = new bootstrap.Modal(modalElement, {
                    backdrop: false,
                    focus: false,
                    keyboard: true
                });

                modalElement.addEventListener('hidden.bs.modal', function () {
                    document.body.classList.remove('chat-delete-open');
                    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
                    this.remove();
                });

                modalElement.addEventListener('shown.bs.modal', function () {
                    document.body.classList.add('chat-delete-open');
                });

                modal.show();

                document.getElementById('confirmDeleteRoomBtn').addEventListener('click', () => {
                    fetch(`/admin/delete_chat_room/${currentRoomId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': CHAT_CSRF_TOKEN
                        }
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (!data.success) {
                                alert('Error: ' + (data.error || 'No se pudo eliminar el chat'));
                                return;
                            }
                            bootstrap.Modal.getInstance(document.getElementById('deleteRoomConfirmModal')).hide();
                            bootstrap.Modal.getInstance(document.getElementById('editRoomModal')).hide();
                            currentRoomId = null;
                            currentRoomData = null;
                            loadChatRooms({ force: true });
                            updateRoomHeader();
                            updateSendState();
                        })
                        .catch(err => {
                            console.error(err);
                            alert('Error al eliminar el chat');
                        });
                });
            });
        }

        const clearRoomBtn = document.getElementById('clearRoomBtn');
        if (clearRoomBtn) {
            clearRoomBtn.addEventListener('click', () => {
                playWarningBeep();
                const existingModal = document.getElementById('clearRoomConfirmModal');
                if (existingModal) existingModal.remove();

                const modalHtml = `
                    <div class="modal fade" id="clearRoomConfirmModal" tabindex="-1">
                        <div class="modal-dialog modal-dialog-centered">
                            <div class="modal-content vio-card chat-delete-modal" style="background: #1f1b2d; color: #fff;">
                                <div class="modal-header violet-modal-header">
                                    <div class="chat-delete-title">
                                        <span class="delete-icon">
                                            <i class="fas fa-triangle-exclamation"></i>
                                        </span>
                                        <h5 class="modal-title">Vaciar chat</h5>
                                    </div>
                                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                                </div>
                                <div class="modal-body">
                                    <p class="mb-2">¿Estás segura de que quieres vaciar este chat?</p>
                                    <p class="text-warning small mb-0">Se eliminarán todos los mensajes, imágenes y archivos. Esta acción no se puede deshacer.</p>
                                </div>
                                <div class="modal-footer">
                                    <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Cancelar</button>
                                    <button type="button" class="btn btn-warning text-dark" id="confirmClearRoomBtn">Sí, vaciar</button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                document.body.insertAdjacentHTML('beforeend', modalHtml);
                const modalElement = document.getElementById('clearRoomConfirmModal');
                const modal = new bootstrap.Modal(modalElement, {
                    backdrop: false,
                    focus: false,
                    keyboard: true
                });

                modalElement.addEventListener('hidden.bs.modal', function () {
                    document.body.classList.remove('chat-delete-open');
                    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
                    this.remove();
                });

                modalElement.addEventListener('shown.bs.modal', function () {
                    document.body.classList.add('chat-delete-open');
                });

                modal.show();

                document.getElementById('confirmClearRoomBtn').addEventListener('click', () => {
                    fetch(`/admin/clear_chat_room/${currentRoomId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': CHAT_CSRF_TOKEN
                        }
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (!data.success) {
                                alert('Error: ' + (data.error || 'No se pudo vaciar el chat'));
                                return;
                            }
                            bootstrap.Modal.getInstance(document.getElementById('clearRoomConfirmModal')).hide();
                            const editModal = bootstrap.Modal.getInstance(document.getElementById('editRoomModal'));
                            if (editModal) editModal.hide();
                            const container = document.querySelector('.chat-messages');
                            if (container) {
                                container.innerHTML = '<div class="chat-placeholder"><p>El chat fue vaciado por una administradora.</p></div>';
                            }
                            if (currentRoomData) {
                                currentRoomData.last_message = null;
                            }
                            updateRoomHeader();
                            updateSendState();
                        })
                        .catch(err => {
                            console.error(err);
                            alert('Error al vaciar el chat');
                        });
                });
            });
        }

        initReportChatMessageModal();

        if (messagesContainer) {
            messagesContainer.addEventListener('click', (e) => {
                const reportBtn = e.target.closest('.chat-msg-report-btn');
                if (reportBtn) {
                    e.preventDefault();
                    const messageId = reportBtn.getAttribute('data-message-id');
                    if (!messageId) return;
                    openChatReportModal(messageId);
                    return;
                }

                const btn = e.target.closest('.chat-msg-delete-btn');
                if (!btn) return;
                e.preventDefault();
                const messageId = btn.getAttribute('data-message-id');
                if (!messageId) {
                    const pendingKey = btn.getAttribute('data-pending-key');
                    if (!pendingKey) return;
                    const pendingRow = btn.closest(`.chat-message-row.pending[data-pending-key="${pendingKey}"]`);
                    if (!pendingRow) return;
                    const previewUrl = pendingRow.getAttribute('data-preview-url');
                    if (previewUrl && previewUrl.startsWith('blob:')) {
                        try { URL.revokeObjectURL(previewUrl); } catch (err) {}
                    }
                    pendingRow.remove();
                    const messagesLeft = messagesContainer.querySelector('.chat-message-row');
                    if (!messagesLeft) {
                        messagesContainer.innerHTML = '<div class="chat-placeholder"><p>Esta sala no tiene mensajes aún. ¡Sé la primera en escribir!</p></div>';
                    }
                    return;
                }

                fetch(`/api/chat/message/${messageId}/delete`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': CHAT_CSRF_TOKEN
                    }
                })
                    .then(response => response.json())
                    .then(data => {
                        if (!data.success) {
                            alert('Error: ' + (data.error || 'No se pudo eliminar el mensaje'));
                            return;
                        }
                        applyMessageDeleted(messageId, data.deleted_reason || 'deleted');
                    })
                    .catch(err => {
                        console.error(err);
                        alert('Error al eliminar el mensaje');
                    });
            });
        }
    }

    function updateSendState() {
        const sendBtn = document.querySelector('.chat-send-btn');
        const input = document.querySelector('.chat-input');
        const inputArea = document.querySelector('.chat-input-area');
        const attachBtn = document.getElementById('chatAttachBtn');
        if (!sendBtn) return;
        const hasText = input && input.value.trim().length > 0;
        const hasAttachment = !!pendingAttachmentFile;
        const canPost = !!currentRoomData && (currentRoomData.can_post !== false);
        const canSend = !!currentRoomId && canPost && (hasText || hasAttachment);
        sendBtn.disabled = !canSend;
        if (attachBtn) {
            attachBtn.disabled = !currentRoomId || !canPost;
        }
        if (input) {
            const shouldDisableInput = !currentRoomId || !canPost;
            input.disabled = shouldDisableInput;
            if (!currentRoomId) {
                input.placeholder = 'Selecciona una sala para escribir...';
            } else if (!canPost) {
                input.placeholder = 'Solo admins y la creadora pueden enviar mensajes en esta sala';
            } else {
                input.placeholder = 'Escribe un mensaje...';
            }
            if (inputArea) {
                if (isMobileChatView()) {
                    inputArea.classList.toggle('d-none', !currentRoomId);
                } else {
                    inputArea.classList.remove('d-none');
                }
            }
        }
        if (!currentRoomId && pendingAttachmentFile) {
            clearAttachment();
        }
    }

    function subscribeToSocketRoom(roomId) {
        const rid = Number(roomId);
        if (!socket || !Number.isFinite(rid) || rid <= 0) return;
        if (joinedSocketRooms.has(rid)) return;
        socket.emit('join_room', { room_id: rid, silent: true });
        joinedSocketRooms.add(rid);
    }

    function unsubscribeFromSocketRoom(roomId) {
        const rid = Number(roomId);
        if (!socket || !Number.isFinite(rid) || rid <= 0) return;
        if (!joinedSocketRooms.has(rid)) return;
        socket.emit('leave_room', { room_id: rid });
        joinedSocketRooms.delete(rid);
    }

    function syncSocketRoomSubscriptions(rooms) {
        const desired = new Set(
            (rooms || [])
                .map(room => Number(room && room.id))
                .filter(id => Number.isFinite(id) && id > 0)
        );

        Array.from(joinedSocketRooms).forEach((rid) => {
            if (!desired.has(rid)) {
                unsubscribeFromSocketRoom(rid);
            }
        });

        desired.forEach((rid) => subscribeToSocketRoom(rid));
    }

    function getRoomLastTimestamp(room) {
        if (!room || !room.last_message || !room.last_message.created_at) return 0;
        const dt = new Date(room.last_message.created_at);
        const ts = dt.getTime();
        return Number.isFinite(ts) ? ts : 0;
    }

    function sortRoomsByRecent(rooms) {
        return (rooms || []).slice().sort((a, b) => {
            const diff = getRoomLastTimestamp(b) - getRoomLastTimestamp(a);
            if (diff !== 0) return diff;
            const bid = Number(b && b.id) || 0;
            const aid = Number(a && a.id) || 0;
            return bid - aid;
        });
    }

    function readCachedChatRooms() {
        try {
            const raw = sessionStorage.getItem(CHAT_ROOMS_CACHE_KEY);
            if (!raw) return null;
            const payload = JSON.parse(raw);
            const rooms = Array.isArray(payload && payload.rooms) ? payload.rooms : null;
            const ts = Number(payload && payload.ts);
            if (!rooms || !Number.isFinite(ts)) return null;
            if ((Date.now() - ts) > CHAT_ROOMS_CACHE_TTL_MS) return null;
            return rooms;
        } catch (e) {
            return null;
        }
    }

    function writeCachedChatRooms(rooms) {
        try {
            sessionStorage.setItem(CHAT_ROOMS_CACHE_KEY, JSON.stringify({
                ts: Date.now(),
                rooms: rooms || []
            }));
        } catch (e) {}
    }

    function applyChatRoomsPayload(rooms) {
        if (rooms && rooms.length > 0) {
            const sorted = sortRoomsByRecent(rooms);
            syncSocketRoomSubscriptions(sorted);
            displayChatRooms(sorted);
            if (autoOpenRoomId && roomIndex && roomIndex[autoOpenRoomId]) {
                const rid = autoOpenRoomId;
                autoOpenRoomId = null;
                selectRoom(rid);
            } else if (!isMobileChatView() && (currentRoomId == null || !roomIndex[currentRoomId])) {
                const firstRoom = sorted[0];
                if (firstRoom && firstRoom.id != null) {
                    selectRoom(Number(firstRoom.id));
                }
            }
        } else {
            showEmptyState();
        }
    }

    function loadChatRooms(options = {}) {
        const force = !!(options && options.force);
        const now = Date.now();
        if (chatRoomsLoadPromise) {
            return chatRoomsLoadPromise;
        }
        if (!force) {
            const cachedRooms = readCachedChatRooms();
            if (cachedRooms && cachedRooms.length) {
                applyChatRoomsPayload(cachedRooms);
                lastChatRoomsLoadedAt = now;
                return Promise.resolve(cachedRooms);
            }
        }
        if (!force && lastChatRoomsLoadedAt && (now - lastChatRoomsLoadedAt) < CHAT_ROOMS_REFRESH_DEBOUNCE_MS && Object.keys(roomIndex || {}).length) {
            displayChatRooms(Object.values(roomIndex || {}));
            return Promise.resolve(Object.values(roomIndex || {}));
        }

        chatRoomsLoadPromise = fetch('/api/chat/rooms')
            .then(response => response.json())
            .then(data => {
                applyChatRoomsPayload(data.rooms || []);
                writeCachedChatRooms(data.rooms || []);
                lastChatRoomsLoadedAt = Date.now();
                return data.rooms || [];
            })
            .catch(error => {
                console.error('Error loading chat rooms:', error);
                showEmptyState();
                return [];
            })
            .finally(() => {
                chatRoomsLoadPromise = null;
            });
        return chatRoomsLoadPromise;
    }

    function displayChatRooms(rooms) {
        const container = document.getElementById('chatRoomsPane');
        if (!container) return;

        const sortedRooms = sortRoomsByRecent(rooms);
        writeCachedChatRooms(sortedRooms);
        roomIndex = {};
        let html = '<div class="chat-rooms-list">';

        sortedRooms.forEach(room => {
            roomIndex[room.id] = room;
            const lastMessage = room.last_message;
            const timeAgo = lastMessage ? formatTimeAgo(new Date(lastMessage.created_at)) : '';
            const roomAvatar = room.image_url || '/static/images/favicon.png';
            const lastMessageText = lastMessage ? formatLastMessage(lastMessage) : 'Sin mensajes';
            const isActive = currentRoomId != null && Number(currentRoomId) === Number(room.id);

            html += `
                <div class="chat-room-item ${room.unread_count > 0 ? 'has-unread' : ''} ${isActive ? 'active' : ''}" data-room-id="${room.id}" onclick="selectRoom(${room.id}, event)">
                    <div class="room-avatar">
                        <img src="${roomAvatar}" alt="avatar">
                    </div>
                    <div class="room-info">
                        <div class="room-name">${escapeHtml(room.name)}</div>
                        <div class="room-last-message">
                            ${lastMessage ? `${escapeHtml(lastMessage.username)}${renderModerationBadge(lastMessage.moderation_level)}${renderStaffBadge(lastMessage.staff_badge, lastMessage.is_super_admin)}: ${lastMessageText}` : 'Sin mensajes'}
                        </div>
                    </div>
                    <div class="room-meta">
                        <div class="room-time">${timeAgo}</div>
                        ${room.unread_count > 0 ? `<div class="unread-badge">${room.unread_count}</div>` : ''}
                    </div>
                </div>
            `;
        });

        html += '</div>';

        container.innerHTML = html;
        const searchInput = document.getElementById('chatSearchInput');
        if (searchInput && searchInput.value) {
            filterChatRooms(searchInput.value);
        }
    }

    // --- Read/unread helpers ---
    let markReadTimer = null;
    let markReadInFlight = false;
    let lastMarkReadAtMs = 0;

    function markRoomRead(roomId, force = false) {
        const rid = Number(roomId);
        if (!Number.isFinite(rid) || rid <= 0) return Promise.resolve(false);

        // Only mark the room as read if it's the active room, unless forced (e.g. leaving the room).
        if (!force) {
            if (currentRoomId == null || Number(currentRoomId) !== rid) return Promise.resolve(false);
        }

        const now = Date.now();
        if (!force) {
            if (markReadInFlight) return Promise.resolve(false);
            if (now - lastMarkReadAtMs < 800) return Promise.resolve(false);
        }

        markReadInFlight = true;
        return fetch(`/api/chat/room/${rid}/read`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CHAT_CSRF_TOKEN
            },
            body: '{}'
        })
            .then(r => r.json())
            .then(() => {
                lastMarkReadAtMs = Date.now();
                try {
                    if (roomIndex && roomIndex[rid]) roomIndex[rid].unread_count = 0;
                } catch (e) {}
                try {
                    displayChatRooms(Object.values(roomIndex || {}));
                } catch (e) {}
                return true;
            })
            .catch(() => false)
            .finally(() => {
                markReadInFlight = false;
            });
    }

    function scheduleMarkRoomRead(roomId) {
        const rid = Number(roomId);
        if (!Number.isFinite(rid) || rid <= 0) return;
        if (markReadTimer) {
            clearTimeout(markReadTimer);
            markReadTimer = null;
        }
        markReadTimer = setTimeout(() => {
            markReadTimer = null;
            markRoomRead(rid);
        }, 250);
    }

    function updateAttachmentUI() {
        const chip = document.getElementById('chatAttachmentChip');
        const nameEl = document.getElementById('chatAttachmentName');
        const attachBtn = document.getElementById('chatAttachBtn');
        if (!chip || !nameEl || !attachBtn) return;

        if (pendingAttachmentFile) {
            nameEl.textContent = pendingAttachmentFile.name;
            chip.classList.remove('d-none');
            attachBtn.classList.add('has-file');
        } else {
            chip.classList.add('d-none');
            nameEl.textContent = 'Archivo adjunto';
            attachBtn.classList.remove('has-file');
        }
    }

    function clearAttachment() {
        pendingAttachmentFile = null;
        const attachInput = document.getElementById('chatAttachmentInput');
        if (attachInput) attachInput.value = '';
        updateAttachmentUI();
        updateSendState();
    }

    function setupAttachmentPicker() {
        const attachBtn = document.getElementById('chatAttachBtn');
        const attachInput = document.getElementById('chatAttachmentInput');
        const removeBtn = document.getElementById('chatAttachmentRemove');
        if (!attachBtn || !attachInput) return;

        attachBtn.addEventListener('click', () => {
            if (attachBtn.disabled) return;
            attachInput.click();
        });

        if (removeBtn) {
            removeBtn.addEventListener('click', clearAttachment);
        }

        attachInput.addEventListener('change', () => {
            const file = attachInput.files && attachInput.files[0];
            if (!file) return;
            const allowed = ['image/jpeg', 'image/png', 'application/pdf'];
            if (!allowed.includes(file.type)) {
                alert('Solo puedes adjuntar imágenes JPG/PNG o archivos PDF.');
                attachInput.value = '';
                pendingAttachmentFile = null;
                updateAttachmentUI();
                return;
            }
            pendingAttachmentFile = file;
            updateAttachmentUI();
            updateSendState();
        });
    }

    function filterChatRooms(query) {
        const q = (query || '').trim().toLowerCase();
        const items = document.querySelectorAll('.chat-room-item');
        items.forEach(item => {
            const name = item.querySelector('.room-name')?.textContent.toLowerCase() || '';
            if (!q || name.includes(q)) {
                item.classList.remove('d-none');
            } else {
                item.classList.add('d-none');
            }
        });
    }

    function showEmptyState() {
        const container = document.getElementById('chatRoomsPane');
        if (!container) return;
        roomIndex = {};

        container.innerHTML = `
            <div class="chat-placeholder">
                <i class="fas fa-comments"></i>
                <p>No tienes salas de chat aún.</p>
                <p>¡Crea una sala para empezar a conversar!</p>
            </div>
        `;
        syncSocketRoomSubscriptions([]);
    }

    function selectRoom(roomId, evt) {
        currentRoomId = roomId;
        window.__CHAT_CURRENT_ROOM_ID = roomId;
        currentRoomData = roomIndex[roomId] || null;
        if (currentRoomData && typeof currentRoomData.can_post === 'undefined') {
            const open = currentRoomData.messages_open !== false;
            const isOwner = currentRoomData.created_by && currentRoomData.created_by === currentUserId;
            currentRoomData.can_post = open || currentIsAdmin || isOwner;
        }

        // Update UI
        document.querySelectorAll('.chat-room-item').forEach(item => item.classList.remove('active'));
        const clicked = (evt && evt.currentTarget) ? evt.currentTarget : document.querySelector(`.chat-room-item[data-room-id="${roomId}"]`);
        if (clicked) {
            clicked.classList.add('active');
            clicked.classList.remove('has-unread');
            const badge = clicked.querySelector('.unread-badge');
            if (badge) badge.remove();
        }
        try {
            if (roomIndex && roomIndex[roomId]) roomIndex[roomId].unread_count = 0;
        } catch (e) {}

        updateRoomHeader();

        // Load messages for this room
        loadRoomMessages(roomId);

        // Ensure realtime subscription for this room.
        subscribeToSocketRoom(roomId);

        // While viewing the room, we should treat messages as "seen".
        scheduleMarkRoomRead(roomId);

        // Clear input and update state when switching room
        const input = document.querySelector('.chat-input');
        if (input) {
            input.value = '';
        }
        updateSendState();
        if (input && !input.disabled && !isMobileChatView()) {
            try {
                input.focus({ preventScroll: true });
            } catch (error) {
                input.focus();
            }
        }
    }

    function updateRoomHeader() {
        const header = document.getElementById('chatRoomHeader');
        const avatar = document.getElementById('chatRoomAvatar');
        const nameEl = document.getElementById('chatRoomName');
        const descEl = document.getElementById('chatRoomDesc');
        const editBtn = document.getElementById('editChatRoomBtn');
        const searchWrap = document.getElementById('chatSearchWrap');
        const searchRow = document.getElementById('chatSearchRow');
        const chatContainer = document.querySelector('.chat-container');
        if (!header || !avatar || !nameEl || !descEl || !editBtn) return;

        if (!currentRoomData) {
            header.classList.add('d-none');
            if (isMobileChatView()) {
                if (searchWrap) searchWrap.classList.remove('d-none');
                if (searchRow) searchRow.classList.remove('d-none');
            } else {
                if (searchWrap) searchWrap.classList.remove('d-none');
                if (searchRow) searchRow.classList.remove('d-none');
            }
            if (chatContainer) chatContainer.classList.remove('room-open');
            return;
        }

        header.classList.remove('d-none');
        if (isMobileChatView()) {
            if (searchWrap) searchWrap.classList.add('d-none');
            if (searchRow) searchRow.classList.add('d-none');
        } else {
            if (searchWrap) searchWrap.classList.remove('d-none');
            if (searchRow) searchRow.classList.remove('d-none');
        }
        if (chatContainer) chatContainer.classList.add('room-open');
        avatar.src = currentRoomData.image_url || '/static/images/favicon.png';
        nameEl.textContent = currentRoomData.name || 'Chat';
        descEl.textContent = currentRoomData.description || 'Sin descripción';

        const canEdit = currentCanManageRooms || (currentRoomData.created_by && currentRoomData.created_by === currentUserId);
        editBtn.classList.toggle('d-none', !canEdit);

        if (currentRoomData.messages_open === false) {
            descEl.textContent = `${currentRoomData.description || 'Sin descripción'} · Solo admins y la creadora pueden enviar mensajes`;
        }
    }

    function loadRoomMessages(roomId) {
        fetch(`/api/chat/room/${roomId}/messages`)
            .then(response => response.json())
            .then(data => {
                displayMessages(data.messages || []);
            })
            .catch(error => {
                console.error('Error loading messages:', error);
            });
    }

    function renderMessageRow(message, opts = {}) {
        const isPending = !!opts.isPending;
        const isOwn = message.username === currentUser;
        const timeStr = opts.timeStr || (isPending ? formatTime(new Date()) : formatTime(new Date(message.created_at)));
        const bodyHtml = renderMessageBody(message);
        const effectiveKey = encodePendingKey((opts.pendingKey || buildPendingKey(message.content, message.attachment_name)));
        let leftActions = '';
        let rightActions = '';

        if (isPending && isOwn) {
            leftActions = renderPendingActionStack(effectiveKey);
        } else {
            const actionPlacement = getMessageActionPlacement(message);
            const actionsHtml = renderMessageActions(message);
            if (actionPlacement === 'left') {
                leftActions = actionsHtml;
            } else if (actionPlacement === 'right') {
                rightActions = actionsHtml;
            }
        }

        const rowAttrs = [];
        rowAttrs.push(`data-message-id="${message.id || ''}"`);
        if (message && message.deleted_reason) {
            rowAttrs.push(`data-deleted-reason="${escapeHtml(message.deleted_reason)}"`);
        }
        if (isPending) {
            rowAttrs.push(`data-pending-key="${effectiveKey}"`);
            if (message && typeof message.attachment_url === 'string' && message.attachment_url.startsWith('blob:')) {
                rowAttrs.push(`data-preview-url="${message.attachment_url}"`);
            }
        }

        const avatar = message.user_avatar || '/static/images/default_avatar.jpg';
        const metaHtml = message.is_deleted ? '' : `
            <div class="chat-message-meta ${isOwn ? 'own' : ''}">
                <div class="chat-username">${escapeHtml(message.username)}${renderModerationBadge(message.moderation_level)}${renderStaffBadge(message.staff_badge, message.is_super_admin)}</div>
            </div>
        `;

        return `
            <div class="chat-message-row ${isOwn ? 'own' : ''} ${isPending ? 'pending' : ''}" ${rowAttrs.join(' ')}>
                ${leftActions}
                ${!isOwn ? `<img class="chat-side-avatar" src="${avatar}" alt="avatar">` : ''}
                <div class="chat-message-stack ${isOwn ? 'own' : ''}">
                    ${metaHtml}
                    <div class="chat-message ${isOwn ? 'own' : ''} ${message.is_deleted ? 'deleted' : ''}">
                        ${bodyHtml}
                    </div>
                    <div class="chat-time">${timeStr}</div>
                </div>
                ${isOwn ? `<img class="chat-side-avatar chat-side-avatar--own" src="${avatar}" alt="avatar">` : ''}
                ${rightActions}
            </div>
        `;
    }

    function displayMessages(messages) {
        const container = document.querySelector('.chat-messages');
        if (!container) return;

        if (messages.length === 0) {
            container.innerHTML = '<div class="chat-placeholder"><p>Esta sala no tiene mensajes aún. ¡Sé la primera en escribir!</p></div>';
            return;
        }

        let html = '';
        messages.forEach(message => {
            html += renderMessageRow(message);
        });

        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
        refreshDeleteButtons();
    }

	    function appendMessage(message, isPending = false, pendingKey = '') {
	        const container = document.querySelector('.chat-messages');
	        if (!container) return;
	        const messageHtml = renderMessageRow(message, { isPending, pendingKey });
	        container.insertAdjacentHTML('beforeend', messageHtml);
	        container.scrollTop = container.scrollHeight;
	        const lastRow = container.querySelector('.chat-message-row:last-child');
	        if (lastRow) {
	            lastRow.classList.add('chat-msg-enter');
	            lastRow.addEventListener('animationend', () => {
	                try { lastRow.classList.remove('chat-msg-enter'); } catch (e) {}
	            }, { once: true });
	        }
	        refreshDeleteButtons();
	    }

	    function sendMessage() {
	        if (typeof isUserVerified === "function" && !isUserVerified()) {
	            if (typeof showVerifyGate === "function") {
	                showVerifyGate();
            }
            return;
        }
        if (!currentRoomId) {
            alert('Selecciona primero una sala');
            return;
        }

        const input = document.querySelector('.chat-input');
        if (!input) return;

        const content = input.value.trim();
        const hasAttachment = !!pendingAttachmentFile;
        if (!content && !hasAttachment) return;

	        const attachmentToSend = pendingAttachmentFile;
	        const pendingKey = buildPendingKey(content, attachmentToSend ? attachmentToSend.name : '');
	        let pendingPreviewUrl = null;

	        // Optimistic update
	        const tempMessage = {
	            username: currentUser,
	            content: content,
	            user_avatar: currentUserAvatar,
	            created_at: new Date().toISOString()
	        };
	        if (attachmentToSend) {
	            tempMessage.attachment_name = attachmentToSend.name;
	            tempMessage.attachment_mime = attachmentToSend.type;
	            tempMessage.message_type = attachmentToSend.type && attachmentToSend.type.startsWith('image/') ? 'image' : 'file';
	            pendingPreviewUrl = URL.createObjectURL(attachmentToSend);
	            tempMessage.attachment_url = pendingPreviewUrl;
	        }
        appendMessage(tempMessage, true, pendingKey);
        updateRoomInList(currentRoomId, {
            ...tempMessage,
            room_id: currentRoomId,
            user_id: currentUserId,
            created_at: new Date().toISOString(),
            is_deleted: false
        });
        input.value = '';
        pendingAttachmentFile = null;
        updateAttachmentUI();
        updateSendState();

        // Send via API
        let fetchOptions = {
            method: 'POST',
            headers: {
                'X-CSRFToken': CHAT_CSRF_TOKEN
            }
        };
        if (attachmentToSend) {
            const formData = new FormData();
            formData.append('content', content);
            formData.append('attachment', attachmentToSend);
            fetchOptions.body = formData;
        } else {
            fetchOptions.headers['Content-Type'] = 'application/json';
            fetchOptions.body = JSON.stringify({ content: content });
        }

		        fetch(`/api/chat/room/${currentRoomId}/send`, fetchOptions)
		            .then(response => response.json())
		            .then(data => {
		                if (data.success) {
			                    const serverMessage = data.message || null;
			                    if (serverMessage) {
			                        // If user navigated to another room while sending, don't append here.
			                        if (serverMessage.room_id != null && serverMessage.room_id != currentRoomId) {
			                            updateRoomInList(serverMessage.room_id || currentRoomId, serverMessage);
			                            return;
			                        }
			                        const upgraded = upgradePendingMessage(pendingKey, serverMessage);
			                        if (!upgraded) {
			                            const pendingMsg = document.querySelector(`.chat-message-row.pending[data-pending-key="${encodePendingKey(pendingKey)}"]`);
			                            if (pendingMsg) pendingMsg.remove();
			                            if (pendingPreviewUrl && typeof pendingPreviewUrl === 'string' && pendingPreviewUrl.startsWith('blob:') && serverMessage.attachment_url) {
			                                try { URL.revokeObjectURL(pendingPreviewUrl); } catch (e) {}
			                            }
			                        }
			                        const existing = (serverMessage.id != null) ? document.querySelector(`.chat-message-row[data-message-id="${serverMessage.id}"]`) : null;
			                        if (!upgraded && !existing) appendMessage(serverMessage);
			                        updateRoomInList(serverMessage.room_id || currentRoomId, serverMessage);
			                    }
			                } else {
		                    alert('Error: ' + (data.error || 'No se pudo enviar el mensaje'));
		                    const pendingMsg = document.querySelector(`.chat-message-row.pending[data-pending-key="${encodePendingKey(pendingKey)}"]`);
	                    if (pendingMsg) pendingMsg.remove();
	                    if (pendingPreviewUrl && typeof pendingPreviewUrl === 'string' && pendingPreviewUrl.startsWith('blob:')) {
	                        try { URL.revokeObjectURL(pendingPreviewUrl); } catch (e) {}
	                    }
	                }
	            })
	            .catch(error => {
	                console.error('Error sending message:', error);
	                alert('Error al enviar mensaje');
	                const pendingMsg = document.querySelector(`.chat-message-row.pending[data-pending-key="${encodePendingKey(pendingKey)}"]`);
	                if (pendingMsg) pendingMsg.remove();
	                if (pendingPreviewUrl && typeof pendingPreviewUrl === 'string' && pendingPreviewUrl.startsWith('blob:')) {
	                    try { URL.revokeObjectURL(pendingPreviewUrl); } catch (e) {}
	                }
	            });
	    }

    function showCreateRoomModal() {
        if (typeof isUserVerified === "function" && !isUserVerified()) {
            if (typeof showVerifyGate === "function") {
                showVerifyGate();
            }
            return;
        }
        // Remove any existing modal first
        const existingModal = document.getElementById('createRoomModal');
        if (existingModal) {
            existingModal.remove();
        }

        const modalHtml = `
            <div class="modal fade" id="createRoomModal" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content vio-glass-modal">
                        <div class="modal-header violet-modal-header">
                            <h5 class="modal-title">
                                <span class="create-room-title-icon"><i class="fas fa-comments me-2"></i></span>Crear nueva sala
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Cerrar"></button>
                        </div>
                        <div class="modal-body violet-modal-body">
                            <form id="createRoomForm">
                                <div class="mb-2">
                                    <label for="roomName" class="form-label">Nombre de la sala</label>
                                    <input type="text" class="form-control vio-input" id="roomName" required placeholder="Ej. Alerta Vecinal Centro">
                                </div>
                                <p class="create-room-helper mt-2 mb-0">
                                    Escribe un nombre claro para que las demás usuarias identifiquen fácilmente el propósito de este chat.
                                </p>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-vio-cancel" data-bs-dismiss="modal">Cancelar</button>
                            <button type="button" class="btn btn-vio-primary" id="createRoomSubmitBtn">
                                <i class="fas fa-plus me-2"></i>Crear sala
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const modalElement = document.getElementById('createRoomModal');
        const modal = new bootstrap.Modal(modalElement);

        // Add event listener for the create button inside the modal
        document.getElementById('createRoomSubmitBtn').addEventListener('click', createRoom);

        // Clean up modal after hiding
        modalElement.addEventListener('hidden.bs.modal', function () {
            this.remove();
        });

        modal.show();
    }

    function createRoom() {
        if (typeof isUserVerified === "function" && !isUserVerified()) {
            if (typeof showVerifyGate === "function") {
                showVerifyGate();
            }
            return;
        }
        const submitBtn = document.getElementById('createRoomSubmitBtn');
        const roomName = document.getElementById('roomName').value.trim();

        if (!roomName) {
            alert('El nombre de la sala es requerido');
            return;
        }

        const requestHeaders = typeof buildHeaders === 'function'
            ? buildHeaders('application/json')
            : {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': CHAT_CSRF_TOKEN
            };

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creando...';
        }

        fetch('/api/chat/create-room', {
            method: 'POST',
            credentials: 'same-origin',
            headers: requestHeaders,
            body: JSON.stringify({
                name: roomName,
                is_private: false
            })
        })
            .then(async response => {
                if (typeof handleAuthRedirect === 'function' && handleAuthRedirect(response)) {
                    throw new Error('Tu sesión expiró. Inicia sesión de nuevo.');
                }

                const contentType = response.headers.get('content-type') || '';
                if (!contentType.includes('application/json')) {
                    const raw = await response.text();
                    if (response.status === 400 && /csrf/i.test(raw)) {
                        throw new Error('La sesión cambió o expiró. Recarga la página e inténtalo de nuevo.');
                    }
                    throw new Error('No pudimos crear la sala. Recarga la página e inténtalo de nuevo.');
                }

                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo crear la sala.');
                }
                return data;
            })
            .then(data => {
                bootstrap.Modal.getInstance(document.getElementById('createRoomModal')).hide();
                if (data.pending) {
                    if (typeof showAlert === 'function') {
                        showAlert(data.message || 'Una administradora debe aprobar la sala.', 'info');
                    } else {
                        alert(data.message || 'Una administradora debe aprobar la sala.');
                    }
                }
                loadChatRooms({ force: true });
                const input = document.querySelector('.chat-input');
                if (input) input.value = '';
                updateSendState();
            })
            .catch(error => {
                console.error('Error creating room:', error);
                if (typeof showAlert === 'function') {
                    showAlert(error.message || 'Error al crear sala', 'warning');
                } else {
                    alert(error.message || 'Error al crear sala');
                }
            })
            .finally(() => {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="fas fa-plus"></i> Crear sala';
                }
            });
    }

    function updateRoomInList(roomId, messageData) {
        // Mantener el índice en memoria actualizado y ordenar por actividad reciente.
        try {
            const rid = Number(roomId);
            if (!Number.isFinite(rid)) return;
            const normalizedMessage = {
                ...(messageData || {}),
                room_id: rid,
                created_at: (messageData && messageData.created_at) ? messageData.created_at : new Date().toISOString()
            };
            if (roomIndex && roomIndex[rid]) {
                roomIndex[rid].last_message = normalizedMessage;
                const isCurrentRoom = currentRoomId != null && Number(currentRoomId) === rid;
                const isOwnMessage = !!normalizedMessage && (
                    (normalizedMessage.user_id != null && Number(normalizedMessage.user_id) === Number(currentUserId)) ||
                    (normalizedMessage.username && normalizedMessage.username === currentUser)
                );
                if (isCurrentRoom) {
                    roomIndex[rid].unread_count = 0;
                } else if (!isOwnMessage) {
                    roomIndex[rid].unread_count = (Number(roomIndex[rid].unread_count) || 0) + 1;
                }
            } else {
                // Si la sala no está en memoria (nueva/aprobada), refrescamos catálogo.
                loadChatRooms({ force: true });
                return;
            }
            if (currentRoomId != null && Number(currentRoomId) === rid && currentRoomData) {
                currentRoomData.last_message = normalizedMessage;
            }
        } catch (e) {}

        displayChatRooms(Object.values(roomIndex || {}));
    }

    function showSystemMessage(message) {
        const container = document.querySelector('.chat-messages');
        if (!container) return;

        const messageHtml = `
            <div class="chat-message system">
                <div class="chat-text" style="text-align: center; font-style: italic; color: rgba(255,255,255,0.6);">
                    ${escapeHtml(message)}
                </div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', messageHtml);
        container.scrollTop = container.scrollHeight;
    }

    // Utility functions
    function buildPendingKey(content, attachmentName) {
        return `${content || ''}|${attachmentName || ''}`;
    }

	    function encodePendingKey(key) {
	        try {
	            return encodeURIComponent(key || '');
	        } catch (e) {
	            return '';
	        }
	    }

    function renderPendingActionStack(encodedPendingKey) {
        if (!encodedPendingKey) return '';
        return `
            <div class="chat-message-actions chat-message-actions--left">
                <button class="chat-msg-action-btn chat-msg-delete-btn chat-msg-delete-btn--left" data-pending-key="${encodedPendingKey}" title="Eliminar mensaje">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
    }

    function upgradePendingMessage(pendingKey, serverMessage) {
        if (!serverMessage || !serverMessage.id) return false;
        const container = document.querySelector('.chat-messages');
        if (!container) return false;

        const effectiveKey = encodePendingKey(pendingKey || buildPendingKey(serverMessage.content, serverMessage.attachment_name));
        const row = container.querySelector(`.chat-message-row.pending[data-pending-key="${effectiveKey}"]`);
        if (!row) return false;

        row.classList.remove('pending');
        row.removeAttribute('data-pending-key');
        row.setAttribute('data-message-id', String(serverMessage.id));
        if (serverMessage.deleted_reason) {
            row.setAttribute('data-deleted-reason', serverMessage.deleted_reason);
        } else {
            row.removeAttribute('data-deleted-reason');
        }

        const timeEl = row.querySelector('.chat-time');
        if (timeEl && serverMessage.created_at) {
            timeEl.textContent = formatTime(new Date(serverMessage.created_at));
        }

        const previewUrl = row.getAttribute('data-preview-url');
        if (previewUrl && typeof previewUrl === 'string' && previewUrl.startsWith('blob:') && serverMessage.attachment_url) {
            const img = row.querySelector('.chat-attachment--image img');
            if (img) img.src = serverMessage.attachment_url;
            const link = row.querySelector('.chat-attachment--file a');
            if (link) link.href = serverMessage.attachment_url;
            try { URL.revokeObjectURL(previewUrl); } catch (e) {}
            row.removeAttribute('data-preview-url');
        }

        row.querySelectorAll('.chat-message-actions').forEach(stack => stack.remove());
        const placement = getMessageActionPlacement(serverMessage);
        const actionsHtml = renderMessageActions(serverMessage);
        if (placement === 'left' && actionsHtml) {
            row.insertAdjacentHTML('afterbegin', actionsHtml);
        }
        if (placement === 'right' && actionsHtml) {
            row.insertAdjacentHTML('beforeend', actionsHtml);
        }

        refreshDeleteButtons();
        return true;
    }

    function renderAttachment(message) {
        if (!message || !message.attachment_url) return '';
        const name = escapeHtml(message.attachment_name || 'Archivo adjunto');
        const mime = (message.attachment_mime || '').toLowerCase();
        const isImage = message.message_type === 'image' || mime.startsWith('image/');
        if (isImage) {
            return `
                <div class="chat-attachment chat-attachment--image">
                    <img src="${message.attachment_url}" alt="${name}">
                </div>
            `;
        }
        return `
            <div class="chat-attachment chat-attachment--file">
                <a href="${message.attachment_url}" target="_blank" rel="noopener noreferrer">
                    <i class="fas fa-file"></i>
                    <span>${name}</span>
                </a>
            </div>
        `;
    }

    function getDeletedMessageText(messageOrReason) {
        const reason = typeof messageOrReason === 'string'
            ? messageOrReason
            : ((messageOrReason && messageOrReason.deleted_reason) || 'deleted');
        return reason === 'reported' ? 'Este mensaje ha sido reportado' : 'Este mensaje ha sido eliminado';
    }

    function getDeletedLastMessageText(messageOrReason) {
        const reason = typeof messageOrReason === 'string'
            ? messageOrReason
            : ((messageOrReason && messageOrReason.deleted_reason) || 'deleted');
        return reason === 'reported' ? 'Mensaje reportado' : 'Mensaje eliminado';
    }

    function renderMessageBody(message) {
        if (message && message.is_deleted) {
            return `<div class="chat-text chat-text--deleted">${getDeletedMessageText(message)}</div>`;
        }
        const text = (message.content || '').trim();
        const textHtml = text ? `<div class="chat-text">${escapeHtml(text)}</div>` : '';
        const attachmentHtml = renderAttachment(message);
        if (!textHtml && !attachmentHtml) {
            return `<div class="chat-text">${escapeHtml(message.content || '')}</div>`;
        }
        return `${textHtml}${attachmentHtml}`;
    }

    function formatLastMessage(message) {
        if (!message) return 'Sin mensajes';
        if (message.is_deleted) {
            return getDeletedLastMessageText(message);
        }
        const hasAttachment = !!message.attachment_name;
        if (hasAttachment) {
            const label = message.message_type === 'image' ? 'Imagen' : 'Archivo';
            const name = escapeHtml(message.attachment_name);
            const content = (message.content || '').trim();
            if (content) {
                return `${escapeHtml(content)} · ${label}: ${name}`;
            }
            return `${label}: ${name}`;
        }
        return escapeHtml(message.content || 'Sin mensajes');
    }

    function getDeletePlacement(message) {
        if (!message || !message.id || message.is_deleted) return null;
        const isSender = Number(message.user_id) === Number(currentUserId);
        const isAdmin = currentIsAdmin;
        const isOwner = currentRoomData && Number(currentRoomData.created_by) === Number(currentUserId);
        if (message.is_super_admin && !isAdmin) {
            return null;
        }
        const createdAt = new Date(message.created_at);
        const within10Min = !Number.isNaN(createdAt.getTime()) && (Date.now() - createdAt.getTime() <= 10 * 60 * 1000);

        if (isSender && within10Min) {
            return 'left';
        }
        if ((isAdmin || isOwner) && !isSender) {
            return 'right';
        }
        return null;
    }

    function getReportPlacement(message) {
        if (!message || !message.id || message.is_deleted) return null;
        const isSender = Number(message.user_id) === Number(currentUserId);
        if (isSender) return null;
        return getDeletePlacement(message) || 'right';
    }

    function getMessageActionPlacement(message) {
        return getDeletePlacement(message) || getReportPlacement(message);
    }

    function renderDeleteButton(message, side) {
        if (!message || !message.id) return '';
        const canShow = getDeletePlacement(message) === side;
        if (!canShow) return '';
        let expireAttr = '';
        if (side === 'left' && Number(message.user_id) === Number(currentUserId)) {
            const createdAt = new Date(message.created_at);
            if (!Number.isNaN(createdAt.getTime())) {
                const expireAt = createdAt.getTime() + (10 * 60 * 1000);
                expireAttr = ` data-expire-at="${expireAt}"`;
            }
        }
        return `
            <button class="chat-msg-action-btn chat-msg-delete-btn chat-msg-delete-btn--${side}" data-message-id="${message.id}"${expireAttr} title="Eliminar mensaje">
                <i class="fas fa-trash"></i>
            </button>
        `;
    }

    function renderReportButton(message, side) {
        if (!message || !message.id) return '';
        const canShow = getReportPlacement(message) === side;
        if (!canShow) return '';
        return `
            <button class="chat-msg-action-btn chat-msg-report-btn chat-msg-report-btn--${side}" data-message-id="${message.id}" title="Reportar mensaje">
                <i class="fas fa-flag"></i>
            </button>
        `;
    }

    function renderMessageActions(message) {
        const placement = getMessageActionPlacement(message);
        if (!placement) return '';
        const reportButton = renderReportButton(message, placement);
        const deleteButton = renderDeleteButton(message, placement);
        if (!reportButton && !deleteButton) return '';
        return `
            <div class="chat-message-actions chat-message-actions--${placement}">
                ${reportButton}
                ${deleteButton}
            </div>
        `;
    }

    function refreshDeleteButtons() {
        const now = Date.now();
        document.querySelectorAll('.chat-msg-delete-btn[data-expire-at]').forEach(btn => {
            const exp = parseInt(btn.getAttribute('data-expire-at'), 10);
            if (Number.isFinite(exp) && now > exp) {
                const stack = btn.closest('.chat-message-actions');
                btn.remove();
                if (stack && !stack.querySelector('.chat-msg-action-btn')) {
                    stack.remove();
                }
            }
        });
    }

    function notifyChatAction(message, type = 'info') {
        if (typeof showAlert === 'function') {
            showAlert(message, type);
        } else {
            alert(message);
        }
    }

    function getReportChatMessageModalRefs() {
        const modalEl = document.getElementById('reportChatMessageModal');
        if (!modalEl) {
            return {};
        }

        return {
            modalEl,
            form: document.getElementById('reportChatMessageForm'),
            detailsEl: document.getElementById('reportChatMessageDetails'),
            errorEl: document.getElementById('reportChatMessageError'),
            detailsSection: document.getElementById('reportChatMessageDetailsSection'),
            formContent: document.getElementById('reportChatMessageFormContent'),
            successState: document.getElementById('reportChatMessageSuccessState'),
            successText: document.getElementById('reportChatMessageSuccessText'),
            footer: document.getElementById('reportChatMessageFooter'),
            submitBtn: document.getElementById('reportChatMessageSubmitBtn'),
            submitText: document.getElementById('reportChatMessageSubmitText'),
            submitSpinner: document.getElementById('reportChatMessageSubmitSpinner'),
            radios: modalEl.querySelectorAll('input[name="chat_report_reason"]'),
            groups: modalEl.querySelectorAll('.report-chat-group')
        };
    }

    function setReportChatMessageSubmittingState(isSubmitting) {
        const { modalEl, submitBtn, submitText, submitSpinner } = getReportChatMessageModalRefs();
        if (!submitBtn) {
            return;
        }

        const hasSelection = !!(modalEl && modalEl.querySelector('input[name="chat_report_reason"]:checked'));
        submitBtn.dataset.loading = isSubmitting ? '1' : '';
        submitBtn.disabled = isSubmitting || !hasSelection;

        if (submitText) {
            submitText.textContent = isSubmitting ? 'Enviando...' : 'Enviar reporte';
        }
        if (submitSpinner) {
            submitSpinner.classList.toggle('d-none', !isSubmitting);
        }
    }

    function updateReportChatMessageFormState() {
        const { modalEl, detailsSection, submitBtn } = getReportChatMessageModalRefs();
        if (!modalEl) {
            return;
        }

        const hasSelection = !!modalEl.querySelector('input[name="chat_report_reason"]:checked');
        if (detailsSection) {
            detailsSection.classList.toggle('is-disabled', !hasSelection);
        }

        if (submitBtn && submitBtn.dataset.loading !== '1') {
            submitBtn.disabled = !hasSelection;
        }
    }

    function closeOtherReportChatMessageGroups(openGroup) {
        const { groups } = getReportChatMessageModalRefs();
        if (!groups || !groups.length) {
            return;
        }

        groups.forEach((group) => {
            if (group !== openGroup) {
                group.open = false;
            }
        });
    }

    function showReportChatMessageSuccessState(message) {
        const { formContent, footer, successState, successText } = getReportChatMessageModalRefs();
        if (formContent) {
            formContent.classList.add('d-none');
        }
        if (footer) {
            footer.classList.add('d-none');
        }
        if (successText) {
            successText.textContent = message || 'Gracias por ayudarnos a mantener el chat seguro para todas.';
        }
        if (successState) {
            successState.classList.remove('d-none');
        }
    }

    function resetReportChatMessageModalState() {
        const {
            form,
            detailsEl,
            errorEl,
            detailsSection,
            formContent,
            successState,
            successText,
            footer,
            submitBtn,
            submitText,
            submitSpinner,
            radios,
            groups
        } = getReportChatMessageModalRefs();

        if (form) {
            form.reset();
        }
        if (radios && radios.length) {
            radios.forEach((radio) => {
                radio.checked = false;
            });
        }
        if (groups && groups.length) {
            groups.forEach((group) => {
                group.open = false;
            });
        }
        if (detailsEl) {
            detailsEl.value = '';
        }
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('d-none');
        }
        if (detailsSection) {
            detailsSection.classList.add('is-disabled');
        }
        if (formContent) {
            formContent.classList.remove('d-none');
            formContent.scrollTop = 0;
        }
        if (footer) {
            footer.classList.remove('d-none');
        }
        if (successState) {
            successState.classList.add('d-none');
        }
        if (successText) {
            successText.textContent = 'Gracias por ayudarnos a mantener el chat seguro para todas.';
        }
        if (submitBtn) {
            submitBtn.dataset.loading = '';
            submitBtn.disabled = true;
        }
        if (submitText) {
            submitText.textContent = 'Enviar reporte';
        }
        if (submitSpinner) {
            submitSpinner.classList.add('d-none');
        }
    }

    function initReportChatMessageModal() {
        const { modalEl, radios, groups } = getReportChatMessageModalRefs();
        if (!modalEl) {
            return;
        }

        radios.forEach((radio) => {
            radio.addEventListener('change', updateReportChatMessageFormState);
        });

        groups.forEach((group) => {
            group.addEventListener('toggle', () => {
                if (group.open) {
                    closeOtherReportChatMessageGroups(group);
                }
            });
        });

        modalEl.addEventListener('hidden.bs.modal', () => {
            resetReportChatMessageModalState();
            currentReportMessageId = null;
        });

        updateReportChatMessageFormState();
    }

    function openChatReportModal(messageId) {
        currentReportMessageId = messageId;
        const { modalEl } = getReportChatMessageModalRefs();
        resetReportChatMessageModalState();
        if (!modalEl || typeof bootstrap === 'undefined') return;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    async function submitChatMessageReport(event) {
        event.preventDefault();
        const {
            modalEl,
            errorEl,
            detailsEl
        } = getReportChatMessageModalRefs();
        const reasonInput = modalEl ? modalEl.querySelector('input[name="chat_report_reason"]:checked') : null;
        const messageId = currentReportMessageId;

        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('d-none');
        }

        if (!messageId) {
            if (errorEl) {
                errorEl.textContent = 'No se encontró el mensaje a reportar.';
                errorEl.classList.remove('d-none');
            }
            return;
        }

        if (!reasonInput) {
            if (errorEl) {
                errorEl.textContent = 'Selecciona una clasificación antes de enviar el reporte.';
                errorEl.classList.remove('d-none');
            }
            return;
        }

        setReportChatMessageSubmittingState(true);
        const reason = reasonInput.value;
        const details = detailsEl ? detailsEl.value.trim() : '';

        try {
            const response = await fetch(`/api/chat/message/${messageId}/report`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CHAT_CSRF_TOKEN
                },
                body: JSON.stringify({ reason, details })
            });

            if (typeof handleAuthRedirect === 'function' && handleAuthRedirect(response)) {
                return;
            }

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || 'No se pudo enviar el reporte');
            }

            if (data.hidden_immediately) {
                applyMessageDeleted(messageId, 'reported');
                const roomId = data.room_id || currentRoomId;
                if (roomId && roomIndex[roomId] && roomIndex[roomId].last_message && Number(roomIndex[roomId].last_message.id) === Number(messageId)) {
                    updateRoomInList(roomId, {
                        ...roomIndex[roomId].last_message,
                        room_id: Number(roomId),
                        id: Number(messageId),
                        is_deleted: true,
                        deleted_reason: 'reported'
                    });
                }
            }
            currentReportMessageId = null;
            showReportChatMessageSuccessState(data.message || 'Gracias por ayudarnos a mantener el chat seguro para todas.');
        } catch (error) {
            if (errorEl) {
                errorEl.textContent = error.message || 'No se pudo enviar el reporte.';
                errorEl.classList.remove('d-none');
            } else {
                notifyChatAction(error.message || 'No se pudo enviar el reporte.', 'danger');
            }
        } finally {
            setReportChatMessageSubmittingState(false);
            updateReportChatMessageFormState();
        }
    }

    function applyMessageDeleted(messageId, deletedReason = 'deleted') {
        const row = document.querySelector(`.chat-message-row[data-message-id="${messageId}"]`);
        if (!row) return;
        row.setAttribute('data-deleted-reason', deletedReason);
        row.querySelectorAll('.chat-message-actions').forEach(stack => stack.remove());
        const meta = row.querySelector('.chat-message-meta');
        if (meta) meta.remove();
        const bubble = row.querySelector('.chat-message');
        if (!bubble) return;
        bubble.classList.add('deleted');
        bubble.innerHTML = `<div class="chat-text chat-text--deleted">${getDeletedMessageText(deletedReason)}</div>`;
    }

    function applyMessageRestored(message) {
        if (!message || !message.id) return;
        const container = document.querySelector('.chat-messages');
        if (!container) return;
        const row = document.querySelector(`.chat-message-row[data-message-id="${message.id}"]`);
        const markup = renderMessageRow(message);
        if (row) {
            row.outerHTML = markup;
        } else {
            const placeholder = container.querySelector('.chat-placeholder');
            if (placeholder) {
                container.innerHTML = '';
            }
            container.insertAdjacentHTML('beforeend', markup);
            container.scrollTop = container.scrollHeight;
        }
        refreshDeleteButtons();
    }

    function renderModerationBadge(level) {
        const numeric = Number(level || 0);
        if (!Number.isFinite(numeric) || numeric <= 0) return '';
        const tone = numeric >= 2 ? 'red' : 'yellow';
        const title = numeric >= 2 ? 'Usuaria con dos strikes o más' : 'Usuaria con un strike';
        return `<span class="moderation-strike-badge moderation-strike-badge--${tone}" title="${title}" aria-label="${title}"><i class="fas fa-triangle-exclamation"></i></span>`;
    }

    function renderAdminBadge(isSuperAdmin, sizeClass = 'admin-badge--xs') {
        if (!isSuperAdmin) return '';
        const cls = sizeClass ? ` ${sizeClass}` : '';
        return `<span class="admin-badge${cls}" title="Admin verificada" aria-label="Admin verificada"><img src="/static/images/admin_badge.svg" alt="Admin"></span>`;
    }

    function renderStaffBadge(staffBadge, isSuperAdmin = false, sizeClass = 'staff-role-badge--xs') {
        if (!staffBadge) {
            return renderAdminBadge(isSuperAdmin, sizeClass.replace('staff-role-badge', 'admin-badge'));
        }
        if (staffBadge.is_admin) {
            return renderAdminBadge(true, sizeClass.replace('staff-role-badge', 'admin-badge'));
        }
        const variant = String(staffBadge.variant || 'support').replace(/[^a-z0-9_-]/gi, '');
        const icon = String(staffBadge.icon || 'fa-shield-halved').replace(/[^a-z0-9_-]/gi, '');
        const label = escapeHtml(staffBadge.label || 'Staff');
        const title = escapeHtml(staffBadge.title || staffBadge.label || 'Staff');
        return `<span class="staff-role-badge staff-role-badge--${variant} ${sizeClass}" title="${title}" aria-label="${title}"><i class="fas ${icon}" aria-hidden="true"></i><span class="staff-role-badge__text">${label}</span></span>`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatTime(date) {
        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (minutes < 1) return 'ahora';
        if (minutes < 60) return `hace ${minutes}m`;
        if (hours < 24) return `hace ${hours}h`;
        if (days < 7) return `hace ${days}d`;

        return date.toLocaleDateString();
    }

    function formatTimeAgo(date) {
        return formatTime(date);
    }
