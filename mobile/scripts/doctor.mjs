import 'dotenv/config';
import { existsSync, readFileSync } from 'node:fs';
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

async function checkHealth(serverUrl) {
  if (!serverUrl) {
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);

  try {
    const healthUrl = new URL('/healthz', serverUrl).toString();
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
  } catch (error) {
    addIssue(
      strict ? 'error' : 'warning',
      'backend_health_unreachable',
      `No se pudo validar /healthz (${error?.name === 'AbortError' ? 'timeout' : 'error de red'}).`
    );
  } finally {
    clearTimeout(timeout);
  }
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

const required = ['package.json', 'capacitor.config.ts', 'www/index.html'];
required.forEach((file) => requireFile(file, `Falta archivo base del scaffold: ${file}.`));

const url = process.env.MOBILE_WEB_URL?.trim();
const serverUrl = parseUrl('MOBILE_WEB_URL', url, { required: true });
const privacyUrl = parseUrl('STORE_PRIVACY_POLICY_URL', process.env.STORE_PRIVACY_POLICY_URL, { required: strict });
const deletionUrl = parseUrl('STORE_ACCOUNT_DELETION_URL', process.env.STORE_ACCOUNT_DELETION_URL, { required: strict });

checkSyncedNativeConfig(serverUrl);
checkNativePermissions();
await checkHealth(serverUrl);

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
}
console.log('\nSiguiente paso recomendado:', nextStep);

if (strict && errorCount > 0) {
  process.exit(1);
}
