# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta, date

import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    from psycopg2.errors import UniqueViolation
except Exception:
    UniqueViolation = Exception

try:
    from odoo.sql_db import IntegrityError
except Exception:
    IntegrityError = Exception


_logger = logging.getLogger(__name__)
AKAHU_API = "https://api.akahu.io/v1"


# ---------------------------------------------------------
# Utilities
# ---------------------------------------------------------
def _parse_iso_to_local_naive(iso_str: str, tz_name: str | None) -> datetime:
    if not iso_str:
        aware = fields.Datetime.now()
        return aware.replace(tzinfo=None)

    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    aware = datetime.fromisoformat(s)

    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=pytz.UTC)

    tz = pytz.timezone(tz_name or "UTC")
    local_aware = aware.astimezone(tz)
    return local_aware.replace(tzinfo=None)


# ---------------------------------------------------------
# Journal Extension
# ---------------------------------------------------------
class AccountJournalAkahu(models.Model):
    _inherit = "account.journal"

    x_defer_bank_posting = fields.Boolean(
        string="Defer Bank Move Posting",
        default=True,
    )


# ---------------------------------------------------------
# Keep liquidity moves in draft
# ---------------------------------------------------------
class StatementLineDeferPosting(models.Model):
    _inherit = "account.bank.statement.line"

    def _prepare_move_values(self):
        vals = super()._prepare_move_values()
        if "auto_post" in self.env["account.move"]._fields:
            vals["auto_post"] = "no"
        return vals


