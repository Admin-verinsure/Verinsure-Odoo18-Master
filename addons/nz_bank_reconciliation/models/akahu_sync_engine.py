# -*- coding: utf-8 -*-
import logging
import time
from datetime import datetime, timezone, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from ..utils.log_redaction import sanitize_log_value

# BUG-01 FIX: Hard cap on paginated fetches. If Akahu ever returns a circular
# cursor or never sends a terminal page, the cron worker would hang forever.
# 500 pages × ~100 tx/page = 50 000 transactions — safely above any real account.
MAX_PAGES = 500
SYNC_LOCK_NAMESPACE = 781018
DEFAULT_RECOVERY_OVERLAP_DAYS = 2
DEFAULT_MAX_RECOVERY_DAYS = 7
DEFAULT_MAX_RECOVERY_TRANSACTIONS = 500
DEFAULT_MAX_RECOVERY_PAGES = 50
RESOLVER_VERSION = 'patch4_phase3b_v1'

_logger = logging.getLogger(__name__)


def _sanitize_error_text(text, limit=512):
    """
    SEC-04 FIX (consistency): apply the same token-shaped-string redaction
    used in akahu.credential._api_get() before persisting exception text to
    akahu.sync.log.error_message, which is readable by account.group_account_user.
    Truncates to *limit* chars and redacts anything matching [a-zA-Z0-9_]{20,}.
    """
    if not text:
        return text
    return str(sanitize_log_value(text))[:limit]


