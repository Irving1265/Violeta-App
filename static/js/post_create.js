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
    const currentStepText = document.getElementById('currentStepText');
    const stepSegments = Array.from(modal.querySelectorAll('.pc-stepper__segment'));
    const stepMeta = document.getElementById('postCreateStepMeta');
    const progressBar = document.getElementById('postCreateProgressBar');

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
    const captureSourceInput = document.getElementById('pcCaptureSourceInput');
    const photoModeToggle = document.getElementById('pcPhotoModeToggle');
    const photoModeButtons = photoModeToggle ? Array.from(photoModeToggle.querySelectorAll('.pc-photo-mode-btn')) : [];
    const cameraPanel = document.getElementById('pcCameraPanel');
    const cameraVideo = document.getElementById('pcCameraVideo');
    const cameraCanvas = document.getElementById('pcCameraCanvas');
    const cameraStartBtn = document.getElementById('pcCameraStartBtn');
    const cameraCaptureBtn = document.getElementById('pcCameraCaptureBtn');
    const cameraRetakeBtn = document.getElementById('pcCameraRetakeBtn');
    const cameraPlaceholder = document.getElementById('pcCameraPlaceholder');
    const cameraHelp = document.getElementById('pcCameraHelp');
    const mobileCameraGuide = document.getElementById('pcMobileCameraGuide');
    const captureStatusCard = document.getElementById('pcCaptureStatusCard');
    const capturePhotoStatus = document.getElementById('pcCapturePhotoStatus');
    const captureSourceStatus = document.getElementById('pcCaptureSourceStatus');
    const captureMotionStatus = document.getElementById('pcCaptureMotionStatus');
    const captureLocationStatus = document.getElementById('pcCaptureLocationStatus');
    const captureStatusHint = document.getElementById('pcCaptureStatusHint');

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
    const locationStatusText = locationStatus
        ? (locationStatus.querySelector('.pc-location-card__status-text') || locationStatus)
        : null;
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
    const nativeBridge = window.VioletaNativeBridge || null;
    const isNativeMobile = !isAdmin && !!(nativeBridge && typeof nativeBridge.isNativePlatform === 'function' && nativeBridge.isNativePlatform());

    const photoErrorsContainer = document.getElementById('postStepPhotoErrors');

    let map;
    let marker;
    let currentStep = 1;
    let isMapInitialized = false;
    let activeUploadTimer = null;
    let cameraStream = null;
    let activeCameraFacingMode = 'environment';
    let currentPhotoMode = isAdmin ? 'upload' : 'camera';
    let modalHideTimer = null;
    const MAX_ALLOWED_WALKING_SPEED_MPS = 2.2;
    const CAPTURE_MOTION_SAMPLE_MS = 2500;
    const MAX_NATIVE_CAPTURE_DRIFT_METERS = 25;
    const TOTAL_STEPS = 3;
    const metroBbox = '-100.80,26.10,-99.90,25.30';
    const allowedCities = new Set([
        'monterrey',
        'san pedro garza garcia', 'san pedro',
        'san nicolas de los garza',
        'guadalupe',
        'apodaca',
        'general escobedo', 'escobedo',
        'pesqueria',
        'santa catarina', 'sta catarina',
        'garcia',
        'juarez', 'ciudad benito juarez', 'benito juarez', 'cd benito juarez'
    ]);

    function applyNativeMobilePhotoUI() {
        if (!isNativeMobile) {
            return;
        }
        if (cameraVideo) {
            cameraVideo.hidden = true;
        }
        if (cameraStartBtn) {
            cameraStartBtn.textContent = 'Abrir cámara del teléfono';
        }
        if (cameraCaptureBtn) {
            cameraCaptureBtn.hidden = true;
            cameraCaptureBtn.disabled = true;
        }
        if (cameraPlaceholder) {
            const label = cameraPlaceholder.querySelector('span');
            if (label) {
                label.textContent = 'Abre la camara nativa para capturar el reporte';
            }
        }
        if (cameraHelp) {
            cameraHelp.textContent = 'Usaremos la cámara nativa del teléfono. No se permiten archivos guardados.';
        }
    }

    const state = {
        file: null,
        fileObjectUrl: null,
        captureSource: '',
        captureFacingMode: '',
        captureMirrorPreview: false,
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
            visibility: 'exact'
        },
        interaction: {
            allowLikes: true,
            allowComments: true,
        },
        captureContext: null,
    };

    const previewImageTargets = [
        previewImg,
        inlinePreviewImg,
        captionStepPreviewImg,
        categoriesStepPreviewImg,
        categoriesInlinePreviewImg,
        locationStepPreviewImg,
    ].filter(Boolean);

    function openModal() {
        if (typeof isUserVerified === 'function' && !isUserVerified()) {
            if (typeof showVerifyGate === 'function') {
                showVerifyGate();
            }
            return;
        }
        if (modalHideTimer) {
            window.clearTimeout(modalHideTimer);
            modalHideTimer = null;
        }
        resetWorkflow();
        modal.hidden = false;
        overlay.hidden = false;
        void modal.offsetWidth;
        void overlay.offsetWidth;

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                modal.classList.add('is-open');
                overlay.classList.add('is-open');
            });
        });

        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        currentStep = 1;
        updateStepUI();
        document.addEventListener('keydown', onKeydown);
        setTimeout(() => {
            modal.querySelector('[data-step-panel="1"]').focus();
        }, 380);
    }

    function closeModal() {
        if (modalHideTimer) {
            window.clearTimeout(modalHideTimer);
            modalHideTimer = null;
        }
        modal.classList.remove('is-open');
        overlay.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        stopCameraStream();

        modalHideTimer = window.setTimeout(() => {
            modal.hidden = true;
            overlay.hidden = true;
            document.body.style.overflow = '';
            if (validationMsg) {
                validationMsg.textContent = '';
            }
            modalHideTimer = null;
        }, 420);

        document.removeEventListener('keydown', onKeydown);
    }

    function resetWorkflow() {
        if (state.fileObjectUrl) {
            URL.revokeObjectURL(state.fileObjectUrl);
            state.fileObjectUrl = null;
        }
        state.file = null;
        state.captureSource = '';
        state.captureFacingMode = '';
        state.captureMirrorPreview = false;
        state.captureContext = null;
        if (captureSourceInput) captureSourceInput.value = '';
        clearImageSource(previewImg);
        clearImageSource(inlinePreviewImg);
        if (inlinePreviewWrapper) inlinePreviewWrapper.classList.remove('has-image');
        clearImageSource(captionStepPreviewImg);
        clearImageSource(categoriesStepPreviewImg);
        clearImageSource(categoriesInlinePreviewImg);
        if (categoriesInlinePreviewWrapper) categoriesInlinePreviewWrapper.classList.remove('has-image');
        clearImageSource(locationStepPreviewImg);
        if (dropzone) {
            dropzone.classList.remove('is-dragover');
        }
        stopCameraStream();
        syncCapturedPhotoMirror();
        if (cameraPanel) {
            cameraPanel.hidden = currentPhotoMode !== 'camera';
        }
        if (previewCard) previewCard.hidden = true;
        syncPhotoStageVisibility();
        if (photoPreviewWrapper) photoPreviewWrapper.classList.remove('has-image');
        if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.remove('has-image');
        if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.remove('has-image');
        if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.remove('has-image');
        captionInput.value = '';
        if (captionCounter) captionCounter.textContent = '0 / 500';
        if (categoriesError) categoriesError.textContent = '';
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
            const container = checkbox.closest('.pc-category-option');
            if (container) {
                container.classList.remove('selected');
            }
        });

        state.location = { lat: null, lng: null, address: '', city: '', country: '', showPublic: true, source: 'person', visibility: 'exact' };
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
        if (locationError) locationError.textContent = '';
        if (locationStatus) {
            locationStatus.classList.remove('pc-location-card__status--success', 'pc-location-card__status--error');
        }
        if (locationStatusText) {
            locationStatusText.textContent = 'Ubicación pendiente';
        }
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
        updateMobileCameraGuide();
    }

    function normalizeCameraFacingMode(value) {
        const normalized = String(value || '').trim().toLowerCase();
        if (normalized === 'user' || normalized === 'front' || normalized === 'frontal' || normalized === 'selfie') {
            return 'user';
        }
        if (normalized === 'environment' || normalized === 'rear' || normalized === 'back' || normalized === 'trasera' || normalized === 'posterior') {
            return 'environment';
        }
        return '';
    }

    function getStreamFacingMode(stream) {
        const track = stream && typeof stream.getVideoTracks === 'function'
            ? stream.getVideoTracks()[0]
            : null;
        if (!track) {
            return '';
        }
        const settings = typeof track.getSettings === 'function' ? track.getSettings() : {};
        const settingsFacingMode = normalizeCameraFacingMode(settings.facingMode);
        if (settingsFacingMode) {
            return settingsFacingMode;
        }
        const label = String(track.label || '').toLowerCase();
        if (/(front|facetime|user|frontal|selfie)/.test(label)) {
            return 'user';
        }
        if (/(back|rear|environment|trasera|posterior)/.test(label)) {
            return 'environment';
        }
        return '';
    }

    function isFrontFacingMode(value) {
        return normalizeCameraFacingMode(value) === 'user';
    }

    function syncLiveCameraMirror() {
        if (!cameraPanel) {
            return;
        }
        cameraPanel.classList.toggle('is-front-camera', isFrontFacingMode(activeCameraFacingMode));
    }

    function syncCapturedPhotoMirror() {
        const shouldMirror = Boolean(state.file && state.captureMirrorPreview);
        previewImageTargets.forEach((element) => {
            element.classList.toggle('pc-preview-image--mirrored', shouldMirror);
        });
    }

    function setCaptureMirrorState(options = {}) {
        state.captureFacingMode = normalizeCameraFacingMode(options.facingMode);
        state.captureMirrorPreview = Boolean(options.mirrorPreview);
        syncCapturedPhotoMirror();
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

    function updateMobileCameraGuide() {
        if (!mobileCameraGuide) {
            return;
        }
        const shouldShow = currentPhotoMode === 'camera' && !state.file;
        mobileCameraGuide.hidden = !shouldShow;
    }

    function syncPhotoStageVisibility() {
        [dropzone, cameraPanel, previewCard].forEach((element) => {
            if (!element) {
                return;
            }
            element.style.display = element.hidden ? 'none' : '';
        });
    }

    function clearImageSource(element) {
        if (!element) {
            return;
        }
        element.removeAttribute('src');
    }

    function clearSelectedPhoto(options = {}) {
        const resetCaptureLocation = Boolean(options.resetCaptureLocation);

        if (activeUploadTimer) {
            clearInterval(activeUploadTimer);
            activeUploadTimer = null;
        }
        if (state.fileObjectUrl) {
            URL.revokeObjectURL(state.fileObjectUrl);
            state.fileObjectUrl = null;
        }

        state.file = null;
        state.captureSource = '';
        state.captureFacingMode = '';
        state.captureMirrorPreview = false;
        state.captureContext = null;

        if (captureSourceInput) captureSourceInput.value = '';
        if (fileInput) fileInput.value = '';
        clearImageSource(previewImg);
        if (previewName) previewName.textContent = 'Ninguna imagen seleccionada';
        if (previewSize) previewSize.textContent = '';
        clearImageSource(inlinePreviewImg);
        clearImageSource(captionStepPreviewImg);
        clearImageSource(categoriesStepPreviewImg);
        clearImageSource(categoriesInlinePreviewImg);
        clearImageSource(locationStepPreviewImg);
        if (previewCard) previewCard.hidden = true;
        if (photoPreviewWrapper) photoPreviewWrapper.classList.remove('has-image');
        if (inlinePreviewWrapper) inlinePreviewWrapper.classList.remove('has-image');
        if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.remove('has-image');
        if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.remove('has-image');
        if (categoriesInlinePreviewWrapper) categoriesInlinePreviewWrapper.classList.remove('has-image');
        if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.remove('has-image');
        if (dropzone) dropzone.classList.remove('is-dragover');

        if (uploadProgress) {
            uploadProgress.hidden = true;
        }
        if (uploadProgressBar) {
            uploadProgressBar.style.width = '0%';
        }

        stopCameraStream();
        syncCapturedPhotoMirror();
        syncPhotoStageVisibility();

        if (resetCaptureLocation) {
            state.location = {
                ...state.location,
                lat: null,
                lng: null,
                address: '',
                city: '',
                country: '',
                source: 'person',
            };
            if (latInput) latInput.value = '';
            if (lngInput) lngInput.value = '';
            if (addressInput) addressInput.value = '';
            if (locationNameInput) locationNameInput.value = '';
            if (cityHiddenInput) cityHiddenInput.value = '';
            if (countryHiddenInput) countryHiddenInput.value = '';
            if (locationError) locationError.textContent = '';
            if (locationResults) locationResults.innerHTML = '';
            if (locationStatus) {
                locationStatus.classList.remove('pc-location-card__status--success', 'pc-location-card__status--error');
            }
            if (locationStatusText) {
                locationStatusText.textContent = 'Ubicación pendiente';
            }
            if (marker && map) {
                marker.setLatLng([25.6866, -100.3161]);
                map.setView([25.6866, -100.3161], 13);
            }
            setLocationMode('person');
        }

        if (validationMsg) {
            validationMsg.textContent = '';
        }
        setPhotoError('');
        syncPhotoStageVisibility();
        renderCaptureStatus();
        updateFooterState();
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
            panel.classList.toggle('active', isActive);
            if (isActive) {
                panel.setAttribute('tabindex', '-1');
                panel.focus({ preventScroll: false });
            } else {
                panel.removeAttribute('tabindex');
            }
        });

        backBtn.disabled = currentStep === 1;
        backBtn.hidden = currentStep === 1;
        nextBtn.dataset.action = currentStep === 3 ? 'submit' : 'next';
        nextBtn.textContent = currentStep === 3 ? 'Publicar' : 'Siguiente';
        if (currentStepText) {
            currentStepText.textContent = String(currentStep);
        }
        if (stepSegments.length) {
            stepSegments.forEach((segment, index) => {
                segment.classList.toggle('active', index < currentStep);
            });
        }
        if (stepMeta) {
            stepMeta.textContent = `Paso ${currentStep} de ${TOTAL_STEPS}`;
        }
        if (progressBar) {
            progressBar.style.width = `${(currentStep / TOTAL_STEPS) * 100}%`;
        }
        updateFooterState();
        renderCaptureStatus();

        if (currentStep === 3) {
            if (!isMapInitialized) {
                initializeMap();
            }
            if (!isAdmin) {
                if (state.captureContext && state.captureContext.lat != null && state.captureContext.lng != null) {
                    freezeIncidentLocationFromCapture(state.captureContext);
                } else {
                    state.location.lat = null;
                    state.location.lng = null;
                    state.location.address = '';
                    if (latInput) latInput.value = '';
                    if (lngInput) lngInput.value = '';
                    if (addressInput) addressInput.value = '';
                    if (locationNameInput) locationNameInput.value = '';
                    if (locationStatus) {
                        locationStatus.classList.remove('pc-location-card__status--success');
                        locationStatus.classList.add('pc-location-card__status--error');
                    }
                    if (locationStatusText) {
                        locationStatusText.textContent = 'La ubicación debe capturarse al tomar la foto.';
                    }
                    updateFooterState();
                }
            }
        }
    }

    function updateFooterState() {
        const { valid, message } = validateStep(currentStep, { silent: true });
        if (validationMsg) {
            validationMsg.textContent = message || '';
        }
        nextBtn.disabled = !valid;
        nextBtn.classList.toggle('btn-disabled', !valid);
        backBtn.classList.toggle('btn-disabled', backBtn.disabled);
    }

    function humanizeCaptureSource(source) {
        if (source === 'camera') {
            return isNativeMobile ? 'Cámara del teléfono' : 'Cámara en vivo';
        }
        if (source === 'upload') {
            return 'Archivo cargado';
        }
        return 'Pendiente';
    }

    function humanizeMotionState(motionState) {
        if (motionState === 'stationary') return 'Detenida';
        if (motionState === 'walking') return 'Caminando';
        if (motionState === 'blocked') return 'No permitido';
        if (motionState === 'unknown') return 'Sin confirmar';
        return 'Sin validar';
    }

    function renderCaptureStatus() {
        if (!captureStatusCard) return;
        const motionState = state.captureContext?.motionState || '';
        const hasLocation = state.captureContext && state.captureContext.lat != null && state.captureContext.lng != null;
        const isReady = !!state.file && (!!isAdmin || (state.captureSource === 'camera' && hasLocation && ['stationary', 'walking'].includes(motionState)));
        const photoError = (photoErrorsContainer?.textContent || '').trim();

        if (capturePhotoStatus) {
            capturePhotoStatus.textContent = state.file ? 'Lista' : 'Pendiente';
        }
        if (captureSourceStatus) {
            captureSourceStatus.textContent = humanizeCaptureSource(state.captureSource);
        }
        if (captureMotionStatus) {
            captureMotionStatus.textContent = isAdmin && !state.captureContext
                ? 'No aplica'
                : humanizeMotionState(motionState);
        }
        if (captureLocationStatus) {
            captureLocationStatus.textContent = hasLocation
                ? 'Fijada al capturar'
                : isAdmin && state.file
                    ? 'Se define después'
                    : 'Pendiente';
        }

        let hint = '';
        if (photoError) {
            hint = photoError;
        } else if (isReady) {
            hint = 'La foto ya está lista. Revisa la vista previa y continúa al siguiente paso.';
        } else if (state.file) {
            hint = 'La foto se guardó, pero aún falta confirmar alguna condición de captura.';
        } else if (currentPhotoMode === 'upload') {
            hint = 'Selecciona o arrastra un archivo para continuar.';
        } else {
            hint = 'Abre la cámara, toma la foto y espera la validación de ubicación y movimiento.';
        }
        if (captureStatusHint) {
            captureStatusHint.textContent = hint;
        }
        captureStatusCard.classList.toggle('is-ready', !!isReady);
        if (changePhotoBtn) {
            changePhotoBtn.textContent = 'Cambiar';
        }
        updateMobileCameraGuide();
    }

    function normLocationToken(value) {
        return (value || '').toString().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    }

    function getLocationCity(address = {}) {
        return address.city
            || address.town
            || address.village
            || address.municipality
            || address.city_district
            || address.county
            || '';
    }

    function isAllowedMetroAddress(address = {}) {
        const cityName = getLocationCity(address);
        const inAllowedCity = cityName ? allowedCities.has(normLocationToken(cityName)) : false;
        const inNuevoLeon = address.state ? normLocationToken(address.state).includes('nuevo leon') : true;
        return inAllowedCity && inNuevoLeon;
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
            if ((!isAdmin || nextMode === 'manual' || nextMode === 'capture') && marker.dragging.disable) {
                marker.dragging.disable();
            } else if (isAdmin && nextMode !== 'manual' && marker.dragging.enable) {
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
            if (validationMsg) {
                validationMsg.textContent = validation.message || '';
            }
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
            if (!isAdmin) {
                const captureLat = state.captureContext?.lat;
                const captureLng = state.captureContext?.lng;
                const motionState = state.captureContext?.motionState;
                if (state.captureSource !== 'camera') {
                    if (!silent) {
                        setPhotoError('Para publicar debes tomar la foto en el momento con la cámara.');
                    }
                    return { valid: false, message: 'Toma la foto con la cámara para continuar.' };
                }
                if (captureLat == null || captureLng == null) {
                    if (!silent) {
                        setPhotoError('Necesitamos la ubicación exacta de donde tomaste la foto.');
                    }
                    return { valid: false, message: 'Confirma la ubicación al momento de tomar la foto.' };
                }
                if (!['stationary', 'walking'].includes(motionState)) {
                    if (!silent) {
                        setPhotoError('Solo puedes reportar si estás detenida o caminando al tomar la foto.');
                    }
                    return { valid: false, message: 'La captura debe hacerse estando detenida o caminando.' };
                }
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

            if (categoriesError) categoriesError.textContent = '';
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
                    if (categoriesError) categoriesError.textContent = message;
                    if (publishError && message.includes('programar')) {
                        publishError.textContent = message;
                        if (categoriesError) categoriesError.textContent = '';
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
            const allowMissingAddressFromCapture = !isAdmin && !!(state.captureContext && lat != null && lng != null);
            if (lat == null || lng == null || (!address && !allowMissingAddressFromCapture)) {
                const message = 'Selecciona una ubicación válida antes de publicar.';
                if (!silent) {
                    if (locationError) locationError.textContent = message;
                    if (locationStatus) {
                        locationStatus.classList.remove('pc-location-card__status--success');
                        locationStatus.classList.add('pc-location-card__status--error');
                    }
                    if (locationStatusText) {
                        locationStatusText.textContent = message;
                    }
                }
                return { valid: false, message };
            }
            if (locationError) locationError.textContent = '';
            return { valid: true };
        }
        return { valid: true };
    }

    function submit() {
        nextBtn.disabled = true;
        if (validationMsg) {
            validationMsg.textContent = 'Enviando publicación...';
        }

        const formData = new FormData();
        if (state.file) {
            formData.append('image', state.file);
        }
        if (state.captureSource) {
            formData.append('capture_source', state.captureSource);
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
        formData.append('location_visibility', state.location.visibility || 'exact');
        if (state.captureContext) {
            formData.append('capture_latitude', state.captureContext.lat);
            formData.append('capture_longitude', state.captureContext.lng);
            if (state.captureContext.takenAt) {
                formData.append('capture_taken_at', state.captureContext.takenAt);
            }
            if (state.captureContext.motionState) {
                formData.append('capture_motion_state', state.captureContext.motionState);
            }
            if (state.captureContext.accuracy != null) {
                formData.append('capture_accuracy', state.captureContext.accuracy);
            }
            if (state.captureContext.speedMps != null) {
                formData.append('capture_speed_mps', state.captureContext.speedMps);
            }
            if (state.location.address) {
                formData.append('capture_location_name', state.location.address);
            }
            if (state.location.city) {
                formData.append('capture_city', state.location.city);
            }
            if (state.location.country) {
                formData.append('capture_country', state.location.country);
            }
        }

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
            const policy = window.VIOLETA_SAFETY_PUBLISH_POLICY || {
                min_delay_minutes: 15,
                distance_meters: 200,
                fallback_minutes: 60
            };
            const noticeHtml = `
                <div style="display:flex;gap:10px;align-items:flex-start;">
                    <i class="fas fa-shield-alt" style="font-size:1.2rem;margin-top:2px;"></i>
                    <div>
                        <strong>Por seguridad tuya</strong>
                        <div style="font-size:0.9rem;opacity:0.9;margin-top:2px;">Tu publicación se hará pública cuando pasen ${policy.min_delay_minutes} min y estés al menos a ${policy.distance_meters} m del punto del reporte, o en máximo ${policy.fallback_minutes} min.</div>
                    </div>
                </div>
            `;
            if (typeof showVioletNotification === 'function') {
                showVioletNotification(noticeHtml, 'info', 15000);
            } else if (typeof showAlert === 'function') {
                showAlert(noticeHtml, 'info');
            } else {
                alert(`Tu publicación se hará pública cuando pasen ${policy.min_delay_minutes} min y estés al menos a ${policy.distance_meters} m del punto del reporte, o en máximo ${policy.fallback_minutes} min.`);
            }
        }

        let noticeShown = false;
        const showNoticeOnce = () => {
            if (noticeShown) return;
            noticeShown = true;
            closeModal();
            window.dispatchEvent(new Event('violeta:safety-publish-created'));
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
                if (validationMsg) {
                    validationMsg.textContent = 'Ocurrió un error al publicar. Inténtalo de nuevo.';
                }
                nextBtn.disabled = false;
            });
    }

    function setPhotoError(message) {
        if (photoErrorsContainer) {
            photoErrorsContainer.textContent = message;
        }
        renderCaptureStatus();
    }

    function formatFileSize(bytes) {
        if (!bytes && bytes !== 0) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return `${(bytes / Math.pow(1024, exponent)).toFixed(1)} ${units[exponent]}`;
    }

    function commitFile(file, source = '') {
        setPhotoError('');
        state.file = file;
        state.captureSource = source || '';
        if (captureSourceInput) captureSourceInput.value = state.captureSource;

        if (state.fileObjectUrl) {
            URL.revokeObjectURL(state.fileObjectUrl);
        }
        const objectUrl = URL.createObjectURL(file);
        state.fileObjectUrl = objectUrl;

        previewImg.src = objectUrl;
        if (previewName) previewName.textContent = file.name;
        if (previewSize) previewSize.textContent = formatFileSize(file.size);
        if (inlinePreviewImg) inlinePreviewImg.src = objectUrl;
        if (inlinePreviewWrapper) inlinePreviewWrapper.classList.add('has-image');
        if (captionStepPreviewImg) captionStepPreviewImg.src = objectUrl;
        if (categoriesStepPreviewImg) categoriesStepPreviewImg.src = objectUrl;
        if (categoriesInlinePreviewImg) categoriesInlinePreviewImg.src = objectUrl;
        if (locationStepPreviewImg) locationStepPreviewImg.src = objectUrl;
        syncCapturedPhotoMirror();
        if (photoPreviewWrapper) photoPreviewWrapper.classList.add('has-image');
        if (captionStepPreviewWrapper) captionStepPreviewWrapper.classList.add('has-image');
        if (categoriesStepPreviewWrapper) categoriesStepPreviewWrapper.classList.add('has-image');
        if (locationStepPreviewWrapper) locationStepPreviewWrapper.classList.add('has-image');
        if (dropzone) dropzone.hidden = true;
        if (cameraPanel) cameraPanel.hidden = true;
        previewCard.hidden = false;
        syncPhotoStageVisibility();

        simulateUploadProgress();
        updateFooterState();
        renderPreviewCard();
        renderCaptureStatus();
    }

    function handleFiles(files, source = '', options = {}) {
        const file = files && files[0];
        if (!file) return;

        if (!isAdmin && source !== 'camera') {
            setPhotoError('Para publicar debes tomar la foto en el momento con la cámara.');
            return;
        }

        if (!['image/jpeg', 'image/png'].includes(file.type)) {
            setPhotoError('Usa JPG o PNG.');
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            setPhotoError('Máx. 10 MB.');
            return;
        }

        setCaptureMirrorState({
            facingMode: source === 'camera' ? options.facingMode : '',
            mirrorPreview: source === 'camera' ? options.mirrorPreview : false,
        });
        commitFile(file, source);
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

    function wait(ms) {
        return new Promise((resolve) => {
            window.setTimeout(resolve, ms);
        });
    }

    function toFiniteNumber(value) {
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    }

    function haversineDistanceMeters(lat1, lng1, lat2, lng2) {
        const radius = 6371000;
        const toRad = (deg) => deg * Math.PI / 180;
        const dLat = toRad(lat2 - lat1);
        const dLng = toRad(lng2 - lng1);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
            + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2))
            * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return radius * c;
    }

    function extractPositionSpeed(position) {
        const directSpeed = toFiniteNumber(position?.raw?.coords?.speed);
        if (directSpeed != null && directSpeed >= 0) {
            return directSpeed;
        }
        return toFiniteNumber(position?.speed);
    }

    function extractPositionTimestamp(position) {
        const rawTimestamp = position?.timestamp ?? position?.raw?.timestamp;
        const numericTimestamp = toFiniteNumber(rawTimestamp);
        if (numericTimestamp != null && numericTimestamp > 0) {
            return numericTimestamp;
        }
        const parsedTimestamp = Date.parse(String(rawTimestamp || ''));
        if (Number.isFinite(parsedTimestamp)) {
            return parsedTimestamp;
        }
        return Date.now();
    }

    function classifyMotionState(speedMps) {
        if (!Number.isFinite(speedMps) || speedMps == null || speedMps < 0) {
            return null;
        }
        if (speedMps <= 0.8) {
            return 'stationary';
        }
        if (speedMps <= MAX_ALLOWED_WALKING_SPEED_MPS) {
            return 'walking';
        }
        return 'blocked';
    }

    function buildCaptureContext(position, extra = {}) {
        const speedMps = toFiniteNumber(extra.speedMps != null ? extra.speedMps : extractPositionSpeed(position));
        return {
            lat: position.lat,
            lng: position.lng,
            accuracy: toFiniteNumber(position.accuracy),
            timestamp: extractPositionTimestamp(position),
            takenAt: new Date(extractPositionTimestamp(position)).toISOString(),
            speedMps,
            motionState: extra.motionState || classifyMotionState(speedMps) || 'unknown',
            sampleDistanceMeters: toFiniteNumber(extra.sampleDistanceMeters),
            source: extra.source || position.source || 'browser',
        };
    }

    function freezeIncidentLocationFromCapture(captureContext) {
        state.captureContext = captureContext;
        state.location.source = 'capture';
        if (locSourceInput) {
            locSourceInput.value = 'capture';
        }
        if (marker && marker.dragging && marker.dragging.disable) {
            marker.dragging.disable();
        }
        updateLocation({
            lat: captureContext.lat,
            lng: captureContext.lng,
            address: captureContext.address || '',
        }, !captureContext.address);
        if (locationStatus) {
            locationStatus.classList.add('pc-location-card__status--success');
            locationStatus.classList.remove('pc-location-card__status--error');
        }
        if (locationStatusText) {
            locationStatusText.textContent = captureContext.address
                ? `Ubicación del reporte: ${captureContext.address}`
                : 'Estamos confirmando la ubicación de donde tomaste la foto.';
        }
        renderCaptureStatus();
    }

    async function getFreshCapturePosition() {
        if (!nativeBridge || typeof nativeBridge.getCurrentPosition !== 'function') {
            throw new Error('No pudimos acceder a la ubicacion del dispositivo.');
        }
        return nativeBridge.getCurrentPosition({
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0,
        });
    }

    async function resolveCaptureContext() {
        if (validationMsg) {
            validationMsg.textContent = 'Confirmando que estas a pie o detenida...';
        }
        const firstPosition = await getFreshCapturePosition();
        let speedMps = extractPositionSpeed(firstPosition);
        let motionState = classifyMotionState(speedMps);
        let selectedPosition = firstPosition;
        let sampledDistanceMeters = null;

        if (!motionState) {
            await wait(CAPTURE_MOTION_SAMPLE_MS);
            const secondPosition = await getFreshCapturePosition();
            const elapsedSeconds = Math.max(
                CAPTURE_MOTION_SAMPLE_MS / 1000,
                (extractPositionTimestamp(secondPosition) - extractPositionTimestamp(firstPosition)) / 1000
            );
            sampledDistanceMeters = haversineDistanceMeters(
                Number(firstPosition.lat),
                Number(firstPosition.lng),
                Number(secondPosition.lat),
                Number(secondPosition.lng)
            );
            speedMps = sampledDistanceMeters / Math.max(1, elapsedSeconds);
            motionState = classifyMotionState(speedMps);
            selectedPosition = secondPosition;
        }

        const captureContext = buildCaptureContext(selectedPosition, {
            motionState: motionState || 'unknown',
            sampleDistanceMeters: sampledDistanceMeters,
            speedMps,
        });

        if (captureContext.motionState === 'blocked') {
            throw new Error('Por seguridad, solo puedes reportar si estas detenida o caminando al tomar la foto.');
        }
        if (captureContext.lat == null || captureContext.lng == null) {
            throw new Error('Necesitamos la ubicacion exacta de donde tomaste la foto.');
        }

        freezeIncidentLocationFromCapture(captureContext);
        return captureContext;
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

        marker = L.marker([25.6866, -100.3161], { draggable: isAdmin && state.location.source !== 'manual' }).addTo(map);
        marker.on('moveend', (event) => {
            if (state.location.source === 'manual' || (!isAdmin && state.location.source === 'capture')) {
                event.target.setLatLng([state.location.lat || 25.6866, state.location.lng || -100.3161]);
                return;
            }
            const { lat, lng } = event.target.getLatLng();
            updateLocation({ lat, lng }, true);
        });

        isMapInitialized = true;
        if ((!isAdmin || state.location.source === 'manual') && marker.dragging && marker.dragging.disable) {
            marker.dragging.disable();
        }

        // Initialize location state with default marker position only for admin or when capture already froze location.
        if (isAdmin || state.captureContext) {
            const { lat, lng } = marker.getLatLng();
            updateLocation({ lat, lng }, true);
        }
    }

    async function captureWithNativeCamera() {
        if (!isNativeMobile || !nativeBridge || typeof nativeBridge.capturePhoto !== 'function') {
            return false;
        }
        setPhotoError('');
        if (cameraStartBtn) {
            cameraStartBtn.disabled = true;
        }
        try {
            const preCaptureContext = await resolveCaptureContext();
            const nativeCapture = await nativeBridge.capturePhoto({
                filenamePrefix: 'captura',
                quality: 92,
            });
            if (!nativeCapture || !nativeCapture.file) {
                return false;
            }
            try {
                const postCapturePosition = await getFreshCapturePosition();
                const driftMeters = haversineDistanceMeters(
                    Number(preCaptureContext.lat),
                    Number(preCaptureContext.lng),
                    Number(postCapturePosition.lat),
                    Number(postCapturePosition.lng)
                );
                if (driftMeters > MAX_NATIVE_CAPTURE_DRIFT_METERS) {
                    throw new Error('Nos movimos demasiado mientras tomabas la foto. Vuelve a intentarlo desde el punto exacto.');
                }
                freezeIncidentLocationFromCapture(buildCaptureContext(postCapturePosition, {
                    motionState: preCaptureContext.motionState,
                    speedMps: preCaptureContext.speedMps,
                    sampleDistanceMeters: driftMeters,
                    source: 'native',
                }));
            } catch (driftError) {
                const msg = String(driftError?.message || '');
                if (msg) {
                    throw driftError;
                }
            }
            handleFiles([nativeCapture.file], 'camera', {
                facingMode: nativeCapture.facingMode || 'environment',
                mirrorPreview: Boolean(nativeCapture.mirrorPreview),
            });
            return true;
        } catch (error) {
            const message = (error && error.message ? String(error.message) : '').toLowerCase();
            if (message.includes('cancel')) {
                return false;
            }
            setPhotoError(error?.message || 'No pudimos abrir la camara del dispositivo. Intentalo de nuevo.');
            return false;
        } finally {
            if (validationMsg) {
                validationMsg.textContent = '';
            }
            if (cameraStartBtn) {
                cameraStartBtn.disabled = false;
            }
        }
    }

    function updateLocation({ lat, lng, address, city, country }, shouldReverse = false) {
        state.location.lat = lat;
        state.location.lng = lng;
        latInput.value = lat != null ? String(lat) : '';
        lngInput.value = lng != null ? String(lng) : '';
        if (typeof city === 'string') {
            state.location.city = city;
        }
        if (typeof country === 'string') {
            state.location.country = country;
        }

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
            if (locationStatus) {
                locationStatus.classList.add('pc-location-card__status--success');
                locationStatus.classList.remove('pc-location-card__status--error');
            }
            if (locationStatusText) {
                locationStatusText.textContent = !isAdmin && state.location.source === 'capture'
                    ? `Ubicación del reporte: ${address}`
                    : `Ubicación detectada: ${address}`;
            }
            renderLocationResultMessage('');
        } else if (shouldReverse && lat != null && lng != null) {
            reverseGeocode(lat, lng).then((result) => {
                if (result) {
                    updateLocation({
                        lat,
                        lng,
                        address: result.address,
                        city: result.city || '',
                        country: result.country || ''
                    }, false);
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
                    updateLocation({
                        lat: item.lat,
                        lng: item.lng,
                        address: item.label,
                        city: item.city || '',
                        country: item.country || ''
                    }, false);
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
            if (locationStatus) {
                locationStatus.classList.remove('pc-location-card__status--error', 'pc-location-card__status--success');
            }
            if (locationStatusText) {
                locationStatusText.textContent = 'Ubicación pendiente';
            }
            return;
        }
        fetchCurrentLocation();
    }

    async function fetchCurrentLocation() {
        setLocationMode('person');
        if (locationStatusText) {
            locationStatusText.textContent = 'Obteniendo ubicación actual...';
        }
        try {
            const position = await getFreshCapturePosition();

            updateLocation({ lat: position.lat, lng: position.lng }, true);
            if (useCurrentLocationToggle) useCurrentLocationToggle.checked = true;
        } catch (error) {
            console.warn('Geolocation error:', error);
            if (locationStatus) {
                locationStatus.classList.add('pc-location-card__status--error');
            }
            if (error && Number(error.code) === 1) {
                if (locationStatusText) {
                    locationStatusText.textContent = 'Permiso de ubicacion denegado. Es necesario para publicar.';
                }
            } else {
                if (locationStatusText) {
                    locationStatusText.textContent = 'No pudimos obtener tu ubicacion. Intentalo de nuevo.';
                }
            }
            if (useCurrentLocationToggle) useCurrentLocationToggle.checked = false;
        }
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
        const trimmed = String(query || '').trim();
        if (!trimmed) {
            return Promise.resolve([]);
        }
        const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&countrycodes=mx&accept-language=es&bounded=1&viewbox=${metroBbox}&q=${encodeURIComponent(trimmed)}&limit=8`;
        return fetch(url, { headers: { Accept: 'application/json' } })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('No se pudo consultar la ubicacion.');
                }
                return response.json();
            })
            .then((list) => {
                return (list || [])
                    .filter((item) => isAllowedMetroAddress(item.address || {}))
                    .map((item) => ({
                        label: item.display_name,
                        lat: parseFloat(item.lat),
                        lng: parseFloat(item.lon),
                        city: getLocationCity(item.address || {}),
                        country: item.address?.country || ''
                    }));
            });
    }

    function reverseGeocode(lat, lng) {
        const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1&accept-language=es&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lng)}&zoom=18`;
        return fetch(url, { headers: { Accept: 'application/json' } })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('No se pudo resolver la direccion.');
                }
                return response.json();
            })
            .then((result) => ({
                address: result.display_name || `Coordenadas ${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}`,
                city: getLocationCity(result.address || {}),
                country: result.address?.country || ''
            }))
            .catch(() => null);
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
        syncPhotoStageVisibility();
        photoModeButtons.forEach(btn => {
            const isActive = btn.dataset.mode === nextMode;
            btn.classList.toggle('is-active', isActive);
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        updateMobileCameraGuide();
        renderCaptureStatus();
    }

    function startCameraStream() {
        if (isNativeMobile) {
            captureWithNativeCamera();
            return;
        }
        if (!cameraVideo) return;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setPhotoError('Tu navegador no permite usar la cámara.');
            return;
        }
        setPhotoError('');
        navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
            .then((stream) => {
                cameraStream = stream;
                activeCameraFacingMode = getStreamFacingMode(stream) || 'environment';
                syncLiveCameraMirror();
                cameraVideo.srcObject = stream;
                cameraVideo.play().catch(() => {});
                if (cameraPlaceholder) cameraPlaceholder.hidden = true;
                if (cameraCaptureBtn) {
                    cameraCaptureBtn.hidden = false;
                    cameraCaptureBtn.disabled = false;
                }
                if (cameraRetakeBtn) {
                    cameraRetakeBtn.hidden = true;
                }
            })
            .catch(() => {
                activeCameraFacingMode = 'environment';
                syncLiveCameraMirror();
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
        activeCameraFacingMode = 'environment';
        syncLiveCameraMirror();
        if (cameraCaptureBtn) {
            cameraCaptureBtn.disabled = true;
            cameraCaptureBtn.hidden = true;
        }
        if (cameraPlaceholder) cameraPlaceholder.hidden = false;
    }

    function captureFromCamera() {
        if (isNativeMobile) {
            captureWithNativeCamera();
            return;
        }
        if (!cameraVideo || !cameraCanvas) return;
        if (!cameraStream) {
            startCameraStream();
            return;
        }
        if (cameraCaptureBtn) {
            cameraCaptureBtn.disabled = true;
        }
        resolveCaptureContext()
            .then(() => {
                const width = cameraVideo.videoWidth || 1280;
                const height = cameraVideo.videoHeight || 720;
                const ctx = cameraCanvas.getContext('2d');
                const shouldMirrorCapture = isFrontFacingMode(activeCameraFacingMode);
                cameraCanvas.width = width;
                cameraCanvas.height = height;
                ctx.save();
                if (shouldMirrorCapture) {
                    ctx.translate(width, 0);
                    ctx.scale(-1, 1);
                }
                ctx.drawImage(cameraVideo, 0, 0, width, height);
                ctx.restore();
                cameraCanvas.toBlob((blob) => {
                    if (!blob) {
                        setPhotoError('No se pudo capturar la foto.');
                        if (cameraCaptureBtn) cameraCaptureBtn.disabled = false;
                        return;
                    }
                    const file = new File([blob], `captura-${Date.now()}.jpg`, { type: 'image/jpeg' });
                    handleFiles([file], 'camera', {
                        facingMode: activeCameraFacingMode,
                        mirrorPreview: false,
                    });
                    stopCameraStream();
                    if (cameraRetakeBtn) cameraRetakeBtn.hidden = true;
                    if (validationMsg) {
                        validationMsg.textContent = '';
                    }
                }, 'image/jpeg', 0.92);
            })
            .catch((error) => {
                setPhotoError(error?.message || 'No pudimos confirmar tu ubicacion al tomar la foto.');
                if (validationMsg) {
                    validationMsg.textContent = '';
                }
                if (cameraCaptureBtn) {
                    cameraCaptureBtn.disabled = false;
                }
            });
    }



    function onCaptionInput() {
        const value = captionInput.value || '';
        if (captionCounter) {
            captionCounter.textContent = `${value.length} / 500`;
        }
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
                handleFiles(event.dataTransfer.files, 'upload');
            });
        }
        if (changePhotoBtn) {
            changePhotoBtn.addEventListener('click', () => {
                const shouldResetCaptureLocation = !isAdmin || state.location.source === 'capture' || !!state.captureContext;

                clearSelectedPhoto({ resetCaptureLocation: shouldResetCaptureLocation });
                if (previewCard) {
                    previewCard.hidden = true;
                }
                clearImageSource(previewImg);
                if (fileInput) {
                    fileInput.value = '';
                }
                setPhotoMode('camera');
                updateMobileCameraGuide();
                updateFooterState();
                startCameraStream();
            });
        }
        if (fileInput) {
            fileInput.addEventListener('change', (event) => {
                if (currentPhotoMode !== 'upload') return;
                handleFiles(event.target.files, 'upload');
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

        captionInput.addEventListener('input', onCaptionInput);

        // Category checkboxes
        document.querySelectorAll('input[name="categories"]').forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                const container = checkbox.closest('.pc-category-option') || checkbox.closest('.pc-category-item');
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
    applyNativeMobilePhotoUI();
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
