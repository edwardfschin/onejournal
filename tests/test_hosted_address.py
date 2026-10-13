"""Focused public-domain/package binding; no DNS mutation or real credentials."""
import json
from pathlib import Path
import unittest

from scripts.web.package_hosted_release import render_caddy
from onejournal.hosted_access import validate_hosted_origin
from test_mac_passkey_access import SyntheticAuthenticator
from webauthn import generate_registration_options, generate_authentication_options, options_to_json, verify_registration_response, verify_authentication_response
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers import base64url_to_bytes

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://journal.onelumiq.com'
RP = 'journal.onelumiq.com'


class HostedAddressTests(unittest.TestCase):
    def test_public_profile_and_rendered_proxy_have_one_approved_origin(self):
        profile = json.loads((ROOT / 'config/hosted/hosted-config.example.json').read_text())
        self.assertEqual(profile['origin'], ORIGIN)
        self.assertEqual(validate_hosted_origin(profile['origin']), ORIGIN)
        template = (ROOT / 'config/hosted/Caddyfile.example').read_text()
        rendered = render_caddy(template, profile['origin'])
        self.assertIn(RP + ' {', rendered)
        self.assertIn('header_up Host ' + RP, rendered)
        self.assertNotIn('{$ONEJOURNAL_DOMAIN}', rendered)
        self.assertIn('{$ONEJOURNAL_PROXY_SECRET}', rendered)
        self.assertNotIn('OWNER-CHOSEN', rendered)

    def test_signed_synthetic_passkey_uses_selected_rp_and_rejects_other_domains(self):
        device = SyntheticAuthenticator()
        options = json.loads(options_to_json(generate_registration_options(rp_id=RP,
            rp_name='OneJournal synthetic validation', user_id=b'synthetic owner handle for testing', user_name='synthetic')))
        credential = device.credential(options, register=True, origin=ORIGIN, rp=RP)
        verified = verify_registration_response(credential=credential,
            expected_challenge=base64url_to_bytes(options['challenge']),
            expected_rp_id=RP, expected_origin=ORIGIN, require_user_verification=True)
        login = generate_authentication_options(rp_id=RP)
        login_json = json.loads(options_to_json(login))
        signed = device.credential(login_json, origin=ORIGIN, rp=RP)
        args = dict(credential=signed, expected_challenge=login.challenge,
            expected_rp_id=RP, expected_origin=ORIGIN, credential_public_key=verified.credential_public_key,
            credential_current_sign_count=verified.sign_count, require_user_verification=True)
        self.assertGreater(verify_authentication_response(**args).new_sign_count, verified.sign_count)
        for mismatch in ({'expected_origin': 'https://journal.dotheone.com'}, {'expected_rp_id': 'onelumiq.com'}):
            with self.assertRaises(WebAuthnException):
                verify_authentication_response(**{**args, **mismatch})


if __name__ == '__main__':
    unittest.main()
