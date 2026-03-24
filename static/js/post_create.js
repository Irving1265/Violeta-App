/* global L */
(function () {
    const modal = document.getElementById('postCreateModal');
    const overlay = document.getElementById('postCreateOverlay');
    if (!modal || !overlay) {
        return;
    }

    const stepPanels = Array.from(modal.querySelectorAll('[data-step-panel]'));
    const form = document.getElementById('postCreateForm');
    const backBtn = document.getElementById('postCreateBackBtn');
    const nextBtn = document.getElementById('postCreateNextBtn');
    const closeBtn = document.getElementById('postCreateCloseBtn');
    const validationMsg = document.getElementById('postCreateValidationMsg');

    const dropzone = document.getElementById('pcDropzone');
    const fileInput = document.getElementById('pcFileInput');
    const previewCard = document.getElementById('pcPhotoPreviewCard');
    const photoPreviewWrapper = document.getElementById('pcPhotoPreviewImageWrapper');
    const changePhotoBtn = document.getElementById('pcChangePhotoBtn');
    const previewImg = document.getElementById('pcPreviewImage');
    const previewName = document.getElementById('pcPreviewFileName');
    const previewSize = document.getElementById('pcPreviewFileSize');
    const uploadProgress = document.getElementById('pcUploadProgress');
    const uploadProgressBar = document.getElementById('pcUploadProgressBar');
    const photoModeToggle = document.getElementById('pcPhotoModeToggle');
    const photoModeButtons = photoModeToggle ? Array.from(photoModeToggle.querySelectorAll('.pc-photo-mode-btn')) : [];
    const cameraPanel = document.getElementById('pcCameraPanel');
    const cameraVideo = document.getElementById('pcCameraVideo');
    const cameraCanvas = document.getElementById('pcCameraCanvas');
    const cameraStartBtn = document.getElementById('pcCameraStartBtn');
    const cameraCaptureBtn = document.getElementById('pcCameraCaptureBtn');
    const cameraRetakeBtn = document.getElementById('pcCameraRetakeBtn');
    const cameraPlaceholder = document.getElementById('pcCameraPlaceholder');
    const cropperModalEl = document.getElementById('pcCropperModal');
    const cropperImage = document.getElementById('pcCropperImage');
    const cropperApplyBtn = document.getElementById('pcApplyCropBtn');
    const cropperChooseBtn = document.getElementById('pcChooseCropFileBtn');

    const inlinePreviewWrapper = document.getElementById('pcInlinePreviewWrapper');
    const inlinePreviewImg = document.getElementById('pcInlinePreviewImage');
    const captionStepPreviewWrapper = document.getElementById('pcCaptionPreviewWrapper');
    const captionStepPreviewImg = document.getElementById('pcCaptionPreviewImg');
    const categoriesStepPreviewWrapper = document.getElementById('pcCategoriesPreviewWrapper');
    const categoriesStepPreviewImg = document.getElementById('pcCategoriesPreviewImg');
    const categoriesInlinePreviewWrapper = document.getElementById('pcCategoriesInlinePreviewWrapper');
    const categoriesInlinePreviewImg = document.getElementById('pcCategoriesInlinePreviewImage');
    const categoriesPreviewCaptionText = document.getElementById('pcCategoriesPreviewCaptionText');
    const locationStepPreviewWrapper = document.getElementById('pcLocationPreviewWrapper');
    const locationStepPreviewImg = document.getElementById('pcLocationPreviewImg');
    const captionInput = document.getElementById('pcCaptionInput');
    const captionCounter = document.getElementById('pcCaptionCount');
    const categoriesError = document.getElementById('pcCategoriesError');
    const publishModeInputs = document.querySelectorAll('input[name="pcPublishMode"]');
    const publishAtInput = document.getElementById('pcPublishAt');
    const publishAtWrap = document.getElementById('pcPublishAtWrap');
    const publishError = document.getElementById('pcPublishError');
    const allowLikesToggle = document.getElementById('pcAllowLikes');
    const allowCommentsToggle = document.getElementById('pcAllowComments');

    const locationStatus = document.getElementById('pcLocationStatus');
    const locationStatusText = locationStatus.querySelector('.pc-location-card__status-text');
    const locationSearchInput = document.getElementById('pcLocationSearch');
    const locationSearchBtn = document.getElementById('pcLocationSearchBtn');
    const locationResults = document.getElementById('pcLocationResults');
    const locationError = document.getElementById('pcLocationError');
    const useCurrentLocationToggle = document.getElementById('pcUseCurrentLocation');
    const hideLocationToggle = document.getElementById('pcHideLocation');
    const latInput = document.getElementById('pcLatInput');
    const lngInput = document.getElementById('pcLngInput');
    const addressInput = document.getElementById('pcAddressInput');
    const locationNameInput = document.getElementById('pcLocationNameInput');
    const cityHiddenInput = document.getElementById('pcCityInput');
    const countryHiddenInput = document.getElementById('pcCountryInput');
    const showPublicInput = document.getElementById('pcShowPublicInput');
    const locSourceInput = document.getElementById('pcLocSourceInput');
    const locationVisibilityInput = document.getElementById('pcLocationVisibilityInput');
    const locationVisibilityRadios = Array.from(document.querySelectorAll('input[name="pcLocationVisibility"]'));
    const locationModeInputs = document.querySelectorAll('input[name="pcLocationMode"]');
    const manualFieldsWrapper = document.getElementById('pcManualLocationFields');
    const manualLatInput = document.getElementById('pcManualLat');
    const manualLngInput = document.getElementById('pcManualLng');
    const manualAddressInput = document.getElementById('pcManualAddress');
    const manualCityInput = document.getElementById('pcManualCity');
    const manualCountryInput = document.getElementById('pcManualCountry');

    const isAdminCtx = document.getElementById('pcIsAdminCtx');
    const isAdmin = isAdminCtx ? isAdminCtx.value === 'true' : false;

    const photoErrorsContainer = document.getElementById('postStepPhotoErrors');

    let map;
    let marker;
    let currentStep = 1;
    let isMapInitialized = false;
    let activeUploadTimer = null;
    let cameraStream = null;
    let currentPhotoMode = isAdmin ? 'upload' : 'camera';
    let cropperInstance = null;
    let cropperModal = null;
    let pendingCropFile = null;
    let pendingCropUrl = null;

    const state = {
        file: null,
        fileObjectUrl: null,
        caption: '',
        alt: '',
        tags: [],
        categories: [],
        location: {
            lat: null,
            lng: null,
            address: '',
            city: '',
            country: '',
            showPublic: true,
            source: 'person',
            visibility: isAdmin ? 'exact' : 'approx'
        },
        interaction: {
            allowLikes: true,
            allowComments: true,
        }
    };

    function openModal() {
        if (typeof isUserVerified === 'function' && !isUserVerified()) {
            if (typeof showVerifyGate === 'function') {
                showVerifyGate();
            }
            return;
        }
        resetWorkflow();
        modal.hidden = false;
        overlay.hidden = false;
        // Force reflow
        console.log(modal.offsetHeight);
        
        requestAnimationFrame(() => {
            modal.classList.add('is-open');
            overlay.classList.add('is-open');
        });

        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        currentStep = 1;
        updateStepUI();
        document.addEventListener('keydown', onKeydown);
        setTimeout(() => {
            modal.querySelector('[data-step-panel="1"]').focus();
        }, 300); // reduced wait for animation
    }

    function closeModal() {
        modal.classList.remove('is-open');
        overlay.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        stopCameraStream();
        
        setTimeout(() => {
            modal.hidden = true;
            overlay.hidden = true;
            document.body.style.overflow = '';
            validationMsg.textContent = '';
        }, 300); // Wait for transition

        document.removeEventListener('keydown', onKeydown);
    }

    function resetWorkflow() {
        if (state.fileObjectUrl) {
            URL.revokeObjectURL(state.fileObjectUrl);
            state.fileObjectUrl = null;
        }
        state.file = null;
        if (previewImg) previewImg.src = '';
        if (inlinePreviewImg) inlinePreviewImg.src = '';
        if (inlinePreviewWrapper) inlinePreviewWrapper.classList.remove('has-image');
        if (captionStepPreviewImg) captionStepPreviewImg.src = '';
        if (categoriesStepPreviewImg) categoriesStepPreviewImg.src = '';
        if (categoriesInlinePreviewImg) categoriesInlinePreviewImg.src = '';
        if (categoriesInlinePreviewWrapper) categoriesInlinePreviewWrapper.classList.remove('has-image');
        if (locationStepPreviewImg) locationStepPreviewImg.src = '';
        if (dropzone) {
            dropzone.classList.remove('is-dragover');
        }
        stopCameraStream();
        if (cameraPanel) {
            cameraPanel.hidden = currentPhotoMode !== 'camera';
        }
        if (previewCard) previewCard.hidden = true;
        if (photoPreviewWrapper) photoPreviewWrapper.classList.remove('has-image');
        if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.remove('has-image');
        if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.remove('has-image');
        if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.remove('has-image');
        captionInput.value = '';
        captionCounter.textContent = '0 / 500';
        categoriesError.textContent = '';
        if (publishError) publishError.textContent = '';
        if (publishAtInput) publishAtInput.value = '';
        if (allowLikesToggle) allowLikesToggle.checked = true;
        if (allowCommentsToggle) allowCommentsToggle.checked = true;
        state.interaction = { allowLikes: true, allowComments: true };
        if (publishModeInputs && publishModeInputs.length) {
            publishModeInputs.forEach((input, idx) => {
                input.checked = idx === 0;
            });
            updatePublishScheduleUI();
        }
        state.caption = '';
        state.categories = [];

        // Reset tag checkboxes
        document.querySelectorAll('input[name="tags"]').forEach(checkbox => {
            checkbox.checked = false;
        });

        // Reset category checkboxes
        document.querySelectorAll('input[name="categories"]').forEach(checkbox => {
            checkbox.checked = false;
            const container = checkbox.closest('.pc-category-checkbox');
            if (container) {
                container.classList.remove('selected');
            }
        });

        state.location = { lat: null, lng: null, address: '', city: '', country: '', showPublic: true, source: 'person', visibility: isAdmin ? 'exact' : 'approx' };
        if (latInput) latInput.value = '';
        if (lngInput) lngInput.value = '';
        if (addressInput) addressInput.value = '';
        if (locationNameInput) locationNameInput.value = '';
        if (cityHiddenInput) cityHiddenInput.value = '';
        if (countryHiddenInput) countryHiddenInput.value = '';
        if (showPublicInput) showPublicInput.value = 'true';
        if (locSourceInput) locSourceInput.value = 'person';
        if (locationVisibilityInput) locationVisibilityInput.value = state.location.visibility;
        if (locationVisibilityRadios.length) {
            locationVisibilityRadios.forEach((radio) => {
                radio.checked = radio.value === state.location.visibility;
            });
        }
        if (hideLocationToggle) hideLocationToggle.checked = false;
        if (useCurrentLocationToggle) useCurrentLocationToggle.checked = false;
        if (locationResults) locationResults.innerHTML = '';
        locationError.textContent = '';
        locationStatus.classList.remove('pc-location-card__status--success', 'pc-location-card__status--error');
        locationStatusText.textContent = 'Ubicación pendiente';
        if (locationModeInputs.length) {
            locationModeInputs.forEach(input => {
                input.checked = input.value === 'person';
            });
        }
        if (manualFieldsWrapper) manualFieldsWrapper.hidden = true;
        if (manualLatInput) manualLatInput.value = '';
        if (manualLngInput) manualLngInput.value = '';
        if (manualAddressInput) manualAddressInput.value = '';
        if (manualCityInput) manualCityInput.value = '';
        if (manualCountryInput) manualCountryInput.value = '';
        setLocationMode('person');

        if (marker && map) {
            marker.setLatLng([25.6866, -100.3161]);
            map.setView([25.6866, -100.3161], 13);
        }

        if (uploadProgress) {
            uploadProgress.hidden = true;
            uploadProgressBar.style.width = '0%';
        }
        setPhotoMode(isAdmin ? 'upload' : 'camera');
    }

    function getPublishMode() {
        if (!publishModeInputs || publishModeInputs.length === 0) return null;
        const selected = Array.from(publishModeInputs).find(input => input.checked);
        return selected ? selected.value : null;
    }

    function updatePublishScheduleUI() {
        if (!publishAtWrap) return;
        const mode = getPublishMode();
        publishAtWrap.hidden = mode !== 'schedule';
    }

    function onKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeModal();
        }
        if (event.key === 'Enter' && !event.shiftKey) {
            const target = event.target;
            const tagName = target.tagName.toLowerCase();
            const isTextInput = tagName === 'textarea' || tagName === 'input';
            if (isTextInput) {
                return;
            }
            event.preventDefault();
            handleNext();
        }
    }

    function setStep(step) {
        currentStep = step;
        updateStepUI();
    }

    function updateStepUI() {
        stepPanels.forEach((panel) => {
            const step = Number(panel.getAttribute('data-step-panel'));
            const isActive = step === currentStep;
            panel.hidden = !isActive;
            panel.classList.toggle('is-active', isActive);
            if (isActive) {
                panel.setAttribute('tabindex', '-1');
                panel.focus({ preventScroll: false });
            } else {
                panel.removeAttribute('tabindex');
            }
        });

        backBtn.disabled = currentStep === 1;
        nextBtn.dataset.action = currentStep === 3 ? 'submit' : 'next';
        nextBtn.textContent = currentStep === 3 ? 'Publicar' : 'Siguiente';
        updateFooterState();

        if (currentStep === 3) {
            if (!isMapInitialized) {
                initializeMap();
            }
            // Enforce auto location for non-admins
            if (!isAdmin) {
                fetchCurrentLocation();
            }
        }
    }

    function updateFooterState() {
        const { valid, message } = validateStep(currentStep, { silent: true });
        validationMsg.textContent = message || '';
        nextBtn.disabled = !valid;
    }

    function syncLocationHiddenFields() {
        if (locationNameInput) {
            locationNameInput.value = state.location.address || '';
        }
        if (cityHiddenInput) {
            cityHiddenInput.value = state.location.city || '';
        }
        if (countryHiddenInput) {
            countryHiddenInput.value = state.location.country || '';
        }
    }

    function setLocationMode(mode) {
        const nextMode = mode || 'person';
        state.location.source = nextMode;
        if (locSourceInput) {
            locSourceInput.value = nextMode;
        }
        if (manualFieldsWrapper) {
            manualFieldsWrapper.hidden = nextMode !== 'manual';
        }
        if (useCurrentLocationToggle) {
            if (nextMode === 'manual') {
                useCurrentLocationToggle.checked = false;
                useCurrentLocationToggle.disabled = true;
            } else {
                useCurrentLocationToggle.disabled = false;
            }
        }
        if (locationModeInputs.length) {
            locationModeInputs.forEach(input => {
                input.checked = input.value === nextMode;
            });
        }
        if (marker && marker.dragging) {
            if (nextMode === 'manual' && marker.dragging.disable) {
                marker.dragging.disable();
            } else if (nextMode !== 'manual' && marker.dragging.enable) {
                marker.dragging.enable();
            }
        }
        if (nextMode !== 'manual') {
            if (manualLatInput) manualLatInput.value = '';
            if (manualLngInput) manualLngInput.value = '';
            if (manualAddressInput) manualAddressInput.value = '';
            if (manualCityInput) manualCityInput.value = '';
            if (manualCountryInput) manualCountryInput.value = '';
            state.location.city = '';
            state.location.country = '';
            syncLocationHiddenFields();
        } else if (locationStatusText) {
            locationStatusText.textContent = 'Introduce latitud y longitud manualmente.';
        }
        updateFooterState();
    }

    function handleManualFieldsChange() {
        if (state.location.source !== 'manual') {
            return;
        }
        const latValue = manualLatInput ? manualLatInput.value.trim() : '';
        const lngValue = manualLngInput ? manualLngInput.value.trim() : '';
        const lat = latValue === '' ? NaN : parseFloat(latValue);
        const lng = lngValue === '' ? NaN : parseFloat(lngValue);
        const label = manualAddressInput ? manualAddressInput.value.trim() : '';
        state.location.address = label;
        if (addressInput) {
            addressInput.value = label;
        }
        state.location.city = manualCityInput ? manualCityInput.value.trim() : '';
        state.location.country = manualCountryInput ? manualCountryInput.value.trim() : '';

        if (Number.isFinite(lat) && Number.isFinite(lng)) {
            const address = label || `Coordenadas manuales (${lat.toFixed(5)}, ${lng.toFixed(5)})`;
            updateLocation({ lat, lng, address }, false);
        } else {
            syncLocationHiddenFields();
        }
    }

    function handleBack() {
        if (currentStep > 1) {
            setStep(currentStep - 1);
        }
    }

    function handleNext() {
        const validation = validateStep(currentStep);
        if (!validation.valid) {
            validationMsg.textContent = validation.message || '';
            return;
        }
        if (currentStep < 3) {
            setStep(currentStep + 1);
        } else {
            submit();
        }
    }

    function validateStep(step, options = {}) {
        const silent = Boolean(options.silent);
        if (step === 1) {
            if (!state.file) {
                if (!silent) {
                    setPhotoError('Selecciona una imagen válida antes de continuar.');
                }
                return { valid: false, message: 'Selecciona una imagen válida.' };
            }
            setPhotoError('');
            return { valid: true };
        }
        if (step === 2) {
            const caption = (captionInput.value || '').trim();
            const categories = document.querySelectorAll('input[name="categories"]:checked');

            let message = '';
            if (caption.length > 500) {
                message = 'La descripción debe tener máximo 500 caracteres.';
            } else if (categories.length === 0) {
                message = 'Debes seleccionar al menos una categoría.';
            }

            categoriesError.textContent = '';
            if (publishError) publishError.textContent = '';

            if (isAdmin) {
                const mode = getPublishMode();
                if (mode === 'schedule') {
                    const scheduledVal = publishAtInput ? publishAtInput.value : '';
                    if (!scheduledVal) {
                        message = 'Selecciona la fecha y hora para programar la publicación.';
                    }
                }
            }

            if (message) {
                if (!silent) {
                    categoriesError.textContent = message;
                    if (publishError && message.includes('programar')) {
                        publishError.textContent = message;
                        categoriesError.textContent = '';
                    }
                }
                return { valid: false, message };
            }

            state.caption = caption;
            state.categories = Array.from(categories).map(cb => cb.value);
            return { valid: true };
        }
        if (step === 3) {
            const { lat, lng, address } = state.location;
            if (lat == null || lng == null || !address) {
                const message = 'Selecciona una ubicación válida antes de publicar.';
                if (!silent) {
                    locationError.textContent = message;
                    locationStatus.classList.remove('pc-location-card__status--success');
                    locationStatus.classList.add('pc-location-card__status--error');
                    locationStatusText.textContent = message;
                }
                return { valid: false, message };
            }
            locationError.textContent = '';
            return { valid: true };
        }
        return { valid: true };
    }

    function submit() {
        nextBtn.disabled = true;
        validationMsg.textContent = 'Enviando publicación...';

        const formData = new FormData();
        if (state.file) {
            formData.append('image', state.file);
        }
        formData.append('caption', state.caption);

        state.categories.forEach(cat => {
            formData.append('categories', cat);
        });

        if (state.location.lat != null) formData.append('latitude', state.location.lat);
        if (state.location.lng != null) formData.append('longitude', state.location.lng);
        if (state.location.address) formData.append('location_name', state.location.address);
        if (state.location.city) formData.append('city', state.location.city);
        if (state.location.country) formData.append('country', state.location.country);
        formData.append('loc_source', state.location.source);
        formData.append('show_public', state.location.showPublic);
        formData.append('location_visibility', state.location.visibility || (isAdmin ? 'exact' : 'approx'));

        state.interaction.allowLikes = allowLikesToggle ? !!allowLikesToggle.checked : true;
        state.interaction.allowComments = allowCommentsToggle ? !!allowCommentsToggle.checked : true;
        formData.append('allow_likes', state.interaction.allowLikes ? 'true' : 'false');
        formData.append('allow_comments', state.interaction.allowComments ? 'true' : 'false');

        if (isAdmin) {
            const mode = getPublishMode();
            if (mode) {
                formData.append('publish_mode', mode);
            }
            if (mode === 'schedule' && publishAtInput && publishAtInput.value) {
                formData.append('publish_at', publishAtInput.value);
            }
        }

        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        function showPublishDelayNotice() {
            if (isAdmin) return;
            const noticeHtml = `
                <div style="display:flex;gap:10px;align-items:flex-start;">
                    <i class="fas fa-shield-alt" style="font-size:1.2rem;margin-top:2px;"></i>
                    <div>
                        <strong>Por seguridad tuya</strong>
                        <div style="font-size:0.9rem;opacity:0.9;margin-top:2px;">Tu publicación se hará pública en 15 min.</div>
                    </div>
                </div>
            `;
            if (typeof showVioletNotification === 'function') {
                showVioletNotification(noticeHtml, 'info', 15000);
            } else if (typeof showAlert === 'function') {
                showAlert(noticeHtml, 'info');
            } else {
                alert('Por seguridad tuya, tu publicación se hará pública en 15 min.');
            }
        }

        let noticeShown = false;
        const showNoticeOnce = () => {
            if (noticeShown) return;
            noticeShown = true;
            closeModal();
            setTimeout(showPublishDelayNotice, 300);
        };

        fetch('/upload', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
            .then(response => {
                if (response.redirected) {
                    if (!isAdmin) {
                        showNoticeOnce();
                    } else {
                        window.location.href = response.url;
                    }
                    return;
                }
                if (!response.ok) {
                    throw new Error('Error en la publicación');
                }
                return response.text();
            })
            .then(() => {
                if (!isAdmin) {
                    showNoticeOnce();
                } else {
                    window.location.reload();
                }
            })
            .catch(error => {
                console.error('Error:', error);
                validationMsg.textContent = 'Ocurrió un error al publicar. Inténtalo de nuevo.';
                nextBtn.disabled = false;
            });
    }

    function setPhotoError(message) {
        if (photoErrorsContainer) {
            photoErrorsContainer.textContent = message;
        }
    }

    function formatFileSize(bytes) {
        if (!bytes && bytes !== 0) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return `${(bytes / Math.pow(1024, exponent)).toFixed(1)} ${units[exponent]}`;
    }

    function openCropper(file) {
        if (!cropperModalEl || !cropperImage || typeof Cropper === 'undefined' || !cropperModal) {
            commitFile(file);
            return;
        }
        stopCameraStream();
        pendingCropFile = file;
        if (pendingCropUrl) {
            URL.revokeObjectURL(pendingCropUrl);
        }
        pendingCropUrl = URL.createObjectURL(file);
        cropperImage.src = pendingCropUrl;
        cropperModal.show();
    }

    function commitFile(file) {
        setPhotoError('');
        state.file = file;

        if (state.fileObjectUrl) {
            URL.revokeObjectURL(state.fileObjectUrl);
        }
        const objectUrl = URL.createObjectURL(file);
        state.fileObjectUrl = objectUrl;

        previewImg.src = objectUrl;
        previewName.textContent = file.name;
        previewSize.textContent = formatFileSize(file.size);
        inlinePreviewImg.src = objectUrl;
        if (inlinePreviewWrapper) inlinePreviewWrapper.classList.add('has-image');
        if (captionStepPreviewImg) captionStepPreviewImg.src = objectUrl;
        if (categoriesStepPreviewImg) categoriesStepPreviewImg.src = objectUrl;
        if (categoriesInlinePreviewImg) categoriesInlinePreviewImg.src = objectUrl;
        if (locationStepPreviewImg) locationStepPreviewImg.src = objectUrl;
        if (photoPreviewWrapper) photoPreviewWrapper.classList.add('has-image');
        if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.add('has-image');
        if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.add('has-image');
        if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.add('has-image');
        if (dropzone) dropzone.hidden = true;
        if (cameraPanel) cameraPanel.hidden = true;
        previewCard.hidden = false;

        simulateUploadProgress();
        updateFooterState();
        renderPreviewCard();
    }

    function handleFiles(files) {
        const file = files && files[0];
        if (!file) return;

        if (!['image/jpeg', 'image/png'].includes(file.type)) {
            setPhotoError('Usa JPG o PNG.');
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            setPhotoError('Máx. 10 MB.');
            return;
        }

        openCropper(file);
    }

    function simulateUploadProgress() {
        if (!uploadProgress || !uploadProgressBar) {
            return;
        }
        if (activeUploadTimer) {
            clearInterval(activeUploadTimer);
        }
        uploadProgress.hidden = false;
        uploadProgressBar.style.width = '0%';
        let progress = 0;
        activeUploadTimer = setInterval(() => {
            progress += Math.random() * 25;
            if (progress >= 100) {
                progress = 100;
                clearInterval(activeUploadTimer);
                activeUploadTimer = null;
                setTimeout(() => {
                    uploadProgress.hidden = true;
                }, 500);
            }
            uploadProgressBar.style.width = `${progress}%`;
        }, 180);
    }



    function renderPreviewCard() {
        // previewCaptionText.textContent = state.caption || 'Aquí verás tu descripción.';
        if (categoriesPreviewCaptionText) categoriesPreviewCaptionText.textContent = state.caption || 'Aquí verás tu descripción.';
        if (state.file) {
            if (photoPreviewWrapper) photoPreviewWrapper.classList.add('has-image');
            if (inlinePreviewWrapper) inlinePreviewWrapper.classList.add('has-image');
            if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.add('has-image');
            if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.add('has-image');
            if (categoriesInlinePreviewWrapper) categoriesInlinePreviewWrapper.classList.add('has-image');
            if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.add('has-image');
        }
    }

    function initializeMap() {
        if (typeof L === 'undefined') {
            console.warn('Leaflet no está disponible. El mapa no se inicializará.');
            return;
        }
        map = L.map('pcMap', {
            zoomControl: true,
            attributionControl: false
        }).setView([25.6866, -100.3161], 13);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19
        }).addTo(map);

        marker = L.marker([25.6866, -100.3161], { draggable: state.location.source !== 'manual' }).addTo(map);
        marker.on('moveend', (event) => {
            if (state.location.source === 'manual') {
                event.target.setLatLng([state.location.lat || 25.6866, state.location.lng || -100.3161]);
                return;
            }
            const { lat, lng } = event.target.getLatLng();
            updateLocation({ lat, lng }, true);
        });

        isMapInitialized = true;
        if (state.location.source === 'manual' && marker.dragging && marker.dragging.disable) {
            marker.dragging.disable();
        }

        // Initialize location state with default marker position
        const { lat, lng } = marker.getLatLng();
        updateLocation({ lat, lng }, true);
    }

    function updateLocation({ lat, lng, address }, shouldReverse = false) {
        state.location.lat = lat;
        state.location.lng = lng;
        latInput.value = lat != null ? String(lat) : '';
        lngInput.value = lng != null ? String(lng) : '';

        if (marker && lat != null && lng != null) {
            marker.setLatLng([lat, lng]);
            map.setView([lat, lng], map.getZoom(), { animate: true });
        }

        if (address) {
            state.location.address = address;
            addressInput.value = address;
            if (locationNameInput) {
                locationNameInput.value = address;
            }
            locationStatus.classList.add('pc-location-card__status--success');
            locationStatus.classList.remove('pc-location-card__status--error');
            locationStatusText.textContent = `Ubicación detectada: ${address}`;
            renderLocationResultMessage('');
        } else if (shouldReverse && lat != null && lng != null) {
            reverseGeocode(lat, lng).then((result) => {
                if (result) {
                    updateLocation({ lat, lng, address: result.address }, false);
                }
            });
        }

        syncLocationHiddenFields();
        updateFooterState();
    }

    function renderLocationResultMessage(message) {
        if (!locationResults) return;
        if (message) {
            locationResults.innerHTML = `<div class="pc-location-result" tabindex="0">${message}</div>`;
        } else {
            locationResults.innerHTML = '';
        }
    }

    function handleLocationSearch() {
        const query = (locationSearchInput.value || '').trim();
        if (!query) {
            renderLocationResultMessage('');
            return;
        }
        if (locationResults) locationResults.innerHTML = '<div class="pc-location-result">Buscando...</div>';
        geocode(query).then((results) => {
            if (!results.length) {
                renderLocationResultMessage('No se encontraron resultados.');
                return;
            }
            if (locationResults) locationResults.innerHTML = '';
            results.forEach((item) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'pc-location-result';
                button.textContent = item.label;
                button.setAttribute('role', 'option');
                button.addEventListener('click', () => {
                    setLocationMode('person');
                    updateLocation({ lat: item.lat, lng: item.lng, address: item.label }, false);
                    renderLocationResultMessage('');
                });
                if (locationResults) locationResults.appendChild(button);
            });
        }).catch(() => {
            renderLocationResultMessage('No se pudo completar la búsqueda.');
        });
    }

    function handleUseCurrentLocationToggle() {
        if (!useCurrentLocationToggle.checked) {
            locationStatus.classList.remove('pc-location-card__status--error', 'pc-location-card__status--success');
            locationStatusText.textContent = 'Ubicación pendiente';
            return;
        }
        fetchCurrentLocation();
    }

    function fetchCurrentLocation() {
        setLocationMode('person');
        locationStatusText.textContent = 'Obteniendo ubicación actual...';
        if (!navigator.geolocation) {
            locationStatus.classList.add('pc-location-card__status--error');
            locationStatusText.textContent = 'Geolocalización no soportada.';
            if (useCurrentLocationToggle) useCurrentLocationToggle.checked = false;
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const { latitude, longitude } = position.coords;
                updateLocation({ lat: latitude, lng: longitude }, true);
                if (useCurrentLocationToggle) useCurrentLocationToggle.checked = true;
            },
            (error) => {
                console.warn('Geolocation error:', error);
                locationStatus.classList.add('pc-location-card__status--error');
                // Customize error message based on error code if needed
                if (error.code === error.PERMISSION_DENIED) {
                    locationStatusText.textContent = 'Permiso de ubicación denegado. Es necesario para publicar.';
                } else {
                    locationStatusText.textContent = 'No pudimos obtener tu ubicación. Inténtalo de nuevo.';
                }
                if (useCurrentLocationToggle) useCurrentLocationToggle.checked = false;
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 5 * 60 * 1000
            }
        );
    }

    function handleHideLocationToggle() {
        state.location.showPublic = !hideLocationToggle.checked;
        showPublicInput.value = String(state.location.showPublic);
    }

    function handleLocationVisibilityChange(event) {
        const input = event?.target;
        if (!input || !input.checked) return;
        state.location.visibility = input.value;
        if (locationVisibilityInput) {
            locationVisibilityInput.value = state.location.visibility;
        }
    }

    function geocode(query) {
        // TODO: Reemplazar con llamada real a un servicio de geocodificación.
        return new Promise((resolve) => {
            setTimeout(() => {
                const sample = [
                    { label: `${query} · Centro, Monterrey`, lat: 25.6741, lng: -100.309 },
                    { label: `${query} · San Pedro Garza García`, lat: 25.657, lng: -100.402 },
                    { label: `${query} · Guadalupe`, lat: 25.672, lng: -100.245 }
                ];
                resolve(sample);
            }, 600);
        });
    }

    function reverseGeocode(lat, lng) {
        // TODO: Reemplazar con llamada real a un servicio de reverse geocoding.
        return new Promise((resolve) => {
            setTimeout(() => {
                resolve({
                    address: `Coordenadas ${lat.toFixed(4)}, ${lng.toFixed(4)}`
                });
            }, 500);
        });
    }

    function setPhotoMode(mode) {
        const nextMode = mode || (isAdmin ? 'upload' : 'camera');
        currentPhotoMode = nextMode;
        if (dropzone) {
            dropzone.hidden = nextMode !== 'upload';
        }
        if (cameraPanel) {
            cameraPanel.hidden = nextMode !== 'camera';
        }
        if (previewCard && state.file) {
            previewCard.hidden = false;
        }
        if (nextMode !== 'camera') {
            stopCameraStream();
        }
        photoModeButtons.forEach(btn => {
            const isActive = btn.dataset.mode === nextMode;
            btn.classList.toggle('is-active', isActive);
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
    }

    function startCameraStream() {
        if (!cameraVideo) return;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setPhotoError('Tu navegador no permite usar la cámara.');
            return;
        }
        setPhotoError('');
        navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
            .then((stream) => {
                cameraStream = stream;
                cameraVideo.srcObject = stream;
                cameraVideo.play().catch(() => {});
                if (cameraPlaceholder) cameraPlaceholder.hidden = true;
                if (cameraCaptureBtn) cameraCaptureBtn.disabled = false;
            })
            .catch(() => {
                setPhotoError('No pudimos acceder a la cámara. Permite el acceso e inténtalo de nuevo.');
            });
    }

    function stopCameraStream() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
            cameraStream = null;
        }
        if (cameraVideo) {
            cameraVideo.srcObject = null;
        }
        if (cameraCaptureBtn) cameraCaptureBtn.disabled = true;
        if (cameraPlaceholder) cameraPlaceholder.hidden = false;
    }

    function captureFromCamera() {
        if (!cameraVideo || !cameraCanvas) return;
        if (!cameraStream) {
            startCameraStream();
            return;
        }
        const width = cameraVideo.videoWidth || 1280;
        const height = cameraVideo.videoHeight || 720;
        const ctx = cameraCanvas.getContext('2d');
        cameraCanvas.width = width;
        cameraCanvas.height = height;
        ctx.drawImage(cameraVideo, 0, 0, width, height);
        cameraCanvas.toBlob((blob) => {
            if (!blob) {
                setPhotoError('No se pudo capturar la foto.');
                return;
            }
            const file = new File([blob], `captura-${Date.now()}.jpg`, { type: 'image/jpeg' });
            handleFiles([file]);
            stopCameraStream();
            if (cameraRetakeBtn) cameraRetakeBtn.hidden = true;
        }, 'image/jpeg', 0.92);
    }



    function onCaptionInput() {
        const value = captionInput.value || '';
        captionCounter.textContent = `${value.length} / 500`;
        state.caption = value.trim();
        renderPreviewCard();
        updateFooterState();
    }

    function bindEvents() {
        if (dropzone) {
            dropzone.addEventListener('click', () => {
                if (currentPhotoMode !== 'upload') return;
                if (fileInput) fileInput.click();
            });
            dropzone.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    if (currentPhotoMode !== 'upload') return;
                    if (fileInput) fileInput.click();
                }
            });
            dropzone.addEventListener('dragover', (event) => {
                if (currentPhotoMode !== 'upload') return;
                event.preventDefault();
                dropzone.classList.add('is-dragover');
            });
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('is-dragover'));
            dropzone.addEventListener('drop', (event) => {
                if (currentPhotoMode !== 'upload') return;
                event.preventDefault();
                dropzone.classList.remove('is-dragover');
                handleFiles(event.dataTransfer.files);
            });
        }
        if (changePhotoBtn) {
            changePhotoBtn.addEventListener('click', () => {
                if (currentPhotoMode === 'camera' || !isAdmin) {
                    setPhotoMode('camera');
                    if (cameraPanel) cameraPanel.hidden = false;
                    startCameraStream();
                    return;
                }
                if (fileInput) fileInput.click();
            });
        }
        if (fileInput) {
            fileInput.addEventListener('change', (event) => {
                if (currentPhotoMode !== 'upload') return;
                handleFiles(event.target.files);
            });
        }

        if (photoModeButtons.length) {
            photoModeButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    setPhotoMode(btn.dataset.mode);
                });
            });
        }

        if (cameraStartBtn) {
            cameraStartBtn.addEventListener('click', () => {
                setPhotoMode('camera');
                startCameraStream();
            });
        }
        if (cameraCaptureBtn) {
            cameraCaptureBtn.addEventListener('click', captureFromCamera);
        }
        if (cameraRetakeBtn) {
            cameraRetakeBtn.addEventListener('click', () => {
                setPhotoMode('camera');
                startCameraStream();
            });
        }

        if (cropperModalEl && window.bootstrap) {
            cropperModal = new bootstrap.Modal(cropperModalEl, {
                backdrop: false,
                focus: false,
                keyboard: true
            });
            cropperModalEl.addEventListener('shown.bs.modal', () => {
                if (!cropperImage || typeof Cropper === 'undefined') return;
                if (cropperInstance) cropperInstance.destroy();
                cropperInstance = new Cropper(cropperImage, {
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
            cropperModalEl.addEventListener('hidden.bs.modal', () => {
                if (cropperInstance) {
                    cropperInstance.destroy();
                    cropperInstance = null;
                }
                if (pendingCropUrl) {
                    URL.revokeObjectURL(pendingCropUrl);
                    pendingCropUrl = null;
                }
                pendingCropFile = null;
                if (fileInput) fileInput.value = '';
                if (document.querySelector('.pc-modal.is-open')) {
                    document.body.classList.add('modal-open');
                }
            });
        }

        if (cropperApplyBtn) {
            cropperApplyBtn.addEventListener('click', () => {
                if (!cropperInstance || !pendingCropFile) return;
                const outputType = pendingCropFile.type === 'image/png' ? 'image/png' : 'image/jpeg';
                const canvas = cropperInstance.getCroppedCanvas({
                    width: 1080,
                    height: 1080,
                    fillColor: '#000'
                });
                if (!canvas) {
                    setPhotoError('No se pudo procesar la imagen.');
                    return;
                }
                const quality = outputType === 'image/jpeg' ? 0.92 : undefined;
                canvas.toBlob((blob) => {
                    if (!blob) {
                        setPhotoError('No se pudo recortar la imagen.');
                        return;
                    }
                    const croppedFile = new File([blob], pendingCropFile.name || `foto-${Date.now()}.jpg`, { type: outputType });
                    commitFile(croppedFile);
                    cropperModal.hide();
                }, outputType, quality);
            });
        }

        if (cropperChooseBtn) {
            cropperChooseBtn.addEventListener('click', () => {
                if (cropperModal) cropperModal.hide();
                if (!isAdmin || currentPhotoMode === 'camera') {
                    setPhotoMode('camera');
                    startCameraStream();
                    return;
                }
                if (fileInput) fileInput.click();
            });
        }

        captionInput.addEventListener('input', onCaptionInput);

        // Category checkboxes
        document.querySelectorAll('input[name="categories"]').forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                const container = checkbox.closest('.pc-category-checkbox');
                if (container) {
                    container.classList.toggle('selected', checkbox.checked);
                }
                updateFooterState();
            });
        });

        if (publishModeInputs && publishModeInputs.length) {
            publishModeInputs.forEach(input => {
                input.addEventListener('change', () => {
                    updatePublishScheduleUI();
                    if (publishError) publishError.textContent = '';
                });
            });
            updatePublishScheduleUI();
        }

        backBtn.addEventListener('click', handleBack);
        nextBtn.addEventListener('click', handleNext);
        closeBtn.addEventListener('click', closeModal);
        overlay.addEventListener('click', closeModal);

        if (locationSearchBtn) locationSearchBtn.addEventListener('click', handleLocationSearch);
        if (locationSearchInput) {
            locationSearchInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    handleLocationSearch();
                }
            });
        }
        if (useCurrentLocationToggle) useCurrentLocationToggle.addEventListener('change', handleUseCurrentLocationToggle);
        if (hideLocationToggle) hideLocationToggle.addEventListener('change', handleHideLocationToggle);
        if (locationVisibilityRadios.length) {
            locationVisibilityRadios.forEach((radio) => {
                radio.addEventListener('change', handleLocationVisibilityChange);
            });
        }
        if (locationModeInputs.length) {
            locationModeInputs.forEach(input => {
                input.addEventListener('change', () => {
                    if (input.checked) {
                        setLocationMode(input.value);
                        if (input.value === 'manual') {
                            handleManualFieldsChange();
                        }
                    }
                });
            });
        }
        [manualLatInput, manualLngInput, manualAddressInput, manualCityInput, manualCountryInput].forEach(input => {
            if (input) {
                input.addEventListener('input', handleManualFieldsChange);
            }
        });
    }

    bindEvents();
    updateStepUI();
    setLocationMode(state.location.source);
    setPhotoMode(isAdmin ? 'upload' : 'camera');

    window.PostCreateModal = {
        open: openModal,
        close: closeModal,
        getState() {
            return JSON.parse(JSON.stringify(state));
        }
    };
})();
