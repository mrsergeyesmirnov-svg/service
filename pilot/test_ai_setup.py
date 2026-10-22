"""Run with python -m unittest test_ai_setup; uses only synthetic credentials."""
import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import HTTPServer
import ai_setup_web as app

class SetupTest(unittest.TestCase):
    def test_one_use_origin_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            app.ROOT = Path(directory)
            server = HTTPServer(('127.0.0.1', 0), app.Handler)
            server.keyhash = hashlib.sha256(b'test-access').hexdigest()
            server.expires = time.time() + 60
            server.next_try = 0
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def post(access, origin, value):
                connection = http.client.HTTPConnection(*server.server_address)
                connection.request('POST', '/ai-setup/save', json.dumps(value), {'Authorization':'Bearer '+access, 'Origin':origin})
                response = connection.getresponse()
                status, body = response.status, response.read()
                connection.close()
                return status, body
            try:
                data = {'key':'synthetic-key-for-testing-only', 'folder':'synthetic-folder'}
                self.assertEqual(post('wrong', app.ORIGIN, data)[0], 403)
                self.assertEqual(post('test-access', 'https://other.invalid', data)[0], 403)
                self.assertEqual(post('test-access', app.ORIGIN, {'key':data['key']+'\nEVIL=1','folder':data['folder']})[0], 422)
                self.assertFalse((app.ROOT/'ai.env').exists())
                server.next_try = 0
                status, body = post('test-access', app.ORIGIN, data)
                self.assertEqual(status, 200)
                self.assertNotIn(data['key'].encode(), body)
                self.assertEqual((app.ROOT/'ai.env').stat().st_mode & 0o777, 0o600)
                self.assertEqual(post('test-access', app.ORIGIN, data)[0], 410)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
