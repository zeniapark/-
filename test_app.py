import unittest
from test_private_access import ServerHarness


class WorkflowTest(unittest.TestCase):
    def test_end_to_end(self):
        site = ServerHarness()
        self.addCleanup(site.close)
        def call(path, data=None):
            status, body, _ = site.request('api/' + path, data)
            self.assertLess(status, 400, path)
            return body
        self.assertEqual(site.request('api/records')[0], 401)
        self.assertGreaterEqual(site.request('api/signup', {'email': 'bad', 'password': 'short', 'initials': 'H'})[0], 400)
        token = site.invite('agent@example.com', admin=True)
        call('signup', {'email': 'agent@example.com', 'password': 'Secure123!', 'initials': 'H', 'invitation_token': token})
        self.assertEqual(call('me')['user']['initials'], 'H')
        base = {'date': '2026-10-30', 'market': '네이버', 'category': '제품', 'content': '제품 문의', 'order_no': 'ORDER-1', 'user_id': 999}
        call('records', {**base, 'kind': '문의글'})
        call('records', {**base, 'kind': '유선', 'phone': '010-1234-5678'})
        call('records', {**base, 'kind': '반품', 'category': '설치불가', 'code': '착하반품', 'customer': '김금화', 'logistics': '0009314025', 'completed': '2026-10-30', 'after_ship': True})
        rows = call('records')
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['initials'] == 'H' and r['user_id'] != 999 for r in rows))
        self.assertEqual(sum(r['after_ship'] for r in rows), 1)
        self.assertIn('다운로드 담당자', call('export', {'ids': [r['id'] for r in rows]})['csv'])
        call('logout', {})
        self.assertEqual(site.request('api/records')[0], 401)
        call('login', {'email': 'agent@example.com', 'password': 'Secure123!'})
        self.assertEqual(len(call('records')), 3)
        invitation = call('invitations', {'email': 'other@example.com'})
        call('signup', {'email': 'other@example.com', 'password': 'Secure456!', 'initials': 'K', 'invitation_token': invitation['invitation_token']})
        self.assertEqual(call('me')['user']['initials'], 'K')
        call('records', {**base, 'kind': '문의글', 'content': '=SUM(1,2)'})
        rows = call('records')
        self.assertEqual(sum(r['initials'] == 'K' for r in rows), 1)
        self.assertIn("'=SUM", call('export', {'ids': [r['id'] for r in rows]})['csv'])
        self.assertGreaterEqual(site.request('api/records', {**base, 'kind': '반품', 'category': '잘못된 값'})[0], 400)


if __name__ == '__main__':
    unittest.main()
