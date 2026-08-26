# -*- coding: utf-8 -*-
from unittest import mock

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

from odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth import AkahuOAuthController, OAUTH_STATE_SESSION_KEY


@tagged('post_install', '-at_install')
class TestPatch5AkahuOAuth(TransactionCase):

    class _FakeSession(dict):
        def __init__(self, uid):
            super().__init__()
            self.uid = uid

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env['akahu.credential'].sudo()
        cls.AccountModel = cls.env['akahu.account'].sudo()
        cls.JournalModel = cls.env['account.journal'].sudo()
        cls.WizardModel = cls.env['akahu.oauth.account.select.wizard'].sudo()
        cls.OptionModel = cls.env['akahu.oauth.account.select.wizard.option'].sudo()

        cls.company = cls.env.company
        cls.credential = cls.Credential.search([('company_id', '=', cls.company.id)], limit=1)
        if not cls.credential:
            cls.credential = cls.Credential.create({
                'company_id': cls.company.id,
                'app_token': 'app_token_patch5_test',
                'user_access_token': 'user_token_patch5_test',
                'app_secret': 'app_secret_patch5_test',
                'oauth_redirect_uri': 'https://example.nz/nz_bank_reconciliation/akahu/oauth/callback',
            })
        else:
            cls.credential.write({
                'app_token': 'app_token_patch5_test',
                'user_access_token': 'user_token_patch5_test',
                'app_secret': 'app_secret_patch5_test',
                'oauth_redirect_uri': 'https://example.nz/nz_bank_reconciliation/akahu/oauth/callback',
            })

    def _make_account(self, suffix='base'):
        journal = self.JournalModel.create({
            'name': 'PATCH5 Journal %s' % suffix,
            'code': ('P5%s' % suffix.upper())[:5],
            'type': 'bank',
            'company_id': self.company.id,
        })
        return self.AccountModel.create({
            'company_id': self.company.id,
            'credential_id': self.credential.id,
            'journal_id': journal.id,
        })

    def test_oauth_authorization_url_contains_required_params(self):
        url = self.credential._build_oauth_authorization_url('state123')
        self.assertIn('https://oauth.akahu.nz?', url)
        self.assertIn('response_type=code', url)
        self.assertIn('client_id=', url)
        self.assertIn('redirect_uri=', url)
        self.assertIn('scope=ENDURING_CONSENT', url)
        self.assertIn('state=state123', url)

    def test_oauth_state_is_generated_securely(self):
        from odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth import _generate_oauth_state
        state = _generate_oauth_state()
        self.assertIsInstance(state, str)
        self.assertGreaterEqual(len(state), 32)

    def test_token_exchange_uses_server_side_secret_and_timeout(self):
        credential = self.credential
        captured = {}

        class Response:
            status_code = 200
            text = '{"access_token": "user_token_from_oauth"}'

            def json(self):
                return {'access_token': 'user_token_from_oauth'}

        def fake_post(url, data=None, timeout=None):
            captured['url'] = url
            captured['data'] = dict(data or {})
            captured['timeout'] = timeout
            return Response()

        with mock.patch('requests.post', side_effect=fake_post):
            token = credential._exchange_oauth_code('auth_code_123', redirect_uri=credential.oauth_redirect_uri)

        self.assertEqual(token, 'user_token_from_oauth')
        self.assertEqual(captured['url'], 'https://api.akahu.io/v1/token')
        self.assertEqual(captured['data']['grant_type'], 'authorization_code')
        self.assertEqual(captured['data']['code'], 'auth_code_123')
        self.assertEqual(captured['data']['redirect_uri'], credential.oauth_redirect_uri)
        self.assertEqual(captured['timeout'], 30)
        self.assertEqual(captured['data']['client_id'], credential._get_app_token())
        self.assertEqual(captured['data']['client_secret'], credential._get_app_secret())

    def test_oauth_authorization_requires_app_secret(self):
        credential = self.credential.copy({
            'company_id': self.company.id,
            'app_token': 'app_token_patch5_secret_required',
            'app_secret': '',
            'oauth_redirect_uri': 'https://example.nz/nz_bank_reconciliation/akahu/oauth/callback',
        })
        with self.assertRaisesRegex(Exception, 'App Secret is required'):
            credential._build_oauth_authorization_url('state123')

    def test_existing_encrypted_token_storage_is_reused(self):
        credential = self.Credential.create({
            'company_id': self.company.id,
            'app_token': 'app_token_patch5_encrypt',
            'user_access_token': 'user_token_patch5_encrypt',
            'app_secret': 'app_secret_patch5_encrypt',
            'oauth_redirect_uri': 'https://example.nz/nz_bank_reconciliation/akahu/oauth/callback',
        })
        self.assertTrue(credential.app_token.startswith('gcm1:'))
        self.assertTrue(credential.user_access_token.startswith('gcm1:'))
        self.assertTrue(credential.app_secret.startswith('gcm1:'))

    def test_accounts_fetch_uses_existing_api_headers(self):
        captured = {}

        def fake_api_get(user_token, path, params=None):
            captured['user_token'] = user_token
            captured['path'] = path
            return {'items': [
                {
                    '_id': 'acc_123',
                    'name': 'Everyday',
                    'formatted_account': '12-3456-7890123-00',
                    'connection': {'name': 'ANZ'},
                },
            ]}

        with mock.patch.object(type(self.credential), '_api_get', side_effect=fake_api_get):
            items = self.credential._fetch_oauth_accounts('user_token_oauth_123')

        self.assertEqual(captured['user_token'], 'user_token_oauth_123')
        self.assertEqual(captured['path'], '/accounts')
        self.assertEqual(items[0]['_id'], 'acc_123')

    def test_wizard_persists_selected_akahu_account_id(self):
        account = self._make_account('select')
        wizard = self.WizardModel.create({
            'credential_id': self.credential.id,
            'account_id': account.id,
        })
        option = self.OptionModel.create({
            'wizard_id': wizard.id,
            'akahu_account_id': 'acc_selected_123',
            'display_name': 'ANZ - 12-3456-7890123-00',
            'bank_name': 'ANZ',
            'account_name': 'Everyday',
            'formatted_account': '12-3456-7890123-00',
            'akahu_status': 'ACTIVE',
        })
        wizard.write({'selected_option_id': option.id})

        wizard.action_save()
        self.assertEqual(account.akahu_account_id, 'acc_selected_123')
        self.assertEqual(account.bank_name, 'ANZ')
        self.assertEqual(account.akahu_account_name, 'Everyday')
        self.assertEqual(account.akahu_formatted_account, '12-3456-7890123-00')
        self.assertEqual(account.akahu_status, 'ACTIVE')

    def test_authorization_url_does_not_expose_secret_values(self):
        url = self.credential._build_oauth_authorization_url('state-secret')
        self.assertNotIn('app_secret_patch5', url)
        self.assertNotIn('user_token_patch5', url)

    def test_callback_rejects_invalid_state(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
        }
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            response = controller.akahu_oauth_callback(state='wrong-state', code='code123')

        self.assertIn('Invalid OAuth state', response)

    def test_callback_handles_missing_authorization_code(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
        }
        credential_record = mock.MagicMock()
        credential_record.exists.return_value = credential_record
        credential_record.company_id.id = self.company.id
        fake_env = mock.MagicMock()
        fake_env.__getitem__.return_value.sudo.return_value.browse.return_value = credential_record
        fake_request.env = fake_env
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            response = controller.akahu_oauth_callback(state='expected-state')

        self.assertIn('Missing authorization code', response)

    def test_callback_handles_denied_authorization(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
        }
        credential_record = mock.MagicMock()
        credential_record.exists.return_value = credential_record
        credential_record.company_id.id = self.company.id
        fake_env = mock.MagicMock()
        fake_env.__getitem__.return_value.sudo.return_value.browse.return_value = credential_record
        fake_request.env = fake_env
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            response = controller.akahu_oauth_callback(state='expected-state', error='access_denied')

        self.assertIn('Akahu OAuth cancelled', response)

    def test_callback_response_escapes_html(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
            'created_at': fields.Datetime.now(),
        }
        credential_record = mock.MagicMock()
        credential_record.exists.return_value = credential_record
        credential_record.company_id.id = self.company.id
        fake_env = mock.MagicMock()
        fake_env.__getitem__.return_value.sudo.return_value.browse.return_value = credential_record
        fake_request.env = fake_env
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            response = controller.akahu_oauth_callback(
                state='expected-state',
                error='bad',
                error_description='<script>alert(1)</script>',
            )

        self.assertNotIn('<script>', response)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', response)

    def test_callback_rejects_expired_state(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
            'created_at': '2000-01-01 00:00:00',
        }
        credential_record = mock.MagicMock()
        credential_record.exists.return_value = credential_record
        credential_record.company_id.id = self.company.id
        fake_env = mock.MagicMock()
        fake_env.__getitem__.return_value.sudo.return_value.browse.return_value = credential_record
        fake_request.env = fake_env
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            response = controller.akahu_oauth_callback(state='expected-state', code='code123')

        self.assertIn('OAuth session expired', response)

    def test_callback_handles_zero_accounts(self):
        controller = AkahuOAuthController()
        fake_request = mock.MagicMock()
        fake_request.session = self._FakeSession(self.env.uid)
        fake_request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': 'expected-state',
            'credential_id': self.credential.id,
            'company_id': self.company.id,
            'user_id': self.env.uid,
            'redirect_uri': self.credential.oauth_redirect_uri,
            'created_at': '2000-01-01 00:00:00',
        }
        credential_record = mock.MagicMock()
        credential_record.exists.return_value = credential_record
        credential_record.company_id.id = self.company.id
        fake_env = mock.MagicMock()
        fake_env.__getitem__.return_value.sudo.return_value.browse.return_value = credential_record
        fake_request.env = fake_env
        fake_request.make_response.side_effect = lambda body, headers=None: body

        with mock.patch('odoo.addons.nz_bank_reconciliation.controllers.akahu_oauth.request', fake_request):
            with mock.patch.object(type(self.credential), '_exchange_oauth_code', return_value='user_token_x'):
                with mock.patch.object(type(self.credential), '_fetch_oauth_accounts', return_value=[]):
                    response = controller.akahu_oauth_callback(state='expected-state', code='code123')

        self.assertIn('did not return any connected accounts', response)

    def test_wizard_rejects_option_from_other_wizard(self):
        account = self._make_account('foreign_option')
        wizard_a = self.WizardModel.create({
            'credential_id': self.credential.id,
            'account_id': account.id,
        })
        wizard_b = self.WizardModel.create({
            'credential_id': self.credential.id,
            'account_id': account.id,
        })
        foreign_option = self.OptionModel.create({
            'wizard_id': wizard_b.id,
            'akahu_account_id': 'acc_foreign_123',
            'display_name': 'Foreign option',
        })
        wizard_a.write({'selected_option_id': foreign_option.id})

        with self.assertRaisesRegex(ValidationError, 'does not belong to this OAuth session'):
            wizard_a.action_save()
