# -*- coding: utf-8 -*-
from unittest import mock

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPatch4Phase3BSyncIntegration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['akahu.sync.engine']
        cls.SyncRun = cls.env['akahu.sync.run'].sudo()
        cls.SyncState = cls.env['akahu.sync.state'].sudo()
        cls.Credential = cls.env['akahu.credential'].sudo()
        cls.AccountModel = cls.env['akahu.account'].sudo()
        cls.JournalModel = cls.env['account.journal'].sudo()
        cls.LineModel = cls.env['account.bank.statement.line'].sudo()
        cls.IdentityModel = cls.env['akahu.transaction.identity'].sudo()
        cls.FindingModel = cls.env['akahu.duplicate.finding'].sudo()

        cls.company = cls.env.company
        cls._journal_seq = 0

        cls.credential = cls.Credential.search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.credential:
            cls.credential = cls.Credential.create({
                'company_id': cls.company.id,
                'app_token': 'app_token_patch4_phase3b_test',
                'user_access_token': 'user_token_patch4_phase3b_test',
            })

    @classmethod
    def _next_journal(cls, suffix):
        cls._journal_seq += 1
        code = ('B%04d' % cls._journal_seq)
        return cls.JournalModel.create({
            'name': 'PATCH4 Phase3B %s %d' % (suffix, cls._journal_seq),
            'code': code,
            'type': 'bank',
            'company_id': cls.company.id,
        })

    def _make_account(self, suffix='base'):
        journal = self._next_journal(suffix)
        return self.AccountModel.create({
            'company_id': self.company.id,
            'credential_id': self.credential.id,
            'journal_id': journal.id,
            'akahu_account_id': 'acc_patch4_%s' % suffix,
            'akahu_status': 'ACTIVE',
        })

    def _tx(self, tx_id, tx_date='2026-08-12T01:02:03Z', amount=-1250.0, description='Payment', meta=None, migrated=False):
        tx = {
            '_id': tx_id,
            'date': tx_date,
            'description': description,
            'amount': amount,
            'meta': meta or {
                'particulars': 'Client',
                'code': 'PAY',
                'reference': 'PAYMENT',
                'other_account': 'ABC',
            },
            'type': 'TRANSFER',
        }
        if migrated:
            tx['_migrated'] = migrated
        return tx

    def _payload(self, items, current='cur_current', nxt=None):
        return {
            'items': items,
            'cursor': {
                'current': current,
                'next': nxt,
            },
        }

    def _line_count(self, journal):
        return self.LineModel.search_count([
            ('journal_id', '=', journal.id),
            ('unique_import_id', 'like', 'akahu-%'),
        ])

    def _identity_count(self, journal):
        return self.IdentityModel.search_count([
            ('journal_id', '=', journal.id),
        ])

    def _create_existing_line_and_identity(self, journal, tx_id='old_tx_a'):
        meta = {
            'particulars': 'Client',
            'code': 'PAY',
            'reference': 'PAYMENT',
            'other_account': 'ABC',
        }
        payment_ref = 'Payment | Client | PAY | PAYMENT'
        line_vals = {
            'journal_id': journal.id,
            'company_id': self.company.id,
            'date': fields.Date.from_string('2026-08-12'),
            'amount': -1250.0,
            'payment_ref': payment_ref,
            'partner_name': 'ABC',
            'unique_import_id': 'akahu-%s' % tx_id,
            'akahu_transaction_id': tx_id,
            'akahu_account_id': 'ACCOUNT_A',
            'akahu_connection_id': 'CONNECTION_A',
        }
        if 'transaction_type' in self.LineModel._fields:
            line_vals['transaction_type'] = 'TRANSFER'
        line = self.LineModel.create(line_vals)

        resolver = self.env['akahu.identity.resolver']
        incoming_sig = resolver._build_incoming_signature(
            journal,
            self._tx(tx_id, tx_date='2026-08-12T01:02:03Z', meta=meta),
            incoming_akahu_account_id='ACCOUNT_A',
            incoming_akahu_connection_id='CONNECTION_A',
        )

        identity = self.IdentityModel.create({
            'journal_id': journal.id,
            'company_id': self.company.id,
            'akahu_transaction_id': tx_id,
            'akahu_account_id': 'ACCOUNT_A',
            'akahu_connection_id': 'CONNECTION_A',
            'first_seen_akahu_account_id': 'ACCOUNT_A',
            'last_seen_akahu_account_id': 'ACCOUNT_A',
            'first_seen_akahu_connection_id': 'CONNECTION_A',
            'last_seen_akahu_connection_id': 'CONNECTION_A',
            'transaction_fingerprint': incoming_sig.get('legacy_fingerprint'),
            'relation_type': 'exact_id',
            'confidence': 'low',
            'identity_match_type': 'new',
            'statement_line_id': line.id,
            'first_seen_at': fields.Datetime.now(),
            'last_seen_at': fields.Datetime.now(),
        })
        return line, identity

    def test_same_id_replay_no_duplicate_line_or_identity(self):
        account = self._make_account('same-id')
        tx = self._tx('tx_same_id')
        payload = self._payload([tx], current='cur_same_id')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                first = self.Engine.sync_account(account, trigger_source='manual_account')
                second = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(first.get('imported'), 1)
        self.assertEqual(second.get('imported'), 0)
        self.assertEqual(self._line_count(account.journal_id), 1)
        self.assertEqual(self._identity_count(account.journal_id), 1)

    def test_explicit_lineage_associates_to_existing_line(self):
        account = self._make_account('lineage')
        existing_line, _ = self._create_existing_line_and_identity(account.journal_id, tx_id='tx_old')

        tx_new = self._tx('tx_new', migrated='tx_old')
        payload = self._payload([tx_new], current='cur_lineage')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 0)
        self.assertEqual(self._line_count(account.journal_id), 1)

        new_identity = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_new'),
        ], limit=1)
        self.assertTrue(new_identity)
        self.assertEqual(new_identity.statement_line_id.id, existing_line.id)

    def test_fingerprint_high_skips_create_and_associates(self):
        account = self._make_account('fingerprint-high')
        existing_line, existing_identity = self._create_existing_line_and_identity(account.journal_id, tx_id='tx_old_fp')

        tx_new = self._tx('tx_new_fp')
        payload = self._payload([tx_new], current='cur_fp')
        resolver_result = {
            'resolution_type': 'fingerprint_high',
            'confidence': 'high',
            'existing_statement_line_id': existing_line.id,
            'existing_identity_id': existing_identity.id,
            'incoming_transaction_id': 'tx_new_fp',
            'matched_fields': ['amount', 'reference', 'other_account'],
            'conflicting_fields': [],
            'reason': 'single_candidate_with_strong_consistent_metadata',
            'candidate_count': 1,
        }

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.env['akahu.identity.resolver']), 'resolve_transaction_identity', return_value=resolver_result):
                    self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(self._line_count(account.journal_id), 1)
        associated = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_new_fp'),
        ], limit=1)
        self.assertTrue(associated)
        self.assertEqual(associated.statement_line_id.id, existing_line.id)

        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.transactions_skipped_fingerprint, 1)

    def test_possible_duplicate_creates_line_identity_and_finding(self):
        account = self._make_account('possible-dup')
        existing_line, _ = self._create_existing_line_and_identity(account.journal_id, tx_id='tx_old_pd')

        tx_new = self._tx('tx_new_pd')
        payload = self._payload([tx_new], current='cur_pd')
        resolver_result = {
            'resolution_type': 'possible_duplicate',
            'confidence': 'medium',
            'existing_statement_line_id': existing_line.id,
            'existing_identity_id': False,
            'incoming_transaction_id': 'tx_new_pd',
            'matched_fields': ['amount', 'reference'],
            'conflicting_fields': [],
            'reason': 'single_candidate_but_metadata_not_strong_enough',
            'candidate_count': 1,
        }

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.env['akahu.identity.resolver']), 'resolve_transaction_identity', return_value=resolver_result):
                    result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 1)
        self.assertEqual(self._line_count(account.journal_id), 2)

        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.possible_duplicates, 1)

        finding = self.FindingModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('incoming_akahu_transaction_id', '=', 'tx_new_pd'),
        ], limit=1)
        self.assertTrue(finding)
        self.assertEqual(finding.existing_statement_line_id.id, existing_line.id)

    def test_identity_conflict_creates_line_identity_and_finding(self):
        account = self._make_account('identity-conflict')
        existing_line, _ = self._create_existing_line_and_identity(account.journal_id, tx_id='tx_old_ic')

        tx_new = self._tx('tx_new_ic')
        payload = self._payload([tx_new], current='cur_ic')
        resolver_result = {
            'resolution_type': 'identity_conflict',
            'confidence': 'low',
            'existing_statement_line_id': existing_line.id,
            'existing_identity_id': False,
            'incoming_transaction_id': 'tx_new_ic',
            'matched_fields': ['amount', 'reference'],
            'conflicting_fields': ['other_account'],
            'reason': 'single_candidate_has_strong_field_conflicts',
            'candidate_count': 1,
        }

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.env['akahu.identity.resolver']), 'resolve_transaction_identity', return_value=resolver_result):
                    result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 1)
        self.assertEqual(self._line_count(account.journal_id), 2)

        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.identity_conflicts, 1)

        finding = self.FindingModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('incoming_akahu_transaction_id', '=', 'tx_new_ic'),
        ], limit=1)
        self.assertTrue(finding)
        self.assertIn('other_account', finding.conflicting_fields or '')

    def test_atomic_create_and_identity_registration(self):
        account = self._make_account('atomic')
        tx = self._tx('tx_atomic')
        payload = self._payload([tx], current='cur_atomic')
        resolver_result = {
            'resolution_type': 'new',
            'confidence': 'none',
            'existing_statement_line_id': False,
            'existing_identity_id': False,
            'incoming_transaction_id': 'tx_atomic',
            'matched_fields': [],
            'conflicting_fields': [],
            'reason': 'new_transaction',
            'candidate_count': 0,
        }

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.env['akahu.identity.resolver']), 'resolve_transaction_identity', return_value=resolver_result):
                    with mock.patch.object(type(self.Engine), '_register_identity_for_transaction', side_effect=RuntimeError('identity create fail')):
                        result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 0)
        self.assertEqual(result.get('failed'), 1)
        self.assertEqual(self._line_count(account.journal_id), 0)
        self.assertEqual(self._identity_count(account.journal_id), 0)

    def test_identity_uniqueness_replay(self):
        account = self._make_account('identity-uniq')
        tx = self._tx('tx_identity_unique')
        payload = self._payload([tx], current='cur_identity_unique')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                self.Engine.sync_account(account, trigger_source='manual_account')
                self.Engine.sync_account(account, trigger_source='manual_account')

        rows = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_identity_unique'),
        ])
        self.assertEqual(len(rows), 1)

    def test_repeated_reconnection_with_lineage_chain(self):
        account = self._make_account('reconnect-chain')
        existing_line, _ = self._create_existing_line_and_identity(account.journal_id, tx_id='tx_a')

        payload_b = self._payload([self._tx('tx_b', migrated='tx_a')], current='cur_chain_b')
        payload_c = self._payload([self._tx('tx_c', migrated='tx_b')], current='cur_chain_c')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=[payload_b, payload_c]):
                self.Engine.sync_account(account, trigger_source='manual_account')
                self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(self._line_count(account.journal_id), 1)

        tx_b = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_b'),
        ], limit=1)
        tx_c = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_c'),
        ], limit=1)
        self.assertTrue(tx_b)
        self.assertTrue(tx_c)
        self.assertEqual(tx_b.statement_line_id.id, existing_line.id)
        self.assertEqual(tx_c.statement_line_id.id, existing_line.id)

    def test_cursor_loss_replay_possible_duplicate_stays_visible(self):
        account = self._make_account('cursor-replay')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
        })

        self._create_existing_line_and_identity(account.journal_id, tx_id='tx_old_cursor')
        tx_new = self._tx('tx_new_cursor')
        payload = self._payload([tx_new], current='cur_cursor_replay')
        resolver_result = {
            'resolution_type': 'possible_duplicate',
            'confidence': 'medium',
            'existing_statement_line_id': self.LineModel.search([
                ('journal_id', '=', account.journal_id.id),
                ('akahu_transaction_id', '=', 'tx_old_cursor'),
            ], limit=1).id,
            'existing_identity_id': False,
            'incoming_transaction_id': 'tx_new_cursor',
            'matched_fields': ['amount', 'reference'],
            'conflicting_fields': [],
            'reason': 'replay_uncertain_identity',
            'candidate_count': 1,
        }

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.env['akahu.identity.resolver']), 'resolve_transaction_identity', return_value=resolver_result):
                    result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 1)
        self.assertEqual(self._line_count(account.journal_id), 2)
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.possible_duplicates, 1)

    def test_legacy_existing_line_is_claimed_not_duplicated(self):
        account = self._make_account('legacy-claim')
        legacy_vals = {
            'journal_id': account.journal_id.id,
            'company_id': self.company.id,
            'date': fields.Date.from_string('2026-08-12'),
            'amount': -1250.0,
            'payment_ref': 'Payment | Client | PAY | PAYMENT',
            'partner_name': 'ABC',
            'unique_import_id': False,
            'akahu_transaction_id': False,
            'akahu_account_id': False,
            'akahu_connection_id': False,
            'akahu_transaction_fingerprint': False,
        }
        if 'transaction_type' in self.LineModel._fields:
            legacy_vals['transaction_type'] = 'TRANSFER'
        legacy_line = self.LineModel.create(legacy_vals)

        tx = self._tx('tx_legacy_claim')
        payload = self._payload([tx], current='cur_legacy_claim')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('imported'), 0)
        self.assertEqual(self.LineModel.search_count([('journal_id', '=', account.journal_id.id)]), 1)

        legacy_line.invalidate_recordset([
            'akahu_transaction_id',
            'unique_import_id',
            'akahu_identity_match_type',
            'akahu_identity_confidence',
        ])
        self.assertEqual(legacy_line.akahu_transaction_id, 'tx_legacy_claim')
        self.assertEqual(legacy_line.unique_import_id, 'akahu-tx_legacy_claim')
        self.assertEqual(legacy_line.akahu_identity_match_type, 'fingerprint_high')
        self.assertEqual(legacy_line.akahu_identity_confidence, 'high')

        identity = self.IdentityModel.search([
            ('journal_id', '=', account.journal_id.id),
            ('akahu_transaction_id', '=', 'tx_legacy_claim'),
        ], limit=1)
        self.assertTrue(identity)
        self.assertEqual(identity.statement_line_id.id, legacy_line.id)
