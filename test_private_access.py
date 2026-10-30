"""Private-access tests use temporary databases and never touch application data."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent


class ServerHarness:
    def __init__(self, seed=None):
        self.tmp = tempfile.TemporaryDirectory(prefix='hanaro-test-')
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        if seed:
            seed(self.db)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.env = {**os.environ, 'CS_DB': str(self.db), 'PORT': str(self.port), 'CS_SECURE_COOKIE': '0'}
        self.base = f'http://127.0.0.1:{self.port}/'
        self.client = self.new_client()
        self.proc = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT, env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.proc.poll() is not None:
                self.close()
                raise RuntimeError('Temporary application server exited before readiness')
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.2):
                    pass
                self.request('api/me')
                break
            except OSError:
                time.sleep(.05)
        else:
            self.close()
            raise RuntimeError('Temporary application server did not become ready')

    @staticmethod
    def new_client():
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None, client=None):
        req = urllib.request.Request(self.base + path,
            None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            response = (client or self.client).open(req)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read().decode()
            body = json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
            return response.status, body, response.headers

    def cli(self, *args):
        completed = subprocess.run([sys.executable, 'manage.py', *args], cwd=ROOT, env=self.env,
                                   capture_output=True, text=True, check=True)
        return json.loads(completed.stdout)

    def invite(self, email, admin=False):
        return self.cli('invite', email, *(['--admin'] if admin else []))['invitation_token']

    def signup(self, email, token, client=None):
        return self.request('api/signup', {'email': email, 'password': 'Private123!',
            'initials': 'H', 'invitation_token': token}, client=client)

    def bootstrap(self):
        email = 'owner@example.com'
        status, _, _ = self.signup(email, self.invite(email, admin=True))
        if status != 200:
            raise AssertionError('Bootstrap administrator signup failed')

    def close(self):
        if getattr(self, 'proc', None) is not None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self.tmp.cleanup()


class PrivateAccessTest(unittest.TestCase):
    def setUp(self):
        self.site = ServerHarness()
        self.addCleanup(self.site.close)

    def test_anonymous_denied_and_noindex_headers(self):
        for path, data in [('api/records', None), ('api/export', {'ids': []}),
                           ('api/invitations', None), ('api/invitations', {'email': 'a@example.com'}),
                           ('api/users', None), ('api/users/access', {'id': 1, 'approved': True})]:
            status, _, headers = self.site.request(path, data)
            self.assertEqual(status, 401, path)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn('noindex', headers['X-Robots-Tag'])
        status, body, headers = self.site.request('robots.txt')
        self.assertEqual(status, 200)
        self.assertIn('Disallow: /', body)
        self.assertIn('noindex', headers['X-Robots-Tag'])
        _, _, headers = self.site.request('')
        self.assertIn('noindex', headers['X-Robots-Tag'])
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_repeated_login_failures_are_rate_limited(self):
        credentials = {'email': 'unknown@example.com', 'password': 'Wrong123!'}
        for _ in range(10):
            self.assertEqual(self.site.request('api/login', credentials)[0], 401)
        status, body, _ = self.site.request('api/login', credentials)
        self.assertEqual(status, 429)
        self.assertIn('15분', body['error'])

    def test_signup_requires_valid_email_bound_single_use_invitation(self):
        self.assertEqual(self.site.signup('member@example.com', '')[0], 403)
        self.assertEqual(self.site.signup('member@example.com', 'not-a-valid-token')[0], 403)
        token = self.site.invite('member@example.com')
        self.assertEqual(self.site.signup('intruder@example.com', token)[0], 403)
        status, _, _ = self.site.request('api/signup', {'email': 'member@example.com',
            'password': 'Private123!', 'initials': 'H', 'invitation_token': token,
            'is_admin': True, 'approved': True})
        self.assertEqual(status, 200)
        self.assertEqual(self.site.request('api/me')[1]['user']['is_admin'], 0)
        self.site.request('api/logout', {})
        self.assertEqual(self.site.signup('member@example.com', token)[0], 403)
        with sqlite3.connect(self.site.db) as c:
            stored = c.execute('SELECT token_hash FROM invitations').fetchone()[0]
            self.assertTrue(stored != token, 'Invitation secrets must not be stored as plaintext')

    def test_one_invitation_cannot_be_consumed_concurrently(self):
        token = self.site.invite('race@example.com')
        def register(_):
            return self.site.signup('race@example.com', token, self.site.new_client())[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(register, range(2)))
        self.assertEqual(sorted(statuses), [200, 403])
        with sqlite3.connect(self.site.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_expired_and_revoked_invites_cannot_register(self):
        self.site.bootstrap()
        status, invite, _ = self.site.request('api/invitations', {'email': 'expired@example.com'})
        self.assertEqual(status, 201)
        with sqlite3.connect(self.site.db) as c:
            c.execute('UPDATE invitations SET expires=? WHERE email=?',
                      ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), 'expired@example.com'))
        self.assertEqual(self.site.signup('expired@example.com', invite['invitation_token'])[0], 403)
        _, invite, _ = self.site.request('api/invitations', {'email': 'revoked@example.com'})
        _, rows, _ = self.site.request('api/invitations')
        row = next(item for item in rows if item['email'] == 'revoked@example.com')
        self.assertTrue(all('invitation_token' not in item and 'token_hash' not in item for item in rows))
        self.assertEqual(self.site.request('api/invitations/revoke', {'id': row['id']})[0], 200)
        self.assertEqual(self.site.signup('revoked@example.com', invite['invitation_token'])[0], 403)

    def test_admin_and_member_permissions_and_account_blocking(self):
        self.site.bootstrap()
        _, admin_me, _ = self.site.request('api/me')
        self.assertEqual(admin_me['user']['is_admin'], 1)
        admin_id = admin_me['user']['id']
        status, invite, _ = self.site.request('api/invitations', {'email': 'member@example.com'})
        self.assertEqual(status, 201)
        member = self.site.new_client()
        self.assertEqual(self.site.signup('member@example.com', invite['invitation_token'], member)[0], 200)
        member_id = self.site.request('api/me', client=member)[1]['user']['id']
        for path, data in [('api/invitations', None), ('api/invitations', {'email': 'outsider@example.com'}),
                           ('api/users', None), ('api/users/access', {'id': admin_id, 'approved': False})]:
            self.assertEqual(self.site.request(path, data, member)[0], 403, path)
        _, users, _ = self.site.request('api/users')
        self.assertEqual(len(users), 2)
        self.assertTrue(all('salt' not in row and 'password' not in row for row in users))
        self.assertEqual(self.site.request('api/users/access', {'id': admin_id, 'approved': False})[0], 400)
        self.assertEqual(self.site.request('api/users/access', {'id': member_id, 'approved': False})[0], 200)
        self.assertEqual(self.site.request('api/me', client=member)[1]['user'], None)
        self.assertEqual(self.site.request('api/records', client=member)[0], 401)
        self.assertEqual(self.site.request('api/login', {'email': 'member@example.com', 'password': 'Private123!'}, member)[0], 403)
        self.assertEqual(self.site.request('api/users/access', {'id': member_id, 'approved': True})[0], 200)
        self.assertEqual(self.site.request('api/login', {'email': 'member@example.com', 'password': 'Private123!'}, member)[0], 200)


class ExistingAccountMigrationTest(unittest.TestCase):
    def test_existing_account_requires_explicit_approval(self):
        password = 'Legacy123!'
        salt = secrets.token_hex(16)
        hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        def seed(db):
            with sqlite3.connect(db) as c:
                c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,initials TEXT NOT NULL,salt TEXT NOT NULL,password TEXT NOT NULL);
CREATE TABLE sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires TEXT);''')
                c.execute('INSERT INTO users(email,initials,salt,password) VALUES(?,?,?,?)',
                          ('legacy@example.com', 'L', salt, hashed))
                c.execute('INSERT INTO sessions VALUES(?,?,?)', ('old-session', 1,
                    (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        site = ServerHarness(seed)
        self.addCleanup(site.close)
        self.assertEqual(site.request('api/login', {'email': 'legacy@example.com', 'password': password})[0], 403)
        req = urllib.request.Request(site.base+'api/records', headers={'Cookie': 'session=old-session'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            site.client.open(req)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        site.cli('approve', 'legacy@example.com', '--admin')
        self.assertEqual(site.request('api/login', {'email': 'legacy@example.com', 'password': password})[0], 200)
        me = site.request('api/me')[1]['user']
        self.assertEqual(me['is_admin'], 1)
        with sqlite3.connect(site.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