# ---------------------------------------------------------
# Main Service
# ---------------------------------------------------------
class AkahuBankStatement(models.Model):
    _name = "akahu.bank.statement"
    _description = "Akahu Bank Statement Import & Reconciliation"

    # -----------------------------------------------------
    # Helpers
    # -----------------------------------------------------
    @api.model
    def _get_headers(self):
        ICP = self.env["ir.config_parameter"].sudo()
        token = ICP.get_param("akahu.access_token")
        app_id = ICP.get_param("akahu.app_id")

        if not token:
            raise UserError(_("Akahu access token not configured."))
        if not app_id:
            raise UserError(_("Akahu App ID not configured."))

        return {
            "Authorization": f"Bearer {token}",
            "X-Akahu-ID": app_id,
        }

    @api.model
    def _get_target_journal(self, journal_id=None):
        if journal_id:
            journal = self.env["account.journal"].browse(int(journal_id))
        else:
            jid = self.env["ir.config_parameter"].sudo().get_param("akahu.journal_id")
            if not jid:
                raise UserError(_("System parameter akahu.journal_id not set."))
            journal = self.env["account.journal"].browse(int(jid))

        if not journal or not journal.exists():
            raise UserError(_("Bank journal not found."))

        return journal

    def _rp_domain(self, inbound: bool):
        Account = self.env["account.account"]
        target = ["receivable"] if inbound else ["payable"]

        if "account_type" in Account._fields:
            return [("account_id.account_type", "in", target)]

        if "internal_type" in Account._fields:
            return [("account_id.internal_type", "in", target)]

        return []

    # -----------------------------------------------------
    # IMPORT (Your original stable logic kept)
    # -----------------------------------------------------
    @api.model
    def import_akahu_transactions(
        self, journal_id=None, days_back=90, tz_name=None, page_limit=200
    ):

        headers = self._get_headers()
        journal = self._get_target_journal(journal_id)
        tz_name = tz_name or self.env.user.tz or "UTC"

        since = (
            fields.Datetime.now() - timedelta(days=int(days_back))
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        acc_resp = requests.get(f"{AKAHU_API}/accounts", headers=headers, timeout=60)
        acc_data = acc_resp.json()
        accounts = acc_data.get("items", []) or []

        created = 0
        skipped = 0

        for acc in accounts:
            acc_id = acc.get("_id")
            if not acc_id:
                continue

            params = {"start": since, "limit": page_limit}
            url = f"{AKAHU_API}/accounts/{acc_id}/transactions"

            while True:
                resp = requests.get(url, headers=headers, params=params, timeout=90)
                data = resp.json()

                items = data.get("items", []) or []

                for tx in items:
                    akahu_id = tx.get("_id")
                    if not akahu_id:
                        continue

                    if self.env["account.bank.statement.line"].search_count(
                        [("unique_import_id", "=", akahu_id)]
                    ):
                        skipped += 1
                        continue

                    raw_date = tx.get("date")
                    local_dt = _parse_iso_to_local_naive(raw_date, tz_name)
                    day = local_dt.date()

                    statement = self.env["account.bank.statement"].search(
                        [("journal_id", "=", journal.id), ("date", "=", day)],
                        limit=1,
                    )

                    if not statement:
                        statement = self.env["account.bank.statement"].create(
                            {
                                "name": f"{journal.name} {day}",
                                "date": day,
                                "journal_id": journal.id,
                            }
                        )

                    self.env["account.bank.statement.line"].create(
                        {
                            "statement_id": statement.id,
                            "date": day,
                            "payment_ref": tx.get("description") or "Akahu",
                            "name": tx.get("description") or "Akahu",
                            "partner_name": (tx.get("counterparty") or {}).get(
                                "name"
                            ),
                            "amount": float(tx.get("amount") or 0.0),
                            "journal_id": journal.id,
                            "unique_import_id": akahu_id,
                        }
                    )

                    created += 1

                cursor_obj = data.get("cursor")
                next_cursor = (
                    cursor_obj.get("next") if isinstance(cursor_obj, dict) else None
                )
                if next_cursor:
                    params = {"cursor": next_cursor}
                    continue

                break

        return {"created": created, "skipped": skipped}

    # -----------------------------------------------------
    # AUTO RECONCILE (Clean & Stable)
    # -----------------------------------------------------
    @api.model
    def auto_reconcile_bank_lines(
        self, journal_id=None, max_days=30, amount_tolerance=0.01, require_text_hint=False,
    ):

        journal = self._get_target_journal(journal_id)

        if not journal.default_account_id:
            raise UserError(
                _("Bank journal %s has no Default Account.") % journal.display_name
            )

        since = fields.Date.today() - timedelta(days=int(max_days))

        st_lines = self.env["account.bank.statement.line"].search(
            [
                ("journal_id", "=", journal.id),
                ("date", ">=", since),
                ("move_id.state", "=", "draft"),
            ]
        )

        reconciled = 0
        missing = 0

        for stl in st_lines:

            if not stl.move_id:
                continue

            amount = abs(stl.amount)
            inbound = stl.amount > 0

            partner = stl.partner_id
            if not partner and stl.partner_name:
                partner = self.env["res.partner"].search(
                    [("name", "ilike", stl.partner_name)], limit=1
                )

            if not partner:
                missing += 1
                continue

            domain = [
                ("partner_id", "=", partner.id),
                ("move_id.state", "=", "posted"),
                ("reconciled", "=", False),
            ] + self._rp_domain(inbound)

            candidates = self.env["account.move.line"].search(domain)

            match = candidates.filtered(
                lambda l: abs(abs(l.amount_residual) - amount)
                <= amount_tolerance
            )

            if len(match) != 1:
                missing += 1
                continue

            counterpart = match[0]
            draft_move = stl.move_id
            bank_account = journal.default_account_id

            bank_leg = draft_move.line_ids.filtered(
                lambda l: l.account_id == bank_account
            )
            other_leg = draft_move.line_ids - bank_leg

            if not bank_leg or not other_leg:
                missing += 1
                continue

            other_leg.write(
                {
                    "account_id": counterpart.account_id.id,
                    "partner_id": counterpart.partner_id.id,
                }
            )

            draft_move.action_post()

            arap_leg = draft_move.line_ids.filtered(
                lambda l: l.account_id == counterpart.account_id
                and l.partner_id == counterpart.partner_id
                and not l.reconciled
            )

            if arap_leg:
                (arap_leg + counterpart).reconcile()
                reconciled += 1
            else:
                missing += 1

        _logger.info(
            "Akahu auto-reconcile: %s reconciled, %s missing.",
            reconciled,
            missing,
        )

        return {"reconciled": reconciled, "missing": missing}
