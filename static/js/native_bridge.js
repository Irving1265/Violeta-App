(function () {
    function getCapacitor() {
        return window.Capacitor || null;
    }

    function isNativePlatform() {
        const capacitor = getCapacitor();
        if (!capacitor) {
            return false;
        }
        try {
            if (typeof capacitor.isNativePlatform === 'function') {
                return !!capacitor.isNativePlatform();
            }
        } catch (error) {
            console.warn('Capacitor native platform check failed:', error);
        }
        try {
            if (typeof capacitor.getPlatform === 'function') {
                const platform = capacitor.getPlatform();
                return platform === 'ios' || platform === 'android';
            }
        } catch (error) {
            console.warn('Capacitor getPlatform failed:', error);
        }
        return false;
    }

    function getPlugin(name) {
        return getCapacitor()?.Plugins?.[name] || null;
    }

    function isMobileViewport() {
        return window.matchMedia?.('(max-width: 992px), (hover: none) and (pointer: coarse)')?.matches || false;
    }

    function removeLoginMapOnMobile() {
        if (!isNativePlatform() && !isMobileViewport()) {
            return;
        }
        document.querySelectorAll('.login-map-section, #loginMapTemplate').forEach((node) => node.remove());
        document.querySelectorAll('#loginMap').forEach((node) => node.remove());
    }

    removeLoginMapOnMobile();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', removeLoginMapOnMobile, { once: true });
    } else {
        removeLoginMapOnMobile();
    }

    function dataUrlToFile(dataUrl, filename) {
        const parts = String(dataUrl || '').split(',');
        if (parts.length < 2) {
            throw new Error('Invalid data URL returned by native camera.');
        }
        const match = /^data:(.*?);base64$/i.exec(parts[0]);
        const mimeType = match?.[1] || 'image/jpeg';
        const binary = atob(parts[1]);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }
        return new File([bytes], filename, { type: mimeType });
    }

    async function requestCameraPermissions(cameraPlugin) {
        if (!cameraPlugin || typeof cameraPlugin.requestPermissions !== 'function') {
            return;
        }
        try {
            await cameraPlugin.requestPermissions({ permissions: ['camera'] });
        } catch (error) {
            console.warn('Native camera permission request failed:', error);
        }
    }

    async function requestLocationPermissions(geoPlugin) {
        if (!geoPlugin || typeof geoPlugin.requestPermissions !== 'function') {
            return;
        }
        try {
            await geoPlugin.requestPermissions({ permissions: ['location'] });
        } catch (error) {
            console.warn('Native location permission request failed:', error);
        }
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

    async function capturePhoto(options = {}) {
        const cameraPlugin = getPlugin('Camera');
        if (!isNativePlatform() || !cameraPlugin || typeof cameraPlugin.getPhoto !== 'function') {
            return null;
        }

        await requestCameraPermissions(cameraPlugin);

        const dataUrl = getCapacitor()?.CameraResultType?.DataUrl || 'dataUrl';
        const sourceCamera = getCapacitor()?.CameraSource?.Camera || 'CAMERA';
        const requestedFacingMode = normalizeCameraFacingMode(options.facingMode) || 'environment';
        const cameraDirections = getCapacitor()?.CameraDirection || {};
        const requestedDirection = requestedFacingMode === 'user'
            ? (cameraDirections.Front || 'FRONT')
            : (cameraDirections.Rear || 'REAR');
        const quality = Number.isFinite(options.quality) ? options.quality : 92;
        const filenamePrefix = (options.filenamePrefix || 'captura').replace(/[^a-z0-9_-]/gi, '') || 'captura';

        const photo = await cameraPlugin.getPhoto({
            allowEditing: false,
            correctOrientation: true,
            quality,
            resultType: dataUrl,
            saveToGallery: false,
            source: sourceCamera,
            direction: requestedDirection,
            presentationStyle: 'fullscreen',
        });

        if (!photo || !photo.dataUrl) {
            throw new Error('Native camera did not return image data.');
        }

        const file = dataUrlToFile(photo.dataUrl, `${filenamePrefix}-${Date.now()}.jpg`);
        return {
            file,
            dataUrl: photo.dataUrl,
            format: photo.format || 'jpeg',
            source: 'native-camera',
            facingMode: requestedFacingMode,
            mirrorPreview: false,
        };
    }

    async function getCurrentPosition(options = {}) {
        const geoPlugin = getPlugin('Geolocation');
        if (isNativePlatform() && geoPlugin && typeof geoPlugin.getCurrentPosition === 'function') {
            await requestLocationPermissions(geoPlugin);
            const nativePosition = await geoPlugin.getCurrentPosition({
                enableHighAccuracy: options.enableHighAccuracy !== false,
                timeout: options.timeout ?? 10000,
                maximumAge: options.maximumAge ?? 300000,
            });
            return {
                lat: nativePosition.coords.latitude,
                lng: nativePosition.coords.longitude,
                accuracy: nativePosition.coords.accuracy || null,
                timestamp: nativePosition.timestamp || Date.now(),
                raw: nativePosition,
                source: 'native',
            };
        }

        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error('Geolocation is unavailable.'));
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => resolve({
                    lat: position.coords.latitude,
                    lng: position.coords.longitude,
                    accuracy: position.coords.accuracy || null,
                    timestamp: position.timestamp || Date.now(),
                    raw: position,
                    source: 'browser',
                }),
                (error) => reject(error),
                {
                    enableHighAccuracy: options.enableHighAccuracy !== false,
                    timeout: options.timeout ?? 10000,
                    maximumAge: options.maximumAge ?? 300000,
                }
            );
        });
    }

    async function watchPosition(options = {}, onSuccess, onError) {
        const geoPlugin = getPlugin('Geolocation');
        if (isNativePlatform() && geoPlugin && typeof geoPlugin.watchPosition === 'function') {
            await requestLocationPermissions(geoPlugin);
            const watchId = await geoPlugin.watchPosition({
                enableHighAccuracy: options.enableHighAccuracy !== false,
                timeout: options.timeout ?? 10000,
                maximumAge: options.maximumAge ?? 300000,
            }, (nativePosition, error) => {
                if (error) {
                    if (typeof onError === 'function') onError(error);
                    return;
                }
                if (!nativePosition?.coords) return;
                if (typeof onSuccess === 'function') {
                    onSuccess({
                        lat: nativePosition.coords.latitude,
                        lng: nativePosition.coords.longitude,
                        accuracy: nativePosition.coords.accuracy || null,
                        timestamp: nativePosition.timestamp || Date.now(),
                        speed: nativePosition.coords.speed ?? null,
                        raw: nativePosition,
                        source: 'native',
                    });
                }
            });
            return { id: watchId, source: 'native' };
        }

        if (!navigator.geolocation) {
            throw new Error('Geolocation is unavailable.');
        }

        const watchId = navigator.geolocation.watchPosition(
            (position) => {
                if (typeof onSuccess === 'function') {
                    onSuccess({
                        lat: position.coords.latitude,
                        lng: position.coords.longitude,
                        accuracy: position.coords.accuracy || null,
                        timestamp: position.timestamp || Date.now(),
                        speed: position.coords.speed ?? null,
                        raw: position,
                        source: 'browser',
                    });
                }
            },
            (error) => {
                if (typeof onError === 'function') onError(error);
            },
            {
                enableHighAccuracy: options.enableHighAccuracy !== false,
                timeout: options.timeout ?? 10000,
                maximumAge: options.maximumAge ?? 300000,
            }
        );

        return { id: watchId, source: 'browser' };
    }

    async function clearPositionWatch(handle) {
        if (!handle || handle.id == null) {
            return;
        }
        if (handle.source === 'native') {
            const geoPlugin = getPlugin('Geolocation');
            if (geoPlugin && typeof geoPlugin.clearWatch === 'function') {
                try {
                    await geoPlugin.clearWatch({ id: handle.id });
                } catch (error) {
                    console.warn('Native geolocation clearWatch failed:', error);
                }
            }
            return;
        }
        if (navigator.geolocation && typeof navigator.geolocation.clearWatch === 'function') {
            navigator.geolocation.clearWatch(handle.id);
        }
    }

    window.VioletaNativeBridge = {
        getCapacitor,
        getPlugin,
        isNativePlatform,
        capturePhoto,
        getCurrentPosition,
        watchPosition,
        clearPositionWatch,
        removeLoginMapOnMobile,
    };
})();
