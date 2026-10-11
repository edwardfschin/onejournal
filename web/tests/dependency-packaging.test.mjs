import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

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
