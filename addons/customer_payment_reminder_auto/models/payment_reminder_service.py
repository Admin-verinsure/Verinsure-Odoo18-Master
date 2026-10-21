import logging
import re
import uuid
from collections import defaultdict
from datetime import timedelta
from email.utils import getaddresses, parseaddr

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

# Single, syntactically complete address: name@domain.tld (no spaces/commas, TLD of 2+ letters).
_EMAIL_RE = re.compile(
    r'^[^@\s,;<>()]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$'
)


class CustomerPaymentReminderService(models.AbstractModel):
    _name = 'customer.payment.reminder.service'
    _description = 'Customer Payment Reminder Service'

    @api.model
    def _payment_reminder_posted_field(self):
        aml_model = self.env['account.move.line']
        return 'parent_state' if 'parent_state' in aml_model._fields else 'move_id.state'

    @api.model
    def _payment_reminder_amount_rounding(self, company):
        return company.currency_id.rounding or 0.01

    @api.model
    def _payment_reminder_template(self, company):
        return company.payment_reminder_template_id or self.env.ref(
            'customer_payment_reminder_auto.mail_template_customer_payment_reminder',
            raise_if_not_found=False,
        )

    @api.model
    def _payment_reminder_email_from(self, company):
        return company.email or self.env.user.email or False

    @api.model
    def _payment_reminder_normalize_email(self, email_value):
        name, address = parseaddr(email_value or '')
        del name
        normalized = (address or '').strip().lower()
        if not normalized or not _EMAIL_RE.match(normalized):
            return False
        return normalized

    @api.model
    def _payment_reminder_overdue_invoices(self, company, partner):
        return self.env['account.move'].sudo().with_company(company).search([
            ('company_id', '=', company.id),
            ('commercial_partner_id', '=', partner.id),
            ('move_type', 'in', ('out_invoice', 'out_receipt')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date_due', '<', fields.Date.context_today(self)),
        ])

    @api.model
    def _payment_reminder_unique_emails(self, raw_values):
        emails = []
        for value in raw_values:
            for _name, address in getaddresses([(value or '').replace(';', ',')]):
                email = self._payment_reminder_normalize_email(address)
                if email and email not in emails:
                    emails.append(email)
        return emails

    @api.model
    def _payment_reminder_customer_moves(self, company, partner):
        """All posted invoices, credit notes and receipts of the customer (any
        payment state): the invoice / statement mail may sit on any of them."""
        return self.env['account.move'].sudo().with_company(company).search([
            ('company_id', '=', company.id),
            ('commercial_partner_id', '=', partner.id),
            ('move_type', 'in', ('out_invoice', 'out_refund', 'out_receipt')),
            ('state', '=', 'posted'),
        ])

    @api.model
    def _payment_reminder_chain_emails(self, moves, latest_only=False):
        """Recipients of the emails already sent from these documents (the mails
        that shared the invoice and statement with the customer).

        The recipients are the partners the mail was addressed to plus every
        partner Odoo actually emailed for it (the delivery records shown by the
        envelope icon in the chatter). With ``latest_only`` only the most recent
        mail is used, so old, outdated recipients are not picked up.
        """
        if not moves:
            return []
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'account.move'),
            ('res_id', 'in', moves.ids),
            ('message_type', 'in', ('comment', 'email_outgoing')),
            ('subtype_id', '!=', False),
            ('subtype_id.internal', '=', False),
        ], order='date desc, id desc')
        if latest_only:
            messages = messages[:1]
        if not messages:
            return []
        raw = [partner.email for partner in messages.partner_ids]
        notifications = self.env['mail.notification'].sudo().search([
            ('mail_message_id', 'in', messages.ids),
            ('notification_type', '=', 'email'),
            ('notification_status', '!=', 'canceled'),
        ])
        raw += notifications.res_partner_id.mapped('email')
        # Mails that still exist may also carry plain addresses (not partners).
        for mail in self.env['mail.mail'].sudo().search([('mail_message_id', 'in', messages.ids)]):
            raw += [mail.email_to, mail.email_cc]
        return self._payment_reminder_unique_emails(raw)

    @api.model
    def _payment_reminder_follower_emails(self, moves):
        followers = moves.sudo().message_follower_ids.partner_id.filtered('active')
        return self._payment_reminder_unique_emails(followers.mapped('email'))

    @api.model
    def _payment_reminder_recipients(self, company, partner):
        """Who receives the reminder for a customer:

        1. the recipients of the emails already sent from the customer's overdue
           invoices (invoice / statement mails);
        2. if there are none, the followers of those invoices (when enabled);
        3. if there are still none, the customer's own address.
        A reminder email override set on the customer is always included.
        """
        recipients = []
        override = self._payment_reminder_normalize_email(partner.payment_reminder_email_override)
        if override:
            recipients.append(override)

        moves = self._payment_reminder_overdue_invoices(company, partner)
        found = self._payment_reminder_chain_emails(moves)
        if not found:
            # The mail may sit on an already paid invoice or on a credit note.
            found = self._payment_reminder_chain_emails(
                self._payment_reminder_customer_moves(company, partner),
                latest_only=True,
            )
        followers_disabled = self.env['ir.config_parameter'].sudo().get_param(
            'customer_payment_reminder_auto.disable_follower_fallback'
        )
        if not found and not followers_disabled:
            found = self._payment_reminder_follower_emails(moves)
        if not found and not override:
            found = self._payment_reminder_unique_emails([partner.email])

        for email in found:
            if email not in recipients:
                recipients.append(email)
        return recipients

    @api.model
    def _payment_reminder_format_amount(self, company, amount):
        rounded_amount = company.currency_id.round(amount)
        symbol = company.currency_id.symbol or company.currency_id.name or ''
        return f'{symbol}{rounded_amount:,.2f}' if symbol else f'{rounded_amount:,.2f}'

    @api.model
    def _payment_reminder_advisory_lock_key(self):
        return 180120261012

    @api.model
    def _payment_reminder_try_lock(self):
        self.env.cr.execute(
            'SELECT pg_try_advisory_xact_lock(%s)',
            [self._payment_reminder_advisory_lock_key()],
        )
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    @api.model
    def _payment_reminder_commit_and_relock(self):
        """Persist the work done so far (logs + already-sent mails) and re-take the
        advisory lock for the next transaction. Returns False when another run has
        taken the lock in the meantime, in which case the caller must stop."""
        if self.env.registry.in_test_mode():
            return True
        self.env.cr.commit()
        if not self._payment_reminder_try_lock():
            _logger.warning('Payment reminder run stopped: advisory lock was taken by another execution.')
            return False
        return True

    @api.model
    def _payment_reminder_base_domain(self, company, commercial_partner=None):
        aml_model = self.env['account.move.line']
        domain = [
            ('company_id', '=', company.id),
            ('partner_id', '!=', False),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('amount_residual', '!=', 0),
            (self._payment_reminder_posted_field(), '=', 'posted'),
            # Only overdue items count: not-yet-due invoices must not trigger or
            # inflate a reminder. Lines without a maturity date are treated as due.
            '|',
            ('date_maturity', '<', fields.Date.context_today(self)),
            ('date_maturity', '=', False),
        ]
        if 'reconciled' in aml_model._fields:
            domain.append(('reconciled', '=', False))
        if commercial_partner:
            domain.append(('partner_id', 'child_of', commercial_partner.ids))
        return domain

    @api.model
    def _payment_reminder_collect_balances(self, company, commercial_partner=None):
        aml_model = self.env['account.move.line'].sudo().with_company(company)
        domain = self._payment_reminder_base_domain(company, commercial_partner=commercial_partner)
        lines = aml_model.search(domain)

        balances = defaultdict(float)
        partners = self.env['res.partner']
        for line in lines:
            partner = line.partner_id.commercial_partner_id
            if not partner:
                continue
            partners |= partner
            balances[partner.id] += line.amount_residual

        # `commercial_partner` may be one or several partners: make sure each of them
        # is evaluated (and logged) even when it has no open receivable line.
        for requested_partner in commercial_partner or []:
            if requested_partner.id not in balances:
                partners |= requested_partner
                balances[requested_partner.id] = 0.0

        return [(partner, balances.get(partner.id, 0.0)) for partner in partners]

    @api.model
    def _payment_reminder_last_sent(self, company, partner):
        return self.env['customer.payment.reminder.log'].sudo().search([
            ('company_id', '=', company.id),
            ('commercial_partner_id', '=', partner.id),
            ('status', '=', 'sent'),
            ('is_dry_run', '=', False),
        ], order='reminder_datetime desc, id desc', limit=1)

    @api.model
    def _payment_reminder_skip_reason(self, company, partner, outstanding_amount):
        rounding = self._payment_reminder_amount_rounding(company)
        rounded_outstanding = company.currency_id.round(outstanding_amount)
        if not partner.active:
            return _('Partner is inactive.'), False
        if not partner.payment_reminder_enabled:
            return _('Automatic payment reminders are disabled for this customer.'), False
        if float_compare(rounded_outstanding, 0.0, precision_rounding=rounding) <= 0:
            return _('Customer does not have a net receivable balance.'), False
        if float_compare(
            rounded_outstanding,
            company.payment_reminder_min_outstanding,
            precision_rounding=rounding,
        ) < 0:
            return _(
                'Outstanding balance %(amount)s is below the threshold %(threshold)s.',
                amount=self._payment_reminder_format_amount(company, rounded_outstanding),
                threshold=self._payment_reminder_format_amount(
                    company,
                    company.payment_reminder_min_outstanding,
                ),
            ), False

        recipients = self._payment_reminder_recipients(company, partner)
        if not recipients:
            return _('Customer does not have a valid reminder email address.'), False
        recipient_email = ', '.join(recipients)

        cooldown_days = max(company.payment_reminder_cooldown_days or 0, 0)
        if cooldown_days:
            latest_log = self._payment_reminder_last_sent(company, partner)
            if latest_log:
                latest_dt = fields.Datetime.to_datetime(latest_log.reminder_datetime)
                now_dt = fields.Datetime.to_datetime(fields.Datetime.now())
                if latest_dt and now_dt and latest_dt + timedelta(days=cooldown_days) > now_dt:
                    return _(
                        'Reminder cooldown is active until %(date)s.',
                        date=fields.Datetime.to_string(latest_dt + timedelta(days=cooldown_days)),
                    ), recipient_email

        return False, recipient_email

    @api.model
    def _payment_reminder_safe_recipient_label(self, company, partner):
        """Recipients for a log line; never raises (used while logging a failure)."""
        try:
            with self.env.cr.savepoint():
                return ', '.join(self._payment_reminder_recipients(company, partner)) or False
        except Exception:
            return False

    @api.model
    def _payment_reminder_statements_enabled(self):
        # Inverted parameter: Odoo deletes a boolean parameter when it is switched off.
        return not self.env['ir.config_parameter'].sudo().get_param(
            'customer_payment_reminder_auto.disable_statement_attachment'
        )

    @api.model
    def _payment_reminder_statement_report(self):
        """The Customer Statement report to use: ``tk_statements`` (preferred) or
        the older ``tk_customer_statements``. Returns ``(report, is_current_api)``."""
        report = self.env.ref(
            'tk_statements.customer_report_template_action', raise_if_not_found=False,
        )
        if report:
            return report, True
        report = self.env.ref(
            'tk_customer_statements.customer_report_template_action', raise_if_not_found=False,
        )
        return report, False

    @api.model
    def _payment_reminder_statement_pdfs(self, company, partner):
        """Generate the up-to-date Customer Statement PDF(s) for a customer.

        Runs the report of the Customer Statement module as of today. Returns a
        list of ``(filename, pdf_bytes)``. Raises ``UserError`` when the statement
        cannot be produced.
        """
        report, current_api = self._payment_reminder_statement_report()
        if not report or 'customer.statement.wizard' not in self.env:
            raise UserError(_(
                'The Customer Statement module (tk_statements) is not installed.'
            ))
        today = fields.Date.context_today(self)
        moves = self.env['account.move'].sudo().with_company(company)
        report = report.sudo().with_company(company)
        Wizard = self.env['customer.statement.wizard'].sudo().with_company(company)

        if current_api:
            # tk_statements keeps a running balance and takes "opening balance" from the
            # current residuals, so the period must start at the customer's first posted
            # invoice or credit note for the balance to be consistent. One statement for
            # the whole company (it already includes all the customer's contacts).
            first = moves.search([
                ('company_id', '=', company.id),
                ('commercial_partner_id', '=', partner.id),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '=', 'posted'),
                ('invoice_date', '!=', False),
            ], order='invoice_date asc, id asc', limit=1)
            if not first:
                raise UserError(_('No posted invoice was found to build the statement from.'))
            wizard = Wizard.create({
                'start_date': first.invoice_date,
                'end_date': today,
                'partner_id': partner.id,
            })
            pdf_content, _report_format = report._render_qweb_pdf(
                report.report_name, wizard.ids, data={'wizard_id': wizard.id},
            )
            label = re.sub(r'[\\/:*?"<>|]+', '-', partner.name or 'Customer')
            return [(f'Statement - {label} - {today}.pdf', pdf_content)]

        # Older tk_customer_statements: invoices of one exact contact between two dates.
        open_invoices = moves.search([
            ('company_id', '=', company.id),
            ('commercial_partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])
        if not open_invoices:
            raise UserError(_('No open invoice was found to build the statement from.'))
        pdfs = []
        for invoice_partner in open_invoices.partner_id:
            invoices = open_invoices.filtered(lambda move: move.partner_id == invoice_partner)
            start_dates = [date for date in invoices.mapped('invoice_date') if date]
            wizard = Wizard.create({
                'start_date': min(start_dates) if start_dates else today,
                'end_date': today,
                'partner_id': invoice_partner.id,
            })
            pdf_content, _report_format = report._render_qweb_pdf(
                report.report_name, wizard.ids, data={'form_data': wizard.read()[0]},
            )
            label = re.sub(r'[\\/:*?"<>|]+', '-', invoice_partner.name or partner.name or 'Customer')
            pdfs.append((f'Statement - {label} - {today}.pdf', pdf_content))
        return pdfs

    @api.model
    def _payment_reminder_log(self, company, partner, outstanding_amount, status, run_token,
                              recipient_email=False, reason=False, is_dry_run=False,
                              mail_mail=False):
        return self.env['customer.payment.reminder.log'].sudo().create({
            'reminder_datetime': fields.Datetime.now(),
            'commercial_partner_id': partner.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'outstanding_amount': company.currency_id.round(outstanding_amount),
            'recipient_email': recipient_email,
            'status': status,
            'reason': reason,
            'run_token': run_token,
            'is_dry_run': is_dry_run,
            'mail_mail_id': mail_mail.id if mail_mail else False,
        })

    @api.model
    def _payment_reminder_send(self, company, partner, outstanding_amount, recipient_email):
        template = self._payment_reminder_template(company)
        if not template:
            return False, _('Payment reminder template is not configured.'), False

        email_from = self._payment_reminder_email_from(company)
        if not email_from:
            return False, _('No sender email is configured for the company or current user.'), False

        email_values = {
            'email_to': recipient_email,
            'email_from': email_from,
            'auto_delete': False,
        }
        statement_pdfs = []
        if self._payment_reminder_statements_enabled():
            try:
                statement_pdfs = self._payment_reminder_statement_pdfs(company, partner)
            except Exception as exc:
                return False, _(
                    'The updated statement could not be generated, so the reminder was not sent: %(error)s',
                    error=str(exc),
                ), False

        ctx = dict(
            self.env.context,
            payment_reminder_statement_attached=bool(statement_pdfs),
            payment_reminder_email_from=email_from,
            payment_reminder_email_to=recipient_email,
            payment_reminder_customer_name=partner.name,
            payment_reminder_company_name=company.name,
            payment_reminder_amount=company.currency_id.round(outstanding_amount),
            payment_reminder_amount_display=self._payment_reminder_format_amount(
                company,
                outstanding_amount,
            ),
        )

        # Only the subject and body are rendered from the template. Sender and
        # recipient come from Python (above), so a stale or customised value in the
        # template's email_from / email_to / reply_to fields can never break sending
        # (mail.template.send_mail would render every one of those fields).
        try:
            rendering_template = template.sudo().with_company(company).with_context(ctx)
            subject = rendering_template._render_field(
                'subject', [partner.id], compute_lang=True,
            )[partner.id]
            body_html = rendering_template._render_field(
                'body_html', [partner.id], compute_lang=True,
            )[partner.id]
            mail_mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body_html,
                'body': body_html,
                'model': 'res.partner',
                'res_id': partner.id,
                'mail_server_id': template.mail_server_id.id or False,
                **email_values,
            })
            if statement_pdfs:
                attachments = self.env['ir.attachment'].sudo().create([{
                    'name': filename,
                    'type': 'binary',
                    'raw': pdf_content,
                    'mimetype': 'application/pdf',
                    'res_model': 'mail.message',
                    'res_id': mail_mail.mail_message_id.id,
                } for filename, pdf_content in statement_pdfs])
                mail_mail.write({'attachment_ids': [(6, 0, attachments.ids)]})
            mail_mail.send(raise_exception=False)
        except Exception as exc:
            return False, str(exc), False

        mail_id = mail_mail.id
        mail_state = getattr(mail_mail, 'state', False) if mail_mail else False
        if mail_state == 'sent':
            return True, False, mail_mail

        failure_reason = False
        if mail_mail:
            failure_reason = getattr(mail_mail, 'failure_reason', False) or _(
                'Mail was not sent successfully. Final state: %(state)s.',
                state=mail_state or 'unknown',
            )
        else:
            failure_reason = _('Mail record was not created.')
        return False, failure_reason, mail_mail

    @api.model
    def _payment_reminder_process_partner(self, company, partner, outstanding_amount, run_token,
                                          dry_run=False):
        outstanding_amount = company.currency_id.round(outstanding_amount)
        skip_reason, recipient_email = self._payment_reminder_skip_reason(
            company,
            partner,
            outstanding_amount,
        )
        if skip_reason:
            _logger.info(
                'Payment reminder skipped: customer=%s company=%s amount=%s reason=%s',
                partner.display_name,
                company.name,
                outstanding_amount,
                skip_reason,
            )
            self._payment_reminder_log(
                company=company,
                partner=partner,
                outstanding_amount=outstanding_amount,
                status='skipped',
                run_token=run_token,
                recipient_email=recipient_email,
                reason=skip_reason,
                is_dry_run=dry_run,
            )
            return 'skipped', False

        if dry_run:
            reason = _('Dry run mode: eligible reminder was evaluated but not sent.')
            _logger.info(
                'Payment reminder dry run: customer=%s company=%s amount=%s recipient=%s',
                partner.display_name,
                company.name,
                outstanding_amount,
                recipient_email,
            )
            self._payment_reminder_log(
                company=company,
                partner=partner,
                outstanding_amount=outstanding_amount,
                status='skipped',
                run_token=run_token,
                recipient_email=recipient_email,
                reason=reason,
                is_dry_run=True,
            )
            return 'eligible_dry_run', True

        sent, failure_reason, mail_mail = self._payment_reminder_send(
            company,
            partner,
            outstanding_amount,
            recipient_email,
        )
        if sent:
            _logger.info(
                'Payment reminder sent: customer=%s company=%s amount=%s recipient=%s',
                partner.display_name,
                company.name,
                outstanding_amount,
                recipient_email,
            )
            self._payment_reminder_log(
                company=company,
                partner=partner,
                outstanding_amount=outstanding_amount,
                status='sent',
                run_token=run_token,
                recipient_email=recipient_email,
                mail_mail=mail_mail,
            )
            return 'sent', True

        _logger.warning(
            'Payment reminder failed: customer=%s company=%s amount=%s recipient=%s reason=%s',
            partner.display_name,
            company.name,
            outstanding_amount,
            recipient_email,
            failure_reason,
        )
        self._payment_reminder_log(
            company=company,
            partner=partner,
            outstanding_amount=outstanding_amount,
            status='failed',
            run_token=run_token,
            recipient_email=recipient_email,
            reason=failure_reason,
            mail_mail=mail_mail,
        )
        return 'failed', True

    @api.model
    def _payment_reminder_run_company(self, company, dry_run=False, commercial_partner=None,
                                      run_token=None, commit=False):
        run_token = run_token or str(uuid.uuid4())
        balances = self._payment_reminder_collect_balances(
            company,
            commercial_partner=commercial_partner,
        )
        rounding = self._payment_reminder_amount_rounding(company)
        stats = {
            'company_id': company.id,
            'company_name': company.name,
            'dry_run': bool(dry_run),
            'evaluated': 0,
            'eligible': 0,
            'sent': 0,
            'skipped': 0,
            'failed': 0,
            'lock_lost': False,
        }

        processed_partner_ids = set()
        for partner, outstanding_amount in balances:
            if partner.id in processed_partner_ids:
                continue
            processed_partner_ids.add(partner.id)

            # Batch runs only deal with customers who actually owe at least the
            # threshold: zero/negative (credit) balances and balances below the
            # threshold are left out entirely instead of being logged as skipped.
            # Targeted runs (a given customer) still log the reason.
            if not commercial_partner:
                rounded_outstanding = company.currency_id.round(outstanding_amount)
                if (
                    float_compare(rounded_outstanding, 0.0, precision_rounding=rounding) <= 0
                    or float_compare(
                        rounded_outstanding,
                        company.payment_reminder_min_outstanding,
                        precision_rounding=rounding,
                    ) < 0
                ):
                    continue

            stats['evaluated'] += 1

            try:
                # Savepoint: a DB-level error for one customer must not poison the
                # transaction (and the log writes) for all remaining customers.
                with self.env.cr.savepoint():
                    result, was_eligible = self._payment_reminder_process_partner(
                        company=company,
                        partner=partner,
                        outstanding_amount=outstanding_amount,
                        run_token=run_token,
                        dry_run=dry_run,
                    )
            except Exception as exc:
                stats['failed'] += 1
                _logger.exception(
                    'Payment reminder processing crashed: customer=%s company=%s amount=%s',
                    partner.display_name,
                    company.name,
                    outstanding_amount,
                )
                self._payment_reminder_log(
                    company=company,
                    partner=partner,
                    outstanding_amount=outstanding_amount,
                    status='failed',
                    run_token=run_token,
                    recipient_email=self._payment_reminder_safe_recipient_label(company, partner),
                    reason=str(exc),
                    is_dry_run=dry_run,
                )
                # Commit per customer so a later crash cannot roll back the logs of
                # mails that were already sent (which would cause duplicate mails).
                if commit and not dry_run and not self._payment_reminder_commit_and_relock():
                    stats['lock_lost'] = True
                    break
                continue

            if was_eligible:
                stats['eligible'] += 1

            if result == 'sent':
                stats['sent'] += 1
            elif result == 'failed':
                stats['failed'] += 1
            else:
                stats['skipped'] += 1

            if commit and not dry_run and not self._payment_reminder_commit_and_relock():
                stats['lock_lost'] = True
                break

        _logger.info(
            'Payment reminder company summary: company=%s evaluated=%s eligible=%s sent=%s skipped=%s failed=%s dry_run=%s',
            company.name,
            stats['evaluated'],
            stats['eligible'],
            stats['sent'],
            stats['skipped'],
            stats['failed'],
            dry_run,
        )
        return stats

    @api.model
    def cron_process_payment_reminders(self):
        service = self.sudo()
        if not service._payment_reminder_try_lock():
            _logger.warning('Payment reminder cron skipped because another execution already holds the advisory lock.')
            return {
                'evaluated': 0,
                'eligible': 0,
                'sent': 0,
                'skipped': 0,
                'failed': 0,
                'locked': True,
            }

        companies = self.env['res.company'].sudo().search([
            ('payment_reminder_enabled', '=', True),
        ])
        totals = {
            'evaluated': 0,
            'eligible': 0,
            'sent': 0,
            'skipped': 0,
            'failed': 0,
            'locked': False,
        }
        for company in companies:
            company_stats = service._payment_reminder_run_company(
                company=company,
                dry_run=company.payment_reminder_dry_run,
                run_token=f'cron:{company.id}:{uuid.uuid4()}',
                commit=True,
            )
            for key in ('evaluated', 'eligible', 'sent', 'skipped', 'failed'):
                totals[key] += company_stats[key]
            if company_stats['lock_lost']:
                totals['locked'] = True
                break

        _logger.info(
            'Payment reminder cron summary: evaluated=%s eligible=%s sent=%s skipped=%s failed=%s companies=%s',
            totals['evaluated'],
            totals['eligible'],
            totals['sent'],
            totals['skipped'],
            totals['failed'],
            len(companies),
        )
        return totals

    @api.model
    def run_manual_payment_reminder(self, partner_id, company_id=None, dry_run=True):
        partner = self.env['res.partner'].browse(partner_id).commercial_partner_id
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        return self.sudo()._payment_reminder_run_company(
            company=company,
            dry_run=dry_run,
            commercial_partner=partner,
            run_token=f'manual:{company.id}:{partner.id}:{uuid.uuid4()}',
        )

    @api.model
    def run_manual_payment_reminders(self, company_id, dry_run=True, partner_ids=None):
        """Manual trigger used by the "Send Payment Reminders" wizard.

        :param partner_ids: optional customers to restrict the run to; when empty,
            every customer of the company with an open receivable is evaluated.
        """
        service = self.sudo()
        company = self.env['res.company'].browse(company_id)
        run_token = f'manual:{company.id}:{uuid.uuid4()}'
        if not dry_run and not service._payment_reminder_try_lock():
            return {
                'evaluated': 0, 'eligible': 0, 'sent': 0, 'skipped': 0, 'failed': 0,
                'locked': True, 'run_token': run_token,
            }
        partners = self.env['res.partner'].browse(partner_ids or []).commercial_partner_id
        stats = service._payment_reminder_run_company(
            company=company,
            dry_run=dry_run,
            commercial_partner=partners or None,
            run_token=run_token,
            commit=True,
        )
        stats['locked'] = bool(stats.get('lock_lost'))
        stats['run_token'] = run_token
        return stats
