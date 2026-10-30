import http.client
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subscription_server import make_server
from traffic import StatisticsUnavailable

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server({'timezone': 'UTC'}, {'mode':'ws','domain':'example.com','https_port':443,'uuid':'test'}, 'secret', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def request(self, method, path):
        conn = http.client.HTTPConnection(*self.server.server_address)
        conn.request(method, path)
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp, data
    def test_get_head_and_auth(self):
        with patch('subscription_server.query_usage', return_value={'upload':0,'download':20,'total':100,'next_reset':1}):
            res, body = self.request('GET', '/subscription/secret')
            self.assertEqual(res.status, 200)
            self.assertEqual(res.getheader('subscription-userinfo'), 'upload=0; download=20; total=100')
            self.assertIn(b'MATCH,Proxy', body)
            res, body = self.request('HEAD', '/subscription/secret')
            self.assertEqual((res.status, body), (200, b''))
        res, _ = self.request('GET', '/subscription/wrong')
        self.assertEqual(res.status, 404)
    def test_failure(self):
        with patch('subscription_server.query_usage', side_effect=StatisticsUnavailable()):
            res, _ = self.request('GET', '/subscription/secret')
            self.assertEqual(res.status, 503)
