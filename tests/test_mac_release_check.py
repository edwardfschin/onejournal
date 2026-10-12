"""Focused integrity and no-state-change checks; synthetic public artifacts."""
from contextlib import redirect_stderr
from hashlib import sha256
import io
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from onejournal.mac_release_check import check_release, check_site, main, ReleaseCheckError
from onejournal.passkey_access import CONTRACT, PREFIX
from onejournal.static_web import PUBLIC_HEADERS
import test_static_web as fixtures


COMMIT = 'a' * 40


def prepared(root):
    fixtures.artifact(root / 'static')
    for name in ('INSTALL.txt', 'requirements.lock', 'requirements-security.lock', 'onejournal-0.1.0-py3-none-any.whl'):
        (root / name).write_bytes(b'synthetic public file')
    manifest={'contract_version':'onejournal.mac-release.v1','source_commit':COMMIT,
              'scope':'prepared_mac_loopback_only','files_sha256':{
        p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}}
    body=json.dumps(manifest).encode();(root/'release-manifest.json').write_bytes(body)
    return sha256(body).hexdigest()


def status():
    return {'contract_version':CONTRACT,'authenticated':False,'enrollment_required':False,
            'passkey_count':None,'csrf':None,'expires_in_seconds':None}


def responses(body, access=None, *, code=200, headers=None):
    factory=MagicMock()
    values=[body,json.dumps(status() if access is None else access).encode()]
    connections=[]
    for data in values:
        connection=MagicMock();connection.__enter__.return_value=connection
        response=connection.getresponse.return_value
        response.status=code;response.read.return_value=data
        response.getheader.side_effect=lambda key: (headers if headers is not None else PUBLIC_HEADERS).get(key)
        connections.append(connection)
    factory.side_effect=connections
    return factory,connections


