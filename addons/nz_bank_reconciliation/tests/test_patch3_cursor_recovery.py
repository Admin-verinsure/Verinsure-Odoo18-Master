# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
from unittest import mock

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPatch3CursorRecovery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['akahu.sync.engine']
        cls.SyncState = cls.env['akahu.sync.state'].sudo()
        cls.SyncRun = cls.env['akahu.sync.run'].sudo()
        cls.Credential = cls.env['akahu.credential'].sudo()
        cls.AccountModel = cls.env['akahu.account'].sudo()
        cls.JournalModel = cls.env['account.journal'].sudo()
        cls.Config = cls.env['ir.config_parameter'].sudo()

        cls.company = cls.env.company
        cls._journal_seq = 0

        cls.credential = cls.Credential.search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.credential:
            cls.credential = cls.Credential.create({
                'company_id': cls.company.id,
                'app_token': 'app_token_patch3_test',
                'user_access_token': 'user_token_patch3_test',
            })

    @classmethod
    def _next_journal(cls, suffix):
        cls._journal_seq += 1
        code = ('R%04d' % cls._journal_seq)
        return cls.JournalModel.create({
            'name': 'PATCH3 Journal %s %d' % (suffix, cls._journal_seq),
            'code': code,
            'type': 'bank',
            'company_id': cls.company.id,
        })

    def _make_account(self, suffix='base', sync_cursor=False):
        journal = self._next_journal(suffix)
        account = self.AccountModel.create({
            'company_id': self.company.id,
            'credential_id': self.credential.id,
            'journal_id': journal.id,
            'akahu_account_id': 'acc_patch3_%s' % suffix,
            'akahu_status': 'ACTIVE',
        })
        if sync_cursor:
            account.write({'sync_cursor': sync_cursor})
        return account

    def _tx(self, tx_id, dt_iso='2026-08-12T01:02:03.000Z'):
        return {
            '_id': tx_id,
            'date': dt_iso,
            'description': 'PATCH3 %s' % tx_id,
            'amount': 10.0,
            'meta': {'reference': 'ref-%s' % tx_id},
            'type': 'TRANSFER',
        }

    def _payload(self, items, current='cur_patch3_current', nxt=None):
        return {
            'items': items,
            'cursor': {
                'current': current,
                'next': nxt,
            },
        }

    def _default_cfg(self):
        self.Config.set_param('nz_bank_reconciliation.recovery_overlap_days', '2')
        self.Config.set_param('nz_bank_reconciliation.max_recovery_days', '7')
        self.Config.set_param('nz_bank_reconciliation.max_recovery_transactions', '500')
        self.Config.set_param('nz_bank_reconciliation.max_recovery_pages', '50')

    def _line_count_for_journal(self, journal):
        return self.env['account.bank.statement.line'].sudo().search_count([
            ('journal_id', '=', journal.id),
            ('unique_import_id', 'like', 'akahu-%'),
        ])

    def test_normal_cursor_based_sync(self):
        self._default_cfg()
        account = self._make_account('normal', sync_cursor='cur_old_normal')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'committed_cursor': 'cur_old_normal'})

        calls = []

        def _api(user_token, path, params=None):
            calls.append(params.copy() if params else {})
            return self._payload([self._tx('trans_patch3_normal')], current='cur_new_normal')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 0)
        self.assertEqual(state.committed_cursor, 'cur_new_normal')
        self.assertTrue(calls)
        self.assertEqual(calls[0].get('cursor'), 'cur_old_normal')
        self.assertFalse(calls[0].get('start'))
        self.assertFalse(calls[0].get('end'))

        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.run_mode, 'normal')

    def test_cursor_missing_with_checkpoint_enters_recovery(self):
        self._default_cfg()
        account = self._make_account('recover1', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 12:00:00',
            'last_successful_transaction_id': 'trans_prev',
        })

        calls = []

        def _api(user_token, path, params=None):
            calls.append(params.copy() if params else {})
            return self._payload([self._tx('trans_patch3_recover1')], current='cur_recover1')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertTrue(calls)
        self.assertTrue(calls[0].get('start'))
        self.assertTrue(calls[0].get('end'))
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.run_mode, 'recovery')

    def test_cursor_missing_without_checkpoint_is_first_sync(self):
        self._default_cfg()
        account = self._make_account('firstsync', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': False,
            'last_successful_transaction_id': False,
            'last_successful_fetch_at': False,
            'inflight_cursor': False,
        })

        calls = []

        def _api(user_token, path, params=None):
            calls.append(params.copy() if params else {})
            return self._payload([self._tx('trans_patch3_firstsync')], current='cur_firstsync')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertTrue(calls)
        self.assertFalse(calls[0].get('start'))
        self.assertFalse(calls[0].get('end'))
        self.assertFalse(calls[0].get('cursor'))
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.run_mode, 'first_sync')

    def test_first_sync_with_new_state_and_no_checkpoint(self):
        self._default_cfg()
        account = self._make_account('firstsync-regression', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'inflight_cursor': False,
            'inflight_page_no': 0,
            'last_successful_transaction_date': False,
            'last_successful_transaction_id': False,
            'last_successful_fetch_at': False,
            'last_successful_sync_at': False,
        })

        def _api(user_token, path, params=None):
            return self._payload([self._tx('trans_patch3_firstsync_reg')], current='cur_firstsync_reg')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 0)
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.run_mode, 'first_sync')

    def test_recovery_overlap_window(self):
        self._default_cfg()
        self.Config.set_param('nz_bank_reconciliation.recovery_overlap_days', '2')

        account = self._make_account('window', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
        })

        calls = []

        def _api(user_token, path, params=None):
            calls.append(params.copy() if params else {})
            return self._payload([self._tx('trans_patch3_window')], current='cur_window')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertIn('2026-08-10', calls[0].get('start', ''))

    def test_recovery_transaction_limit_retains_old_checkpoint(self):
        self._default_cfg()
        self.Config.set_param('nz_bank_reconciliation.max_recovery_transactions', '1')

        account = self._make_account('txlimit', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        prev_date = '2026-08-12 00:00:00'
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': prev_date,
            'last_successful_transaction_id': 'trans_prev_limit',
        })

        payload = self._payload([
            self._tx('trans_patch3_limit_1'),
            self._tx('trans_patch3_limit_2'),
        ], current='cur_limit')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with self.assertRaises(UserError):
                    self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertFalse(state.committed_cursor)
        self.assertEqual(fields.Datetime.to_string(state.last_successful_transaction_date), prev_date)
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.failure_reason, 'max_transactions_limit')

    def test_recovery_page_failure_retains_old_checkpoint(self):
        self._default_cfg()
        account = self._make_account('pagefail', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        prev_date = '2026-08-12 00:00:00'
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': prev_date,
            'last_successful_transaction_id': 'trans_prev_pagefail',
        })

        payload = self._payload([self._tx('trans_patch3_pagefail')], current='cur_pagefail')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                with mock.patch.object(type(self.Engine), '_create_statement_lines', return_value=0):
                    self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertFalse(state.committed_cursor)
        self.assertEqual(fields.Datetime.to_string(state.last_successful_transaction_date), prev_date)

    def test_recovery_success_commits_new_checkpoint(self):
        self._default_cfg()
        account = self._make_account('recover-success', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
            'last_successful_transaction_id': 'trans_prev_success',
        })

        payload = self._payload([self._tx('trans_patch3_recover_success')], current='cur_recover_success')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 0)
        self.assertEqual(state.committed_cursor, 'cur_recover_success')
        self.assertTrue(state.last_successful_fetch_at)

    def test_persistent_checkpoint_survives_reload(self):
        account = self._make_account('reload', sync_cursor='cur_reload')
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': 'cur_reload',
            'last_successful_transaction_id': 'trans_reload',
            'last_successful_transaction_date': '2026-08-12 00:00:00',
        })

        state_refetched = self.SyncState.browse(state.id)
        self.assertTrue(state_refetched.exists())
        self.assertEqual(state_refetched.committed_cursor, 'cur_reload')
        self.assertEqual(state_refetched.last_successful_transaction_id, 'trans_reload')

    def test_account_recreation_reuses_journal_sync_state(self):
        self._default_cfg()
        account1 = self._make_account('recreate-old', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account1)
        state_id = state.id
        old_akahu_id = account1.akahu_account_id
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
        })

        journal_id = account1.journal_id.id
        account1.unlink()

        account2 = self.AccountModel.create({
            'company_id': self.company.id,
            'credential_id': self.credential.id,
            'journal_id': journal_id,
            'akahu_account_id': 'acc_patch3_recreate_new',
            'akahu_status': 'ACTIVE',
        })

        payload = self._payload([self._tx('trans_patch3_recreate')], current='cur_recreate')
        with mock.patch.object(type(account2), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                self.Engine.sync_account(account2, trigger_source='manual_account')

        state_after = self.SyncState.browse(state_id)
        self.assertTrue(state_after.exists())
        self.assertEqual(state_after.previous_akahu_account_id, old_akahu_id)
        self.assertEqual(state_after.current_akahu_account_id, account2.akahu_account_id)

    def test_same_recovery_window_twice_no_extra_records_for_same_ids(self):
        self._default_cfg()
        account = self._make_account('replay2', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
        })

        payload = self._payload([self._tx('trans_patch3_replay2')], current='cur_replay2')
        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                first = self.Engine.sync_account(account, trigger_source='manual_account')
                state.write({'committed_cursor': False})
                account.write({'sync_cursor': False})
                second = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(first.get('imported'), 1)
        self.assertEqual(second.get('imported'), 0)

    def test_concurrent_recovery_lock_prevents_duplicate_processing(self):
        self._default_cfg()
        account = self._make_account('concurrent', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({'last_successful_transaction_date': '2026-08-12 00:00:00'})

        with mock.patch.object(type(self.Engine), '_try_acquire_journal_lock', return_value=False):
            result = self.Engine.sync_account(account, trigger_source='cron')

        self.assertTrue(result.get('skipped_lock'))
        run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run.status, 'partial')

    def test_unexpected_huge_historical_response_aborts_safely(self):
        self._default_cfg()
        self.Config.set_param('nz_bank_reconciliation.max_recovery_pages', '1')

        account = self._make_account('huge', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
            'last_successful_transaction_id': 'trans_prev_huge',
        })

        responses = [
            self._payload([self._tx('trans_patch3_huge_1')], current='cur_huge_1', nxt='next_page_token'),
            self._payload([self._tx('trans_patch3_huge_2')], current='cur_huge_2', nxt=None),
        ]

        def _api(user_token, path, params=None):
            return responses.pop(0)

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                with self.assertRaises(UserError):
                    self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertFalse(state.committed_cursor)
        latest_run = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertTrue(latest_run.recovery_limit_hit)
        self.assertEqual(latest_run.failure_reason, 'max_pages_limit')

    def test_timezone_aware_matches_naive_checkpoint(self):
        self._default_cfg()
        account = self._make_account('tz-naive-aware', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 10:30:00',
            'last_successful_transaction_id': 'tz_prev',
        })

        payload = self._payload([
            self._tx('trans_patch3_tz_aware', dt_iso='2026-08-12T10:30:00+00:00')
        ], current='cur_tz_naive_aware')

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 0)
        self.assertEqual(state.committed_cursor, 'cur_tz_naive_aware')

    def test_datetime_normalization_non_utc_offset(self):
        normalized = self.Engine._normalize_datetime_utc('2026-08-12T22:30:00+12:00')
        self.assertEqual(normalized, datetime(2026, 8, 12, 10, 30, 0))

    def test_exact_recovery_day_limit_boundaries(self):
        account = self._make_account('days-boundary', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        self.Config.set_param('nz_bank_reconciliation.recovery_overlap_days', '1')
        self.Config.set_param('nz_bank_reconciliation.max_recovery_days', '7')

        fixed_now = '2026-08-21 00:00:00'
        payload = self._payload([self._tx('trans_patch3_days_boundary')], current='cur_days_boundary')

        # total span = 7 days exactly -> allowed
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-15 00:00:00',
            'last_successful_transaction_id': 'days_prev_1',
        })
        with mock.patch('odoo.fields.Datetime.now', return_value=fixed_now):
            with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
                with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                    ok_result = self.Engine.sync_account(account, trigger_source='manual_account')
        self.assertEqual(ok_result.get('failed'), 0)

        # total span = 7 days + 1 second -> rejected
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-14 23:59:59',
            'last_successful_transaction_id': 'days_prev_2',
        })
        with mock.patch('odoo.fields.Datetime.now', return_value=fixed_now):
            with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
                with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                    with self.assertRaises(UserError):
                        self.Engine.sync_account(account, trigger_source='manual_account')
        run_fail = self.SyncRun.search([('journal_id', '=', account.journal_id.id)], order='id desc', limit=1)
        self.assertEqual(run_fail.failure_reason, 'max_days_limit')

        # total span = 6d 23:59:59 -> allowed
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-15 00:00:01',
            'last_successful_transaction_id': 'days_prev_3',
        })
        with mock.patch('odoo.fields.Datetime.now', return_value=fixed_now):
            with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
                with mock.patch.object(type(self.credential), '_api_get', return_value=payload):
                    ok_result_2 = self.Engine.sync_account(account, trigger_source='manual_account')
        self.assertEqual(ok_result_2.get('failed'), 0)

    def test_recovery_page1_success_page2_failure_checkpoint_alignment(self):
        self._default_cfg()
        account = self._make_account('page1ok-page2fail', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
            'last_successful_transaction_id': 'page_prev',
        })

        tx1 = self._tx('trans_patch3_page_tx1')
        # Duplicate in second page triggers unique constraint failure during create,
        # exercising rollback-to-page-savepoint behavior.
        tx2_dup = self._tx('trans_patch3_page_tx1')
        responses = [
            self._payload([tx1], current='cur_page_1', nxt='cursor_page_2'),
            self._payload([tx2_dup], current='cur_page_2', nxt=None),
        ]

        def _api(user_token, path, params=None):
            return responses.pop(0)

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(result.get('failed'), 1)
        self.assertEqual(state.committed_cursor, 'cur_page_1')
        self.assertEqual(state.checkpoint_status, 'committed')
        self.assertEqual(self._line_count_for_journal(account.journal_id), 1)

        # Retry should not duplicate page 1 and should import page 2 safely.
        tx2_new = self._tx('trans_patch3_page_tx2')
        responses_retry = [
            self._payload([tx1], current='cur_page_1', nxt='cursor_page_2'),
            self._payload([tx2_new], current='cur_page_2', nxt=None),
        ]

        def _api_retry(user_token, path, params=None):
            return responses_retry.pop(0)

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api_retry):
                retry_result = self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(retry_result.get('failed'), 0)
        self.assertEqual(self._line_count_for_journal(account.journal_id), 2)
        self.assertEqual(state.committed_cursor, 'cur_page_2')
        self.assertEqual(state.checkpoint_status, 'committed')

    def test_recovery_page_creation_hard_exception_keeps_page1_checkpoint(self):
        self._default_cfg()
        account = self._make_account('hard-create-exception', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
            'last_successful_transaction_id': 'hard_prev',
        })

        responses = [
            self._payload([self._tx('trans_patch3_hard_1')], current='cur_hard_1', nxt='cursor_hard_2'),
            self._payload([self._tx('trans_patch3_hard_2')], current='cur_hard_2', nxt=None),
        ]

        def _api(user_token, path, params=None):
            return responses.pop(0)

        original_create = type(self.Engine)._create_statement_lines
        call_count = {'n': 0}

        def _create_with_crash(engine_self, akahu_account, transactions):
            call_count['n'] += 1
            if call_count['n'] == 2:
                raise RuntimeError('forced create crash page2')
            return original_create(engine_self, akahu_account, transactions)

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                with mock.patch.object(type(self.Engine), '_create_statement_lines', autospec=True, side_effect=_create_with_crash):
                    with self.assertRaises(RuntimeError):
                        self.Engine.sync_account(account, trigger_source='manual_account')

        self.assertEqual(self._line_count_for_journal(account.journal_id), 1)
        self.assertEqual(state.committed_cursor, 'cur_hard_1')
        self.assertEqual(state.checkpoint_status, 'committed')

    def test_cron_exception_keeps_checkpoint_consistent_with_persisted_lines(self):
        self._default_cfg()
        account = self._make_account('cron-exception', sync_cursor=False)
        state = self.Engine._get_or_create_sync_state(account)
        state.write({
            'committed_cursor': False,
            'last_successful_transaction_date': '2026-08-12 00:00:00',
            'last_successful_transaction_id': 'cron_prev',
        })

        responses = [
            self._payload([self._tx('trans_patch3_cron_1')], current='cur_cron_1', nxt='cursor_cron_2'),
            UserError('forced second-page failure'),
        ]

        def _api(user_token, path, params=None):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with mock.patch.object(type(account), '_get_user_token', return_value='user_token_x'):
            with mock.patch.object(type(self.credential), '_api_get', side_effect=_api):
                self.Engine.cron_sync_all()

        self.assertEqual(self._line_count_for_journal(account.journal_id), 1)
        self.assertEqual(state.committed_cursor, 'cur_cron_1')
        self.assertEqual(state.checkpoint_status, 'committed')
        self.assertEqual(account.sync_failure_count, 1)
