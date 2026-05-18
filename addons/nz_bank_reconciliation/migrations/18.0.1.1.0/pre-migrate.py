# -*- coding: utf-8 -*-
"""
Migration 18.0.1.1.0 — Add reference matching config columns.

Adds match_by_reference, match_by_date_window, date_window_days to
auto_reconciliation_config so existing installs don't crash on upgrade
with a missing-column error before the ORM gets a chance to add them.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM handles column creation
    cr.execute("""
        ALTER TABLE auto_reconciliation_config
        ADD COLUMN IF NOT EXISTS match_by_reference    BOOLEAN DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS match_by_date_window  BOOLEAN DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS date_window_days      INTEGER DEFAULT 60
    """)
    _logger.info("Migration 18.0.1.1.0: added reference matching columns to auto_reconciliation_config")
