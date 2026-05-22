(function () {
  const page = document.querySelector('[data-verification-page]');
  if (!page) return;

  const livenessPhrases = [
    'El piano brillante camina sobre un sombrero de la luna',
    'La estrella oxidada baila bajo el martillo con su arena',
    'Un viento lejano duerme contra mi violín sin una nube',
    'Una montaña dulce corre hacia aquel desierto por mi brisa',
    'Este queso gigante viaja entre otro túnel para su playa',
    'Aquel puente frío brilla desde el faro ante la sombra',
    'Otra lluvia blanda muerde según su cofre tras la selva',
    'Esta arena antigua llora contra la brisa con el río',
    'Un reloj seco vuela hacia este bosque por su calma',
    'El espejo maduro sueña bajo un globo en la nieve',
    'Aquella roca verde canta entre mi martillo sin la ola',
    'Ningún pez veloz duerme sobre el cuaderno con la cueva',
    'Este mapa hondo rompe desde su cable por la tierra',
    'Un lobo antiguo salta contra otro cofre tras la brisa',
    'La calma blanda viaja hacia un sombrero con la lluvia',
    'Aquel cuaderno oxidado ríe entre esta playa sin la estrella',
    'Una brisa madura muerde bajo el violín por la montaña',
    'Este faro dulce duerme contra la luna con el viento',
    'La sombra gigante camina sobre un martillo ante la nieve',
    'El libro frío baila desde aquel túnel por la arena',
    'Un cable lejano corre hacia su bosque con la selva',
    'Otra estrella seca brilla entre mi cofre sin la calma',
    'Esta cueva brillante rompe bajo el puente por la ola',
    'Aquella nube veloz sueña contra una montaña con la luna',
    'El vaso verde salta sobre su desierto tras la sombra',
    'Un pan antiguo canta desde el faro por la brisa',
    'Ningún reloj gigante duerme hacia este cuaderno con la nieve',
    'Esta lluvia madura vuela entre mi sombrero sin la tierra',
    'Aquel pez dulce camina bajo el violín por la arena',
    'Una roca hondo ríe contra aquel túnel tras la playa',
    'El cofre seco viaja sobre una nube con la calma',
    'Este nudo brillante baila desde mi cofre por la ola',
    'Otra montaña fría rompe bajo su bosque ante la selva',
    'Un lobo veloz duerme hacia este faro con la sombra',
    'La selva blanda corre entre el cuaderno sin la estrella',
    'Aquella mesa madura sueña contra mi martillo por la lluvia',
    'Este piano antiguo canta sobre un violín con la brisa',
    'Un espejo gigante vuela desde la luna tras la nieve',
    'El desierto verde ríe bajo el cofre por la calma',
    'Una bota lejana camina contra su túnel con la arena',
    'Este viento maduro duerme sobre mi desierto por la tierra',
    'Aquel violín brillante vuela hacia una playa con la selva',
    'Una sombra seca baila entre el faro sin la luna',
    'Un martillo dulce corre bajo su bosque por la nube',
    'La ola fría camina contra aquel sombrero con la brisa',
    'Ningún cofre antiguo rompe desde mi cuaderno tras la nieve',
    'Este faro gigante duerme sobre esta montaña por la calma',
    'Otra roca blanda vuela hacia un túnel con la arena',
    'Aquella brisa verde sueña entre mi violín sin la selva',
    'Un lobo brillante ríe bajo el cofre por la estrella',
    'El piano lejano viaja contra la luna con la lluvia',
    'Esta nieve seca corre sobre su bosque tras la sombra',
    'Una playa dulce baila desde mi martillo por la brisa',
    'El puente antiguo vuela hacia aquel desierto con la calma',
    'Aquel reloj gigante duerme entre una nube sin la ola',
    'Ningún vaso maduro camina bajo su cofre por la nieve',
    'Un cable frío ríe contra este faro con la selva',
    'La estrella blanda sueña sobre mi violín tras la arena',
    'Este túnel verde corre hacia el cuaderno por la tierra',
    'Otra bota brillante rompe bajo aquel sombrero con la luna',
    'El desierto seco camina entre su bosque sin la brisa',
    'Una brisa antigua baila contra mi faro por la calma',
    'Un cofre dulce duerme sobre esta montaña con la nieve',
    'Aquel violín gigante vuela hacia mi playa tras la sombra',
    'Este martillo verde ríe bajo el túnel por la lluvia',
    'La luna fría sueña contra una nube con la estrella',
    'Ningún lobo brillante camina desde el cofre por la arena',
    'Esta arena madura corre entre su bosque sin la selva',
    'Un espejo antiguo vuela sobre mi violín tras la brisa',
    'Otra roca seca baila hacia aquel desierto con la calma',
    'El piano gigante duerme bajo el sombrero por la nieve',
    'Aquella sombra blanda ríe contra mi faro con la ola',
    'Este faro verde sueña sobre una playa tras la luna',
    'Un viento dulce camina hacia el cuaderno por la tierra',
    'La ola antigua vuela entre mi túnel sin la estrella',
    'Ningún cofre maduro baila bajo su bosque por la calma',
    'Este violín frío corre contra aquel desierto con la brisa',
    'Otra brisa brillante duerme desde mi faro tras la nieve',
    'Una nube gigante ríe sobre el cofre por la selva',
    'El lobo seco sueña hacia una montaña con la luna',
    'Aquel puente verde camina entre su túnel sin la ola',
    'Este espejo maduro vuela contra mi faro por la arena',
    'Una estrella dulce baila sobre esta playa con la calma',
    'Un martillo brillante duerme bajo el cuaderno tras la brisa',
    'La montaña lejana corre hacia mi cofre por la lluvia',
    'Ningún reloj antiguo ríe entre aquel sombrero sin la nieve',
    'Esta bota gigante sueña contra su bosque con la selva',
    'Otra roca fría camina sobre el violín por la luna',
    'El cofre verde vuela hacia una nube tras la sombra',
    'Un piano seco baila bajo mi faro con la calma',
    'Aquella brisa blanda duerme entre su túnel sin la brisa',
    'Este viento brillante ríe contra el cofre por la estrella',
    'Una luna madura sueña sobre mi playa con la nieve',
    'Un violín antiguo camina hacia aquel desierto tras la arena',
    'La selva dulce vuela bajo su bosque por la tierra',
    'Ningún lobo verde baila contra el faro con la ola',
    'Esta montaña seca corre entre mi cofre sin la calma',
    'Otra estrella fría duerme sobre aquel sombrero por la brisa',
    'El espejo gigante ríe hacia una playa con la selva',
    'Un cofre brillante sueña bajo mi violín tras la luna'
  ];

  const MAX_RECORDING_SECONDS = 60;
  const MIN_RECORDING_SECONDS = 5;
  const MAX_VIDEO_BYTES = 40 * 1024 * 1024;
  const HIDDEN_CLASS = 'is-hidden';
  const DISABLED_CLASS = 'is-disabled';

  const elements = {
    form: document.getElementById('verifyForm'),
    steps: [document.getElementById('step1'), document.getElementById('step2'), document.getElementById('step3')],
    stepIndicatorLabel: document.getElementById('stepIndicatorLabel'),
    stepTitle: document.getElementById('stepTitle'),
    progressBar: document.getElementById('progressBar'),
    headerStatusIcon: document.getElementById('headerStatusIcon'),
    cameraVideo: document.getElementById('cameraVideo'),
    playbackVideo: document.getElementById('playbackVideo'),
    playbackOverlay: document.getElementById('playbackOverlay'),
    playbackIcon: document.getElementById('playbackIcon'),
    cameraPlaceholder: document.getElementById('cameraPlaceholder'),
    recordingOverlay: document.getElementById('recordingOverlay'),
    recordingTimer: document.getElementById('recordingTimer'),
    recordingMinIndicator: document.getElementById('recordingMinIndicator'),
    recordingBarContainer: document.getElementById('recordingBarContainer'),
    recordingProgressBar: document.getElementById('recordingProgressBar'),
    cameraControls: document.getElementById('cameraControls'),
    liveControls: document.getElementById('liveControls'),
    btnRecordToggle: document.getElementById('btnRecordToggle'),
    recordToggleIcon: document.getElementById('recordToggleIcon'),
    recordToggleText: document.getElementById('recordToggleText'),
    previewControls: document.getElementById('previewControls'),
    btnNextToStep3: document.getElementById('btnNextToStep3'),
    submitVerificationBtn: document.getElementById('submitVerificationBtn'),
    verificationConsent: document.getElementById('verificationConsent'),
    verificationNote: document.getElementById('verificationNote'),
    charCounter: document.getElementById('charCounter'),
    livenessPhraseDisplay: document.getElementById('livenessPhraseDisplay'),
    toastContainer: document.getElementById('toastContainer'),
    toastIcon: document.getElementById('toastIcon'),
    toastMessage: document.getElementById('toastMessage'),
    sendingState: document.getElementById('sendingState'),
    successState: document.getElementById('successState')
  };

  if (!elements.form) return;

  const state = {
    currentStep: 1,
    mediaStream: null,
    mediaRecorder: null,
    recordedBlobs: [],
    isRecording: false,
    timerInterval: null,
    elapsedSeconds: 0,
    finalEvidenceBlob: null,
    evidenceObjectUrl: '',
    evidenceMimeType: 'video/webm',
    isSubmitting: false
  };

  const stepTitles = {
    1: 'Bienvenida y Beneficios',
    2: 'Evidencia Visual',
    3: 'Pasos Finales'
  };

  const stepIcons = {
    1: '<i class="fas fa-user-shield"></i>',
    2: '<i class="fas fa-camera"></i>',
    3: '<i class="fas fa-circle-check"></i>'
  };

  function setHidden(element, hidden) {
    if (!element) return;
    element.classList.toggle(HIDDEN_CLASS, hidden);
  }

  function setButtonEnabled(button, enabled) {
    if (!button) return;
    button.disabled = !enabled;
    button.classList.toggle(DISABLED_CLASS, !enabled);
  }

  function assignRandomPhrase() {
    const randomIndex = Math.floor(Math.random() * livenessPhrases.length);
    elements.livenessPhraseDisplay.textContent = `"${livenessPhrases[randomIndex]}"`;
  }

  function goToStep(stepNumber) {
    if (state.currentStep === 2 && stepNumber !== 2 && !state.finalEvidenceBlob) {
      stopCamera();
    }

    elements.steps.forEach((step, index) => {
      setHidden(step, index + 1 !== stepNumber);
    });

    state.currentStep = stepNumber;
    elements.stepIndicatorLabel.textContent = `Paso ${stepNumber} de 3`;
    elements.stepTitle.textContent = stepTitles[stepNumber];
    elements.progressBar.style.width = `${(stepNumber / 3) * 100}%`;
    elements.headerStatusIcon.innerHTML = stepIcons[stepNumber];

    if (stepNumber === 2 && !state.mediaStream && !state.finalEvidenceBlob) {
      initiateCamera();
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function getRecorderOptions() {
    const preferredTypes = [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
      'video/mp4;codecs=h264',
      'video/mp4'
    ];

    for (const mimeType of preferredTypes) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(mimeType)) {
        return { mimeType };
      }
    }
    return {};
  }

  function filenameForMimeType(mimeType) {
    if (mimeType.includes('mp4')) return 'video_verificacion.mp4';
    if (mimeType.includes('quicktime')) return 'video_verificacion.mov';
    return 'video_verificacion.webm';
  }

  async function initiateCamera() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      showToast('Tu dispositivo no permite grabar desde esta pantalla.', 'error');
      return;
    }

    try {
      setHidden(elements.cameraPlaceholder, true);
      setHidden(elements.cameraVideo, false);
      setHidden(elements.cameraControls, false);
      setHidden(elements.playbackVideo, true);
      setHidden(elements.playbackOverlay, true);

      try {
        state.mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user' },
          audio: true
        });
      } catch (audioError) {
        state.mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user' },
          audio: false
        });
      }

      elements.cameraVideo.srcObject = state.mediaStream;
      await elements.cameraVideo.play();
      showLiveControls();
      showToast('Cámara activa. Prepárate para leer tu frase.', 'info');
    } catch (error) {
      stopCamera();
      setHidden(elements.cameraPlaceholder, false);
      setHidden(elements.cameraVideo, true);
      setHidden(elements.cameraControls, true);
      showToast('No pudimos acceder a tu cámara. Verifica los permisos del navegador.', 'error');
    }
  }

  function stopCamera() {
    if (state.mediaStream) {
      state.mediaStream.getTracks().forEach((track) => track.stop());
      state.mediaStream = null;
    }
    if (elements.cameraVideo) {
      elements.cameraVideo.srcObject = null;
    }
  }

  function startVideoRecording() {
    if (!state.mediaStream || state.isRecording) return;

    state.recordedBlobs = [];
    state.isRecording = true;
    state.elapsedSeconds = 0;

    setHidden(elements.recordingOverlay, false);
    setHidden(elements.recordingBarContainer, false);
    setHidden(elements.recordingMinIndicator, false);
    setButtonEnabled(elements.btnNextToStep3, false);
    updateRecordingUI();

    const recorderOptions = getRecorderOptions();

    try {
      state.mediaRecorder = new MediaRecorder(state.mediaStream, recorderOptions);
      state.evidenceMimeType = state.mediaRecorder.mimeType || recorderOptions.mimeType || 'video/webm';
    } catch (error) {
      state.isRecording = false;
      setHidden(elements.recordingOverlay, true);
      setHidden(elements.recordingBarContainer, true);
      showToast('No se pudo iniciar la grabación en este dispositivo.', 'error');
      return;
    }

    state.mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        state.recordedBlobs.push(event.data);
      }
    };

    state.mediaRecorder.onstop = () => {
      state.finalEvidenceBlob = new Blob(state.recordedBlobs, { type: state.evidenceMimeType });
      if (state.evidenceObjectUrl) {
        window.URL.revokeObjectURL(state.evidenceObjectUrl);
      }
      state.evidenceObjectUrl = window.URL.createObjectURL(state.finalEvidenceBlob);
      elements.playbackVideo.src = state.evidenceObjectUrl;
      setHidden(elements.cameraVideo, true);
      setHidden(elements.playbackVideo, false);
      setHidden(elements.playbackOverlay, false);
      elements.playbackOverlay.classList.remove('is-playing');
      showPreviewControls();
      stopCamera();
      validateEvidenceStatus();
    };

    state.mediaRecorder.start();
    const startTime = Date.now();
    state.timerInterval = setInterval(() => {
      state.elapsedSeconds = (Date.now() - startTime) / 1000;
      updateRecordingUI();
      if (state.elapsedSeconds >= MAX_RECORDING_SECONDS) {
        stopVideoRecording();
      }
    }, 100);
  }

  function updateRecordingUI() {
    const minutes = Math.floor(state.elapsedSeconds / 60);
    const seconds = Math.floor(state.elapsedSeconds % 60);
    elements.recordingTimer.textContent = `${minutes}:${seconds < 10 ? '0' : ''}${seconds} / 1:00`;
    elements.recordingProgressBar.style.width = `${Math.min(100, (state.elapsedSeconds / MAX_RECORDING_SECONDS) * 100)}%`;

    if (state.elapsedSeconds < MIN_RECORDING_SECONDS) {
      setButtonEnabled(elements.btnRecordToggle, false);
      elements.btnRecordToggle.classList.add('verification-button--record-waiting');
      elements.recordToggleIcon.className = 'fas fa-spinner fa-spin';
      elements.recordToggleText.textContent = 'Grabando... (Mínimo 5s)';
      setHidden(elements.recordingMinIndicator, false);
      return;
    }

    setButtonEnabled(elements.btnRecordToggle, true);
    elements.btnRecordToggle.classList.remove('verification-button--record-waiting');
    elements.recordToggleIcon.className = 'fas fa-square';
    elements.recordToggleText.textContent = 'Detener Grabación';
    setHidden(elements.recordingMinIndicator, true);
  }

  function stopVideoRecording() {
    if (!state.isRecording) return;
    clearInterval(state.timerInterval);
    state.timerInterval = null;
    state.isRecording = false;
    setHidden(elements.recordingOverlay, true);
    setHidden(elements.recordingBarContainer, true);
    if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
      state.mediaRecorder.stop();
    }
  }

  function handleRecordToggle() {
    if (!state.isRecording) {
      startVideoRecording();
      return;
    }

    if (state.elapsedSeconds >= MIN_RECORDING_SECONDS) {
      stopVideoRecording();
    }
  }

  function togglePlayback() {
    if (elements.playbackVideo.paused) {
      elements.playbackVideo.play();
      elements.playbackIcon.className = 'fas fa-pause';
      elements.playbackOverlay.classList.add('is-playing');
      return;
    }

    elements.playbackVideo.pause();
    elements.playbackIcon.className = 'fas fa-play';
    elements.playbackOverlay.classList.remove('is-playing');
  }

  function resetCapture() {
    elements.playbackVideo.pause();
    elements.playbackVideo.removeAttribute('src');
    elements.playbackVideo.load();
    if (state.evidenceObjectUrl) {
      window.URL.revokeObjectURL(state.evidenceObjectUrl);
    }
    state.evidenceObjectUrl = '';
    state.finalEvidenceBlob = null;
    setHidden(elements.playbackVideo, true);
    setHidden(elements.playbackOverlay, true);
    setHidden(elements.cameraVideo, false);
    showLiveControls();
    validateEvidenceStatus();
    if (!state.mediaStream) {
      initiateCamera();
    }
  }

  function showLiveControls() {
    setHidden(elements.liveControls, false);
    setHidden(elements.previewControls, true);
    setButtonEnabled(elements.btnRecordToggle, true);
    elements.btnRecordToggle.classList.remove('verification-button--record-waiting');
    elements.recordToggleIcon.className = 'fas fa-circle';
    elements.recordToggleText.textContent = 'Iniciar Grabación';
  }

  function showPreviewControls() {
    setHidden(elements.liveControls, true);
    setHidden(elements.previewControls, false);
  }

  function validateEvidenceStatus() {
    setButtonEnabled(elements.btnNextToStep3, Boolean(state.finalEvidenceBlob && state.finalEvidenceBlob.size > 0));
  }

  function validateStep2AndProceed() {
    if (!state.finalEvidenceBlob || state.finalEvidenceBlob.size <= 0) {
      showToast('Por favor graba tu video antes de continuar.', 'error');
      return;
    }

    if (state.finalEvidenceBlob.size > MAX_VIDEO_BYTES) {
      showToast('El video es demasiado grande. El máximo permitido es 40 MB.', 'error');
      return;
    }

    goToStep(3);
  }

  function updateCharCounter() {
    elements.charCounter.textContent = `${elements.verificationNote.value.length}/1200`;
  }

  function updateConsentState() {
    setButtonEnabled(elements.submitVerificationBtn, elements.verificationConsent.checked);
  }

  function showToast(message, type = 'info') {
    elements.toastContainer.classList.remove('verification-toast--error', 'verification-toast--success');
    if (type === 'error') {
      elements.toastContainer.classList.add('verification-toast--error');
      elements.toastIcon.innerHTML = '<i class="fas fa-circle-exclamation"></i>';
    } else if (type === 'success') {
      elements.toastContainer.classList.add('verification-toast--success');
      elements.toastIcon.innerHTML = '<i class="fas fa-circle-check"></i>';
    } else {
      elements.toastIcon.innerHTML = '<i class="fas fa-info-circle"></i>';
    }
    elements.toastMessage.textContent = message;
    setHidden(elements.toastContainer, false);
    window.clearTimeout(showToast.hideTimer);
    showToast.hideTimer = window.setTimeout(closeToast, 5000);
  }

  function closeToast() {
    setHidden(elements.toastContainer, true);
  }

  async function handleFormSubmit(event) {
    event.preventDefault();
    if (state.isSubmitting) return;

    if (!elements.verificationConsent.checked) {
      showToast('Es necesario que aceptes el consentimiento de privacidad.', 'error');
      return;
    }

    if (!state.finalEvidenceBlob || state.finalEvidenceBlob.size <= 0) {
      showToast('El video de verificación es requerido. Regresa e inicia la grabación.', 'error');
      goToStep(2);
      return;
    }

    if (state.finalEvidenceBlob.size > MAX_VIDEO_BYTES) {
      showToast('El video es demasiado grande. El máximo permitido es 40 MB.', 'error');
      return;
    }

    state.isSubmitting = true;
    setButtonEnabled(elements.submitVerificationBtn, false);
    setHidden(document.getElementById('step3'), true);
    setHidden(elements.sendingState, false);
    elements.stepIndicatorLabel.textContent = 'Procesando...';
    elements.stepTitle.textContent = 'Subiendo evidencia';

    const formData = new FormData();
    formData.append('evidence', state.finalEvidenceBlob, filenameForMimeType(state.evidenceMimeType));
    formData.append('note', elements.verificationNote.value);
    formData.append('consent_accepted', 'on');
    formData.append('capture_source', 'app_camera');

    try {
      const response = await fetch(page.dataset.submitUrl || '/api/verify/submit', {
        method: 'POST',
        headers: {
          'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
        },
        body: formData
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'No pudimos enviar la solicitud.');
      }

      setHidden(elements.sendingState, true);
      setHidden(elements.successState, false);
      elements.progressBar.style.width = '100%';
      elements.stepIndicatorLabel.textContent = 'Completado';
      elements.stepTitle.textContent = 'Verificación enviada';
      showToast(data.message || 'Tu solicitud ha sido enviada.', 'success');
    } catch (error) {
      state.isSubmitting = false;
      setHidden(elements.sendingState, true);
      setHidden(document.getElementById('step3'), false);
      updateConsentState();
      showToast(error.message || 'No pudimos enviar tu solicitud.', 'error');
    }
  }

  function bindEvents() {
    document.querySelectorAll('[data-step-target]').forEach((button) => {
      button.addEventListener('click', () => goToStep(Number(button.dataset.stepTarget)));
    });
    document.querySelector('[data-camera-start]')?.addEventListener('click', initiateCamera);
    document.querySelector('[data-record-toggle]')?.addEventListener('click', handleRecordToggle);
    document.querySelector('[data-reset-capture]')?.addEventListener('click', resetCapture);
    document.querySelector('[data-next-final]')?.addEventListener('click', validateStep2AndProceed);
    document.querySelector('[data-playback-toggle]')?.addEventListener('click', togglePlayback);
    document.querySelector('[data-close-toast]')?.addEventListener('click', closeToast);
    elements.verificationNote.addEventListener('input', updateCharCounter);
    elements.verificationConsent.addEventListener('change', updateConsentState);
    elements.form.addEventListener('submit', handleFormSubmit);
    elements.playbackVideo.addEventListener('ended', () => {
      elements.playbackIcon.className = 'fas fa-play';
      elements.playbackOverlay.classList.remove('is-playing');
    });
    window.addEventListener('pagehide', stopCamera);
    window.addEventListener('beforeunload', stopCamera);
  }

  assignRandomPhrase();
  updateCharCounter();
  updateConsentState();
  bindEvents();
})();
