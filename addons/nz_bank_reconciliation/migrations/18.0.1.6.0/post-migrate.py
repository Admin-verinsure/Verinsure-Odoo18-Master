# -*- coding: utf-8 -*-
"""
Migration 18.0.1.6.0 — PATCH 4 Phase 2 schema backfill.

Conservative behavior:
- Preserve existing unique_import_id values and unique constraint semantics.
- Populate source Akahu transaction IDs only when derivable.
- Compute deterministic fingerprints from existing stored statement-line fields.
- Seed/extend identity registry without inferring lineage.
- Do not merge, delete, or mutate accounting values.
"""
import logging
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime

_logger = logging.getLogger(__name__)

_FINGERPRINT_AMOUNT_QUANT = Decimal('0.000001')


def _normalize_str(value):
    if value is None:
        return ''
    text = str(value)
    text = ' '.join(text.split())
    return text.lower().strip()


def _normalize_amount(value):
    if value is None:
        return ''
    try:
        dec_value = Decimal(str(value)).quantize(_FINGERPRINT_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return ''
    return format(dec_value, 'f')


def _normalize_date(value):
    if not value:
        return ''
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ''
    # Postgres date columns arrive as YYYY-MM-DD; keep only date segment deterministically.
    return text.split(' ')[0].split('T')[0]


def _build_legacy_bootstrap_fingerprint(journal_id, tx_date, amount, payment_ref, partner_name):
    """
    PATCH 4 Phase 2 legacy/bootstrap fingerprint.

    This hash is for historical lookup/forensics bootstrap only and MUST NOT be
    treated as high-confidence duplicate proof. Phase 3 introduces stronger
    runtime identity evaluation.
    """
    fields_ordered = [
        str(journal_id or ''),
        _normalize_date(tx_date),
        _normalize_amount(amount),
        _normalize_str(payment_ref),
        _normalize_str(partner_name),
    ]
    payload = '|'.join(fields_ordered)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _table_exists(cr, table_name):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    return bool(cr.fetchone()[0])


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        )
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone()[0])


def _backfill_statement_line_identity(cr):
    cr.execute(
        """
        UPDATE account_bank_statement_line
           SET akahu_transaction_id = substring(unique_import_id from 7)
         WHERE (akahu_transaction_id IS NULL OR akahu_transaction_id = '')
           AND unique_import_id LIKE 'akahu-%'
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: backfilled akahu_transaction_id for %s statement line(s).',
        cr.rowcount,
    )

    cr.execute(
        """
        SELECT id, journal_id, date, amount, payment_ref, partner_name
          FROM account_bank_statement_line
         WHERE akahu_transaction_fingerprint IS NULL
           AND journal_id IS NOT NULL
        """
    )
    rows = cr.fetchall()
    for row in rows:
        fingerprint = _build_legacy_bootstrap_fingerprint(
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
        )
        cr.execute(
            """
            UPDATE account_bank_statement_line
               SET akahu_transaction_fingerprint = %s
             WHERE id = %s
            """,
            (fingerprint, row[0]),
        )
    _logger.info(
        'Migration 18.0.1.6.0: backfilled legacy SHA-256 bootstrap fingerprint for %s statement line(s).',
        len(rows),
    )

    cr.execute(
        """
        UPDATE account_bank_statement_line
           SET akahu_identity_confidence = COALESCE(akahu_identity_confidence, 'unknown'),
               akahu_identity_match_type = COALESCE(akahu_identity_match_type, 'new'),
               akahu_identity_last_seen_at = COALESCE(akahu_identity_last_seen_at, write_date, create_date, NOW())
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: initialized identity classification metadata for %s statement line(s).',
        cr.rowcount,
    )


def _backfill_sync_state_window(cr):
    cr.execute(
        """
        UPDATE akahu_sync_state
           SET identity_match_window_days = COALESCE(NULLIF(identity_match_window_days, 0), 7)
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: initialized identity_match_window_days for %s sync state row(s).',
        cr.rowcount,
    )


def _backfill_sync_run_counters(cr):
    cr.execute(
        """
        UPDATE akahu_sync_run
           SET transactions_seen = COALESCE(transactions_seen, transactions_fetched, 0),
               transactions_created = COALESCE(transactions_created, created_count, transactions_imported, 0),
               transactions_skipped_same_id = COALESCE(transactions_skipped_same_id, skipped_by_id_count, 0),
               transactions_skipped_lineage = COALESCE(transactions_skipped_lineage, 0),
               transactions_skipped_fingerprint = COALESCE(transactions_skipped_fingerprint, 0),
               possible_duplicates = COALESCE(possible_duplicates, 0),
               identity_conflicts = COALESCE(identity_conflicts, 0),
               identity_match_type = COALESCE(identity_match_type, 'new')
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: initialized PATCH 4 run counters for %s sync run row(s).',
        cr.rowcount,
    )


