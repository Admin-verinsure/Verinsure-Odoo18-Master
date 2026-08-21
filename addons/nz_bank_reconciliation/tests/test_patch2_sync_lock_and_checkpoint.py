# -*- coding: utf-8 -*-
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPatch2SyncLockAndCheckpoint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['akahu.sync.engine']
        cls.SyncState = cls.env['akahu.sync.state'].sudo()
        cls.SyncRun = cls.env['akahu.sync.run'].sudo()
        cls.Credential = cls.env['akahu.credential'].sudo()
        cls.AccountModel = cls.env['akahu.account'].sudo()
        cls.JournalModel = cls.env['account.journal'].sudo()

        cls.company = cls.env.company

        cls.credential = cls.Credential.search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.credential:
            cls.credential = cls.Credential.create({
                'company_id': cls.company.id,
                'app_token': 'app_token_patch2_test',
                'user_access_token': 'user_token_patch2_test',
            })

    def _make_account(self, suffix='base'):
        journal = self.JournalModel.create({
            'name': 'PATCH2 Journal %s' % suffix,
            'code': ('P2%s' % suffix.upper())[:5],
            'type': 'bank',
            'company_id': self.company.id,
        })
        return self.AccountModel.create({
            'company_id': self.company.id,
            'credential_id': self.credential.id,
            'journal_id': journal.id,
            'akahu_account_id': 'acc_patch2_%s' % suffix,
            'akahu_status': 'ACTIVE',
        })

    def _single_page_payload(self, tx_id='trans_patch2_1', current='cur_patch2_1'):
        return {
            'items': [{
                '_id': tx_id,
                'date': '2026-08-20T01:02:03Z',
                'description': 'Patch2 Tx %s' % tx_id,
                'amount': 12.34,
                'meta': {
                    'particulars': 'P',
                    'reference': 'R',
                    'other_account': 'Counterparty',
                },
                'type': 'TRANSFER',
            }],
            'cursor': {
                'current': current,
                'next': None,
            },
        }

    def test_lock_acquisition_and_release(self):
        account = self._make_account('lock')
        acquired = self.Engine._try_acquire_journal_lock(account.journal_id.id)
        self.assertTrue(acquired)
        self.Engine._release_journal_lock(account.journal_id.id)

    def test_second_concurrent_sync_rejected_or_skipped(self):
        account = self._make_account('concurrent')

        with mock.patch.object(type(self.Engine), '_try_acquire_journal_lock', return_value=False):
            result = self.Engine.sync_account(account, trigger_source='cron')
            self.assertTrue(result.get('skipped_lock'))

        latest_run = self.SyncRun.search([
            ('journal_id', '=', account.journal_id.id),
        ], order='id desc', limit=1)
        self.assertEqual(latest_run.status, 'partial')

        with mock.patch.object(type(self.Engine), '_try_acquire_journal_lock', return_value=False):
            with self.assertRaises(UserError):
                self.Engine.sync_account(account, trigger_source='manual_account')

    def test_successful_checkpoint_and_sync_run_success(self):
        account = self._make_account('success')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'committed_cursor': 'cur_old_success'})

        payload = self._single_page_payload('trans_patch2_success', 'cur_new_success')
        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 0)
        self.assertEqual(state.committed_cursor, 'cur_new_success')
        self.assertEqual(account.sync_cursor, 'cur_new_success')

        latest_run = self.SyncRun.search([
            ('journal_id', '=', account.journal_id.id),
        ], order='id desc', limit=1)
        self.assertEqual(latest_run.status, 'success')
        self.assertEqual(latest_run.cursor_before, 'cur_old_success')
        self.assertEqual(latest_run.cursor_after, 'cur_new_success')
        self.assertGreaterEqual(latest_run.transactions_fetched, 1)

    def test_failed_sync_retains_old_committed_cursor(self):
        account = self._make_account('failed')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'committed_cursor': 'cur_old_failed'})

        payload = self._single_page_payload('trans_patch2_failed', 'cur_new_failed')
        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.Engine), '_create_statement_lines', return_value=0):
                    result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 1)
        self.assertEqual(state.committed_cursor, 'cur_old_failed')

        latest_run = self.SyncRun.search([
            ('journal_id', '=', account.journal_id.id),
        ], order='id desc', limit=1)
        self.assertEqual(latest_run.status, 'error')

    def test_sync_run_failure_on_exception(self):
        account = self._make_account('exception')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=UserError('boom')):
                with self.assertRaises(UserError):
                    self.Engine.sync_account(account, trigger_source='manual_account')

        latest_run = self.SyncRun.search([
            ('journal_id', '=', account.journal_id.id),
        ], order='id desc', limit=1)
        self.assertEqual(latest_run.status, 'error')
        self.assertIn('boom', latest_run.error_message or '')

    def test_crash_before_checkpoint_keeps_committed_cursor(self):
        account = self._make_account('crash')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'committed_cursor': 'cur_old_crash'})

        payload = self._single_page_payload('trans_patch2_crash', 'cur_new_crash')
        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.Engine), '_create_statement_lines', side_effect=RuntimeError('simulated crash')):
                    with self.assertRaises(RuntimeError):
                        self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(state.committed_cursor, 'cur_old_crash')

    def test_repeated_page_processing_is_idempotent_with_existing_dedup(self):
        account = self._make_account('replay')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'committed_cursor': False})

        payload = self._single_page_payload('trans_patch2_replay', 'cur_replay')
        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                first = self.Engine.sync_account(account, trigger_source='manual_account')
                second = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(first.get('imported'), 1)
        self.assertEqual(second.get('imported'), 0)
        self.assertEqual(state.committed_cursor, 'cur_replay')
