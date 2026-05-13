import 'dotenv/config';
import type { CapacitorConfig } from '@capacitor/cli';

function resolveServerUrl(): string | undefined {
  const raw = process.env.MOBILE_WEB_URL?.trim();
  if (!raw) {
    return undefined;
  }
  try {
    return new URL(raw).toString().replace(/\/$/, '');
  } catch {
    throw new Error(`MOBILE_WEB_URL invalido: ${raw}`);
  }
}

const serverUrl = resolveServerUrl();
const allowNavigation = serverUrl ? [new URL(serverUrl).host] : undefined;

const config: CapacitorConfig = {
  appId: 'com.violeta.app',
  appName: 'Violeta',
  webDir: 'www',
  bundledWebRuntime: false,
  backgroundColor: '#13111C',
  server: serverUrl
    ? {
        url: serverUrl,
        cleartext: serverUrl.startsWith('http://'),
        androidScheme: serverUrl.startsWith('http://') ? 'http' : 'https',
        allowNavigation,
      }
    : undefined,
  ios: {
    backgroundColor: '#13111C',
    contentInset: 'never',
  },
  android: {
    allowMixedContent: false,
  },
};

export default config;
