"""Isolated Google authentication regression checks; no Google credentials needed."""
import time
import unittest
from unittest.mock import patch

from smoke_test_cases import VioletaSmokeTests, app, db, User
from models import GoogleIdentity


class GoogleAuthTests(VioletaSmokeTests):
    # Reuse only isolated fixtures, not the inherited suite below.
    def setUp(self):
        super().setUp()
        self.original_config = dict(app.config)
        app.config.update(GOOGLE_CLIENT_ID='test-client', GOOGLE_CLIENT_SECRET='test-secret',
                          GOOGLE_REDIRECT_URI='http://localhost/auth/google/callback')
        self.google = app.extensions['violeta_google_client']

    def tearDown(self):
        app.config.update(self.original_config)
        super().tearDown()

    def callback(self, client, **claims):
        payload = {'sub': 'google-subject', 'email': 'new@gmail.com', 'email_verified': True}
        payload.update(claims)
        with patch.object(self.google, 'authorize_access_token', return_value={'id_token': 'validated-test-token', 'userinfo': payload}):
            response = client.get('/auth/google/callback')
        if response.location == '/auth/google/complete':
            response = client.post('/auth/google/complete', data={'eligibility_attestation': 'y'})
        return response

    def test_google_registration_requires_attestation(self):
        client = self.client_for()
        with client.session_transaction() as state:
            state['google_signup'] = {'subject': 'new-sub', 'email': 'new@gmail.com', 'created_at': time.time()}
        response = client.post('/auth/google/complete', data={})
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_google_new_account_stays_limited_and_reuses_subject(self):
        client = self.client_for()
        self.assertEqual(self.callback(client).location, '/')
        with app.app_context():
            user = User.query.one()
            user_id = user.id
            self.assertFalse(user.is_verified)
            self.assertEqual(user.verification_status, 'unverified')
            self.assertFalse(user.roles)
            self.assertEqual(user.trial_location_views_limit, 3)
        client.get('/logout')
        self.callback(client, email='changed@gmail.com')
        with client.session_transaction() as state:
            self.assertEqual(state['_user_id'], str(user_id))
        with app.app_context():
            self.assertEqual(User.query.count(), 1)

    def test_google_existing_email_requires_password(self):
        user_id = self.create_user('existing')
        client = self.client_for()
        self.assertEqual(self.callback(client, email='existing@example.com').location, '/login')
        with client.session_transaction() as state:
            self.assertNotIn('_user_id', state)
        client.post('/login', data={'login': 'existing', 'password': 'wrong'})
        with app.app_context():
            self.assertEqual(GoogleIdentity.query.count(), 0)
        client.post('/login', data={'login': 'existing', 'password': 'Password123'})
        with app.app_context():
            self.assertEqual(GoogleIdentity.query.one().user_id, user_id)
        client.get('/logout')
        self.assertEqual(self.callback(client).location, '/')

    def test_google_wrong_account_and_expired_link_not_linked(self):
        self.create_user('existing')
        self.create_user('other')
        client = self.client_for()
        self.callback(client, email='existing@example.com')
        client.post('/login', data={'login': 'other', 'password': 'Password123'})
        with app.app_context():
            self.assertEqual(GoogleIdentity.query.count(), 0)
        client.get('/logout')
        self.callback(client, email='existing@example.com')
        with client.session_transaction() as state:
            pending = state['google_link']
            pending['created_at'] = time.time() - 601
            state['google_link'] = pending
        client.post('/login', data={'login': 'existing', 'password': 'Password123'})
        with app.app_context():
            self.assertEqual(GoogleIdentity.query.count(), 0)

    def test_google_rejects_invalid_identity_and_oauth_state(self):
        for claims in ({'email_verified': False}, {'sub': ''}, {'email': ''}):
            client = self.client_for()
            self.assertEqual(self.callback(client, **claims).location, '/login')
            with client.session_transaction() as state:
                self.assertNotIn('_user_id', state)
        client = self.client_for()
        response = client.get('/auth/google/callback?code=forged&state=forged')
        self.assertEqual(response.location, '/login')
        with app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_google_preserves_restrictions_and_forced_password_reset(self):
        client = self.client_for()
        self.callback(client)
        client.get('/logout')
        with app.app_context():
            user = User.query.one()
            user.force_password_change = True
            db.session.commit()
        self.assertEqual(self.callback(client).location, '/force-password-reset')
        client.get('/logout')
        with app.app_context():
            user = User.query.one()
            user.force_password_change = False
            from datetime import datetime, timezone
            user.permanently_banned_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
        self.assertEqual(self.callback(client).location, '/account-restricted')

    def test_google_delete_account_removes_identity(self):
        self.callback(self.client_for())
        with app.app_context():
            db.session.delete(User.query.one())
            db.session.commit()
            self.assertEqual(GoogleIdentity.query.count(), 0)

    def test_google_disabled_and_csrf_protected(self):
        client = self.client_for()
        app.config['GOOGLE_CLIENT_ID'] = ''
        self.assertEqual(client.post('/auth/google').location, '/login')
        app.config['GOOGLE_CLIENT_ID'] = 'test-client'
        app.config['WTF_CSRF_ENABLED'] = True
        with patch.object(self.google, 'authorize_redirect') as start:
            self.assertEqual(client.post('/auth/google').status_code, 400)
            start.assert_not_called()

    def test_google_real_oidc_validation_and_replay(self):
        from joserfc import jwt
        from joserfc.jwk import RSAKey
        from urllib.parse import parse_qs, urlsplit
        key = RSAKey.generate_key(parameters={'kid': 'test-key'})
        wrong_key = RSAKey.generate_key(parameters={'kid': 'test-key'})
        metadata = {
            'issuer': 'https://accounts.google.com',
            'authorization_endpoint': 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_endpoint': 'https://oauth2.googleapis.com/token',
            'id_token_signing_alg_values_supported': ['RS256'],
        }
        with patch.object(self.google, 'client_id', 'test-client'), patch.object(
            self.google, 'client_secret', 'test-secret'
        ), patch.object(self.google, 'load_server_metadata', return_value=metadata), patch.object(
            self.google, 'fetch_jwk_set', return_value={'keys': [key.as_dict()]}
        ):
            for mutation in ('valid', 'audience', 'issuer', 'expired', 'nonce', 'signature'):
                with self.subTest(mutation=mutation):
                    from smoke_test_cases import app_module
                    app_module._RATE_LIMIT_BUCKETS.clear()
                    client = self.client_for()
                    start = client.post('/auth/google', data={'remember': '1'})
                    params = parse_qs(urlsplit(start.location).query)
                    self.assertEqual(params['code_challenge_method'], ['S256'])
                    self.assertEqual(params['redirect_uri'], [app.config['GOOGLE_REDIRECT_URI']])
                    now = int(time.time())
                    claims = {'sub': 'signed-sub', 'email': 'signed@gmail.com', 'email_verified': True,
                              'iss': metadata['issuer'], 'aud': 'test-client', 'iat': now,
                              'exp': now + 300, 'nonce': params['nonce'][0]}
                    if mutation == 'audience':
                        claims['aud'] = 'another-client'
                    if mutation == 'issuer':
                        claims['iss'] = 'https://attacker.example'
                    if mutation == 'expired':
                        claims['exp'] = now - 600
                    if mutation == 'nonce':
                        claims['nonce'] = 'wrong-nonce'
                    signed = jwt.encode({'alg': 'RS256', 'kid': 'test-key'}, claims,
                                        wrong_key if mutation == 'signature' else key)
                    callback_url = '/auth/google/callback?code=test-code&state=' + params['state'][0]
                    with patch.object(self.google, 'fetch_access_token', return_value={
                        'id_token': signed, 'access_token': 'temporary-test-token', 'token_type': 'Bearer',
                    }) as exchange:
                        result = client.get(callback_url)
                        self.assertEqual(result.location, '/auth/google/complete' if mutation == 'valid' else '/login')
                        self.assertTrue(exchange.call_args.kwargs.get('code_verifier'))
                        self.assertEqual(client.get(callback_url).location, '/login')
                        self.assertEqual(exchange.call_count, 1)


if __name__ == '__main__':
    suite = unittest.TestSuite(GoogleAuthTests(name) for name in GoogleAuthTests.__dict__ if name.startswith('test_google_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