class AkahuSyncEngine(models.Model):
    """
    Core sync engine. Pulls transactions from Akahu and creates
    account.bank.statement.line records in Odoo for reconciliation.

    Odoo 18 deduplication: uses unique_import_id column (built-in).
    No custom narration/memo embedding needed.
    """
    _name = 'akahu.sync.engine'
    _description = 'Akahu Sync Engine'

    _SYNC_FAILURE_NOTIFICATION_THRESHOLD = 3
    _SYNC_FAILURE_NOTIFICATION_COOLDOWN_HOURS = 24

    def _get_active_erp_admins(self):
        """Return active ERP Managers to notify for cron-related failures."""
        return self.env['res.users'].sudo().search([
            ('groups_id', 'in', self.env.ref('base.group_erp_manager').id),
            ('active', '=', True),
        ])

    def _notify_admins_of_cron_permission_loss(self, method_name):
        """
        VNZ-20 FIX: scheduled jobs previously failed silently (server log
        only) if the akahu_cron_technical user ever lost
        account.group_account_manager. Escalate to a real notification —
        an email to every Settings Administrator — so an admin sees it
        instead of the sync just quietly stopping. Best-effort: a mail
        failure here must never mask the original AccessError.
        """
        try:
            admins = self._get_active_erp_admins()
            if not admins:
                return
            body = _(
                'The Akahu integration\'s scheduled job "%s" was blocked because '
                'the technical user (%s) no longer has the Accounting Manager '
                'group. Scheduled bank sync / reconciliation will not run until '
                'this is restored.'
            ) % (method_name, self.env.user.login)
            self.env['mail.mail'].sudo().create({
                'subject': _('Akahu integration: scheduled job blocked (permission lost)'),
                'body_html': '<p>%s</p>' % body,
                'email_to': ','.join(admins.mapped('email') or []),
            }).send()
        except Exception as e:
            _logger.exception(
                'VNZ-20: failed to notify administrators about cron permission loss for %s: %s',
                sanitize_log_value(method_name),
                sanitize_log_value(e),
            )

    def _notify_admins_of_sync_failure(self, account, error_message):
        """Notify ERP managers of repeated scheduled sync failures."""
        try:
            admins = self._get_active_erp_admins()
            if not admins:
                return False

            body = _(
                'Akahu scheduled sync has failed repeatedly for this account.\n\n'
                'Company: %s\n'
                'Journal: %s\n'
                'Account: %s\n'
                'Time: %s\n'
                'Failure count: %s\n'
                'Error: %s'
            ) % (
                sanitize_log_value(account.company_id.name or ''),
                sanitize_log_value(account.journal_id.display_name or ''),
                sanitize_log_value(account.name or ''),
                sanitize_log_value(fields.Datetime.now()),
                sanitize_log_value(account.sync_failure_count),
                sanitize_log_value(error_message or ''),
            )

            self.env['mail.mail'].sudo().create({
                'subject': _('Akahu Scheduled Sync Failure'),
                'body_html': '<pre>%s</pre>' % body,
                'email_to': ','.join(admins.mapped('email') or []),
            }).send()
            return True
        except Exception as e:
            _logger.exception(
                'VNZ-20: failed to notify administrators about repeated sync failure for account %s: %s',
                sanitize_log_value(account.name if account else ''),
                sanitize_log_value(e),
            )
            return False

    def _get_or_create_sync_state(self, akahu_account):
        """Return persistent sync state anchored to the Odoo journal."""
        state_model = self.env['akahu.sync.state'].sudo()
        state = state_model.search([('journal_id', '=', akahu_account.journal_id.id)], limit=1)
        if state:
            return state

        initial_cursor = akahu_account.sync_cursor or False
        initial_mode = 'normal_incremental' if initial_cursor else 'first_sync'
        return state_model.create({
            'journal_id': akahu_account.journal_id.id,
            'company_id': akahu_account.company_id.id,
            'current_akahu_account_id': akahu_account.akahu_account_id or False,
            'committed_cursor': initial_cursor,
            'inflight_cursor': initial_cursor,
            'inflight_page_no': 0,
            'checkpoint_status': 'ready',
            'checkpoint_updated_at': fields.Datetime.now(),
            'recovery_mode': 'normal' if initial_cursor else 'first_sync',
            'sync_mode': initial_mode,
            'state_status': 'ready',
            'recovery_overlap_days': DEFAULT_RECOVERY_OVERLAP_DAYS,
            'recovery_overlap_minutes': 60,
        })

    def _create_sync_run(self, akahu_account, state, trigger_source='manual'):
        """Create audit row for each sync attempt."""
        return self.env['akahu.sync.run'].sudo().create({
            'journal_id': akahu_account.journal_id.id,
            'company_id': akahu_account.company_id.id,
            'current_akahu_account_id': akahu_account.akahu_account_id or state.current_akahu_account_id,
            'previous_akahu_account_id': state.previous_akahu_account_id,
            'current_akahu_connection_id': state.current_akahu_connection_id,
            'previous_akahu_connection_id': state.previous_akahu_connection_id,
            'sync_mode': state.sync_mode or 'normal_incremental',
            'run_mode': state.recovery_mode or 'normal',
            'dry_run': False,
            'cursor_before': state.committed_cursor or akahu_account.sync_cursor or False,
            'previous_checkpoint_date': state.last_successful_transaction_date,
            'previous_checkpoint_transaction_id': state.last_successful_transaction_id,
            'status': 'running',
            'anomaly_flags': 'trigger_source=%s' % trigger_source,
        })

    def _get_sync_config(self):
        icp = self.env['ir.config_parameter'].sudo()

        def _to_int(param_name, default, minimum=1):
            raw = icp.get_param(param_name)
            try:
                value = int(raw)
            except Exception:
                value = default
            if value < minimum:
                value = default
            return value

        return {
            'recovery_overlap_days': _to_int(
                'nz_bank_reconciliation.recovery_overlap_days',
                DEFAULT_RECOVERY_OVERLAP_DAYS,
                1,
            ),
            'max_recovery_days': _to_int(
                'nz_bank_reconciliation.max_recovery_days',
                DEFAULT_MAX_RECOVERY_DAYS,
                1,
            ),
            'max_recovery_transactions': _to_int(
                'nz_bank_reconciliation.max_recovery_transactions',
                DEFAULT_MAX_RECOVERY_TRANSACTIONS,
                1,
            ),
            'max_recovery_pages': _to_int(
                'nz_bank_reconciliation.max_recovery_pages',
                DEFAULT_MAX_RECOVERY_PAGES,
                1,
            ),
        }

    def _to_akahu_iso(self, value):
        dt = self._normalize_datetime_utc(value)
        if not dt:
            return False
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _normalize_datetime_utc(self, value):
        """
        Normalize datetime-like values to naive UTC datetimes.

        Odoo `fields.Datetime` values are usually stored as naive UTC while
        API timestamps may include timezone offsets. This helper converts all
        forms to a single comparable convention.
        """
        if not value:
            return None

        dt = None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except Exception:
                dt = fields.Datetime.to_datetime(value)
        else:
            dt = fields.Datetime.to_datetime(value)

        if not dt:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _parse_tx_datetime(self, tx):
        for key in ('date', 'updated_at', 'created_at'):
            raw = tx.get(key)
            if not raw:
                continue
            try:
                return self._normalize_datetime_utc(raw)
            except Exception:
                continue
        return None

    def _extract_last_checkpoint(self, items):
        latest_dt = None
        latest_id = None
        for tx in items:
            tx_dt = self._parse_tx_datetime(tx)
            if not tx_dt:
                continue
            if latest_dt is None or tx_dt > latest_dt:
                latest_dt = tx_dt
                latest_id = tx.get('_id')
        return latest_dt, latest_id

    def _determine_sync_mode(self, state, akahu_account, account_changed=False, explicit_recovery=False):
        has_checkpoint = bool(
            state.last_successful_transaction_date
            or state.last_successful_transaction_id
            or state.last_successful_fetch_at
            or state.last_successful_sync_at
        )
        has_inflight_checkpoint = bool(state.inflight_cursor or state.inflight_page_no)
        has_completed_history = bool(has_checkpoint or state.committed_cursor or has_inflight_checkpoint)

        if not has_completed_history:
            return 'first_sync'

        has_committed = bool(state.committed_cursor)
        inconsistent_cursor = bool(state.inflight_cursor and not state.committed_cursor)
        account_cursor_stale = bool(akahu_account.sync_cursor and has_committed and akahu_account.sync_cursor != state.committed_cursor)

        if has_committed and not inconsistent_cursor and not account_changed and not explicit_recovery and not account_cursor_stale:
            return 'normal'

        return 'recovery'

    def _map_run_mode_to_sync_mode(self, run_mode):
        if run_mode == 'normal':
            return 'normal_incremental'
        if run_mode == 'recovery':
            return 'cursor_recovery'
        return 'first_sync'

    def _try_acquire_journal_lock(self, journal_id):
        """Acquire per-journal PostgreSQL advisory lock."""
        self.env.cr.execute('SELECT pg_try_advisory_lock(%s, %s)', (SYNC_LOCK_NAMESPACE, int(journal_id)))
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    def _release_journal_lock(self, journal_id):
        """Release per-journal PostgreSQL advisory lock."""
        self.env.cr.execute('SELECT pg_advisory_unlock(%s, %s)', (SYNC_LOCK_NAMESPACE, int(journal_id)))

    def _finalize_sync_run(self, sync_run, values):
        vals = dict(values)
        vals.setdefault('ended_at', fields.Datetime.now())
        sync_run.sudo().write(vals)

    # ── PUBLIC ENTRY POINTS ────────────────────────────────────────────────────

    @api.model
    def cron_sync_all(self):
        """
        Called by scheduled cron — syncs all active ACTIVE accounts.

        METHOD GUARD (SEC-02): Restricted to account managers. Prevents an
        unprivileged internal user from triggering a full sync run via RPC.
        The dedicated cron technical user has account.group_account_manager
        so scheduled execution is unaffected.
        """
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        #
        # VNZ-20 FIX: this guard also fires for the legitimate scheduled cron
        # if the akahu_cron_technical user ever loses account.group_account_manager
        # (e.g. an admin edits the noupdate="1" user record). Previously that
        # produced only a log line and the sync silently stopped running.
        # Escalate to a mail activity for administrators so it is visible
        # outside the server log.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            self.sudo()._notify_admins_of_cron_permission_loss(
                'akahu.sync.engine.cron_sync_all',
            )
            raise AccessError(_('This action is restricted to Accounting Managers.'))
        _logger.info('Akahu Sync Cron: Starting')
        # sudo(): cron technical user needs cross-company read access to akahu.account
        accounts = self.env['akahu.account'].sudo().search([
            ('active', '=', True),
            ('akahu_status', '!=', 'INACTIVE'),
            ('credential_id.active', '=', True),
        ])
        total_imported = 0
        for account in accounts:
            try:
                result = self.sync_account(account, trigger_source='cron')
                if result.get('skipped_lock'):
                    continue
                total_imported += result.get('imported', 0)
                account.sudo().write({
                    'sync_failure_count': 0,
                    'last_failure': False,
                    'last_failure_notification': False,
                })
            except Exception as e:
                now = fields.Datetime.now()
                next_count = (account.sync_failure_count or 0) + 1
                account.sudo().write({
                    'sync_failure_count': next_count,
                    'last_failure': now,
                })

                should_notify = next_count >= self._SYNC_FAILURE_NOTIFICATION_THRESHOLD
                if should_notify and account.last_failure_notification:
                    last_notice = fields.Datetime.to_datetime(account.last_failure_notification)
                    if last_notice and fields.Datetime.to_datetime(now) < (last_notice + timedelta(hours=self._SYNC_FAILURE_NOTIFICATION_COOLDOWN_HOURS)):
                        should_notify = False

                if should_notify:
                    sent = self._notify_admins_of_sync_failure(account, e)
                    if sent:
                        account.sudo().write({'last_failure_notification': now})
                        _logger.info(
                            'Notification email sent for account %s after %d consecutive failures.',
                            sanitize_log_value(account.name),
                            sanitize_log_value(next_count),
                        )

                _logger.error(
                    'Akahu sync failed for account %s: %s',
                    sanitize_log_value(account.name),
                    sanitize_log_value(e),
                )
                # sudo(): cron technical user has no create permission on akahu.sync.log; escalate only for log writes
                self.env['akahu.sync.log'].sudo().create({
                    'akahu_account_id': account.id,
                    'company_id': account.company_id.id,
                    'status': 'error',
                    'transactions_imported': 0,
                    'error_message': _sanitize_error_text(str(e)),
                })
        _logger.info(
            'Akahu Sync Cron: Done. Total imported: %d',
            sanitize_log_value(total_imported),
        )

    @api.model
    def sync_account(self, akahu_account, trigger_source='manual'):
        """
        Sync one Akahu account → Odoo bank statement lines.
        Handles pagination with cursor.
        Deduplication via unique_import_id (Odoo 18 native column).
        Returns dict with 'imported' count.
        """
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        cred = akahu_account.credential_id
        state = self.sudo()._get_or_create_sync_state(akahu_account)
        sync_run = self.sudo()._create_sync_run(akahu_account, state, trigger_source=trigger_source)
        sync_cfg = self._get_sync_config()

        lock_acquired = False
        total_fetched = 0
        total_imported = 0
        total_failed = 0
        total_skipped_by_id = 0
        total_seen = 0
        total_skipped_lineage = 0
        total_skipped_fingerprint = 0
        total_possible_duplicates = 0
        total_identity_conflicts = 0
        decision_counts = {
            'exact_id': 0,
            'lineage': 0,
            'fingerprint_high': 0,
            'possible_duplicate': 0,
            'identity_conflict': 0,
            'new': 0,
        }
        page_count = 0
        pages_processed = 0
        error_message = False
        sync_ok = False
        run_finalized = False
        lock_contention = False
        recovery_limit_hit = False
        failure_reason = False

        try:
            lock_acquired = self._try_acquire_journal_lock(akahu_account.journal_id.id)
            if not lock_acquired:
                lock_error = _('A sync is already running for journal %s.') % akahu_account.journal_id.display_name
                self._finalize_sync_run(sync_run, {
                    'status': 'partial',
                    'error_message': lock_error,
                    'cursor_after': state.committed_cursor or akahu_account.sync_cursor or False,
                    'transactions_fetched': 0,
                    'created_count': 0,
                    'skipped_by_id_count': 0,
                    'pages_requested': 0,
                    'pages_processed': 0,
                    'transactions_imported': 0,
                    'transactions_skipped': 0,
                    'transactions_duplicate': 0,
                    'failure_reason': 'lock_contention',
                })
                run_finalized = True
                lock_contention = True
                if trigger_source == 'cron':
                    _logger.info(
                        'Akahu sync skipped for %s because another sync holds the journal lock.',
                        sanitize_log_value(akahu_account.name),
                    )
                    return {'imported': 0, 'fetched': 0, 'failed': 0, 'skipped_lock': True}
                raise UserError(lock_error)

            state.sudo().write({
                'state_status': 'running',
                'lock_owner_run_id': sync_run.id,
            })

            account_id = akahu_account.akahu_account_id
            if not account_id:
                akahu_account.action_refresh_account_info()
                account_id = akahu_account.akahu_account_id
                sync_run.sudo().write({'current_akahu_account_id': account_id or False})

            account_changed = bool(
                account_id
                and state.current_akahu_account_id
                and state.current_akahu_account_id != account_id
            )
            if account_changed:
                previous_account_id = state.current_akahu_account_id
                state.sudo().write({
                    'previous_akahu_account_id': previous_account_id,
                    'current_akahu_account_id': account_id,
                })
                sync_run.sudo().write({
                    'previous_akahu_account_id': previous_account_id,
                    'current_akahu_account_id': account_id,
                })
            elif account_id and state.current_akahu_account_id != account_id:
                state.sudo().write({'current_akahu_account_id': account_id})

            if not account_id:
                raise UserError(_('Could not determine Akahu Account ID for %s') % akahu_account.name)

            if akahu_account.akahu_status == 'INACTIVE':
                raise UserError(_(
                    'Account %s is INACTIVE on Akahu. '
                    'The user must reconnect via the Akahu OAuth flow.'
                ) % akahu_account.name)

            path = '/accounts/%s/transactions' % account_id
            params = {}
            committed_cursor = state.committed_cursor or False
            cursor_before = committed_cursor or akahu_account.sync_cursor or False

            explicit_recovery = bool(self.env.context.get('akahu_force_recovery'))
            run_mode = self._determine_sync_mode(
                state,
                akahu_account,
                account_changed=account_changed,
                explicit_recovery=explicit_recovery,
            )
            recovery_start = False
            recovery_end = False

            if run_mode == 'normal':
                params['cursor'] = committed_cursor
            elif run_mode == 'recovery':
                if not state.last_successful_transaction_date:
                    raise UserError(_(
                        'Cursor recovery is required for %s, but no historical checkpoint date is available. '
                        'Refusing unbounded historical import.'
                    ) % akahu_account.name)

                overlap_days = sync_cfg['recovery_overlap_days']
                max_days = sync_cfg['max_recovery_days']
                recovery_end = self._normalize_datetime_utc(fields.Datetime.now())
                checkpoint_dt = self._normalize_datetime_utc(state.last_successful_transaction_date)
                recovery_start = checkpoint_dt - timedelta(days=overlap_days)
                total_span = recovery_end - recovery_start
                if total_span.total_seconds() > (max_days * 86400):
                    recovery_limit_hit = True
                    failure_reason = 'max_days_limit'
                    raise UserError(_(
                        'Recovery window for %s spans %.6f days which exceeds the configured maximum of %d days. '
                        'Refusing unbounded recovery import.'
                    ) % (akahu_account.name, total_span.total_seconds() / 86400.0, max_days))

                params['start'] = self._to_akahu_iso(recovery_start)
                params['end'] = self._to_akahu_iso(recovery_end)

                state.sudo().write({
                    'recovery_reason': 'cursor_missing_or_inconsistent',
                    'recovery_window_start': recovery_start,
                    'recovery_window_end': recovery_end,
                    'recovery_overlap_days': overlap_days,
                })

            state.sudo().write({
                'recovery_mode': run_mode,
                'sync_mode': self._map_run_mode_to_sync_mode(run_mode),
                'checkpoint_status': 'inflight',
                'checkpoint_updated_at': fields.Datetime.now(),
            })

            sync_run.sudo().write({
                'cursor_before': cursor_before,
                'sync_mode': state.sync_mode or self._map_run_mode_to_sync_mode(run_mode),
                'run_mode': run_mode,
                'recovery_start': recovery_start,
                'recovery_end': recovery_end,
                'recovery_overlap_days': sync_cfg['recovery_overlap_days'] if run_mode == 'recovery' else 0,
            })

            existing_ids_by_journal = {}
            resolver = self.env['akahu.identity.resolver']

            def _get_existing_ids_for_journal(journal):
                journal_key = journal.id
                if journal_key not in existing_ids_by_journal:
                    existing_ids_by_journal[journal_key] = self._get_existing_akahu_ids(journal)
                return existing_ids_by_journal[journal_key]

            pending_last_successful_date = self._normalize_datetime_utc(state.last_successful_transaction_date)
            pending_last_successful_tx_id = state.last_successful_transaction_id

            while True:
                allowed_pages = sync_cfg['max_recovery_pages'] if run_mode == 'recovery' else MAX_PAGES
                if page_count >= allowed_pages:
                    recovery_limit_hit = run_mode == 'recovery'
                    failure_reason = 'max_pages_limit'
                    raise UserError(_(
                        'Akahu sync for account %s aborted: exceeded %d page limit.'
                    ) % (akahu_account.name, allowed_pages))

                page_count += 1
                _logger.info(
                    'Akahu sync: fetching page %d for account %s (cursor: %s)',
                    sanitize_log_value(page_count),
                    sanitize_log_value(akahu_account.name),
                    sanitize_log_value(params.get('cursor', 'none')),
                )

                try:
                    data = cred._api_get(akahu_account._get_user_token(), path, params=params)
                except UserError as e:
                    if '401' in str(e) or '403' in str(e):
                        akahu_account.write({'akahu_status': 'INACTIVE'})
                    raise

                items = data.get('items', [])
                if run_mode == 'recovery':
                    max_recovery_transactions = sync_cfg['max_recovery_transactions']
                    if (total_fetched + len(items)) > max_recovery_transactions:
                        recovery_limit_hit = True
                        failure_reason = 'max_transactions_limit'
                        raise UserError(_(
                            'Akahu recovery sync for %s aborted: transaction count exceeds configured limit (%d).'
                        ) % (akahu_account.name, max_recovery_transactions))

                total_fetched += len(items)

                page_imported = 0
                page_failed = 0
                page_seen = 0
                page_skipped_by_id = 0
                page_skipped_lineage = 0
                page_skipped_fingerprint = 0
                page_possible_duplicates = 0
                page_identity_conflicts = 0
                page_savepoint = False
                if run_mode == 'recovery':
                    page_savepoint = 'akahu_recovery_page_%s' % page_count
                    self.env.cr.execute('SAVEPOINT %s' % page_savepoint)
                try:
                    for tx in items:
                        tx_id = tx.get('_id')
                        if not tx_id:
                            _logger.warning(
                                'Akahu sync: skipping transaction with missing _id for account %s',
                                sanitize_log_value(akahu_account.name),
                            )
                            continue

                        page_seen += 1
                        destination_journal = self._resolve_journal(tx, akahu_account)
                        existing_identity = self._find_identity_for_journal_tx(destination_journal, tx_id)

                        if existing_identity:
                            page_skipped_by_id += 1
                            decision_counts['exact_id'] += 1
                            _logger.info(
                                'Akahu identity decision: exact_id skip for tx %s in journal %s',
                                sanitize_log_value(tx_id),
                                sanitize_log_value(destination_journal.id),
                            )
                            self._refresh_identity_observation(
                                existing_identity,
                                tx,
                                sync_run=sync_run,
                                incoming_akahu_account_id=akahu_account.akahu_account_id,
                                incoming_akahu_connection_id=state.current_akahu_connection_id,
                            )
                            continue

                        existing_ids = _get_existing_ids_for_journal(destination_journal)
                        if tx_id in existing_ids:
                            page_skipped_by_id += 1
                            decision_counts['exact_id'] += 1
                            _logger.info(
                                'Akahu identity decision: unique_import_id replay skip for tx %s in journal %s',
                                sanitize_log_value(tx_id),
                                sanitize_log_value(destination_journal.id),
                            )
                            existing_line = self._find_statement_line_by_unique_import(destination_journal, tx_id)
                            self._register_identity_for_transaction(
                                destination_journal,
                                akahu_account.company_id,
                                tx,
                                statement_line=existing_line,
                                sync_run=sync_run,
                                relation_type='exact_id',
                                identity_match_type='exact_id',
                                confidence='high',
                                matched_fields=['akahu_transaction_id'],
                                conflicting_fields=[],
                                reason='unique_import_id_replay',
                                incoming_akahu_account_id=akahu_account.akahu_account_id,
                                incoming_akahu_connection_id=state.current_akahu_connection_id,
                            )
                            continue

                        resolution = resolver.resolve_transaction_identity(
                            destination_journal,
                            tx,
                            sync_state=state,
                            incoming_akahu_account_id=akahu_account.akahu_account_id,
                            incoming_akahu_connection_id=state.current_akahu_connection_id,
                        )
                        resolution_type = resolution.get('resolution_type') or 'new'
                        if resolution_type not in decision_counts:
                            resolution_type = 'new'
                        decision_counts[resolution_type] += 1

                        _logger.info(
                            'Akahu identity decision: %s (%s) for tx %s in journal %s',
                            sanitize_log_value(resolution_type),
                            sanitize_log_value(resolution.get('confidence') or 'none'),
                            sanitize_log_value(tx_id),
                            sanitize_log_value(destination_journal.id),
                        )

                        if resolution_type in ('lineage', 'fingerprint_high'):
                            existing_line_id = resolution.get('existing_statement_line_id')
                            existing_line = self.env['account.bank.statement.line'].sudo().browse(existing_line_id) if existing_line_id else False
                            if not existing_line or not existing_line.exists():
                                # Safety invariant: uncertain identity must not be suppressed.
                                resolution_type = 'possible_duplicate'
                                decision_counts[resolution.get('resolution_type')] -= 1
                                decision_counts['possible_duplicate'] += 1
                                resolution = dict(resolution)
                                resolution.update({
                                    'resolution_type': 'possible_duplicate',
                                    'confidence': 'low',
                                    'reason': 'missing_existing_line_for_suppression',
                                })
                            else:
                                relation_type = 'migrated_from' if resolution_type == 'lineage' else 'fingerprint_high'
                                self._register_identity_for_transaction(
                                    destination_journal,
                                    akahu_account.company_id,
                                    tx,
                                    statement_line=existing_line,
                                    sync_run=sync_run,
                                    relation_type=relation_type,
                                    identity_match_type=resolution_type,
                                    confidence=resolution.get('confidence') or 'high',
                                    matched_fields=resolution.get('matched_fields') or [],
                                    conflicting_fields=resolution.get('conflicting_fields') or [],
                                    reason=resolution.get('reason') or '',
                                    incoming_akahu_account_id=akahu_account.akahu_account_id,
                                    incoming_akahu_connection_id=state.current_akahu_connection_id,
                                )

                                if resolution_type == 'lineage':
                                    page_skipped_lineage += 1
                                else:
                                    page_skipped_fingerprint += 1
                                continue

                        line, created = self._create_statement_line_with_identity(
                            akahu_account,
                            tx,
                            destination_journal,
                            sync_run=sync_run,
                            resolution=resolution,
                            incoming_akahu_account_id=akahu_account.akahu_account_id,
                            incoming_akahu_connection_id=state.current_akahu_connection_id,
                        )
                        if created:
                            page_imported += 1
                            if resolution_type == 'possible_duplicate':
                                page_possible_duplicates += 1
                            elif resolution_type == 'identity_conflict':
                                page_identity_conflicts += 1
                        else:
                            page_failed += 1

                    total_imported += page_imported
                    total_failed += page_failed
                    total_seen += page_seen
                    total_skipped_by_id += page_skipped_by_id
                    total_skipped_lineage += page_skipped_lineage
                    total_skipped_fingerprint += page_skipped_fingerprint
                    total_possible_duplicates += page_possible_duplicates
                    total_identity_conflicts += page_identity_conflicts

                    cursor = data.get('cursor', {})
                    next_cursor = cursor.get('next') if cursor else None
                    page_committed_cursor = cursor.get('current') if cursor else None

                    if page_failed == 0:
                        pages_processed += 1
                        checkpoint_cursor = page_committed_cursor or state.committed_cursor or akahu_account.sync_cursor
                        page_last_dt, page_last_tx_id = self._extract_last_checkpoint(items)

                        if page_last_dt and (
                            not pending_last_successful_date
                            or page_last_dt > pending_last_successful_date
                        ):
                            pending_last_successful_date = page_last_dt
                            pending_last_successful_tx_id = page_last_tx_id

                        state_vals = {
                            'inflight_cursor': checkpoint_cursor,
                            'inflight_page_no': page_count,
                            'last_successful_transaction_date': pending_last_successful_date,
                            'last_successful_transaction_id': pending_last_successful_tx_id,
                            'last_successful_fetch_at': fields.Datetime.now(),
                            'checkpoint_status': 'committed',
                            'checkpoint_updated_at': fields.Datetime.now(),
                        }
                        if checkpoint_cursor:
                            state_vals['committed_cursor'] = checkpoint_cursor
                        state.sudo().write(state_vals)
                        if checkpoint_cursor:
                            akahu_account.sudo().write({'sync_cursor': checkpoint_cursor})

                        if page_savepoint:
                            self.env.cr.execute('RELEASE SAVEPOINT %s' % page_savepoint)
                    else:
                        if page_savepoint:
                            self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % page_savepoint)
                        error_message = (
                            '%d of %d new transaction(s) on page %d failed to import; '
                            'cursor checkpoint not advanced for this page.'
                        ) % (page_failed, len(new_transactions), page_count)
                        failure_reason = 'page_import_failure'
                        _logger.error(
                            'Akahu sync: %s for account %s',
                            sanitize_log_value(error_message),
                            sanitize_log_value(akahu_account.name),
                        )
                        break
                except Exception:
                    if page_savepoint:
                        self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % page_savepoint)
                    raise

                if not next_cursor:
                    break
                params['cursor'] = next_cursor

            sync_ok = total_failed == 0
            now = fields.Datetime.now()

            if sync_ok and run_mode == 'recovery':
                state.sudo().write({
                    'checkpoint_status': 'committed',
                    'checkpoint_updated_at': now,
                })

            account_write_vals = {'last_synced': now}
            if sync_ok and state.committed_cursor:
                account_write_vals['sync_cursor'] = state.committed_cursor
            akahu_account.sudo().write(account_write_vals)

            if sync_ok:
                state.sudo().write({
                    'state_status': 'ready',
                    'last_successful_sync_at': now,
                    'checkpoint_status': 'committed',
                    'checkpoint_updated_at': now,
                    'recovery_reason': False if run_mode != 'recovery' else state.recovery_reason,
                })
            else:
                checkpoint_status = 'failed'
                if run_mode == 'recovery' and state.committed_cursor:
                    checkpoint_status = 'committed'
                state.sudo().write({
                    'state_status': 'failed',
                    'checkpoint_status': checkpoint_status,
                    'checkpoint_updated_at': now,
                })

            log_vals = {
                'akahu_account_id': akahu_account.id,
                'company_id': akahu_account.company_id.id,
                'status': 'success' if sync_ok else 'error',
                'transactions_fetched': total_fetched,
                'transactions_imported': total_imported,
            }
            if not sync_ok:
                log_vals['error_message'] = error_message or (
                    '%d transaction(s) failed; cursor checkpoint was not advanced on failing page(s).'
                ) % total_failed
            self.env['akahu.sync.log'].sudo().create(log_vals)

            self._finalize_sync_run(sync_run, {
                'status': 'success' if sync_ok else 'error',
                'cursor_after': state.committed_cursor or akahu_account.sync_cursor or False,
                'pages_fetched': page_count,
                'pages_requested': page_count,
                'pages_processed': pages_processed,
                'transactions_fetched': total_fetched,
                'created_count': total_imported,
                'skipped_by_id_count': total_skipped_by_id,
                'transactions_seen': total_seen,
                'transactions_created': total_imported,
                'transactions_imported': total_imported,
                'transactions_skipped': total_skipped_by_id + total_skipped_lineage + total_skipped_fingerprint,
                'transactions_duplicate': total_skipped_by_id + total_skipped_lineage + total_skipped_fingerprint,
                'transactions_skipped_same_id': total_skipped_by_id,
                'transactions_skipped_lineage': total_skipped_lineage,
                'transactions_skipped_fingerprint': total_skipped_fingerprint,
                'possible_duplicates': total_possible_duplicates,
                'identity_conflicts': total_identity_conflicts,
                'identity_match_type': self._dominant_identity_match_type(decision_counts),
                'recovery_limit_hit': recovery_limit_hit,
                'failure_reason': failure_reason or ('recovery_failed' if not sync_ok and run_mode == 'recovery' else False),
                'error_message': error_message or False,
            })
            run_finalized = True

            return {
                'imported': total_imported,
                'fetched': total_fetched,
                'failed': total_failed,
                'skipped_by_id': total_skipped_by_id,
                'seen': total_seen,
                'skipped_lineage': total_skipped_lineage,
                'skipped_fingerprint': total_skipped_fingerprint,
                'possible_duplicates': total_possible_duplicates,
                'identity_conflicts': total_identity_conflicts,
            }

        except Exception as e:
            if not lock_contention:
                current_mode = locals().get('run_mode')
                checkpoint_status = 'failed'
                if current_mode == 'recovery' and state.committed_cursor:
                    checkpoint_status = 'committed'
                state.sudo().write({
                    'state_status': 'failed',
                    'checkpoint_status': checkpoint_status,
                    'checkpoint_updated_at': fields.Datetime.now(),
                })
            if not run_finalized:
                self._finalize_sync_run(sync_run, {
                    'status': 'error',
                    'cursor_after': state.committed_cursor or akahu_account.sync_cursor or False,
                    'pages_fetched': page_count,
                    'pages_requested': page_count,
                    'pages_processed': pages_processed,
                    'transactions_fetched': total_fetched,
                    'created_count': total_imported,
                    'skipped_by_id_count': total_skipped_by_id,
                    'transactions_seen': total_seen,
                    'transactions_created': total_imported,
                    'transactions_imported': total_imported,
                    'transactions_skipped': total_skipped_by_id + total_skipped_lineage + total_skipped_fingerprint,
                    'transactions_duplicate': total_skipped_by_id + total_skipped_lineage + total_skipped_fingerprint,
                    'transactions_skipped_same_id': total_skipped_by_id,
                    'transactions_skipped_lineage': total_skipped_lineage,
                    'transactions_skipped_fingerprint': total_skipped_fingerprint,
                    'possible_duplicates': total_possible_duplicates,
                    'identity_conflicts': total_identity_conflicts,
                    'identity_match_type': self._dominant_identity_match_type(decision_counts),
                    'recovery_limit_hit': recovery_limit_hit,
                    'failure_reason': failure_reason or 'exception',
                    'error_message': _sanitize_error_text(str(e)),
                })
            raise
        finally:
            if lock_acquired:
                try:
                    self._release_journal_lock(akahu_account.journal_id.id)
                except Exception as lock_err:
                    _logger.warning(
                        'Failed to release advisory lock for journal %s: %s',
                        sanitize_log_value(akahu_account.journal_id.id),
                        sanitize_log_value(lock_err),
                    )
            state.sudo().write({'lock_owner_run_id': False})

    # ── HELPERS ────────────────────────────────────────────────────────────────

    def _get_existing_akahu_ids(self, journal):
        """
        Odoo 18 uses unique_import_id for deduplication — a native column
        on account_bank_statement_line. We store the Akahu _id there directly.

        C2 FIX: If the calling user cannot read this journal (multi-company
        access rules) journal.id resolves to False, which turns the WHERE clause
        into `journal_id = False`, matching nothing — so every transaction looks
        new and gets re-imported on every cron run.  We raise explicitly so the
        caller's error handler can log it rather than silently duplicating data.
        """
        if not journal.id:
            raise UserError(_(
                'Cannot deduplicate transactions: journal is not readable '
                'by the current user. Ensure the sync runs with sudo() or '
                'that the user has access to the journal.'
            ))
        self.env.cr.execute("""
            SELECT unique_import_id FROM account_bank_statement_line
            WHERE journal_id = %s
              AND unique_import_id LIKE 'akahu-%%'
        """, (journal.id,))
        rows = self.env.cr.fetchall()
        # Strip the 'akahu-' prefix to get back the raw Akahu _id
        return {row[0].replace('akahu-', '', 1) for row in rows if row[0]}

    def _dominant_identity_match_type(self, decision_counts):
        if not decision_counts:
            return False
        dominant = None
        dominant_count = 0
        for key, value in decision_counts.items():
            if value > dominant_count:
                dominant = key
                dominant_count = value
        return dominant or False

    def _find_identity_for_journal_tx(self, journal, tx_id):
        return self.env['akahu.transaction.identity'].sudo().search([
            ('journal_id', '=', journal.id),
            ('akahu_transaction_id', '=', tx_id),
        ], limit=1)

    def _find_statement_line_by_unique_import(self, journal, tx_id):
        if not tx_id:
            return self.env['account.bank.statement.line']
        return self.env['account.bank.statement.line'].sudo().search([
            ('journal_id', '=', journal.id),
            ('unique_import_id', '=', 'akahu-%s' % tx_id),
        ], order='id desc', limit=1)

    def _create_statement_line_with_identity(
        self,
        akahu_account,
        tx,
        destination_journal,
        sync_run,
        resolution,
        incoming_akahu_account_id=False,
        incoming_akahu_connection_id=False,
    ):
        tx_id = tx.get('_id') or 'unknown'
        savepoint_name = 'akahu_phase3b_%s' % ''.join(c if c.isalnum() else '_' for c in tx_id)[:40]
        self.env.cr.execute('SAVEPOINT %s' % savepoint_name)
        try:
            created = self._create_statement_lines(akahu_account, [tx])
            if created != 1:
                raise UserError(_('Statement line creation failed for transaction %s') % tx_id)

            line = self._find_statement_line_by_unique_import(destination_journal, tx.get('_id'))
            if not line:
                raise UserError(_('Created statement line could not be reloaded for transaction %s') % tx_id)

            resolution_type = (resolution or {}).get('resolution_type') or 'new'
            relation_type = {
                'possible_duplicate': 'possible_fingerprint',
                'identity_conflict': 'identity_conflict',
                'new': 'new',
            }.get(resolution_type, 'new')
            identity_match_type = {
                'possible_duplicate': 'possible_fingerprint',
                'identity_conflict': 'identity_conflict',
                'new': 'new',
            }.get(resolution_type, 'new')
            confidence = (resolution or {}).get('confidence') or (
                'medium' if resolution_type == 'possible_duplicate' else 'low' if resolution_type == 'identity_conflict' else 'none'
            )

            self._register_identity_for_transaction(
                destination_journal,
                akahu_account.company_id,
                tx,
                statement_line=line,
                sync_run=sync_run,
                relation_type=relation_type,
                identity_match_type=identity_match_type,
                confidence=confidence,
                matched_fields=(resolution or {}).get('matched_fields') or [],
                conflicting_fields=(resolution or {}).get('conflicting_fields') or [],
                reason=(resolution or {}).get('reason') or '',
                incoming_akahu_account_id=incoming_akahu_account_id,
                incoming_akahu_connection_id=incoming_akahu_connection_id,
            )

            if resolution_type in ('possible_duplicate', 'identity_conflict'):
                self._create_forensic_finding(
                    akahu_account,
                    destination_journal,
                    tx,
                    line,
                    resolution,
                    sync_run=sync_run,
                    resolver_version=RESOLVER_VERSION,
                )

            self.env.cr.execute('RELEASE SAVEPOINT %s' % savepoint_name)
            return line, True
        except Exception as e:
            self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % savepoint_name)
            _logger.warning(
                'Failed Phase 3B atomic create+identity for tx %s: %s',
                sanitize_log_value(tx.get('_id')),
                sanitize_log_value(e),
            )
            return False, False

    def _refresh_identity_observation(
        self,
        identity,
        tx,
        sync_run,
        incoming_akahu_account_id=False,
        incoming_akahu_connection_id=False,
    ):
        vals = {
            'last_seen_at': fields.Datetime.now(),
            'last_seen_run_id': sync_run.id,
        }
        if incoming_akahu_account_id:
            vals['last_seen_akahu_account_id'] = incoming_akahu_account_id
        if incoming_akahu_connection_id:
            vals['last_seen_akahu_connection_id'] = incoming_akahu_connection_id
        identity.sudo().write(vals)

    def _register_identity_for_transaction(
        self,
        journal,
        company,
        tx,
        statement_line,
        sync_run,
        relation_type,
        identity_match_type,
        confidence,
        matched_fields,
        conflicting_fields,
        reason,
        incoming_akahu_account_id=False,
        incoming_akahu_connection_id=False,
    ):
        tx_id = tx.get('_id')
        if not tx_id:
            return self.env['akahu.transaction.identity']

        Identity = self.env['akahu.transaction.identity'].sudo()
        existing = Identity.search([
            ('journal_id', '=', journal.id),
            ('akahu_transaction_id', '=', tx_id),
        ], limit=1)
        if existing:
            self._refresh_identity_observation(
                existing,
                tx,
                sync_run=sync_run,
                incoming_akahu_account_id=incoming_akahu_account_id,
                incoming_akahu_connection_id=incoming_akahu_connection_id,
            )
            return existing

        resolver = self.env['akahu.identity.resolver']
        incoming_sig = resolver._build_incoming_signature(
            journal,
            tx,
            incoming_akahu_account_id=incoming_akahu_account_id,
            incoming_akahu_connection_id=incoming_akahu_connection_id,
        )
        now = fields.Datetime.now()
        vals = {
            'journal_id': journal.id,
            'company_id': company.id,
            'akahu_transaction_id': tx_id,
            'akahu_account_id': incoming_akahu_account_id or incoming_sig.get('akahu_account_id') or False,
            'akahu_connection_id': incoming_akahu_connection_id or incoming_sig.get('akahu_connection_id') or False,
            'akahu_migrated_from': tx.get('_migrated') or False,
            'akahu_migrated_account': tx.get('_migrated_account') or False,
            'first_seen_akahu_account_id': incoming_akahu_account_id or incoming_sig.get('akahu_account_id') or False,
            'last_seen_akahu_account_id': incoming_akahu_account_id or incoming_sig.get('akahu_account_id') or False,
            'first_seen_akahu_connection_id': incoming_akahu_connection_id or incoming_sig.get('akahu_connection_id') or False,
            'last_seen_akahu_connection_id': incoming_akahu_connection_id or incoming_sig.get('akahu_connection_id') or False,
            'transaction_fingerprint': incoming_sig.get('legacy_fingerprint') or False,
            'relation_type': relation_type,
            'confidence': confidence if confidence in ('high', 'medium', 'low', 'unknown') else 'unknown',
            'identity_match_type': identity_match_type,
            'statement_line_id': statement_line.id if statement_line else False,
            'first_seen_run_id': sync_run.id,
            'last_seen_run_id': sync_run.id,
            'first_seen_at': now,
            'last_seen_at': now,
            'matched_fields': ','.join(sorted(set(matched_fields or []))) or False,
            'conflicting_fields': ','.join(sorted(set(conflicting_fields or []))) or False,
            'source_payload_signature': incoming_sig.get('legacy_fingerprint') or False,
            'forensic_note': reason or False,
        }
        try:
            return Identity.create(vals)
        except Exception:
            # Concurrent insertion may have created this identity row first.
            return Identity.search([
                ('journal_id', '=', journal.id),
                ('akahu_transaction_id', '=', tx_id),
            ], limit=1)

    def _create_forensic_finding(self, akahu_account, journal, tx, incoming_line, resolution, sync_run, resolver_version):
        existing_line = self.env['account.bank.statement.line'].sudo().browse(
            (resolution or {}).get('existing_statement_line_id')
        ) if (resolution or {}).get('existing_statement_line_id') else self.env['account.bank.statement.line']

        batch = self.env['akahu.duplicate.finding.batch'].sudo().search([
            ('sync_run_id', '=', sync_run.id),
            ('journal_id', '=', journal.id),
        ], limit=1)
        if not batch:
            batch = self.env['akahu.duplicate.finding.batch'].sudo().create({
                'name': 'AKAHU-DUP-%s' % ((sync_run.run_id or str(sync_run.id)).split('-')[0]),
                'company_id': akahu_account.company_id.id,
                'journal_id': journal.id,
                'sync_run_id': sync_run.id,
                'state': 'draft',
                'note': 'resolver_version=%s' % resolver_version,
            })

        meta = tx.get('meta') or {}
        tx_date = self._parse_tx_datetime(tx)
        incoming_date = tx_date.date() if tx_date else fields.Date.today()
        description = tx.get('description') or tx.get('type') or _('Akahu Transaction')
        ref_parts = [description]
        for key in ('particulars', 'code', 'reference'):
            val = meta.get(key)
            if val and str(val).strip():
                ref_parts.append(str(val).strip())
        incoming_payment_ref = ' | '.join(ref_parts)

        incoming_sig = self.env['akahu.identity.resolver']._build_incoming_signature(
            journal,
            tx,
            incoming_akahu_account_id=akahu_account.akahu_account_id,
            incoming_akahu_connection_id=False,
        )

        self.env['akahu.duplicate.finding'].sudo().create({
            'batch_id': batch.id,
            'company_id': akahu_account.company_id.id,
            'journal_id': journal.id,
            'classification': 'possible_duplicate' if (resolution or {}).get('resolution_type') == 'possible_duplicate' else 'unknown',
            'confidence': (resolution or {}).get('confidence') or 'unknown',
            'identity_match_type': 'possible_fingerprint' if (resolution or {}).get('resolution_type') == 'possible_duplicate' else 'identity_conflict',
            'existing_statement_line_id': existing_line.id if existing_line else False,
            'incoming_statement_line_id': incoming_line.id if incoming_line else False,
            'existing_unique_import_id': existing_line.unique_import_id if existing_line else False,
            'incoming_unique_import_id': 'akahu-%s' % (tx.get('_id') or ''),
            'existing_akahu_transaction_id': existing_line.akahu_transaction_id if existing_line else False,
            'incoming_akahu_transaction_id': tx.get('_id') or False,
            'incoming_akahu_migrated_from': tx.get('_migrated') or False,
            'incoming_akahu_migrated_account': tx.get('_migrated_account') or False,
            'existing_date': existing_line.date if existing_line else False,
            'incoming_date': incoming_date,
            'existing_amount': existing_line.amount if existing_line else 0.0,
            'incoming_amount': float(tx.get('amount', 0.0)),
            'existing_payment_ref': existing_line.payment_ref if existing_line else False,
            'incoming_payment_ref': incoming_payment_ref,
            'existing_partner_name': existing_line.partner_name if existing_line else False,
            'incoming_partner_name': meta.get('other_account') or False,
            'existing_fingerprint': existing_line.akahu_transaction_fingerprint if existing_line else False,
            'incoming_fingerprint': incoming_sig.get('legacy_fingerprint'),
            'matching_fields': ','.join((resolution or {}).get('matched_fields') or []),
            'conflicting_fields': ','.join((resolution or {}).get('conflicting_fields') or []),
            'reason': '%s | resolver_version=%s | candidate_count=%s' % (
                (resolution or {}).get('reason') or '',
                resolver_version,
                (resolution or {}).get('candidate_count', 0),
            ),
            'existing_is_reconciled': bool(existing_line and existing_line.is_reconciled),
            'existing_move_id': existing_line.move_id.id if existing_line and existing_line.move_id else False,
            'existing_move_name': existing_line.move_id.name if existing_line and existing_line.move_id else False,
        })

        batch.with_context(allow_akahu_forensic_write=True).sudo().write({
            'finding_count': batch.finding_count + 1,
            'state': 'completed',
        })

    def _create_statement_lines(self, akahu_account, transactions):
        """
        Create account.bank.statement.line records for each transaction.
        Returns count of lines created.

        C3 FIX: Each create() is wrapped in an explicit SAVEPOINT so that a
        DB constraint failure (e.g. malformed unique_import_id, bad date) only
        aborts that single row.  Without savepoints, a mid-batch IntegrityError
        leaves the transaction in a broken state — subsequent ORM calls raise
        "InternalError: current transaction is aborted" and sync_cursor still
        gets updated, permanently losing those transactions.
        """
        # sudo(): statement lines are written by the sync cron which runs as a limited technical user
        BankLine = self.env['account.bank.statement.line'].sudo()
        count = 0

        for tx in transactions:
            # RISK-02 FIX: Savepoint names go directly into SQL without
            # parameter binding. Sanitize by keeping only alphanumeric chars
            # and underscores — Akahu IDs are currently alphanumeric but the
            # format is not formally guaranteed.
            raw_id = (tx.get('_id') or 'unknown')
            safe_id = ''.join(c if c.isalnum() else '_' for c in raw_id)
            savepoint = 'akahu_tx_%s' % safe_id[:50]  # also cap length
            try:
                self.env.cr.execute('SAVEPOINT %s' % savepoint)
                line_vals = self._map_transaction_to_statement_line(tx, akahu_account)
                BankLine.create(line_vals)
                self.env.cr.execute('RELEASE SAVEPOINT %s' % savepoint)
                count += 1
            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % savepoint)
                _logger.warning(
                    'Failed to create statement line for tx %s (savepoint rolled back): %s',
                    sanitize_log_value(tx.get('_id')),
                    sanitize_log_value(e),
                )

        return count

    def _map_transaction_to_statement_line(self, tx, akahu_account):
        """
        Map an Akahu transaction dict to account.bank.statement.line values.

        Odoo 18 schema used:
          unique_import_id  → 'akahu-{tx._id}'  (deduplication)
          payment_ref       → description + meta fields
          amount            → transaction amount
          partner_name      → other_account from meta
          transaction_type  → Akahu tx type (CARD, TRANSFER etc.)
          foreign_currency_id / amount_currency → for USD/AUD transactions
        """
        tx_id = tx.get('_id', '')
        date_str = tx.get('date', '')
        description = tx.get('description') or tx.get('type') or _('Akahu Transaction')
        amount = float(tx.get('amount', 0.0))
        meta = tx.get('meta') or {}

        # Parse date
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            tx_date = dt.date()
        except Exception:
            tx_date = fields.Date.today()

        # Build payment_ref from description + meta fields
        ref_parts = [description]
        for key in ['particulars', 'code', 'reference']:
            val = meta.get(key)
            if val and val.strip():
                ref_parts.append(val.strip())
        payment_ref = ' | '.join(ref_parts)

        # Route to correct journal (credit card vs bank)
        resolved_journal = self._resolve_journal(tx, akahu_account)

        vals = {
            'journal_id': resolved_journal.id,
            'date': tx_date,
            'payment_ref': payment_ref[:255],
            'amount': amount,
            'partner_name': meta.get('other_account') or False,
            'company_id': akahu_account.company_id.id,
            # Odoo 18 native deduplication field — prefix with 'akahu-' to namespace it
            'unique_import_id': 'akahu-%s' % tx_id,
        }

        # BUG-03 FIX: `transaction_type` only exists in Odoo Enterprise
        # (account_accountant module). Writing it on Community raises an
        # immediate KeyError / ValueError that crashes every transaction import.
        # Conditionally include it only when the field is actually present.
        BankLine = self.env['account.bank.statement.line']
        if 'transaction_type' in BankLine._fields:
            vals['transaction_type'] = tx.get('type') or False

        # Multi-currency: ASB returns conversion details for foreign card transactions
        # tx.meta.conversion = {"amount": -42.50, "currency": "USD", "rate": 0.6516}
        conversion = meta.get('conversion') or {}
        foreign_currency_code = conversion.get('currency')
        foreign_amount = conversion.get('amount')
        if foreign_currency_code and foreign_amount is not None:
            # sudo(): res.currency is only readable by internal users; cron technical user needs this for FX lookup
            foreign_currency = self.env['res.currency'].sudo().search(
                [('name', '=', foreign_currency_code.upper())], limit=1
            )
            if foreign_currency:
                vals['foreign_currency_id'] = foreign_currency.id
                vals['amount_currency'] = float(foreign_amount)

        return vals

    # ── Credit card journal routing ────────────────────────────────────────────
    CARD_TX_TYPES = {'CARD', 'EFTPOS', 'CREDIT_CARD'}

    # BUG FIX 6: Credit-card journal routing used `('name', 'ilike', 'credit')`
    # which matches any journal whose name contains the substring "credit" —
    # e.g. "Letters of Credit", "Accredited Partners" — silently routing card
    # transactions into the wrong journal with no warning.
    #
    # Fix: match on the journal's short code instead of its display name.
    # Standard NZ Odoo setups use codes like 'CC', 'VISA', 'AMEX', 'EFTPOS'
    # for credit/charge card journals.  The list is configurable below.
    # If none of these codes exist the method falls back to the account's
    # own journal (same safe behaviour as before).
    CREDIT_CARD_JOURNAL_CODES = {'CC', 'VISA', 'AMEX', 'MC', 'EFTPOS', 'CCARD'}

    def _resolve_journal(self, tx, akahu_account):
        """Route CARD/EFTPOS transactions to a credit card journal if one exists."""
        tx_type = (tx.get('type') or '').upper()
        if tx_type in self.CARD_TX_TYPES:
            # BUG FIX 6: Match on journal code, not on a substring of the name.
            # sudo(): cron technical user needs cross-company journal read for currency conversion entries
            cc_journal = self.env['account.journal'].sudo().search([
                ('company_id', '=', akahu_account.company_id.id),
                ('type', '=', 'bank'),
                ('code', 'in', list(self.CREDIT_CARD_JOURNAL_CODES)),
            ], limit=1)
            if cc_journal:
                return cc_journal
            _logger.debug(
                'Akahu: CARD transaction for %s but no credit-card journal found '
                '(codes checked: %s) — using default journal %s.',
                sanitize_log_value(akahu_account.name),
                sanitize_log_value(self.CREDIT_CARD_JOURNAL_CODES),
                sanitize_log_value(akahu_account.journal_id.code),
            )
        return akahu_account.journal_id
