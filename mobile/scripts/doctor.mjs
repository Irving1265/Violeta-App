import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const required = ['package.json', 'capacitor.config.ts', 'www/index.html'];
const missing = required.filter((file) => !existsSync(resolve(process.cwd(), file)));

if (missing.length) {
  console.error('Faltan archivos base del scaffold:', missing.join(', '));
  process.exit(1);
}

const url = process.env.MOBILE_WEB_URL?.trim();
console.log('Violeta Mobile Doctor');
console.log(`- MOBILE_WEB_URL: ${url || 'no configurado'}`);
console.log(`- iOS folder: ${existsSync(resolve(process.cwd(), 'ios')) ? 'presente' : 'ausente'}`);
console.log(`- Android folder: ${existsSync(resolve(process.cwd(), 'android')) ? 'presente' : 'ausente'}`);
const hasIos = existsSync(resolve(process.cwd(), 'ios'));
const nextStep = url ? 'npm run cap:sync' : (hasIos ? 'definir MOBILE_WEB_URL y luego npm run cap:sync' : 'definir MOBILE_WEB_URL y luego npm run cap:add:ios');
console.log('- Siguiente paso recomendado:', nextStep);
