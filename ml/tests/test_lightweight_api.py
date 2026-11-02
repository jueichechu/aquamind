import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from aquamind_ml.api import create_app


class LightweightApiTests(unittest.TestCase):
    def test_bill_and_mcp_service_runs_when_torch_imports_are_forbidden(self):
        # A separate interpreter ensures earlier ML tests cannot hide eager imports.
        script = textwrap.dedent('''
            import asyncio, importlib.abc, sys
            class NoTorch(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'torch' or fullname.startswith('torch.'):
                        raise AssertionError('Torch must not load in the lightweight service')
            sys.meta_path.insert(0, NoTorch())
            from fastapi.testclient import TestClient
            from aquamind_ml.api import create_app
            from aquamind_ml.mcp_server import create_server
            from mcp import Client
            with TestClient(create_app()) as client:
                assert client.get('/health').status_code == 200
                assert client.get('/ready').status_code == 503
                token = client.post('/v1/sessions').json()['session_token']
                headers = {'Authorization': 'Bearer ' + token}
                result = client.post('/v1/bills/normalize', headers=headers, json={
                    'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                    'usage': '8.5', 'usage_unit': 'ccf'})
                assert result.status_code == 200
                assert result.json()['us_gallons_per_day'] == '211.948052'
            async def tools():
                async with Client(create_server(None, frozenset({'utility:read'}))) as client:
                    result = await client.call_tool('estimate_water_cost', {'request': {'gallons': 1000}})
                    assert not result.is_error
            asyncio.run(tools())
            assert 'torch' not in sys.modules
            print('Lightweight API and actual MCP tool execution passed without Torch.')
        ''')
        env = os.environ | {'AQUAMIND_INFERENCE_ENABLED': '0', 'AQUAMIND_AGENT_ENABLED': '0',
                            'AQUAMIND_PUBLIC_MODE': '0', 'AQUAMIND_DETECTOR_PATH': '',
                            'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('passed without Torch', result.stdout)

    def test_invalid_or_conflicting_inference_settings_fail_startup(self):
        for mode, detector in (('invalid', ''), ('0', '/configured-detector')):
            with patch.dict(os.environ, {'AQUAMIND_INFERENCE_ENABLED': mode,
                                         'AQUAMIND_DETECTOR_PATH': detector}):
                with self.assertRaises(ValueError):
                    with TestClient(create_app()):
                        pass
