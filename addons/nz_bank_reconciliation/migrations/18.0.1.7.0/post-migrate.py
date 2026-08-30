# -*- coding: utf-8 -*-
"""
Migration 18.0.1.7.0 — allow multiple Akahu credentials per company.

Drops legacy UNIQUE(company_id) constraints on akahu_credential so each
credential configuration can be managed independently.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Drop any unique constraint that is exactly UNIQUE(company_id).
    cr.execute(
        """
        SELECT c.conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE t.relname = 'akahu_credential'
           AND c.contype = 'u'
        """
    )
    rows = cr.fetchall() or []
    dropped = 0

    for conname, condef in rows:
        normalized = (condef or '').replace(' ', '').upper()
        if normalized == 'UNIQUE(COMPANY_ID)':
            cr.execute(
                'ALTER TABLE akahu_credential DROP CONSTRAINT IF EXISTS "%s"' % conname
            )
            dropped += 1

    _logger.info(
        'Migration 18.0.1.7.0: dropped %s legacy akahu_credential UNIQUE(company_id) constraint(s).',
        dropped,
    )
