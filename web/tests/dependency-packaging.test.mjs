import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const root = new URL('../', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('package.json', root), 'utf8'));
const lock = JSON.parse(readFileSync(new URL('package-lock.json', root), 'utf8'));

test('component generator stays development-only and the React application is retained', () => {
  assert.equal(manifest.dependencies.shadcn, undefined);
  assert.equal(lock.packages[''].devDependencies.shadcn, manifest.devDependencies.shadcn);
  assert.equal(lock.packages['node_modules/shadcn'].dev, true);
  assert.ok(manifest.dependencies['@shadcn/react']);
  assert.notEqual(lock.packages['node_modules/@shadcn/react'].dev, true);
  for (const [path, entry] of Object.entries(lock.packages)) {
    if (path.endsWith('/proxy-addr')) assert.equal(entry.dev, true, path);
  }
});

test('the declared build is static Vite, without SSR or a hosting runtime', () => {
  assert.equal(manifest.scripts.build, 'vite build');
  for (const name of ['vinext', 'react-server-dom-webpack', '@vitejs/plugin-rsc',
    '@cloudflare/vite-plugin', '@openai/sites-vite-plugin', 'wrangler']) {
    assert.equal(manifest.dependencies[name], undefined);
    assert.equal(manifest.devDependencies[name], undefined);
    assert.equal(lock.packages[`node_modules/${name}`], undefined);
  }
  assert.equal(manifest.devDependencies['@vitejs/plugin-react'], '6.0.2');
  assert.equal(manifest.dependencies.react, '19.2.8');
});

test('private builds always mount the existing passkey boundary before page content', () => {
  const entry = readFileSync(new URL('main.tsx', root), 'utf8');
  assert.match(entry, /enabled=\{import\.meta\.env\.PROD \|\|/);
  assert.match(entry, /<PasskeyBoundary[\s\S]*<Suspense[\s\S]*<Page \/>[\s\S]*<\/PasskeyBoundary>/);
  const boundary = readFileSync(new URL('components/passkey-boundary.tsx', root), 'utf8');
  assert.match(boundary, /pathname\?\.startsWith\('\/local\/'\)/);
});

test('reviewed build-security pins are present in every locked dependency copy', () => {
  assert.equal(manifest.devDependencies.vite, '8.0.16');
  assert.equal(lock.packages['node_modules/vite'].version, '8.0.16');
  for (const [name, version] of Object.entries(manifest.overrides)) {
    const copies = Object.entries(lock.packages).filter(([path]) => path.endsWith(`/${name}`));
    assert.ok(copies.length, name);
    for (const [path, entry] of copies) assert.equal(entry.version, version, path);
  }
});

test('locally packaged font URLs have no network or workstation dependency', () => {
  const css = readFileSync(new URL('public/fonts/geist.css', root), 'utf8');
  const paths = [...css.matchAll(/url\(([^)]+)\)/g)].map((match) => match[1]);
  assert.equal(paths.length, 11);
  for (const path of paths) {
    assert.match(path, /^\/fonts\/[a-z0-9-]+\/[a-z0-9-]+\.woff2$/);
    assert.ok(existsSync(new URL(`public${path}`, root)), path);
  }
  assert.match(readFileSync(new URL('public/fonts/OFL.txt', root), 'utf8'), /SIL OPEN FONT LICENSE Version 1.1/);
});

test('development response headers are applied before redirects and API handling', () => {
  const config = readFileSync(new URL('vite.config.ts', root), 'utf8');
  assert.match(config, /const middleware:[\s\S]*Object\.entries\(securityHeaders\)[\s\S]*response\.setHeader\(name, value\)[\s\S]*const url = new URL/);
});
