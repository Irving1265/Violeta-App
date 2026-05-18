import 'dotenv/config';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const args = new Set(process.argv.slice(2));
const strict = args.has('--strict');
const issues = [];

function addIssue(level, code, message) {
  issues.push({ level, code, message });
}

function requireFile(file, message) {
  if (!existsSync(resolve(process.cwd(), file))) {
    addIssue('error', `missing_${file.replaceAll('/', '_')}`, message || `Falta ${file}.`);
    return false;
  }
  return true;
}

function readText(file) {
  try {
    return readFileSync(resolve(process.cwd(), file), 'utf8');
  } catch {
    return '';
  }
}

function fileExists(file) {
  return existsSync(resolve(process.cwd(), file));
}

function readPngSize(file) {
  try {
    const buffer = readFileSync(resolve(process.cwd(), file));
    const isPng = buffer.length >= 24
      && buffer[0] === 0x89
      && buffer[1] === 0x50
      && buffer[2] === 0x4e
      && buffer[3] === 0x47;
    if (!isPng) {
      return null;
    }
    return {
      width: buffer.readUInt32BE(16),
      height: buffer.readUInt32BE(20),
      bytes: statSync(resolve(process.cwd(), file)).size,
    };
  } catch {
    return null;
  }
}

function requirePngSize(file, width, height, label) {
  const size = readPngSize(file);
  if (!size) {
    addIssue('error', `missing_${label}`, `Falta o no es PNG valido: ${file}.`);
    return;
  }
  if (size.width !== width || size.height !== height) {
    addIssue('error', `invalid_${label}`, `${file} debe medir ${width}x${height}px; mide ${size.width}x${size.height}px.`);
  }
}

function parseUrl(name, value, { required = false } = {}) {
  const raw = value?.trim();
  if (!raw) {
    if (required) {
      addIssue(strict ? 'error' : 'warning', `missing_${name.toLowerCase()}`, `${name} no esta configurado.`);
    }
    return null;
  }

  try {
    const url = new URL(raw);
    const normalized = url.toString().replace(/\/$/, '');
    if (url.protocol !== 'https:') {
      addIssue('error', `invalid_${name.toLowerCase()}_scheme`, `${name} debe usar HTTPS para tiendas moviles.`);
    }
    if (/example\.com|tu-backend|tu-dominio/i.test(normalized)) {
      addIssue('error', `placeholder_${name.toLowerCase()}`, `${name} todavia usa un valor placeholder.`);
    }
    return normalized;
  } catch {
    addIssue('error', `invalid_${name.toLowerCase()}`, `${name} no es una URL valida.`);
    return null;
  }
}

