import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
import { defineConfig, type Plugin, type Connect } from 'vite';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { DEMO_ROUTES, LOCAL_ROUTES, LEGACY_ROUTE_REDIRECTS } from './lib/routes';

const securityHeaders = {
  'Cache-Control': 'no-store',
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'publickey-credentials-get=(self), publickey-credentials-create=(self)',
  'X-Content-Type-Options': 'nosniff',
};

function routeContract(apiTarget: string | undefined): Plugin {
  const middleware: Connect.NextHandleFunction = (request, response, next) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const redirect = LEGACY_ROUTE_REDIRECTS.find(({ source }) => source === url.pathname);
    if (redirect) {
      response.statusCode = 307;
      response.setHeader('Location', redirect.destination + url.search);
      response.end();
    } else if (url.pathname.startsWith('/api/') && !apiTarget) {
      // An unavailable API must not become an HTML success response.
      response.statusCode = 404;
      response.setHeader('Content-Type', 'application/json');
      response.end('{"detail":"Private API unavailable"}');
    } else next();
  };
  return {
    name: 'onejournal-static-route-contract',
    configureServer(server) { server.middlewares.use(middleware); },
    configurePreviewServer(server) { server.middlewares.use(middleware); },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'onejournal-static-web.json', source: JSON.stringify({
        contract_version: 'onejournal.static-web.v1', passkey_required: true,
        routes: [...Object.values(DEMO_ROUTES), ...Object.values(LOCAL_ROUTES)], redirects: LEGACY_ROUTE_REDIRECTS,
      }, null, 2) + '\n' });
    },
  };
}

export default defineConfig(({ command, isPreview }) => {
  const passkeyMode = process.env.ONEJOURNAL_PASSKEY_MODE === '1';
  const apiTarget = command === 'serve' && !isPreview ? process.env.ONEJOURNAL_LOCAL_API_URL : undefined;
  const privateDev = command === 'serve' && !isPreview && passkeyMode;
  if (privateDev && (!process.env.ONEJOURNAL_TEST_TLS_CERT || !process.env.ONEJOURNAL_TEST_TLS_KEY)) {
    throw new Error('The passkey prototype requires explicit localhost HTTPS; no HTTP fallback.');
  }
  return {
    resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
    define: { 'import.meta.env.VITE_ONEJOURNAL_PASSKEY_MODE': JSON.stringify(passkeyMode ? '1' : '0') },
    css: { postcss: { plugins: [tailwindcss()] } },
    server: {
      host: '127.0.0.1', port: 4173, strictPort: true, headers: securityHeaders,
      ...(privateDev ? { https: { cert: readFileSync(process.env.ONEJOURNAL_TEST_TLS_CERT!), key: readFileSync(process.env.ONEJOURNAL_TEST_TLS_KEY!) } } : {}),
      ...(process.env.CODEX_SANDBOX === 'seatbelt' ? { watch: { useFsEvents: false, usePolling: true } } : {}),
      ...(apiTarget ? { proxy: {
        '/api/v1/local-owner': { target: apiTarget, changeOrigin: false },
        '/api/v5/local-owner': { target: apiTarget, changeOrigin: false },
      } } : {}),
    },
    // Fixture/demo preview only; private builds are served by the Python app.
    preview: { host: '127.0.0.1', port: 4187, strictPort: true, headers: securityHeaders, proxy: {} },
    plugins: [react(), routeContract(apiTarget)],
  };
});
