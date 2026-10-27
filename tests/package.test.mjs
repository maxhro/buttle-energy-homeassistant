import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { copyFileSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = fileURLToPath(new URL('../', import.meta.url));
const component = 'custom_components/powermesh_energy';

function fixture(t) {
  const work = join(root, 'tests', `.package-${randomUUID()}`);
  mkdirSync(work);
  t.after(() => rmSync(work, { recursive: true }));
  copyFileSync(join(root, 'build-package.ps1'), join(work, 'build-package.ps1'));
  for (const [name, content] of Object.entries({
    [`${component}/manifest.json`]: '{"domain":"powermesh_energy","version":"0.5.0"}',
    [`${component}/const.py`]: 'VERSION: Final = "0.5.0"\n',
    [`${component}/__init__.py`]: '',
    [`${component}/translations/de.json`]: '{}',
    [`${component}/__pycache__/cached.py`]: 'never package',
    [`${component}/.env`]: 'never package',
    '.env': 'SYNTHETIC_NEVER_READ=1',
    LICENSE: 'Synthetic license fixture',
  })) {
    mkdirSync(dirname(join(work, name)), { recursive: true });
    writeFileSync(join(work, name), content);
  }
  return work;
}

function run(work, flag) {
  return spawnSync('pwsh', ['-NoProfile', '-File', join(work, 'build-package.ps1'), flag], {
    encoding: 'utf8', timeout: 30_000,
  });
}

function zipNames(path) {
  const bytes = readFileSync(path);
  const end = bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  assert.ok(end >= 0);
  const names = [];
  let offset = bytes.readUInt32LE(end + 16);
  for (let i = 0; i < bytes.readUInt16LE(end + 10); i++) {
    assert.equal(bytes.readUInt32LE(offset), 0x02014b50);
    const length = bytes.readUInt16LE(offset + 28);
    names.push(bytes.subarray(offset + 46, offset + 46 + length).toString());
    offset += 46 + length + bytes.readUInt16LE(offset + 30) + bytes.readUInt16LE(offset + 32);
  }
  return names;
}

test('manual-install ZIP includes exactly component sources and license without caches or secrets', (t) => {
  const work = fixture(t);
  const dry = run(work, '-DryRun');
  assert.equal(dry.status, 0, dry.stderr);
  assert.doesNotMatch(dry.stdout, /__pycache__|SYNTHETIC_NEVER|\.env/);
  assert.equal(existsSync(join(work, 'dist')), false);
  const built = run(work, '-BuildPackage');
  assert.equal(built.status, 0, built.stderr);
  const path = join(work, 'dist/powermesh-energy-homeassistant-0.5.0.zip');
  assert.deepEqual(zipNames(path), [
    `${component}/__init__.py`, `${component}/const.py`, `${component}/manifest.json`,
    `${component}/translations/de.json`, 'LICENSE',
  ]);
  const original = readFileSync(path);
  assert.notEqual(run(work, '-BuildPackage').status, 0);
  assert.deepEqual(readFileSync(path), original);
});

test('version drift, JSON secret files and links are rejected before output', (t) => {
  const work = fixture(t);
  writeFileSync(join(work, component, 'const.py'), 'VERSION: Final = "1.0.0"\n');
  assert.notEqual(run(work, '-BuildPackage').status, 0);
  writeFileSync(join(work, component, 'const.py'), 'VERSION: Final = "0.5.0"\n');
  const secret = join(work, component, 'secrets.json');
  writeFileSync(secret, '{}');
  assert.notEqual(run(work, '-BuildPackage').status, 0);
  rmSync(secret);
  if (process.platform === 'win32') {
    t.diagnostic('Symlink fixture requires additional Windows privileges; symlink rejection is exercised on Unix.');
    return;
  }
  symlinkSync(join(work, 'LICENSE'), join(work, component, 'unsafe.py'));
  assert.notEqual(run(work, '-BuildPackage').status, 0);
  assert.equal(existsSync(join(work, 'dist')), false);
});
