# -*- coding: utf-8 -*-
import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo import fields, models

_FINGERPRINT_AMOUNT_QUANT = Decimal('0.000001')


class AkahuIdentityResolver(models.AbstractModel):
    """Read-only transaction identity resolver for PATCH 4 Phase 3A."""

    _name = 'akahu.identity.resolver'
    _description = 'Akahu Identity Resolver'

    # These fields are considered strong because mismatches indicate a different
    # transaction even when date/amount/fingerprint are close.
    _STRONG_FIELDS = (
        'amount',
        'transaction_type',
        'other_account',
        'reference',
        'code',
    )
    _MAX_FINGERPRINT_CANDIDATES = 25

    def resolve_transaction_identity(
        self,
        journal,
        tx,
        sync_state=False,
        incoming_akahu_account_id=False,
        incoming_akahu_connection_id=False,
    ):
        """
        Resolve an incoming Akahu transaction identity in strict order:
        exact_id -> lineage -> fingerprint candidate evaluation -> new.

        This method is intentionally read-only and must not mutate accounting data.
        """
        journal = journal.sudo()
        if not journal or not journal.id:
            return self._result(
                resolution_type='identity_conflict',
                confidence='none',
                incoming_transaction_id=(tx or {}).get('_id') or False,
                reason='invalid_journal_context',
            )

        tx = tx or {}
        tx_id = tx.get('_id') or False
        incoming_sig = self._build_incoming_signature(
            journal,
            tx,
            incoming_akahu_account_id=incoming_akahu_account_id,
            incoming_akahu_connection_id=incoming_akahu_connection_id,
        )

        if tx_id:
            exact_identity = self._find_identity_by_tx_id(journal.id, tx_id)
            if exact_identity:
                return self._result(
                    resolution_type='exact_id',
                    confidence='high',
                    existing_statement_line_id=exact_identity.statement_line_id.id or False,
                    existing_identity_id=exact_identity.id,
                    incoming_transaction_id=tx_id,
                    matched_fields=['akahu_transaction_id'],
                    reason='journal_and_akahu_transaction_id_match',
                    candidate_count=1,
                )

        migrated_from = incoming_sig['migrated_from']
        if migrated_from:
            lineage_identity = self._find_identity_by_tx_id(journal.id, migrated_from)
            if lineage_identity:
                return self._result(
                    resolution_type='lineage',
                    confidence='high',
                    existing_statement_line_id=lineage_identity.statement_line_id.id or False,
                    existing_identity_id=lineage_identity.id,
                    incoming_transaction_id=tx_id,
                    matched_fields=['_migrated', 'journal_id'],
                    reason='explicit_akahu_lineage_match',
                    candidate_count=1,
                    old_akahu_account_id=lineage_identity.last_seen_akahu_account_id or lineage_identity.akahu_account_id,
                    new_akahu_account_id=incoming_sig['akahu_account_id'],
                    old_akahu_connection_id=lineage_identity.last_seen_akahu_connection_id or lineage_identity.akahu_connection_id,
                    new_akahu_connection_id=incoming_sig['akahu_connection_id'],
                )

        return self._resolve_by_fingerprint_candidates(journal, incoming_sig, tx_id, sync_state=sync_state)

    def _resolve_by_fingerprint_candidates(self, journal, incoming_sig, tx_id, sync_state=False):
        if not incoming_sig['tx_date'] or incoming_sig['amount_norm'] == '':
            return self._result(
                resolution_type='new',
                confidence='none',
                incoming_transaction_id=tx_id,
                reason='insufficient_core_fields_for_candidate_search',
            )

        window_days = self._get_identity_window_days(journal, sync_state=sync_state)
        date_min = incoming_sig['tx_date'] - timedelta(days=window_days)
        date_max = incoming_sig['tx_date'] + timedelta(days=window_days)

        candidates, candidate_overflow, total_candidate_count = self._search_fingerprint_candidates(
            journal_id=journal.id,
            legacy_fingerprint=incoming_sig['legacy_fingerprint'],
            date_min=date_min,
            date_max=date_max,
            amount_norm=incoming_sig['amount_norm'],
        )

        if candidate_overflow:
            return self._result(
                resolution_type='possible_duplicate',
                confidence='low',
                incoming_transaction_id=tx_id,
                reason='candidate_overflow_requires_manual_review',
                candidate_count=total_candidate_count,
            )

        filtered = []
        for identity in candidates:
            line = identity.statement_line_id
            if not line:
                continue
            comparison = self._compare_candidate(incoming_sig, line)
            filtered.append((identity, line, comparison))

        if not filtered:
            legacy_candidates, legacy_overflow, legacy_total = self._search_legacy_statement_line_candidates(
                journal_id=journal.id,
                date_min=date_min,
                date_max=date_max,
                amount_norm=incoming_sig['amount_norm'],
            )

            if legacy_overflow:
                return self._result(
                    resolution_type='possible_duplicate',
                    confidence='low',
                    incoming_transaction_id=tx_id,
                    reason='legacy_candidate_overflow_requires_manual_review',
                    candidate_count=legacy_total,
                )

            legacy_filtered = []
            for line in legacy_candidates:
                comparison = self._compare_candidate(incoming_sig, line)
                legacy_filtered.append((line, comparison))

            if legacy_filtered:
                if len(legacy_filtered) > 1:
                    all_conflicts = sorted({field for _, cmp_data in legacy_filtered for field in cmp_data['conflicting_fields']})
                    return self._result(
                        resolution_type='identity_conflict' if all_conflicts else 'possible_duplicate',
                        confidence='low',
                        incoming_transaction_id=tx_id,
                        conflicting_fields=all_conflicts,
                        reason='multiple_plausible_legacy_statement_line_candidates',
                        candidate_count=len(legacy_filtered),
                    )

                line, cmp_data = legacy_filtered[0]
                if cmp_data['conflicting_fields']:
                    return self._result(
                        resolution_type='identity_conflict',
                        confidence='low',
                        existing_statement_line_id=line.id,
                        incoming_transaction_id=tx_id,
                        matched_fields=cmp_data['matched_fields'],
                        conflicting_fields=cmp_data['conflicting_fields'],
                        reason='legacy_statement_line_has_strong_field_conflicts',
                        candidate_count=1,
                    )

                if cmp_data['sufficient_identifying_metadata']:
                    return self._result(
                        resolution_type='fingerprint_high',
                        confidence='high',
                        existing_statement_line_id=line.id,
                        incoming_transaction_id=tx_id,
                        matched_fields=cmp_data['matched_fields'],
                        reason='legacy_statement_line_high_confidence_match',
                        candidate_count=1,
                    )

                return self._result(
                    resolution_type='possible_duplicate',
                    confidence='medium',
                    existing_statement_line_id=line.id,
                    incoming_transaction_id=tx_id,
                    matched_fields=cmp_data['matched_fields'],
                    conflicting_fields=cmp_data['conflicting_fields'],
                    reason='legacy_statement_line_not_strong_enough',
                    candidate_count=1,
                )

            reason = 'no_candidate_after_window_amount_fingerprint_filter'
            if incoming_sig['migrated_account'] and not incoming_sig['migrated_from']:
                reason = 'migrated_account_without_explicit_lineage'
            return self._result(
                resolution_type='new',
                confidence='none',
                incoming_transaction_id=tx_id,
                reason=reason,
                candidate_count=0,
            )

        if len(filtered) > 1:
            all_conflicts = sorted({field for _, _, cmp_data in filtered for field in cmp_data['conflicting_fields']})
            return self._result(
                resolution_type='identity_conflict' if all_conflicts else 'possible_duplicate',
                confidence='low',
                incoming_transaction_id=tx_id,
                conflicting_fields=all_conflicts,
                reason='multiple_plausible_candidates',
                candidate_count=len(filtered),
            )

        identity, line, cmp_data = filtered[0]
        if cmp_data['conflicting_fields']:
            return self._result(
                resolution_type='identity_conflict',
                confidence='low',
                existing_statement_line_id=line.id,
                existing_identity_id=identity.id,
                incoming_transaction_id=tx_id,
                matched_fields=cmp_data['matched_fields'],
                conflicting_fields=cmp_data['conflicting_fields'],
                reason='single_candidate_has_strong_field_conflicts',
                candidate_count=1,
            )

        if cmp_data['sufficient_identifying_metadata'] and self._has_independent_identity_evidence(identity, incoming_sig, cmp_data):
            return self._result(
                resolution_type='fingerprint_high',
                confidence='high',
                existing_statement_line_id=line.id,
                existing_identity_id=identity.id,
                incoming_transaction_id=tx_id,
                matched_fields=cmp_data['matched_fields'],
                reason='single_candidate_with_strong_consistent_metadata',
                candidate_count=1,
            )

        return self._result(
            resolution_type='possible_duplicate',
            confidence='medium',
            existing_statement_line_id=line.id,
            existing_identity_id=identity.id,
            incoming_transaction_id=tx_id,
            matched_fields=cmp_data['matched_fields'],
            conflicting_fields=cmp_data['conflicting_fields'],
            reason='single_candidate_but_metadata_not_strong_enough',
            candidate_count=1,
        )

    def _has_independent_identity_evidence(self, identity, incoming_sig, cmp_data):
        signals = 0
        matched_fields = cmp_data.get('matched_fields') or []
        if 'transaction_type' in matched_fields:
            signals += 1

        incoming_account = incoming_sig.get('akahu_account_id')
        existing_account = identity.last_seen_akahu_account_id or identity.akahu_account_id
        if incoming_account and existing_account and incoming_account == existing_account:
            signals += 1

        incoming_connection = incoming_sig.get('akahu_connection_id')
        existing_connection = identity.last_seen_akahu_connection_id or identity.akahu_connection_id
        if incoming_connection and existing_connection and incoming_connection == existing_connection:
            signals += 1

        # Phase 3B policy: transaction_type alone or account/connection continuity
        # alone is not enough to auto-suppress. Require at least two independent
        # continuity signals.
        return signals >= 2

    def _find_identity_by_tx_id(self, journal_id, akahu_transaction_id):
        if not akahu_transaction_id:
            return self.env['akahu.transaction.identity']
        return self.env['akahu.transaction.identity'].sudo().search([
            ('journal_id', '=', journal_id),
            ('akahu_transaction_id', '=', akahu_transaction_id),
        ], limit=1)

    def _search_fingerprint_candidates(self, journal_id, legacy_fingerprint, date_min, date_max, amount_norm):
        if not legacy_fingerprint:
            return self.env['akahu.transaction.identity'], False, 0

        try:
            amount_value = float(amount_norm)
        except Exception:
            return self.env['akahu.transaction.identity'], False, 0

        domain = [
            ('journal_id', '=', journal_id),
            ('transaction_fingerprint', '=', legacy_fingerprint),
            ('statement_line_id', '!=', False),
            ('statement_line_id.date', '>=', date_min),
            ('statement_line_id.date', '<=', date_max),
            ('statement_line_id.amount', '=', amount_value),
        ]
        Identity = self.env['akahu.transaction.identity'].sudo()
        total = Identity.search_count(domain)
        overflow = total > self._MAX_FINGERPRINT_CANDIDATES
        if overflow:
            return self.env['akahu.transaction.identity'], True, total

        return Identity.search(domain, limit=self._MAX_FINGERPRINT_CANDIDATES), False, total

    def _search_legacy_statement_line_candidates(self, journal_id, date_min, date_max, amount_norm):
        try:
            amount_value = float(amount_norm)
        except Exception:
            return self.env['account.bank.statement.line'], False, 0

        Line = self.env['account.bank.statement.line'].sudo()
        domain = [
            ('journal_id', '=', journal_id),
            ('date', '>=', date_min),
            ('date', '<=', date_max),
            ('amount', '=', amount_value),
            ('akahu_transaction_id', '=', False),
        ]
        total = Line.search_count(domain)
        overflow = total > self._MAX_FINGERPRINT_CANDIDATES
        if overflow:
            return self.env['account.bank.statement.line'], True, total
        return Line.search(domain, limit=self._MAX_FINGERPRINT_CANDIDATES), False, total

    def _get_identity_window_days(self, journal, sync_state=False):
        if sync_state:
            try:
                val = int(sync_state.identity_match_window_days or 0)
                if val > 0:
                    return val
            except Exception:
                pass

        state = self.env['akahu.sync.state'].sudo().search([
            ('journal_id', '=', journal.id),
        ], limit=1)
        try:
            val = int(state.identity_match_window_days or 0)
            if val > 0:
                return val
        except Exception:
            pass
        return 7

    def _build_incoming_signature(self, journal, tx, incoming_akahu_account_id=False, incoming_akahu_connection_id=False):
        meta = tx.get('meta') or {}
        description = tx.get('description') or tx.get('type') or ''
        payment_ref = self._build_payment_ref(description, meta)
        tx_date = self._parse_tx_date(tx.get('date'))
        amount_norm = self._normalize_amount(tx.get('amount'))

        return {
            'tx_date': tx_date,
            'amount_norm': amount_norm,
            'description': self._normalize_str(description),
            'transaction_type': self._normalize_str(tx.get('type')),
            'particulars': self._normalize_str(meta.get('particulars')),
            'code': self._normalize_str(meta.get('code')),
            'reference': self._normalize_str(meta.get('reference')),
            'other_account': self._normalize_str(meta.get('other_account')),
            'card_suffix': self._normalize_str(meta.get('card_suffix')),
            'merchant': self._normalize_merchant(tx.get('merchant') or meta.get('merchant')),
            'payment_ref': self._normalize_str(payment_ref),
            'legacy_fingerprint': self._build_legacy_search_fingerprint(
                journal.id,
                tx_date,
                amount_norm,
                payment_ref,
                meta.get('other_account'),
            ),
            'migrated_from': tx.get('_migrated') or False,
            'migrated_account': tx.get('_migrated_account') or False,
            'akahu_account_id': incoming_akahu_account_id or tx.get('account') or tx.get('_account') or False,
            'akahu_connection_id': (
                incoming_akahu_connection_id
                or tx.get('connection')
                or tx.get('_connection')
                or (tx.get('connection_details') or {}).get('_id')
                or False
            ),
        }

    def _compare_candidate(self, incoming_sig, line):
        existing_payment_ref = self._normalize_str(line.payment_ref)
        payment_ref_tokens = self._payment_ref_tokens(line.payment_ref)
        parsed_meta = self._parse_payment_ref_meta(line.payment_ref)

        matched = []
        conflicts = []

        if incoming_sig['amount_norm'] and self._normalize_amount(line.amount) == incoming_sig['amount_norm']:
            matched.append('amount')

        existing_type = ''
        if 'transaction_type' in line._fields:
            existing_type = self._normalize_str(line.transaction_type)
            if incoming_sig['transaction_type'] and existing_type:
                if incoming_sig['transaction_type'] == existing_type:
                    matched.append('transaction_type')
                else:
                    conflicts.append('transaction_type')

        existing_other_account = self._normalize_str(line.partner_name)
        if incoming_sig['other_account'] and existing_other_account:
            if incoming_sig['other_account'] == existing_other_account:
                matched.append('other_account')
            else:
                conflicts.append('other_account')

        if incoming_sig['reference']:
            if incoming_sig['reference'] in payment_ref_tokens:
                matched.append('reference')
            elif parsed_meta['has_explicit_meta'] and parsed_meta['reference'] and incoming_sig['reference'] != parsed_meta['reference']:
                conflicts.append('reference')

        if incoming_sig['code']:
            if incoming_sig['code'] in payment_ref_tokens:
                matched.append('code')
            elif parsed_meta['has_explicit_meta'] and parsed_meta['code'] and incoming_sig['code'] != parsed_meta['code']:
                conflicts.append('code')

        # Weak field matches improve confidence explanation but are not enough for auto-high.
        for weak_field, weak_value in (
            ('particulars', incoming_sig['particulars']),
            ('description', incoming_sig['description']),
            ('merchant', incoming_sig['merchant']),
            ('card_suffix', incoming_sig['card_suffix']),
        ):
            if weak_value and weak_value in payment_ref_tokens:
                matched.append(weak_field)

        strong_matches = [f for f in matched if f in self._STRONG_FIELDS]

        has_sufficient_metadata = len(strong_matches) >= 3 and not conflicts

        # Explicitly disallow date+amount-only and date+amount+description-only auto-match.
        only_weak = set(matched).issubset({'amount', 'description'})
        if only_weak:
            has_sufficient_metadata = False

        return {
            'matched_fields': sorted(set(matched)),
            'conflicting_fields': sorted(set(conflicts)),
            'sufficient_identifying_metadata': has_sufficient_metadata,
        }

    def _result(
        self,
        resolution_type,
        confidence,
        existing_statement_line_id=False,
        existing_identity_id=False,
        incoming_transaction_id=False,
        matched_fields=False,
        conflicting_fields=False,
        reason='',
        candidate_count=0,
        old_akahu_account_id=False,
        new_akahu_account_id=False,
        old_akahu_connection_id=False,
        new_akahu_connection_id=False,
    ):
        return {
            'resolution_type': resolution_type,
            'confidence': confidence,
            'existing_statement_line_id': existing_statement_line_id,
            'existing_identity_id': existing_identity_id,
            'incoming_transaction_id': incoming_transaction_id,
            'matched_fields': matched_fields or [],
            'conflicting_fields': conflicting_fields or [],
            'reason': reason,
            'candidate_count': candidate_count,
            'old_akahu_account_id': old_akahu_account_id,
            'new_akahu_account_id': new_akahu_account_id,
            'old_akahu_connection_id': old_akahu_connection_id,
            'new_akahu_connection_id': new_akahu_connection_id,
        }

    def _build_payment_ref(self, description, meta):
        parts = [description or '']
        for key in ('particulars', 'code', 'reference'):
            value = meta.get(key)
            if value and str(value).strip():
                parts.append(str(value).strip())
        return ' | '.join([p for p in parts if p])

    def _payment_ref_tokens(self, payment_ref):
        normalized = self._normalize_str(payment_ref)
        if not normalized:
            return set()
        return {part.strip() for part in normalized.split('|') if part.strip()}

    def _parse_payment_ref_meta(self, payment_ref):
        parts = [self._normalize_str(p) for p in str(payment_ref or '').split('|')]
        parts = [p for p in parts if p]
        if len(parts) >= 4:
            return {
                'has_explicit_meta': True,
                'particulars': parts[-3],
                'code': parts[-2],
                'reference': parts[-1],
            }
        return {
            'has_explicit_meta': False,
            'particulars': '',
            'code': '',
            'reference': '',
        }

    def _build_legacy_search_fingerprint(self, journal_id, tx_date, amount_norm, payment_ref, partner_name):
        fields_ordered = [
            str(journal_id or ''),
            tx_date.isoformat() if isinstance(tx_date, date) else '',
            amount_norm or '',
            self._normalize_str(payment_ref),
            self._normalize_str(partner_name),
        ]
        payload = '|'.join(fields_ordered)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def _normalize_str(self, value):
        if value is None:
            return ''
        text = str(value)
        text = ' '.join(text.split())
        return text.lower().strip()

    def _normalize_amount(self, value):
        if value is None or value == '':
            return ''
        try:
            dec_value = Decimal(str(value)).quantize(_FINGERPRINT_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return ''
        return format(dec_value, 'f')

    def _normalize_merchant(self, merchant):
        if isinstance(merchant, dict):
            for key in ('name', 'merchant_name'):
                if merchant.get(key):
                    return self._normalize_str(merchant.get(key))
            return ''
        return self._normalize_str(merchant)

    def _parse_tx_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return False
        text = text.split('T')[0].split(' ')[0]
        try:
            return fields.Date.from_string(text)
        except Exception:
            return False
