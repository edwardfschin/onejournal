"""Read-only release integrity and optional anonymous loopback transport check.

Pins come from a separately trusted release receipt, never the checked artifact.
This checks neither financial correctness nor owner/hosted acceptance.
"""
import argparse
from contextlib import closing
from hashlib import sha256
import http.client
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import sys
from urllib.parse import urlsplit

from onejournal.passkey_access import CONTRACT as ACCESS_CONTRACT, PREFIX, validate_origin
from onejournal.static_web import PUBLIC_HEADERS, static_routes


class ReleaseCheckError(ValueError):
    """Fixed, value-free failure; source paths and response bodies stay private."""


def _hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseCheckError('Duplicate release field.')
        value[key] = item
    return value


def check_release(directory, *, manifest_sha256, source_commit):
    """Check the existing v1 producer contract and exact public file inventory."""
    root = Path(directory)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or not re.fullmatch(r'[0-9a-f]{64}', manifest_sha256)
            or not re.fullmatch(r'[0-9a-f]{40}', source_commit)):
        raise ReleaseCheckError('Exact release directory and independently recorded pins required.')
    inventory = {}
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ReleaseCheckError('Release contains a link or special file.')
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = path
    manifest = inventory.pop('release-manifest.json', None)
    if manifest is None or manifest.stat().st_size > 1024 * 1024 or _hash(manifest) != manifest_sha256:
        raise ReleaseCheckError('Release manifest does not match the independent receipt.')
    value = json.loads(manifest.read_bytes(), object_pairs_hook=_unique)
    if (not isinstance(value, dict) or set(value) != {'contract_version', 'source_commit', 'scope', 'files_sha256'}
            or value['contract_version'] != 'onejournal.mac-release.v1'
            or value['scope'] != 'prepared_mac_loopback_only' or value['source_commit'] != source_commit
            or not isinstance(value['files_sha256'], dict)):
        raise ReleaseCheckError('Release scope or source differs from its receipt.')
    for name, expected in value['files_sha256'].items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or name != relative.as_posix() or '..' in relative.parts
                or '\\' in name or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise ReleaseCheckError('Unsafe release manifest entry.')
    if set(inventory) != set(value['files_sha256']):
        raise ReleaseCheckError('Release has missing or unexpected files.')
    if not {'INSTALL.txt', 'requirements.lock', 'requirements-security.lock', 'static/index.html'} <= set(inventory):
        raise ReleaseCheckError('Release is missing installation or website inputs.')
    if len([name for name in inventory if '/' not in name and re.fullmatch(r'onejournal-[^/]+\.whl', name)]) != 1:
        raise ReleaseCheckError('Exactly one application wheel is required.')
    for name, path in inventory.items():
        if _hash(path) != value['files_sha256'][name]:
            raise ReleaseCheckError('Release file checksum differs.')
    static_routes(root / 'static')
    return {'source_commit': source_commit, 'public_file_count': len(inventory),
            'index_sha256': value['files_sha256']['static/index.html'], 'artifact_integrity_verified': True}


def check_site(origin, *, index_sha256, tls_cert=None, tls_cert_sha256=None):
    """Two GETs only; verified TLS, no proxies, cookies, retries or redirects."""
    origin = validate_origin(origin)
    address = urlsplit(origin)
    if (tls_cert is None) != (tls_cert_sha256 is None):
        raise ReleaseCheckError('Local certificate and independent certificate pin must be paired.')
    if tls_cert is not None:
        certificate=Path(tls_cert)
        if (not certificate.is_absolute() or certificate.is_symlink() or not certificate.is_file()
                or not re.fullmatch(r'[0-9a-f]{64}', tls_cert_sha256) or _hash(certificate)!=tls_cert_sha256):
            raise ReleaseCheckError('Local certificate differs from the previously approved setup receipt.')
    context=ssl.create_default_context(cafile=str(tls_cert) if tls_cert is not None else None)
    result = {}
    for path in ('/local/reports', PREFIX + '/session'):
        with closing(http.client.HTTPSConnection('localhost', address.port, timeout=5,
                                                 context=context)) as connection:
            connection.request('GET', path, headers={'Host': address.netloc})
            response = connection.getresponse()
            body = response.read(1024 * 1024 + 1)
            if (response.status != 200 or len(body) > 1024 * 1024 or response.getheader('Set-Cookie') is not None
                    or any(response.getheader(key) != expected for key, expected in PUBLIC_HEADERS.items())):
                raise ReleaseCheckError('Protected Mac transport or response headers differ.')
            if path == '/local/reports':
                if sha256(body).hexdigest() != index_sha256:
                    raise ReleaseCheckError('Served page differs from the selected artifact.')
            else:
                value = json.loads(body, object_pairs_hook=_unique)
                if (not isinstance(value, dict) or set(value) != {'contract_version', 'authenticated', 'enrollment_required',
                                                                 'csrf', 'passkey_count', 'expires_in_seconds'}
                        or value.get('contract_version') != ACCESS_CONTRACT
                        or value.get('authenticated') is not False or value.get('enrollment_required') is not False
                        or any(value.get(key) is not None for key in ('csrf', 'passkey_count', 'expires_in_seconds'))):
                    raise ReleaseCheckError('Expected anonymous enrolled access service unavailable.')
                result = {'trusted_https_verified': True, 'served_shell_verified': True,
                          'anonymous_enrolled_access_status_verified': True}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-dir', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--site-origin', help='Optional exact HTTPS localhost origin; never a hosted URL.')
    parser.add_argument('--tls-cert', type=Path, help='Optional existing approved localhost certificate; never the private key.')
    parser.add_argument('--tls-cert-sha256', help='Independent certificate pin from its existing setup/handover receipt.')
    args = parser.parse_args(argv)
    try:
        result = check_release(args.release_dir, manifest_sha256=args.manifest_sha256, source_commit=args.source_commit)
        if (args.tls_cert is not None or args.tls_cert_sha256 is not None) and not args.site_origin:
            raise ReleaseCheckError('Certificate options require the exact localhost site check.')
        if args.site_origin:
            check_site(args.site_origin, index_sha256=result['index_sha256'],
                       tls_cert=args.tls_cert,tls_cert_sha256=args.tls_cert_sha256)
    except Exception:
        print('Mac check failed: check independent release pins, exact public files, trusted localhost TLS and the existing protected service. No repair, restart or data change was attempted.', file=sys.stderr)
        return 1
    print('Mac release integrity verified.' + (' Loopback HTTPS shell and anonymous enrolled access status verified.' if args.site_origin else '')
          + ' Not financial, login, dependency-security or hosted acceptance. No state change attempted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
