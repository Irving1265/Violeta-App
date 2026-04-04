(function () {
    const config = window.DEFERRED_PAGE_CONFIG || null;
    if (!config) {
        return;
    }

    const scriptPromises = new Map();

    function getById(id) {
        return id ? document.getElementById(id) : null;
    }

    function ensureScript(src) {
        if (!src) {
            return Promise.resolve();
        }

        if (scriptPromises.has(src)) {
            return scriptPromises.get(src);
        }

        const existing = document.querySelector(`script[data-deferred-src="${src}"]`);
        if (existing) {
            const ready = Promise.resolve();
            scriptPromises.set(src, ready);
            return ready;
        }

        const promise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.defer = true;
            script.dataset.deferredSrc = src;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error(`No se pudo cargar ${src}`));
            document.body.appendChild(script);
        });

        scriptPromises.set(src, promise);
        return promise;
    }

    function getFragments() {
        if (Array.isArray(config.fragments) && config.fragments.length) {
            return config.fragments.filter((fragment) => fragment && fragment.mountId && fragment.contentUrl);
        }

        if (!config.contentUrl) {
            return [];
        }

        return [{
            mountId: config.mountId || 'deferredPageMount',
            skeletonId: config.skeletonId || 'deferredPageSkeleton',
            contentUrl: config.contentUrl,
        }];
    }

    function mountHasContent(mount) {
        return Boolean(mount && String(mount.innerHTML || '').trim());
    }

    async function loadFragment(fragmentConfig) {
        const mount = getById(fragmentConfig.mountId);
        const skeleton = getById(fragmentConfig.skeletonId);

        if (!mount) {
            return null;
        }

        if (mountHasContent(mount)) {
            mount.hidden = false;
            mount.setAttribute('aria-busy', 'false');
            if (skeleton) {
                skeleton.hidden = true;
            }
            return mount;
        }

        mount.setAttribute('aria-busy', 'true');

        const response = await fetch(fragmentConfig.contentUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                Accept: 'text/html',
                'X-Requested-With': 'XMLHttpRequest',
            },
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const html = await response.text();
        mount.innerHTML = html;
        mount.hidden = false;
        mount.setAttribute('aria-busy', 'false');

        if (skeleton) {
            skeleton.hidden = true;
        }

        return mount;
    }

    async function loadDeferredContent() {
        const fragments = getFragments();
        const errorBox = getById(config.errorId || 'deferredPageError');

        if (!fragments.length) {
            return;
        }

        if (errorBox) {
            errorBox.hidden = true;
        }

        const results = await Promise.allSettled(
            fragments.map(async (fragment) => loadFragment(fragment)),
        );

        const successfulMounts = [];
        let hasFailures = false;

        results.forEach((result, index) => {
            const fragment = fragments[index];
            const mount = getById(fragment.mountId);
            const skeleton = getById(fragment.skeletonId);

            if (result.status === 'fulfilled') {
                if (result.value) {
                    successfulMounts.push(result.value);
                }
                return;
            }

            hasFailures = true;
            console.error('deferred page load error:', result.reason);
            if (mount) {
                mount.hidden = true;
                mount.setAttribute('aria-busy', 'false');
            }
            if (skeleton) {
                skeleton.hidden = true;
            }
        });

        if (!successfulMounts.length) {
            if (errorBox) {
                errorBox.hidden = false;
            }
            return;
        }

        if (errorBox) {
            errorBox.hidden = !hasFailures;
        }

        const scripts = Array.isArray(config.scriptSrcs)
            ? config.scriptSrcs.filter(Boolean)
            : (config.scriptSrc ? [config.scriptSrc] : []);

        for (const src of scripts) {
            await ensureScript(src);
        }

        if (config.initFn && typeof window[config.initFn] === 'function') {
            window[config.initFn](
                successfulMounts.length === 1 ? successfulMounts[0] : successfulMounts,
            );
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadDeferredContent, { once: true });
    } else {
        loadDeferredContent();
    }

    window.addEventListener('pageshow', () => {
        loadDeferredContent().catch((error) => {
            console.error('deferred page reload error:', error);
        });
    });
})();