class MacReleaseCheckTests(unittest.TestCase):
    def test_exact_artifact_is_readonly_and_receipt_pins_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pin=prepared(root)
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertTrue(check_release(root,manifest_sha256=pin,source_commit=COMMIT)['artifact_integrity_verified'])
            self.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})
            for manifest_pin,commit in [('b'*64,COMMIT),(pin,'b'*40)]:
                with self.assertRaises(ReleaseCheckError):
                    check_release(root,manifest_sha256=manifest_pin,source_commit=commit)

    def test_changed_missing_extra_and_linked_files_fail(self):
        for mode in ('changed','missing','extra','link'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);pin=prepared(root)
                if mode=='changed':(root/'static/index.html').write_text('changed')
                if mode=='missing':(root/'INSTALL.txt').unlink()
                if mode=='extra':(root/'unlisted.txt').write_text('not public release evidence')
                if mode=='link':(root/'link').symlink_to(root/'INSTALL.txt')
                with self.assertRaises(ReleaseCheckError):
                    check_release(root,manifest_sha256=pin,source_commit=COMMIT)

    def test_bad_scope_and_traversal_fail_even_with_recomputed_manifest_pin(self):
        for mode in ('scope','traversal'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);prepared(root);path=root/'release-manifest.json'
                value=json.loads(path.read_bytes())
                if mode=='scope':value['scope']='hosted_production'
                else:value['files_sha256']['../private.txt']='b'*64
                body=json.dumps(value).encode();path.write_bytes(body)
                with self.assertRaises(ReleaseCheckError):
                    check_release(root,manifest_sha256=sha256(body).hexdigest(),source_commit=COMMIT)

    def test_probe_has_exact_two_cookie_free_gets_and_verified_tls(self):
        body=b'synthetic shell';factory,connections=responses(body)
        with patch('onejournal.mac_release_check.http.client.HTTPSConnection',factory):
            self.assertTrue(check_site('https://localhost:4173',index_sha256=sha256(body).hexdigest())['trusted_https_verified'])
        self.assertEqual(factory.call_count,2)
        for index,path in enumerate(('/local/reports',PREFIX+'/session')):
            connections[index].request.assert_called_once_with('GET',path,headers={'Host':'localhost:4173'})
            args,kwargs=factory.call_args_list[index]
            self.assertEqual(args,('localhost',4173));self.assertEqual(kwargs['timeout'],5)
            self.assertEqual(kwargs['context'].verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(kwargs['context'].check_hostname)

    def test_probe_refuses_redirect_tampering_bad_headers_and_unenrolled_access(self):
        body=b'synthetic shell'
        for options in ({'code':307},{'headers':{}},{'access':{**status(),'enrollment_required':True}},
                        {'access':{**status(),'csrf':'private-synthetic-token'}}):
            with self.subTest(options=options):
                factory,_=responses(body,**options)
                with patch('onejournal.mac_release_check.http.client.HTTPSConnection',factory),self.assertRaises(ReleaseCheckError):
                    check_site('https://localhost:4173',index_sha256=sha256(body).hexdigest())
        factory,_=responses(body)
        with patch('onejournal.mac_release_check.http.client.HTTPSConnection',factory),self.assertRaises(ReleaseCheckError):
            check_site('https://localhost:4173',index_sha256='b'*64)

    def test_nonlocal_or_insecure_origins_fail_before_connecting(self):
        for origin in ('http://localhost:4173','https://example.test:4173','https://localhost:4173/path'):
            with self.subTest(origin=origin),patch('onejournal.mac_release_check.http.client.HTTPSConnection') as connect:
                with self.assertRaises(ValueError):check_site(origin,index_sha256='a'*64)
                connect.assert_not_called()

    def test_explicit_local_cert_requires_independent_pin_and_never_disables_tls(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-approved-cert.pem';path.write_bytes(b'synthetic certificate bytes')
            pin=sha256(path.read_bytes()).hexdigest();body=b'synthetic shell'
            for certificate,expected in ((path,None),(None,pin),(path,'b'*64)):
                with patch('onejournal.mac_release_check.http.client.HTTPSConnection') as connect,self.assertRaises(ReleaseCheckError):
                    check_site('https://localhost:4173',index_sha256=sha256(body).hexdigest(),
                               tls_cert=certificate,tls_cert_sha256=expected)
                connect.assert_not_called()
            factory,_=responses(body)
            verified_context=ssl.create_default_context()
            with patch('onejournal.mac_release_check.ssl.create_default_context',return_value=verified_context) as context, \
                 patch('onejournal.mac_release_check.http.client.HTTPSConnection',factory):
                check_site('https://localhost:4173',index_sha256=sha256(body).hexdigest(),tls_cert=path,tls_cert_sha256=pin)
            context.assert_called_once_with(cafile=str(path))
            self.assertTrue(verified_context.check_hostname)
            self.assertEqual(verified_context.verify_mode,ssl.CERT_REQUIRED)

    def test_cli_failure_is_nonzero_and_value_free(self):
        errors=io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(main(['--release-dir','/synthetic/private-path','--manifest-sha256','bad','--source-commit','bad']),1)
        self.assertNotIn('/synthetic/private-path',errors.getvalue())
        errors=io.StringIO()
        with patch('onejournal.mac_release_check.check_release',return_value={'index_sha256':'a'*64}), \
             patch('onejournal.mac_release_check.check_site',side_effect=OSError('private-synthetic-response')), \
             redirect_stderr(errors):
            self.assertEqual(main(['--release-dir','/synthetic/public','--manifest-sha256','a'*64,
                                   '--source-commit',COMMIT,'--site-origin','https://localhost:4173']),1)
        self.assertNotIn('private-synthetic-response',errors.getvalue())


class AccessStatusReadonlyTest(unittest.TestCase):
    def test_existing_status_endpoint_reads_no_financials_or_security_audit(self):
        fixture=fixtures.StaticWebTests('test_shell_assets_routes_and_redirects_are_public_but_never_private_state')
        fixture.setUp()
        try:
            before=fixture.access.con.execute('SELECT count(*) FROM access_audit').fetchone()
            response=fixture.client.get(PREFIX+'/session')
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.json()['authenticated'])
            self.assertEqual(fixture.calls,[])
            self.assertEqual(before,fixture.access.con.execute('SELECT count(*) FROM access_audit').fetchone())
            self.assertEqual(fixture.access.sessions,{})
            self.assertEqual(fixture.access.ceremonies,{})
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
