import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const serverUrl = process.env.MOBILE_WEB_URL?.trim() || null;
const payload = {
  serverUrl,
  generatedAt: new Date().toISOString(),
};

const outDir = resolve(process.cwd(), 'www');
await mkdir(outDir, { recursive: true });
await writeFile(resolve(outDir, 'runtime-config.json'), JSON.stringify(payload, null, 2));

console.log(
  serverUrl
    ? `runtime-config.json generado con MOBILE_WEB_URL=${serverUrl}`
    : 'runtime-config.json generado sin backend publico. Se usara la pantalla local de onboarding.'
);