async function checkPublicPage(label, url) {
  if (!url) {
    return;
  }

  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: { Accept: 'text/html,application/xhtml+xml' },
    });
    if (!response.ok) {
      addIssue(strict ? 'error' : 'warning', `${label}_url_http_error`, `${url} respondio HTTP ${response.status}.`);
      return;
    }
    const html = await response.text().catch(() => '');
    if (!/Violeta/i.test(html)) {
      addIssue('warning', `${label}_url_missing_app_name`, `${url} no parece mencionar Violeta en el contenido.`);
    }
  } catch {
    addIssue(strict ? 'error' : 'warning', `${label}_url_unreachable`, `No se pudo abrir ${url}.`);
  }
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function checkHealth(serverUrl) {
  if (!serverUrl) {
    return;
  }

  const healthUrl = new URL('/healthz', serverUrl).toString();
  const timeoutMs = parsePositiveInt(process.env.MOBILE_HEALTH_TIMEOUT_MS, 15000);
  const maxAttempts = parsePositiveInt(process.env.MOBILE_HEALTH_RETRIES, 3);
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(healthUrl, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });

      if (!response.ok) {
        addIssue('error', 'backend_health_http_error', `/healthz respondio HTTP ${response.status}.`);
        return;
      }

      const payload = await response.json().catch(() => null);
      if (!payload || payload.status !== 'ok') {
        addIssue(strict ? 'error' : 'warning', 'backend_health_degraded', '/healthz no esta en status ok.');
      }
      return;
    } catch (error) {
      lastError = error;
      if (attempt < maxAttempts) {
        await sleep(1000 * attempt);
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  addIssue(
    strict ? 'error' : 'warning',
    'backend_health_unreachable',
    `No se pudo validar /healthz despues de ${maxAttempts} intento(s) (${lastError?.name === 'AbortError' ? 'timeout' : 'error de red'}).`
  );
}

function checkStoreMetadata() {
  const capacitorConfig = readText('capacitor.config.ts');
  if (!capacitorConfig.includes("appId: 'com.violeta.app'")) {
    addIssue('error', 'invalid_capacitor_app_id', 'capacitor.config.ts debe usar appId com.violeta.app.');
  }
  if (!capacitorConfig.includes("appName: 'Violeta'")) {
    addIssue('error', 'invalid_capacitor_app_name', 'capacitor.config.ts debe usar appName Violeta.');
  }

  const androidStrings = readText('android/app/src/main/res/values/strings.xml');
  if (!androidStrings.includes('<string name="app_name">Violeta</string>')) {
    addIssue('error', 'invalid_android_app_name', 'Android debe mostrar Violeta como nombre de app.');
  }

  const infoPlist = readText('ios/App/App/Info.plist');
  if (!infoPlist.includes('<key>CFBundleDisplayName</key>') || !infoPlist.includes('<string>Violeta</string>')) {
    addIssue('error', 'invalid_ios_display_name', 'iOS debe mostrar Violeta como CFBundleDisplayName.');
  }
}

function checkNativeAssets() {
  requirePngSize(
    'ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png',
    1024,
    1024,
    'ios_app_icon',
  );

  [
    'ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732.png',
    'ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732-1.png',
    'ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732-2.png',
  ].forEach((file, index) => requirePngSize(file, 2732, 2732, `ios_splash_${index + 1}`));

  const androidLauncherSizes = {
    mdpi: 48,
    hdpi: 72,
    xhdpi: 96,
    xxhdpi: 144,
    xxxhdpi: 192,
  };
  for (const [density, size] of Object.entries(androidLauncherSizes)) {
    requirePngSize(`android/app/src/main/res/mipmap-${density}/ic_launcher.png`, size, size, `android_icon_${density}`);
    requirePngSize(`android/app/src/main/res/mipmap-${density}/ic_launcher_round.png`, size, size, `android_round_icon_${density}`);
  }

  [
    'android/app/src/main/res/drawable/splash.png',
    'android/app/src/main/res/drawable-port-xxxhdpi/splash.png',
    'android/app/src/main/res/drawable-land-xxxhdpi/splash.png',
  ].forEach((file, index) => {
    if (!fileExists(file)) {
      addIssue('error', `missing_android_splash_${index + 1}`, `Falta ${file}.`);
    }
  });
}

function checkSyncedNativeConfig(serverUrl) {
  const files = [
    'ios/App/App/capacitor.config.json',
    'android/app/src/main/assets/capacitor.config.json',
  ];

  for (const file of files) {
    if (!existsSync(resolve(process.cwd(), file))) {
      addIssue('warning', `missing_native_config_${file.replaceAll('/', '_')}`, `Falta ${file}; ejecuta npm run cap:sync.`);
      continue;
    }

    const raw = readText(file);
    let config;
    try {
      config = JSON.parse(raw);
    } catch {
      addIssue('error', `invalid_native_config_${file.replaceAll('/', '_')}`, `${file} no contiene JSON valido.`);
      continue;
    }

    const configuredUrl = config?.server?.url ? String(config.server.url).replace(/\/$/, '') : null;
    if (serverUrl && configuredUrl !== serverUrl) {
      addIssue('warning', `stale_native_config_${file.replaceAll('/', '_')}`, `${file} no apunta a MOBILE_WEB_URL; ejecuta npm run cap:sync.`);
    }
  }
}

function checkNativePermissions() {
  const androidManifest = readText('android/app/src/main/AndroidManifest.xml');
  const androidPermissions = [
    'android.permission.INTERNET',
    'android.permission.CAMERA',
    'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.ACCESS_FINE_LOCATION',
    'android.permission.POST_NOTIFICATIONS',
  ];

  for (const permission of androidPermissions) {
    if (!androidManifest.includes(permission)) {
      addIssue('warning', `missing_android_${permission.split('.').pop().toLowerCase()}`, `Android no declara ${permission}.`);
    }
  }

  const infoPlist = readText('ios/App/App/Info.plist');
  const iosPrivacyKeys = [
    'NSCameraUsageDescription',
    'NSLocationWhenInUseUsageDescription',
    'NSPhotoLibraryUsageDescription',
    'NSUserNotificationsUsageDescription',
  ];

  for (const key of iosPrivacyKeys) {
    if (!infoPlist.includes(key)) {
      addIssue('warning', `missing_ios_${key.toLowerCase()}`, `iOS no declara ${key}.`);
    }
  }
}

function checkReleaseSigning() {
  const androidKeystore = fileExists('android/keystore.properties');
  const androidEnvSigning = [
    'ANDROID_KEYSTORE_PATH',
    'ANDROID_KEYSTORE_PASSWORD',
    'ANDROID_KEY_ALIAS',
    'ANDROID_KEY_PASSWORD',
  ].every((name) => Boolean(process.env[name]?.trim()));
  const androidStorePath = process.env.ANDROID_KEYSTORE_PATH?.trim();
  if (androidStorePath && !existsSync(resolve(process.cwd(), androidStorePath))) {
    addIssue(strict ? 'error' : 'warning', 'missing_android_keystore_file', `ANDROID_KEYSTORE_PATH apunta a ${androidStorePath}, pero el archivo no existe.`);
  }
  if (!androidKeystore && !androidEnvSigning) {
    addIssue(
      strict ? 'error' : 'warning',
      'android_release_signing_missing',
      'Falta signing de Android: crea android/keystore.properties o define ANDROID_KEYSTORE_* antes de generar bundleRelease.',
    );
  }

  const xcodeProject = readText('ios/App/App.xcodeproj/project.pbxproj');
  const hasDevelopmentTeam = /DEVELOPMENT_TEAM = [A-Z0-9]+;/.test(xcodeProject) || Boolean(process.env.IOS_DEVELOPMENT_TEAM?.trim());
  if (!hasDevelopmentTeam) {
    addIssue(
      strict ? 'error' : 'warning',
      'ios_development_team_missing',
      'Falta Team ID de Apple Developer para archivar y subir a TestFlight.',
    );
  }
}

const required = ['package.json', 'capacitor.config.ts', 'www/index.html'];
required.forEach((file) => requireFile(file, `Falta archivo base del scaffold: ${file}.`));

const url = process.env.MOBILE_WEB_URL?.trim();
const serverUrl = parseUrl('MOBILE_WEB_URL', url, { required: true });
const privacyUrl = parseUrl('STORE_PRIVACY_POLICY_URL', process.env.STORE_PRIVACY_POLICY_URL, { required: strict });
const deletionUrl = parseUrl('STORE_ACCOUNT_DELETION_URL', process.env.STORE_ACCOUNT_DELETION_URL, { required: strict });

checkSyncedNativeConfig(serverUrl);
checkNativePermissions();
checkStoreMetadata();
checkNativeAssets();
checkReleaseSigning();
await checkHealth(serverUrl);
await checkPublicPage('privacy_policy', privacyUrl);
await checkPublicPage('account_deletion', deletionUrl);

const hasIos = existsSync(resolve(process.cwd(), 'ios'));
const hasAndroid = existsSync(resolve(process.cwd(), 'android'));
if (!hasIos) {
  addIssue('warning', 'missing_ios_project', 'Falta carpeta ios; ejecuta npm run cap:add:ios.');
}
if (!hasAndroid) {
  addIssue('warning', 'missing_android_project', 'Falta carpeta android; ejecuta npm run cap:add:android.');
}

console.log('Violeta Mobile Doctor');
console.log(`- Strict: ${strict ? 'si' : 'no'}`);
console.log(`- MOBILE_WEB_URL: ${serverUrl || 'no configurado'}`);
console.log(`- STORE_PRIVACY_POLICY_URL: ${privacyUrl || 'no configurado'}`);
console.log(`- STORE_ACCOUNT_DELETION_URL: ${deletionUrl || 'no configurado'}`);
console.log(`- iOS folder: ${hasIos ? 'presente' : 'ausente'}`);
console.log(`- Android folder: ${hasAndroid ? 'presente' : 'ausente'}`);

if (issues.length) {
  console.log('\nHallazgos:');
  for (const issue of issues) {
    console.log(`- [${issue.level.toUpperCase()}] ${issue.code}: ${issue.message}`);
  }
} else {
  console.log('\nSin hallazgos.');
}

const errorCount = issues.filter((issue) => issue.level === 'error').length;
let nextStep = 'npm run cap:sync';
if (!serverUrl) {
  nextStep = 'definir MOBILE_WEB_URL con la URL HTTPS de Render y luego npm run cap:sync';
} else if (!privacyUrl || !deletionUrl) {
  nextStep = 'definir URLs de privacidad y borrado de cuenta antes de enviar a tiendas';
} else if (issues.some((issue) => ['android_release_signing_missing', 'ios_development_team_missing'].includes(issue.code))) {
  nextStep = 'configurar signing de Android y Team ID de iOS antes de generar builds de tienda';
}
console.log('\nSiguiente paso recomendado:', nextStep);

if (strict && errorCount > 0) {
  process.exit(1);
}
