# -*- coding: utf-8 -*-
"""
Migration 18.0.1.3.0 — persistent sync-state foundation.

Patch 1 (schema + backfill only):
- Backfill account.bank.statement.line.akahu_transaction_id from unique_import_id.
- Create one akahu.sync.state per logical journal if missing.
- Seed committed_cursor from akahu.account.sync_cursor when available.
- Seed akahu.transaction.identity from existing imported statement lines.

No sync-engine behavior changes are applied in this migration.
"""
import logging

_logger = logging.getLogger(__name__)


def _backfill_statement_line_akahu_txid(cr):
    cr.execute(
        """
        UPDATE account_bank_statement_line
           SET akahu_transaction_id = substring(unique_import_id from 7)
         WHERE akahu_transaction_id IS NULL
           AND unique_import_id LIKE 'akahu-%'
        """
    )
    _logger.info(
        'Migration 18.0.1.3.0: backfilled statement-line akahu_transaction_id from unique_import_id for %s row(s).',
        cr.rowcount,
    )


def _seed_sync_state(cr):
    cr.execute(
        """
        INSERT INTO akahu_sync_state (
            journal_id,
            company_id,
            current_akahu_account_id,
            committed_cursor,
            sync_mode,
            state_status,
            recovery_overlap_minutes,
            last_successful_sync_at,
            create_uid,
            create_date,
            write_uid,
            write_date
        )
        SELECT
            aa.journal_id,
            aa.company_id,
            aa.akahu_account_id,
            aa.sync_cursor,
            CASE
                WHEN aa.sync_cursor IS NOT NULL AND aa.sync_cursor != '' THEN 'normal_incremental'
                ELSE 'cursor_recovery'
            END,
            'ready',
            60,
            aa.last_synced,
            1,
            NOW(),
            1,
            NOW()
        FROM akahu_account aa
        WHERE aa.journal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM akahu_sync_state st WHERE st.journal_id = aa.journal_id
          )
        """
    )
    _logger.info(
        'Migration 18.0.1.3.0: created %s persistent sync state row(s).',
        cr.rowcount,
    )


def _seed_transaction_identity(cr):
    cr.execute(
        """
        INSERT INTO akahu_transaction_identity (
            journal_id,
            company_id,
            akahu_transaction_id,
            statement_line_id,
            first_seen_at,
            last_seen_at,
            create_uid,
            create_date,
            write_uid,
            write_date
        )
        SELECT
            l.journal_id,
            l.company_id,
            l.akahu_transaction_id,
            l.id,
            COALESCE(l.create_date, NOW()),
            COALESCE(l.write_date, l.create_date, NOW()),
            1,
            NOW(),
            1,
            NOW()
        FROM account_bank_statement_line l
        WHERE l.akahu_transaction_id IS NOT NULL
          AND l.akahu_transaction_id != ''
          AND l.journal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM akahu_transaction_identity i
              WHERE i.journal_id = l.journal_id
                AND i.akahu_transaction_id = l.akahu_transaction_id
          )
        """
    )
    _logger.info(
        'Migration 18.0.1.3.0: seeded %s identity registry row(s).',
        cr.rowcount,
    )


def migrate(cr, version):
    if not version:
        return

    _logger.info('Migration 18.0.1.3.0: starting PATCH 1 backfill tasks.')

    _backfill_statement_line_akahu_txid(cr)
    _seed_sync_state(cr)
    _seed_transaction_identity(cr)

    _logger.info('Migration 18.0.1.3.0: completed PATCH 1 backfill tasks.')
