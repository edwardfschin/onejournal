import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { copyRuntimePeers, MAC_PREVIEW_STARTER, packagePreview } from '../scripts/package-mac-preview.mjs';

const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));

test('component generator and build-time CSS package stay development-only', () => {
  assert.equal(manifest.dependencies.shadcn, undefined);
  assert.ok(manifest.devDependencies.shadcn);
  assert.equal(lock.packages[''].devDependencies.shadcn, manifest.devDependencies.shadcn);
  assert.equal(lock.packages[''].dependencies.shadcn, undefined);
  assert.equal(lock.packages['node_modules/shadcn'].dev, true);
  // @shadcn/react is a separate application dependency, not the generator.
  assert.ok(manifest.dependencies['@shadcn/react']);
  assert.notEqual(lock.packages['node_modules/@shadcn/react'].dev, true);
});

test('generator-only proxy dependency is excluded from production installs', () => {
  const proxies = Object.entries(lock.packages).filter(([path]) => path.endsWith('/proxy-addr'));
  for (const [path, entry] of proxies) assert.equal(entry.dev, true, path);
});

test('standalone candidate includes the locked runtime peers missed by upstream', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'onejournal-runtime-peers-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const packages = {};
  for (const name of ['react', 'react-dom', 'scheduler']) {
    mkdirSync(join(root, 'node_modules', name), { recursive: true });
    writeFileSync(join(root, 'node_modules', name, 'package.json'), JSON.stringify({ name, version: '1.0.0' }));
    packages[`node_modules/${name}`] = { version: '1.0.0' };
  }
  writeFileSync(join(root, 'package-lock.json'), JSON.stringify({ packages }));
  const destination = join(root, 'candidate');
  copyRuntimePeers(root, destination);
  for (const name of ['react', 'react-dom', 'scheduler']) {
    assert.equal(JSON.parse(readFileSync(join(destination, 'node_modules', name, 'package.json'))).version, '1.0.0');
  }
  packages['node_modules/react'].version = '2.0.0';
  writeFileSync(join(root, 'package-lock.json'), JSON.stringify({ packages }));
  assert.throws(() => copyRuntimePeers(root, destination), /differs from the lockfile/);
});

test('candidate refuses overwrite or incomplete builds and has a fixed loopback starter', async (t) => {
  const root = mkdtempSync(join(tmpdir(), 'onejournal-preview-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  await assert.rejects(packagePreview(root), /complete fresh build/);
  mkdirSync(join(root, 'dist', 'standalone'), { recursive: true });
  await assert.rejects(packagePreview(root), /already exists/);
  assert.match(MAC_PREVIEW_STARTER, /host: '127\.0\.0\.1', port: 4187/);
  assert.match(MAC_PREVIEW_STARTER, /delete process\.env\[key\]/);
  assert.doesNotMatch(MAC_PREVIEW_STARTER, /process\.env\.(HOST|PORT)|loadDotenv|0\.0\.0\.0/);
});
