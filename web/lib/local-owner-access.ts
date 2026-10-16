// Volatile session/CSRF state only. No browser storage and no bearer tokens.
let csrf: string | null = null;
let expiresAt = 0;
let expiryTimer: ReturnType<typeof setTimeout> | null = null;
let revocationChannel: BroadcastChannel | null = null;
export const ACCESS_REQUIRED_EVENT = 'onejournal-access-required';
export const ACCESS_PREFIX = '/api/v1/local-owner/access';
const REVOCATION_CHANNEL = 'onejournal-access-revoked';

function channel() {
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') return null;
  try {
    revocationChannel ??= new BroadcastChannel(REVOCATION_CHANNEL);
    return revocationChannel;
  } catch { return null; }
}

export function listenForAccessRevocation() {
  const connection = channel();
  if (!connection) return () => {};
  const onMessage = (event: MessageEvent) => {
    if (event.data === 'logout') expireAccess();
  };
  connection.addEventListener('message', onMessage);
  return () => connection.removeEventListener('message', onMessage);
}

export function revokeAccessAcrossTabs() {
  expireAccess();
  // A missing or blocked browser channel must not turn a confirmed server
  // logout into an apparent failure. Other tabs still lose server access.
  try { channel()?.postMessage('logout'); } catch { /* Best-effort display lock. */ }
}

function clearExpiryTimer() {
  if (expiryTimer !== null) clearTimeout(expiryTimer);
  expiryTimer = null;
}

function expireAccess() {
  clearExpiryTimer();
  if (csrf === null) return;
  csrf = null;
  expiresAt = 0;
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(ACCESS_REQUIRED_EVENT));
}

export function expireAccessIfDue() {
  if (csrf !== null && Date.now() >= expiresAt) expireAccess();
}

export function setAccessSession(value: string | null, expiresInSeconds?: number) {
  clearExpiryTimer();
  csrf = value;
  expiresAt = 0;
  if (value === null) return;
  if (typeof expiresInSeconds !== 'number' || !Number.isFinite(expiresInSeconds)
    || expiresInSeconds < 0 || expiresInSeconds > 8 * 60 * 60) {
    csrf = null;
    throw new Error('Access session expiry is unavailable.');
  }
  const delay = Math.floor(expiresInSeconds * 1000);
  expiresAt = Date.now() + delay;
  expiryTimer = setTimeout(expireAccess, delay);
}

export async function fetchLocalOwner(path: string, init: RequestInit = {}) {
  expireAccessIfDue();
  const headers = new Headers(init.headers);
  if (csrf && !['GET', 'HEAD'].includes((init.method ?? 'GET').toUpperCase())) {
    headers.set('X-OneJournal-CSRF', csrf);
  }
  const response = await fetch(path, { ...init, headers, cache: 'no-store', credentials: 'same-origin' });
  if (response.status === 401) {
    csrf = null;
    if (typeof window !== 'undefined') window.dispatchEvent(new Event(ACCESS_REQUIRED_EVENT));
  }
  return response;
}

export async function accessJson<T = unknown>(path: string, body?: object): Promise<T> {
  const response = await fetchLocalOwner(`${ACCESS_PREFIX}/${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.status === 429
    ? 'Too many attempts. Wait before trying again.'
    : 'Access could not be verified. Try again, or use the private offline recovery procedure.');
  return response.json() as Promise<T>;
}

export function decodeBase64url(value: string): ArrayBuffer {
  const binary = atob(value.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(value.length / 4) * 4, '='));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export function encodeBase64url(buffer: ArrayBuffer): string {
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export function credentialJson(credential: PublicKeyCredential) {
  const response = credential.response;
  const common = { id: credential.id, rawId: encodeBase64url(credential.rawId), type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(), authenticatorAttachment: credential.authenticatorAttachment };
  if (response instanceof AuthenticatorAttestationResponse) {
    return { ...common, response: { clientDataJSON: encodeBase64url(response.clientDataJSON),
      attestationObject: encodeBase64url(response.attestationObject), transports: response.getTransports() } };
  }
  if (response instanceof AuthenticatorAssertionResponse) {
    return { ...common, response: { clientDataJSON: encodeBase64url(response.clientDataJSON),
      authenticatorData: encodeBase64url(response.authenticatorData), signature: encodeBase64url(response.signature),
      userHandle: response.userHandle ? encodeBase64url(response.userHandle) : null } };
  }
  throw new Error('This browser returned an unsupported credential.');
}
