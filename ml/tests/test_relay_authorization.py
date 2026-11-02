import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from aquamind_ml.api import create_app


class RelayAuthorizationTests(unittest.TestCase):
    def test_backend_requires_host_key_and_preserves_independent_session_auth(self):
        secret = 'server-test-key-' * 3
        env = {'AQUAMIND_RELAY_REQUIRED': '1', 'AQUAMIND_RELAY_SECRET': secret,
               'AQUAMIND_INFERENCE_ENABLED': '0', 'AQUAMIND_AGENT_ENABLED': '0',
               'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_DETECTOR_PATH': ''}
        with patch.dict(os.environ, env), TestClient(create_app()) as client:
            for headers in ({}, {'X-AquaMind-Relay-Key': 'wrong'},
                            [('X-AquaMind-Relay-Key', secret), ('X-AquaMind-Relay-Key', secret)]):
                result = client.post('/v1/sessions', headers=headers)
                self.assertEqual(result.status_code, 401)
                self.assertNotIn(secret, result.text)
            self.assertEqual(client.get('/health').status_code, 200)
            relay = {'X-AquaMind-Relay-Key': secret}
            created = client.post('/v1/sessions', headers=relay)
            self.assertEqual(created.status_code, 201)
            token = created.json()['session_token']
            body = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                    'usage': '8.5', 'usage_unit': 'ccf'}
            self.assertEqual(client.post('/v1/bills/normalize', headers=relay, json=body).status_code, 401)
            self.assertEqual(client.post('/v1/bills/normalize',
                headers={'Authorization': 'Bearer ' + token}, json=body).status_code, 401)
            result = client.post('/v1/bills/normalize',
                headers=relay | {'Authorization': 'Bearer ' + token}, json=body)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['us_gallons_per_day'], '211.948052')
            self.assertNotIn(secret, result.text)

    def test_required_missing_or_malformed_keys_fail_startup(self):
        for required, secret in (('1', ''), ('1', 'short'), ('1', ' ' * 40), ('invalid', '')):
            with patch.dict(os.environ, {'AQUAMIND_RELAY_REQUIRED': required, 'AQUAMIND_RELAY_SECRET': secret}):
                with self.assertRaises(ValueError):
                    with TestClient(create_app()):
                        pass
