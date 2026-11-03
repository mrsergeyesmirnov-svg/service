"""Security regression checks for browser fallback. Run: python -m unittest pilot/test_browser_auth.py"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from fastapi import HTTPException
from browser_auth import password_hash, verify, throttle, _RATE

class BrowserSecurityTests(unittest.TestCase):
    def setUp(self):
        _RATE.clear()

    def test_password_salted_and_verifiable(self):
        a = password_hash("Correct Horse Battery 2026!")
        b = password_hash("Correct Horse Battery 2026!")
        self.assertNotEqual(a, b)
        self.assertTrue(verify("Correct Horse Battery 2026!", a))
        self.assertFalse(verify("wrong password", a))

    def test_short_password_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            password_hash("short")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_malformed_hash_rejected(self):
        self.assertFalse(verify("any", "not-a-hash"))

    def test_burst_throttle(self):
        req = SimpleNamespace(client=SimpleNamespace(host="198.51.100.2"))
        for _ in range(15):
            throttle(req)
        with self.assertRaises(HTTPException) as ctx:
            throttle(req)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_throttle_separates_clients(self):
        a = SimpleNamespace(client=SimpleNamespace(host="198.51.100.2"))
        b = SimpleNamespace(client=SimpleNamespace(host="198.51.100.3"))
        for _ in range(15):
            throttle(a)
        throttle(b)

if __name__ == "__main__":
    unittest.main()
