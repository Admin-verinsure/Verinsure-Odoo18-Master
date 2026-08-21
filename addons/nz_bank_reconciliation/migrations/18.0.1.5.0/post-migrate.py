# -*- coding: utf-8 -*-
"""
Migration 18.0.1.5.0 — PATCH 3 checkpoint/recovery field backfill.

This migration is backward-compatible and does not alter transaction import
behavior directly. It only initializes newly added persistent checkpoint and
recovery audit fields.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE akahu_sync_state
           SET checkpoint_status = COALESCE(checkpoint_status, 'ready'),
               checkpoint_updated_at = COALESCE(checkpoint_updated_at, write_date, NOW()),
               recovery_mode = COALESCE(recovery_mode,
                   CASE
                       WHEN committed_cursor IS NOT NULL AND committed_cursor != '' THEN 'normal'
                       WHEN last_successful_transaction_date IS NOT NULL THEN 'recovery'
                       ELSE 'first_sync'
                   END
               ),
               recovery_overlap_days = COALESCE(NULLIF(recovery_overlap_days, 0), 2),
               last_successful_fetch_at = COALESCE(last_successful_fetch_at, last_successful_sync_at)
        """
    )
    _logger.info('Migration 18.0.1.5.0: initialized akahu_sync_state checkpoint/recovery fields for %s row(s).', cr.rowcount)

    cr.execute(
        """
        UPDATE akahu_sync_run
           SET run_mode = COALESCE(run_mode,
                   CASE
                       WHEN sync_mode IN ('cursor_recovery', 'account_reconnected', 'manual_recovery') THEN 'recovery'
                       WHEN sync_mode = 'first_sync' THEN 'first_sync'
                       ELSE 'normal'
                   END
               ),
               pages_requested = COALESCE(pages_requested, pages_fetched, 0),
               pages_processed = COALESCE(pages_processed, pages_fetched, 0),
               transactions_imported = COALESCE(transactions_imported, created_count, 0),
               transactions_skipped = COALESCE(transactions_skipped, skipped_by_id_count, 0),
               transactions_duplicate = COALESCE(transactions_duplicate, skipped_by_id_count, 0),
               recovery_limit_hit = COALESCE(recovery_limit_hit, FALSE)
        """
    )
    _logger.info('Migration 18.0.1.5.0: initialized akahu_sync_run recovery audit fields for %s row(s).', cr.rowcount)
