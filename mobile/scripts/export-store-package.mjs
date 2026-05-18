import 'dotenv/config';
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

const root = process.cwd();
const projectRoot = resolve(root, '..');
const outputDir = resolve(root, 'build/store-submission');

const docsToInclude = [
  'docs/mobile-appstore.md',
  'docs/mobile-store-release-checklist.md',
  'docs/mobile-screenshot-plan.md',
  'docs/app-store-privacy-answers.md',
  'docs/google-play-data-safety.md',
];

function ensureExists(path, label) {
  if (!existsSync(path)) {
    throw new Error(`Falta ${label}: ${path}`);
  }
}

function copyDir(source, destination) {
  ensureExists(source, 'directorio fuente');
  mkdirSync(destination, { recursive: true });

  for (const entry of readdirSync(source)) {
    const sourcePath = join(source, entry);
    const destinationPath = join(destination, entry);
    if (statSync(sourcePath).isDirectory()) {
      copyDir(sourcePath, destinationPath);
    } else {
      copyFileSync(sourcePath, destinationPath);
    }
  }
}

function copyDocs() {
  const docsOutput = join(outputDir, 'docs');
  mkdirSync(docsOutput, { recursive: true });

  for (const doc of docsToInclude) {
    const source = resolve(projectRoot, doc);
    ensureExists(source, doc);
    copyFileSync(source, join(docsOutput, basename(doc)));
  }
}

function readGitValue(args, fallback) {
  try {
    return execFileSync('git', args, {
      cwd: projectRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim() || fallback;
  } catch {
    return fallback;
  }
}

function parseCapacitorValue(source, key) {
  const match = source.match(new RegExp(`${key}:\\s*['"]([^'"]+)['"]`));
  return match?.[1] || null;
}

function buildSummary() {
  const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'));
  const capacitorConfig = readFileSync(resolve(root, 'capacitor.config.ts'), 'utf8');
  const gitStatus = readGitValue(['status', '--short'], '');

  return {
    generatedAt: new Date().toISOString(),
    appName: parseCapacitorValue(capacitorConfig, 'appName') || 'Violeta',
    appId: parseCapacitorValue(capacitorConfig, 'appId') || 'com.violeta.app',
    mobilePackageName: packageJson.name,
    mobileVersion: packageJson.version,
    backendUrl: process.env.MOBILE_WEB_URL || 'https://violeta-app.onrender.com',
    privacyPolicyUrl: process.env.STORE_PRIVACY_POLICY_URL || 'https://violeta-app.onrender.com/privacy',
    accountDeletionUrl: process.env.STORE_ACCOUNT_DELETION_URL || 'https://violeta-app.onrender.com/account/delete',
    git: {
      branch: readGitValue(['branch', '--show-current'], 'unknown'),
      commit: readGitValue(['rev-parse', '--short', 'HEAD'], 'unknown'),
      dirty: Boolean(gitStatus),
    },
    accountRequiredLater: [
      'Apple Developer Team ID para archivar y subir a TestFlight.',
      'Google Play Console y upload key real para generar app-release.aab firmado.',
      'Capturas reales de tienda desde simulador o dispositivos finales.',
    ],
  };
}

function writeReadme(summary) {
  const content = `# Paquete de tienda Violeta

Generado: ${summary.generatedAt}

## Contenido

- \`metadata/\`: textos iniciales para App Store y Google Play.
- \`docs/\`: privacidad, Data Safety, checklist y plan de screenshots.
- \`release-summary.json\`: resumen tecnico de la app y URLs publicas.

## Validacion recomendada antes de subir a tiendas

\`\`\`bash
cd mobile
npm run store:check
npm run doctor:strict
npm run build:android:release
\`\`\`

## Pendiente que requiere cuentas

- Configurar Apple Developer Team ID y subir primero a TestFlight.
- Crear o configurar upload key real de Android y subir AAB a Play Console.
- Capturar screenshots finales con los dispositivos requeridos por cada tienda.
`;

  writeFileSync(join(outputDir, 'README.md'), content, 'utf8');
}

rmSync(outputDir, { recursive: true, force: true });
mkdirSync(outputDir, { recursive: true });

copyDir(resolve(root, 'store'), join(outputDir, 'metadata'));
copyDocs();

const summary = buildSummary();
writeFileSync(join(outputDir, 'release-summary.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
writeReadme(summary);

console.log('Paquete de tienda generado en mobile/build/store-submission');
