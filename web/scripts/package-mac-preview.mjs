// Packaging feasibility only: no private API, TLS, passkey activation or deployment.
// Run after a clean build of tracked public source in a disposable directory.
import { cpSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const MAC_PREVIEW_STARTER = `#!/usr/bin/env node
import { join } from 'node:path';

// Intentionally ignore HOST, PORT and dotenv: this public portability candidate
// must never replace the protected site or listen on a public/LAN interface.
for (const key of Object.keys(process.env)) delete process.env[key];
function fail() {
  console.error('Packaging preview not started. Check runtime, package and port availability.');
  process.exit(1);
}
// The pinned server can throw from its socket error backstop on an occupied
// port instead of rejecting startup. Fail privately; never take over a listener.
process.once('uncaughtException', fail);
process.once('unhandledRejection', fail);
const { startProdServer } = await import('vinext/server/prod-server');
startProdServer({
  host: '127.0.0.1', port: 4187,
  outDir: join(import.meta.dirname, 'dist'), silent: true,
}).then(() => {
  console.log('Public Mac packaging preview: http://127.0.0.1:4187/demo/reports');
  console.log('No private API connection. Not the protected website or a production release.');
}).catch(fail);
`;

export function copyRuntimePeers(root, destination) {
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  // Vinext's empty application-externals manifest misses its own React peer
  // imports. React DOM also needs scheduler. Copy locked existing packages;
  // do not resolve new versions, copy build tools or rely on ancestor modules.
  const names = ['react', 'react-dom', 'scheduler'];
  for (const name of names) {
    const source = join(root, 'node_modules', name);
    const installed = JSON.parse(readFileSync(join(source, 'package.json'), 'utf8'));
    if (installed.version !== lock.packages[`node_modules/${name}`]?.version) {
      throw new Error('Runtime peer differs from the lockfile; packaging stopped.');
    }
  }
  for (const name of names) {
    cpSync(join(root, 'node_modules', name), join(destination, 'node_modules', name), { recursive: true, dereference: true });
  }
}

export async function packagePreview(root) {
  const outDir = join(root, 'dist');
  const destination = join(outDir, 'standalone');
  if (existsSync(destination)) throw new Error('Standalone output already exists; use a fresh disposable build.');
  if (!existsSync(join(outDir, 'server', 'vinext-externals.json'))) {
    throw new Error('A complete fresh build with its externals manifest is required.');
  }
  const upstream = pathToFileURL(join(root, 'node_modules/vinext/dist/build/standalone.js'));
  const { emitStandaloneOutput } = await import(upstream.href);
  emitStandaloneOutput({ root, outDir, vinextPackageRoot: join(root, 'node_modules/vinext') });
  writeFileSync(join(destination, 'server.js'), MAC_PREVIEW_STARTER, { mode: 0o755 });
  copyRuntimePeers(root, destination);
  cpSync(join(root, 'package-lock.json'), join(destination, 'source-package-lock.json'));
  return destination;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await packagePreview(fileURLToPath(new URL('..', import.meta.url)));
    console.log('Mac portability candidate prepared in dist/standalone; no services started.');
  } catch {
    console.error('Packaging failed. Use a fresh disposable public-source build with locked dependencies. No live service was changed.');
    process.exitCode = 1;
  }
}
