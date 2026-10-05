'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { accessJson, ACCESS_REQUIRED_EVENT, credentialJson, decodeBase64url, setAccessSession } from '@/lib/local-owner-access';
import './passkey-boundary.css';

type SessionStatus = { contract_version: string; authenticated: boolean; enrollment_required: boolean; csrf: string | null; passkey_count: number | null };
type CeremonyOptions = {
  ceremony: string;
  options: Omit<PublicKeyCredentialCreationOptions, 'challenge' | 'user' | 'excludeCredentials'> &
    Omit<PublicKeyCredentialRequestOptions, 'challenge' | 'allowCredentials'> & {
    challenge: string; user: { id: string; name: string; displayName: string };
    excludeCredentials?: { id: string; type: PublicKeyCredentialType }[];
    allowCredentials?: { id: string; type: PublicKeyCredentialType }[];
  };
};

function ProtectedWorkspace({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [error, setError] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef({ value: 0 });
  const logoutUnconfirmed = useRef(false);
  const refresh = useCallback(async () => {
    if (logoutUnconfirmed.current) return;
    const requestGeneration = ++generation.current.value;
    try {
      const state = await accessJson<SessionStatus>('session');
      if (state.contract_version !== 'onejournal.mac-passkey.v1' || typeof state.authenticated !== 'boolean'
        || (state.authenticated && (typeof state.csrf !== 'string' || !state.csrf))) throw new Error('Access service is unavailable.');
      if (requestGeneration !== generation.current.value || logoutUnconfirmed.current) return;
      setAccessSession(state.csrf);
      setSession(state);
    } catch {
      if (requestGeneration !== generation.current.value) return;
      setAccessSession(null); setSession(null); setError('The protected service is unavailable. No private view is loaded.');
    }
  }, []);
  useEffect(() => {
    const epoch = generation.current;
    const initial = setTimeout(() => { void refresh(); }, 0);
    const timer = setInterval(() => { void refresh(); }, 30_000);
    const lock = () => { ++epoch.value; setAccessSession(null); setSession(null); void refresh(); };
    const focus = () => { void refresh(); };
    window.addEventListener(ACCESS_REQUIRED_EVENT, lock);
    window.addEventListener('focus', focus);
    return () => { ++epoch.value; clearTimeout(initial); clearInterval(timer); window.removeEventListener(ACCESS_REQUIRED_EVENT, lock); window.removeEventListener('focus', focus); setAccessSession(null); };
  }, [refresh]);

  async function ceremony(register: boolean) {
    setBusy(true); setError('');
    try {
      if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('Use a supported browser with trusted localhost HTTPS.');
      const enrollment = register && !session?.authenticated ? { enrollment_secret: secret } : {};
      const value = await accessJson<CeremonyOptions>(register ? 'register/options' : 'login/options', enrollment);
      const options = { ...value.options, challenge: decodeBase64url(value.options.challenge) };
      let credential: Credential | null;
      if (register) {
        const { allowCredentials: _allow, ...creation } = options;
        const publicKey = { ...creation,
          user: { ...value.options.user, id: decodeBase64url(value.options.user.id) },
          excludeCredentials: (options.excludeCredentials ?? []).map((item) => ({ ...item, id: decodeBase64url(item.id) })) };
        credential = await navigator.credentials.create({ publicKey });
      } else {
        const { excludeCredentials: _exclude, ...authentication } = options;
        const publicKey = { ...authentication,
          allowCredentials: (options.allowCredentials ?? []).map((item) => ({ ...item, id: decodeBase64url(item.id) })) };
        credential = await navigator.credentials.get({ publicKey });
      }
      if (!(credential instanceof PublicKeyCredential)) throw new Error('No passkey was returned.');
      await accessJson(register ? 'register/verify' : 'login/verify', { ...enrollment, ceremony: value.ceremony, credential: credentialJson(credential) });
      setSecret('');
      await refresh();
      if (register) setError(session?.authenticated ? 'Backup passkey registered.' : 'Passkey registered. Sign in with it to open the workspace.');
    } catch (issue) {
      // Never display browser credential/challenge details or raw API bodies.
      setError(issue instanceof DOMException ? 'Passkey action cancelled or unavailable. Try again in a supported, trusted browser.'
        : issue instanceof Error ? issue.message : 'Passkey verification failed.');
    } finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true);
    ++generation.current.value;
    logoutUnconfirmed.current = true;
    // Hide private views immediately; keep the CSRF value until the request is sent.
    setSession(null);
    try { await accessJson('logout', {}); logoutUnconfirmed.current = false; setError(''); }
    catch { setError('Logout could not be confirmed. Stop the prototype to revoke this session.'); }
    finally { setAccessSession(null); setBusy(false); }
    if (!logoutUnconfirmed.current) await refresh();
  }

  if (session?.authenticated) return <>
    <aside className="passkey-session-bar" aria-label="Private session">
      <span>Mac passkey test · {session.passkey_count} registered</span>
      <button type="button" disabled={busy} onClick={() => { void ceremony(true); }}>Add backup passkey</button>
      <button type="button" disabled={busy} onClick={() => { void logout(); }}>Sign out</button>
      {error ? <output>{error}</output> : null}
    </aside>
    {children}
  </>;
  return <main className="passkey-login"><section aria-labelledby="passkey-title">
    <p className="passkey-eyebrow">OneJournal · Mac-only security test</p>
    <h1 id="passkey-title">Your private workspace</h1>
    <p>Use your passkey with device verification. No password or authenticator code.</p>
    {session?.enrollment_required ? <>
      <label htmlFor="enrollment-secret">One-time private enrollment code</label>
      <input id="enrollment-secret" type="password" autoComplete="off" value={secret} maxLength={128}
        onChange={(event) => setSecret(event.target.value)} disabled={busy} />
      <p className="passkey-help">Read it from the private file created by the operator command. Never paste it into chat. It expires after 10 minutes.</p>
      <button type="button" disabled={busy || secret.length < 32} onClick={() => { void ceremony(true); }}>Register passkey</button>
    </> : <button type="button" disabled={busy || !session} onClick={() => { void ceremony(false); }}>{busy ? 'Waiting for your device…' : 'Sign in with passkey'}</button>}
    {error ? <output>{error}</output> : null}
    <button type="button" className="passkey-secondary" disabled={busy} onClick={() => { setError(''); void refresh(); }}>Check connection</button>
    <p className="passkey-help">Lost access? Stop the prototype and use private offline recovery. There is no password, SMS, or email fallback.</p>
  </section></main>;
}

export default function PasskeyBoundary({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const pathname = usePathname();
  return enabled && pathname?.startsWith('/local/') ? <ProtectedWorkspace>{children}</ProtectedWorkspace> : <>{children}</>;
}
