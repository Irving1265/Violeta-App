import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(scriptDir, '..');
const cordovaBuildGradle = path.join(
  mobileRoot,
  'android',
  'capacitor-cordova-android-plugins',
  'build.gradle',
);
const gradleProperties = path.join(mobileRoot, 'android', 'gradle.properties');

function patchFile(filePath, replacements, label) {
  if (!existsSync(filePath)) {
    return;
  }

  const source = readFileSync(filePath, 'utf8');
  const patched = replacements.reduce(
    (content, [pattern, replacement]) => content.replace(pattern, replacement),
    source,
  );

  if (patched !== source) {
    writeFileSync(filePath, patched);
    console.log(`${label} cleanup applied.`);
  }
}

const deprecatedAndroidOptions = [
  'android.defaults.buildfeatures.resvalues',
  'android.sdk.defaultTargetSdkToCompileSdkIfUnset',
  'android.enableAppCompileTimeRClass',
  'android.usesSdkInManifest.disallowed',
  'android.uniquePackageNames',
  'android.dependency.useConstraints',
  'android.r8.strictFullModeForKeepRules',
  'android.r8.optimizedResourceShrinking',
  'android.builtInKotlin',
  'android.newDsl',
];
const escapedOptions = deprecatedAndroidOptions.map((option) =>
  option.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
);

patchFile(
  cordovaBuildGradle,
  [[/\n\s*flatDir\s*\{\s*\n\s*dirs 'src\/main\/libs', 'libs'\s*\n\s*\}\s*/m, '\n']],
  'Android generated Gradle',
);

patchFile(
  gradleProperties,
  [[new RegExp(`^(${escapedOptions.join('|')})=.*\\n?`, 'gm'), '']],
  'Android Gradle properties',
);
