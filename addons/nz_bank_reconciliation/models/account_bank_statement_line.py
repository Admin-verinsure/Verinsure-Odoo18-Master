# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountBankStatementLine(models.Model):
    """
    VNZ-05 FIX: the sync engine deduplicates and inserts Akahu transactions
    using a `unique_import_id` field on account.bank.statement.line. That
    field belonged to Odoo's older bank-statement-import framework and does
    NOT exist on a stock Odoo 18 Community install (no `account_bank_statement_import`
    module declared as a dependency) — every dedup query and every insert
    failed with the target platform.

    This module now supplies the column itself so both the raw SQL dedup
    query in akahu_sync_engine.py and the ORM create() in
    _map_transaction_to_statement_line() have a real field to read/write,
    on every Odoo 18 edition (Community or Enterprise) regardless of which
    other modules are installed.
    """
    _inherit = 'account.bank.statement.line'

    unique_import_id = fields.Char(
        string='Import ID',
        copy=False,
        index=True,
        help='Set by bank-feed integrations (including Akahu sync) to '
             'deduplicate imported transactions. Not user-editable.',
    )

    _sql_constraints = [
        (
            'unique_import_id_uniq',
            'unique(unique_import_id, journal_id)',
            'A transaction with this Import ID has already been imported into this journal.',
        ),
    ]
