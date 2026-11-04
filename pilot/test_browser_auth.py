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

import os
import test_pilot

@unittest.skipUnless(os.getenv('DATABASE_URL'), 'requires isolated PostgreSQL schema')
class BrowserIntegration(unittest.TestCase):
    setUp = test_pilot.Integration.setUp
    tearDown = test_pilot.Integration.tearDown
    auth = test_pilot.Integration.auth

    def test_invite_approval_permissions_and_logout(self):
        _RATE.clear()
        owner = self.auth(999)
        invite = self.client.post('/api/invites', json={'role':'trainee'}, headers=owner).json()['browser_url'].split('invite=')[1]
        payload = {'invite':invite, 'name':'Browser Student', 'password':'Long password 2026!'}
        response = self.client.post('/api/browser/register', json=payload)
        self.assertEqual(response.status_code,200,response.text)
        uid = response.json()['staff_id']
        self.assertLess(abs(uid),2**53)
        login = {'staff_id':str(uid),'password':payload['password']}
        self.assertEqual(self.client.post('/api/browser/login',json=login).status_code,403)
        self.assertEqual(self.client.post('/api/browser/register',json=payload).status_code,403)
        self.assertEqual(self.client.post(f'/api/team/{uid}/approve',headers=self.auth(103)).status_code,403)
        self.assertEqual(self.client.post(f'/api/team/{uid}/approve',headers=owner).status_code,200)
        response=self.client.post('/api/browser/login',json=login)
        self.assertEqual(response.status_code,200,response.text)
        headers={'Authorization':'Bearer '+response.json()['token']}
        self.assertEqual(self.client.get('/api/team',headers=headers).status_code,403)
        self.assertEqual(self.client.post('/api/browser/logout',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/courses',headers=headers).status_code,401)

    def test_existing_identity_password_rotation_and_blocking(self):
        _RATE.clear()
        old=self.auth(101)
        payload={'password':'Long password 2026!'}
        self.assertEqual(self.client.post('/api/browser/enable',headers=old,json=payload).status_code,200)
        self.assertEqual(self.client.get('/api/courses',headers=old).status_code,401)
        response=self.client.post('/api/browser/login',json={'staff_id':'101',**payload})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['id'],101)
        headers={'Authorization':'Bearer '+response.json()['token']}
        import server
        with server.db() as c:c.execute('UPDATE staff SET active=false WHERE id=101')
        self.assertEqual(self.client.get('/api/courses',headers=headers).status_code,401)

    def test_bad_ids_and_login_lock(self):
        _RATE.clear()
        headers=self.auth(101)
        self.client.post('/api/browser/enable',headers=headers,json={'password':'Long password 2026!'})
        for uid in ['--1','9999999999999999999']:
            self.assertEqual(self.client.post('/api/browser/login',json={'staff_id':uid,'password':'wrong'}).status_code,401)
        for _ in range(5):
            self.assertEqual(self.client.post('/api/browser/login',json={'staff_id':'101','password':'wrong'}).status_code,401)
        self.assertEqual(self.client.post('/api/browser/login',json={'staff_id':'101','password':'Long password 2026!'}).status_code,429)

    def test_setup_link_single_use_expiry_and_identity(self):
        import hashlib, server
        _RATE.clear()
        old = self.auth(101)
        token = 'a' * 43
        with server.db() as c:
            c.execute("INSERT INTO browser_password_setup VALUES(%s,%s,now()+interval '30 minutes')", (101,hashlib.sha256(token.encode()).hexdigest()))
        payload={'token':token,'password':'Long password 2026!', 'staff_id':999}
        self.assertEqual(self.client.post('/api/browser/setup-password',json={**payload,'token':'b'*43}).status_code,403)
        self.assertEqual(self.client.post('/api/browser/setup-password',json={**payload,'password':'short'}).status_code,422)
        response=self.client.post('/api/browser/setup-password',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['staff_id'],101)
        self.assertEqual(self.client.get('/api/courses',headers=old).status_code,401)
        self.assertEqual(self.client.post('/api/browser/setup-password',json=payload).status_code,403)
        self.assertEqual(self.client.post('/api/browser/login',json={'staff_id':'101','password':payload['password']}).status_code,200)
        with server.db() as c:
            c.execute("INSERT INTO browser_password_setup VALUES(%s,%s,now()-interval '1 minute')", (101,hashlib.sha256(token.encode()).hexdigest()))
        self.assertEqual(self.client.post('/api/browser/setup-password',json=payload).status_code,403)
        with server.db() as c:
            c.execute("UPDATE browser_password_setup SET expires_at=now()+interval '30 minutes'")
            c.execute("UPDATE staff SET active=false WHERE id=101")
        self.assertEqual(self.client.post('/api/browser/setup-password',json=payload).status_code,403)
        self.assertEqual(self.client.get('/pilot/setup-password').status_code,200)