def _backfill_identity_registry(cr):
    cr.execute(
        """
        UPDATE akahu_transaction_identity
           SET relation_type = COALESCE(relation_type, 'new'),
               confidence = COALESCE(confidence, 'unknown'),
               identity_match_type = COALESCE(identity_match_type, 'new'),
               is_replacement_current = COALESCE(is_replacement_current, TRUE),
               first_seen_akahu_account_id = COALESCE(first_seen_akahu_account_id, akahu_account_id),
               last_seen_akahu_account_id = COALESCE(last_seen_akahu_account_id, akahu_account_id),
               first_seen_akahu_connection_id = COALESCE(first_seen_akahu_connection_id, akahu_connection_id),
               last_seen_akahu_connection_id = COALESCE(last_seen_akahu_connection_id, akahu_connection_id)
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: initialized extended identity registry metadata for %s row(s).',
        cr.rowcount,
    )

    cr.execute(
        """
        INSERT INTO akahu_transaction_identity (
            journal_id,
            company_id,
            akahu_transaction_id,
            akahu_account_id,
            akahu_connection_id,
            transaction_fingerprint,
            statement_line_id,
            relation_type,
            confidence,
            identity_match_type,
            is_replacement_current,
            first_seen_akahu_account_id,
            last_seen_akahu_account_id,
            first_seen_akahu_connection_id,
            last_seen_akahu_connection_id,
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
            l.akahu_account_id,
            l.akahu_connection_id,
            l.akahu_transaction_fingerprint,
            l.id,
            CASE
                WHEN l.akahu_transaction_id IS NOT NULL AND l.akahu_transaction_id != '' THEN 'exact_id'
                ELSE 'new'
            END,
            CASE
                WHEN l.akahu_transaction_id IS NOT NULL AND l.akahu_transaction_id != '' THEN 'low'
                ELSE 'low'
            END,
            CASE
                WHEN l.akahu_transaction_id IS NOT NULL AND l.akahu_transaction_id != '' THEN 'exact_id'
                ELSE 'new'
            END,
            TRUE,
            l.akahu_account_id,
            l.akahu_account_id,
            l.akahu_connection_id,
            l.akahu_connection_id,
            COALESCE(l.create_date, NOW()),
            COALESCE(l.write_date, l.create_date, NOW()),
            1,
            NOW(),
            1,
            NOW()
        FROM account_bank_statement_line l
        WHERE l.journal_id IS NOT NULL
          AND l.company_id IS NOT NULL
          AND l.akahu_transaction_id IS NOT NULL
          AND l.akahu_transaction_id != ''
          AND NOT EXISTS (
              SELECT 1
                FROM akahu_transaction_identity i
               WHERE i.journal_id = l.journal_id
                 AND i.akahu_transaction_id = l.akahu_transaction_id
          )
        """
    )
    _logger.info(
        'Migration 18.0.1.6.0: seeded %s missing identity registry row(s) from legacy statement lines.',
        cr.rowcount,
    )


def _create_supporting_indexes(cr):
    index_specs = [
        {
            'name': 'akahu_tx_identity_journal_fingerprint_idx',
            'table': 'akahu_transaction_identity',
            'columns': ['journal_id', 'transaction_fingerprint'],
            'optional': False,
        },
        {
            'name': 'akahu_tx_identity_journal_migrated_from_idx',
            'table': 'akahu_transaction_identity',
            'columns': ['journal_id', 'akahu_migrated_from'],
            'optional': False,
        },
        {
            'name': 'akahu_tx_identity_statement_line_idx',
            'table': 'akahu_transaction_identity',
            'columns': ['statement_line_id'],
            'optional': False,
        },
        {
            'name': 'absl_journal_fingerprint_idx',
            'table': 'account_bank_statement_line',
            'columns': ['journal_id', 'akahu_transaction_fingerprint'],
            'optional': False,
        },
        {
            'name': 'absl_journal_date_amount_idx',
            'table': 'account_bank_statement_line',
            'columns': ['journal_id', 'date', 'amount'],
            'optional': False,
        },
        {
            'name': 'akahu_duplicate_finding_batch_journal_idx',
            'table': 'akahu_duplicate_finding_batch',
            'columns': ['company_id', 'journal_id', 'create_date'],
            'optional': True,
        },
        {
            'name': 'akahu_duplicate_finding_journal_class_idx',
            'table': 'akahu_duplicate_finding',
            'columns': ['company_id', 'journal_id', 'classification'],
            'optional': True,
        },
    ]

    for spec in index_specs:
        table_exists = _table_exists(cr, spec['table'])
        missing_columns = [
            col for col in spec['columns']
            if table_exists and not _column_exists(cr, spec['table'], col)
        ]

        if not table_exists or missing_columns:
            message = (
                'Migration 18.0.1.6.0: index %s skipped because table/columns are unavailable '
                '(table_exists=%s, missing_columns=%s).'
            ) % (spec['name'], table_exists, ','.join(missing_columns) if missing_columns else 'none')
            if spec['optional']:
                _logger.warning(message)
                continue
            raise RuntimeError(message)

        cr.execute(
            'CREATE INDEX IF NOT EXISTS %s ON %s (%s)'
            % (spec['name'], spec['table'], ', '.join(spec['columns']))
        )


def migrate(cr, version):
    if not version:
        return

    _logger.info('Migration 18.0.1.6.0: starting PATCH 4 Phase 2 backfill.')
    _backfill_statement_line_identity(cr)
    _backfill_sync_state_window(cr)
    _backfill_sync_run_counters(cr)
    _backfill_identity_registry(cr)
    _create_supporting_indexes(cr)
    _logger.info('Migration 18.0.1.6.0: completed PATCH 4 Phase 2 backfill.')
