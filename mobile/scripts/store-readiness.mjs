import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const projectRoot = resolve(root, '..');
const issues = [];

function addIssue(level, code, message) {
  issues.push({ level, code, message });
}

function readRequiredText(file, { minLength = 20, maxLength = null } = {}) {
  const path = resolve(root, file);
  if (!existsSync(path)) {
    addIssue('error', `missing_${file.replaceAll('/', '_')}`, `Falta ${file}.`);
    return '';
  }

  const text = readFileSync(path, 'utf8').trim();
  if (text.length < minLength) {
    addIssue('error', `short_${file.replaceAll('/', '_')}`, `${file} esta demasiado corto.`);
  }
  if (maxLength && text.length > maxLength) {
    addIssue('error', `long_${file.replaceAll('/', '_')}`, `${file} supera ${maxLength} caracteres.`);
  }
  if (/tu-app|tu-backend|example\.com|CAMBIA|TODO|PENDIENTE/i.test(text)) {
    addIssue('error', `placeholder_${file.replaceAll('/', '_')}`, `${file} contiene placeholders.`);
  }
  return text;
}

function readRequiredDoc(file) {
  const path = resolve(projectRoot, file);
  if (!existsSync(path)) {
    addIssue('error', `missing_${file.replaceAll('/', '_')}`, `Falta ${file}.`);
    return '';
  }
  const text = readFileSync(path, 'utf8');
  if (!/Violeta/i.test(text)) {
    addIssue('error', `missing_violeta_${file.replaceAll('/', '_')}`, `${file} debe referirse explicitamente a Violeta.`);
  }
  return text;
}

const shortDescription = readRequiredText('store/google-play/short-description.es-MX.txt', {
  minLength: 20,
  maxLength: 80,
});
readRequiredText('store/google-play/full-description.es-MX.txt', { minLength: 500, maxLength: 4000 });
readRequiredText('store/google-play/release-notes.es-MX.txt', { minLength: 20, maxLength: 500 });
readRequiredText('store/app-store/subtitle.es-MX.txt', { minLength: 10, maxLength: 30 });
readRequiredText('store/app-store/promotional-text.es-MX.txt', { minLength: 20, maxLength: 170 });
const reviewNotes = readRequiredText('store/app-store/review-notes.es-MX.txt', {
  minLength: 120,
  maxLength: 4000,
});

const privacyAnswers = readRequiredDoc('docs/app-store-privacy-answers.md');
const dataSafety = readRequiredDoc('docs/google-play-data-safety.md');
readRequiredDoc('docs/mobile-store-release-checklist.md');

if (shortDescription && !/seguridad|reporta|zonas/i.test(shortDescription)) {
  addIssue('warning', 'weak_short_description', 'La short description deberia mencionar seguridad, reportes o zonas.');
}
if (!/No tracking/i.test(privacyAnswers)) {
  addIssue('warning', 'privacy_tracking_not_explicit', 'App Store privacy answers deberia declarar No tracking si sigue sin SDKs de tracking.');
}
if (!/Account deletion/i.test(dataSafety) && !/borrado de cuenta/i.test(dataSafety)) {
  addIssue('warning', 'data_safety_deletion_not_explicit', 'Google Play Data Safety debe mencionar borrado de cuenta.');
}
if (reviewNotes && (!/Capacitor/i.test(reviewNotes) || !/Render/i.test(reviewNotes))) {
  addIssue('warning', 'review_notes_mobile_architecture_missing', 'Las notas de revision deberian explicar Capacitor y backend en Render.');
}
if (reviewNotes && !/camara|galeria|ubicacion|mapa|moderacion|eliminacion/i.test(reviewNotes)) {
  addIssue('warning', 'review_notes_mobile_value_missing', 'Las notas de revision deberian explicar capacidades moviles reales.');
}

console.log('Violeta Store Readiness');
if (issues.length) {
  console.log('\nHallazgos:');
  for (const issue of issues) {
    console.log(`- [${issue.level.toUpperCase()}] ${issue.code}: ${issue.message}`);
  }
} else {
  console.log('\nSin hallazgos.');
}

if (issues.some((issue) => issue.level === 'error')) {
  process.exit(1);
}
