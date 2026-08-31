# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPatch4IdentityResolver(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Journal = cls.env['account.journal'].sudo()
        cls.Line = cls.env['account.bank.statement.line'].sudo()
        cls.Identity = cls.env['akahu.transaction.identity'].sudo()
        cls.SyncState = cls.env['akahu.sync.state'].sudo()
        cls.Resolver = cls.env['akahu.identity.resolver']

        cls._journal_seq = 0

    @classmethod
    def _next_journal(cls, suffix):
        cls._journal_seq += 1
        return cls.Journal.create({
            'name': 'PATCH4 Resolver %s %d' % (suffix, cls._journal_seq),
            'code': 'P4%03d' % cls._journal_seq,
            'type': 'bank',
            'company_id': cls.company.id,
        })

    def _tx(
        self,
        tx_id,
        tx_date='2026-08-12',
        amount=-1250.0,
        tx_type='TRANSFER',
        description='Invoice payment',
        meta=None,
        migrated=False,
        migrated_account=False,
    ):
        meta = meta or {}
        tx = {
            '_id': tx_id,
            'date': tx_date,
            'amount': amount,
            'type': tx_type,
            'description': description,
            'meta': meta,
        }
        if migrated:
            tx['_migrated'] = migrated
        if migrated_account:
            tx['_migrated_account'] = migrated_account
        return tx

    def _create_line_and_identity(
        self,
        journal,
        tx_id,
        tx_date='2026-08-12',
        amount=-1250.0,
        tx_type='TRANSFER',
        description='Invoice payment',
        meta=None,
        akahu_account_id='acc_old_1',
        akahu_connection_id='conn_old_1',
    ):
        meta = meta or {}
        payment_ref = self.Resolver._build_payment_ref(description, meta)
        tx_date_obj = fields.Date.from_string(tx_date)
        amount_norm = self.Resolver._normalize_amount(amount)
        fingerprint = self.Resolver._build_legacy_search_fingerprint(
            journal.id,
            tx_date_obj,
            amount_norm,
            payment_ref,
            meta.get('other_account'),
        )

        line_vals = {
            'journal_id': journal.id,
            'company_id': self.company.id,
            'date': tx_date_obj,
            'amount': amount,
            'payment_ref': payment_ref,
            'partner_name': meta.get('other_account') or False,
            'unique_import_id': 'akahu-%s' % tx_id,
            'akahu_transaction_id': tx_id,
            'akahu_account_id': akahu_account_id,
            'akahu_connection_id': akahu_connection_id,
            'akahu_transaction_fingerprint': fingerprint,
        }
        if 'transaction_type' in self.Line._fields:
            line_vals['transaction_type'] = tx_type

        line = self.Line.create(line_vals)

        identity = self.Identity.create({
            'journal_id': journal.id,
            'company_id': self.company.id,
            'akahu_transaction_id': tx_id,
            'akahu_account_id': akahu_account_id,
            'akahu_connection_id': akahu_connection_id,
            'first_seen_akahu_account_id': akahu_account_id,
            'last_seen_akahu_account_id': akahu_account_id,
            'first_seen_akahu_connection_id': akahu_connection_id,
            'last_seen_akahu_connection_id': akahu_connection_id,
            'transaction_fingerprint': fingerprint,
            'relation_type': 'exact_id',
            'confidence': 'low',
            'identity_match_type': 'new',
            'statement_line_id': line.id,
            'first_seen_at': fields.Datetime.now(),
            'last_seen_at': fields.Datetime.now(),
        })
        return line, identity

    def _create_legacy_line_without_identity(
        self,
        journal,
        tx_date='2026-08-12',
        amount=-1250.0,
        tx_type='TRANSFER',
        description='Invoice payment',
        meta=None,
    ):
        meta = meta or {}
        payment_ref = self.Resolver._build_payment_ref(description, meta)
        tx_date_obj = fields.Date.from_string(tx_date)
        line_vals = {
            'journal_id': journal.id,
            'company_id': self.company.id,
            'date': tx_date_obj,
            'amount': amount,
            'payment_ref': payment_ref,
            'partner_name': meta.get('other_account') or False,
            'unique_import_id': False,
            'akahu_transaction_id': False,
            'akahu_account_id': False,
            'akahu_connection_id': False,
            'akahu_transaction_fingerprint': False,
        }
        if 'transaction_type' in self.Line._fields:
            line_vals['transaction_type'] = tx_type
        return self.Line.create(line_vals)

    def _create_sync_state(self, journal, window_days=7):
        return self.SyncState.create({
            'journal_id': journal.id,
            'company_id': self.company.id,
            'recovery_mode': 'normal',
            'sync_mode': 'normal_incremental',
            'state_status': 'ready',
            'identity_match_window_days': window_days,
        })

    def test_01_same_akahu_id_returns_exact_high(self):
        journal = self._next_journal('exact')
        _, identity = self._create_line_and_identity(journal, tx_id='old_tx_001')

        result = self.Resolver.resolve_transaction_identity(journal, self._tx('old_tx_001'))

        self.assertEqual(result['resolution_type'], 'exact_id')
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['existing_identity_id'], identity.id)

    def test_02_different_id_with_migrated_returns_lineage_high(self):
        journal = self._next_journal('lineage')
        _, identity = self._create_line_and_identity(journal, tx_id='old_tx_001')

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', migrated='old_tx_001'),
        )

        self.assertEqual(result['resolution_type'], 'lineage')
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['existing_identity_id'], identity.id)

    def test_03_lineage_allows_different_akahu_account_ids(self):
        journal = self._next_journal('lineage-account-change')
        _, _ = self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            akahu_account_id='acc_old_123',
            akahu_connection_id='conn_old_123',
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', migrated='old_tx_001', migrated_account='acc_old_123'),
            incoming_akahu_account_id='acc_new_789',
            incoming_akahu_connection_id='conn_new_789',
        )

        self.assertEqual(result['resolution_type'], 'lineage')
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['old_akahu_account_id'], 'acc_old_123')
        self.assertEqual(result['new_akahu_account_id'], 'acc_new_789')

    def test_04_one_strong_candidate_returns_fingerprint_high(self):
        journal = self._next_journal('fp-high')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        line, identity = self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            meta=meta,
            description='Invoice payment',
            amount=-1250.0,
        )
        self._create_sync_state(journal, window_days=7)

        incoming = self._tx(
            'new_tx_001',
            amount=-1250.0,
            description='Invoice payment',
            meta=meta,
        )
        result = self.Resolver.resolve_transaction_identity(
            journal,
            incoming,
            incoming_akahu_account_id='acc_old_1',
            incoming_akahu_connection_id='conn_old_1',
        )

        self.assertEqual(result['resolution_type'], 'fingerprint_high')
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['existing_statement_line_id'], line.id)
        self.assertEqual(result['existing_identity_id'], identity.id)

    def test_05_two_candidates_returns_possible_or_conflict(self):
        journal = self._next_journal('two-candidates')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        self._create_line_and_identity(journal, tx_id='old_tx_001', meta=meta)
        self._create_line_and_identity(journal, tx_id='old_tx_002', meta=meta)

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', meta=meta),
        )

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'identity_conflict'))
        self.assertGreaterEqual(result['candidate_count'], 2)

    def test_06_same_date_amount_only_is_not_high(self):
        journal = self._next_journal('date-amount-only')
        self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            description='Only desc',
            meta={},
            amount=-1250.0,
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', description='Only desc', meta={}, amount=-1250.0),
        )

        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_07_date_amount_description_only_is_not_high(self):
        journal = self._next_journal('date-amount-desc')
        self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            description='Recurring payment',
            meta={},
            amount=-1250.0,
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', description='Recurring payment', meta={}, amount=-1250.0),
        )

        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_08_conflicting_strong_metadata_returns_identity_conflict(self):
        journal = self._next_journal('conflict')
        old_meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty Y',
        }
        new_meta = dict(old_meta)
        new_meta['other_account'] = 'Counterparty Z'

        self._create_line_and_identity(journal, tx_id='old_tx_001', meta=old_meta)

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', meta=new_meta),
        )

        self.assertEqual(result['resolution_type'], 'identity_conflict')
        self.assertIn('other_account', result['conflicting_fields'])

    def test_09_candidate_outside_window_returns_new(self):
        journal = self._next_journal('outside-window')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            tx_date='2026-07-01',
            meta=meta,
            amount=-1250.0,
        )
        state = self._create_sync_state(journal, window_days=2)

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', tx_date='2026-08-12', meta=meta, amount=-1250.0),
            sync_state=state,
        )

        self.assertEqual(result['resolution_type'], 'new')

    def test_10_incident_replay_high_only_with_sufficient_evidence(self):
        journal = self._next_journal('incident-175')
        meta = {
            'particulars': 'Membership',
            'code': 'SUB',
            'reference': 'AUG17-4128',
            'other_account': 'Counterparty Incident',
        }
        self._create_line_and_identity(
            journal,
            tx_id='old_tx_001',
            tx_date='2026-06-29',
            amount=4128.50,
            description='Incident replay',
            meta=meta,
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx(
                'new_tx_001',
                tx_date='2026-06-29',
                amount=4128.50,
                description='Incident replay',
                meta=meta,
            ),
            incoming_akahu_account_id='acc_old_1',
            incoming_akahu_connection_id='conn_old_1',
        )

        self.assertEqual(result['resolution_type'], 'fingerprint_high')

    def test_11_distinct_same_value_transactions_are_not_auto_merged(self):
        journal = self._next_journal('distinct-same-values')
        meta_a = {
            'particulars': 'Run A',
            'code': 'INV',
            'reference': 'REF-42',
            'other_account': 'Counterparty A',
        }
        meta_b = {
            'particulars': 'Run A',
            'code': 'INV',
            'reference': 'REF-42',
            'other_account': 'Counterparty B',
        }
        self._create_line_and_identity(journal, tx_id='old_tx_001', meta=meta_a)
        self._create_line_and_identity(journal, tx_id='old_tx_002', meta=meta_b)

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', meta=meta_a),
        )

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'identity_conflict', 'new'))
        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_12_reconciled_line_is_not_modified(self):
        journal = self._next_journal('readonly')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        line, _ = self._create_line_and_identity(journal, tx_id='old_tx_001', meta=meta)

        before_write_date = line.write_date
        result = self.Resolver.resolve_transaction_identity(journal, self._tx('old_tx_001', meta=meta))
        line.invalidate_recordset(['write_date'])

        self.assertEqual(result['resolution_type'], 'exact_id')
        self.assertEqual(line.write_date, before_write_date)

    def test_migrated_account_without_lineage_does_not_auto_merge(self):
        journal = self._next_journal('migrated-account-only')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        self._create_line_and_identity(journal, tx_id='old_tx_001', meta=meta)

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_001', meta=meta, migrated_account='acc_old_only'),
            incoming_akahu_account_id='acc_new_account',
            incoming_akahu_connection_id='conn_new_connection',
        )

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'identity_conflict', 'new'))
        self.assertNotEqual(result['resolution_type'], 'lineage')

    def test_recurring_payments_do_not_collapse_without_unique_evidence(self):
        journal = self._next_journal('recurring')
        recurring_meta = {
            'particulars': 'Monthly fee',
            'code': 'PAY',
            'reference': 'PAYMENT',
            'other_account': 'ABC',
        }
        recurring_dates = ['2026-08-09', '2026-08-10', '2026-08-11', '2026-08-12']
        for idx, tx_date in enumerate(recurring_dates, start=1):
            self._create_line_and_identity(
                journal,
                tx_id='old_tx_recurring_%d' % idx,
                tx_date=tx_date,
                amount=-1250.0,
                meta=recurring_meta,
                description='Recurring payment',
            )

        state = self._create_sync_state(journal, window_days=7)
        incoming = self._tx(
            'new_tx_recurring',
            tx_date='2026-08-12',
            amount=-1250.0,
            meta=recurring_meta,
            description='Recurring payment',
        )
        result = self.Resolver.resolve_transaction_identity(journal, incoming, sync_state=state)

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'identity_conflict'))
        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_more_than_25_candidates_never_auto_match(self):
        journal = self._next_journal('overflow')
        meta = {
            'particulars': 'Batch',
            'code': 'PAY',
            'reference': 'PAYMENT',
            'other_account': 'ABC',
        }
        for idx in range(26):
            self._create_line_and_identity(
                journal,
                tx_id='old_tx_overflow_%02d' % idx,
                tx_date='2026-08-12',
                amount=-1250.0,
                meta=meta,
                description='Overflow candidate',
            )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_overflow', tx_date='2026-08-12', amount=-1250.0, meta=meta, description='Overflow candidate'),
        )

        self.assertEqual(result['resolution_type'], 'possible_duplicate')
        self.assertEqual(result['reason'], 'candidate_overflow_requires_manual_review')
        self.assertGreaterEqual(result['candidate_count'], 26)

    def test_migration_confidence_is_not_used_as_proof(self):
        journal = self._next_journal('confidence-proof')
        line, identity = self._create_line_and_identity(
            journal,
            tx_id='old_tx_confidence',
            tx_date='2026-08-12',
            amount=-1250.0,
            description='Sparse payment',
            meta={},
        )
        identity.write({'confidence': 'high'})

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_confidence', tx_date='2026-08-12', amount=-1250.0, description='Sparse payment', meta={}),
        )

        self.assertTrue(line.exists())
        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_account_recreation_without_lineage_is_not_auto_high(self):
        journal = self._next_journal('account-recreate-no-lineage')
        meta = {
            'particulars': 'Subscription',
            'code': 'SUB',
            'reference': 'PAYMENT',
            'other_account': 'ABC',
        }
        self._create_line_and_identity(
            journal,
            tx_id='tx_a',
            tx_date='2026-08-12',
            amount=-1250.0,
            meta=meta,
            description='Subscription payment',
            akahu_account_id='ACCOUNT_A',
            akahu_connection_id='CONN_A',
        )

        incoming = self._tx(
            'tx_b',
            tx_date='2026-08-12',
            amount=-1250.0,
            meta=meta,
            description='Subscription payment',
            migrated=False,
            migrated_account=False,
        )
        result = self.Resolver.resolve_transaction_identity(
            journal,
            incoming,
            incoming_akahu_account_id='ACCOUNT_B',
            incoming_akahu_connection_id='CONN_B',
        )

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'identity_conflict', 'new'))
        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')

    def test_legacy_line_without_identity_can_match_high_confidence(self):
        journal = self._next_journal('legacy-high')
        meta = {
            'particulars': 'Client A',
            'code': 'INV',
            'reference': 'R-1001',
            'other_account': 'Counterparty A',
        }
        line = self._create_legacy_line_without_identity(
            journal,
            tx_date='2026-08-12',
            amount=-1250.0,
            meta=meta,
            description='Invoice payment',
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_legacy_001', tx_date='2026-08-12', amount=-1250.0, meta=meta, description='Invoice payment'),
        )

        self.assertEqual(result['resolution_type'], 'fingerprint_high')
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['existing_statement_line_id'], line.id)

    def test_legacy_line_without_identity_not_strong_enough_is_not_high(self):
        journal = self._next_journal('legacy-not-strong')
        self._create_legacy_line_without_identity(
            journal,
            tx_date='2026-08-12',
            amount=-1250.0,
            meta={},
            description='Recurring payment',
        )

        result = self.Resolver.resolve_transaction_identity(
            journal,
            self._tx('new_tx_legacy_002', tx_date='2026-08-12', amount=-1250.0, meta={}, description='Recurring payment'),
        )

        self.assertIn(result['resolution_type'], ('possible_duplicate', 'new', 'identity_conflict'))
        self.assertNotEqual(result['resolution_type'], 'fingerprint_high')
