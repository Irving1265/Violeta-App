import { existsSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const mobileRoot = resolve(scriptDir, '..');
const androidRoot = resolve(mobileRoot, 'android');
const gradleArgs = process.argv.slice(2);

function javaBin(javaHome) {
  return javaHome ? join(javaHome, 'bin/java') : 'java';
}

function parseJavaMajor(versionOutput) {
  const match = versionOutput.match(/version "([^"]+)"/) || versionOutput.match(/openjdk version "([^"]+)"/);
  const version = match?.[1];
  if (!version) return null;
  if (version.startsWith('1.')) {
    return Number.parseInt(version.split('.')[1], 10);
  }
  return Number.parseInt(version.split('.')[0], 10);
}

function getJavaMajor(javaHome) {
  const command = javaBin(javaHome);
  if (javaHome && !existsSync(command)) {
    return null;
  }

  const result = spawnSync(command, ['-version'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (result.error || result.status !== 0) {
    return null;
  }
  return parseJavaMajor(`${result.stdout}\n${result.stderr}`);
}

function listJavaVirtualMachines() {
  const base = '/Library/Java/JavaVirtualMachines';
  if (!existsSync(base)) {
    return [];
  }
  return readdirSync(base)
    .filter((entry) => entry.endsWith('.jdk'))
    .map((entry) => join(base, entry, 'Contents/Home'));
}

function resolveJavaHome() {
  const currentMajor = getJavaMajor(process.env.JAVA_HOME);
  if (currentMajor && currentMajor >= 11) {
    return process.env.JAVA_HOME || null;
  }

  if (!process.env.JAVA_HOME) {
    const pathMajor = getJavaMajor(null);
    if (pathMajor && pathMajor >= 11) {
      return null;
    }
  }

  const candidates = [
    '/Applications/Android Studio.app/Contents/jbr/Contents/Home',
    ...listJavaVirtualMachines(),
  ];

  return candidates.find((candidate) => getJavaMajor(candidate) >= 11) || null;
}

const selectedJavaHome = resolveJavaHome();
const selectedMajor = getJavaMajor(selectedJavaHome);
if (!selectedMajor || selectedMajor < 11) {
  console.error('Android Gradle necesita Java 11 o superior.');
  console.error('Instala JDK 17/21 o Android Studio, o exporta JAVA_HOME antes de ejecutar este comando.');
  process.exit(1);
}

const env = { ...process.env };
if (selectedJavaHome) {
  env.JAVA_HOME = selectedJavaHome;
  env.PATH = `${join(selectedJavaHome, 'bin')}:${env.PATH || ''}`;
}

execFileSync('./gradlew', gradleArgs, {
  cwd: androidRoot,
  env,
  stdio: 'inherit',
});
