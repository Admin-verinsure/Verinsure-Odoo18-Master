# -*- coding: utf-8 -*-
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountAnalyticLineCron(models.Model):
    """Scheduled-action entry points for Timesheet Billing. Kept on the
    analytic line model (rather than a standalone transient) so the
    business logic that touches timesheets lives next to the model it
    operates on; the actual invoice creation is delegated to the wizard
    to avoid duplicating the grouping/validation logic.
    """
    _inherit = 'account.analytic.line'

    @api.model
    def _tb_eligible_projects(self):
        return self.env['project.project'].search([
            ('billing_type', 'in', ('hourly', 'time_material')),
            ('sale_order_id', '!=', False),
            ('service_product_id', '!=', False),
        ])

    @api.model
    def _tb_cron_generate_invoices(self, post=False):
        """Shared implementation for the weekly/monthly invoicing crons.
        One invoice per (project, customer) that has approved, billable,
        uninvoiced hours - never blocks the whole run if a single project
        fails validation (e.g. missing rate); that project is logged and
        skipped so the rest of the run still completes.
        """
        Wizard = self.env['timesheet.billing.invoice.wizard']
        generated = 0
        for project in self._tb_eligible_projects():
            domain = self._tb_invoiceable_domain(project=project)
            if not self.search_count(domain):
                continue
            wizard = Wizard.create({
                'partner_id': project.customer_id.id,
                'project_id': project.id,
                'sale_order_id': project.sale_order_id.id,
                'grouping': 'task',
                'action_after': 'post' if post else 'draft',
            })
            try:
                wizard.with_context(tb_from_cron=True).action_generate_invoice()
                generated += 1
            except UserError as exc:
                _logger.warning(
                    'Timesheet Billing cron: skipped project %s (%s): %s',
                    project.name, project.id, exc,
                )
        _logger.info('Timesheet Billing cron: generated %d invoice(s).', generated)
        return generated

    @api.model
    def _cron_generate_weekly_invoices(self):
        self._tb_cron_generate_invoices(post=False)

    @api.model
    def _cron_generate_monthly_invoices(self):
        self._tb_cron_generate_invoices(post=False)

    @api.model
    def _cron_remind_unapproved_timesheets(self):
        """Notify each Timesheet/Billing manager of billable timesheets
        still waiting for approval, via chatter activity on the project
        (keeps the reminder inside Odoo's own notification system rather
        than assuming outbound email is configured).
        """
        lines = self.search([
            ('billable', '=', True),
            ('approved', '=', False),
            ('billing_status', '!=', 'invoiced'),
        ])
        if not lines:
            return
        template = self.env.ref(
            'timesheet_billing.mail_template_unapproved_timesheets', raise_if_not_found=False)
        for project in lines.project_id:
            project_lines = lines.filtered(lambda l: l.project_id == project)
            if template:
                template.with_context(
                    tb_line_count=len(project_lines),
                    tb_total_hours=sum(project_lines.mapped('unit_amount')),
                ).send_mail(project.id, force_send=False)
            else:
                project.message_post(body=_(
                    '%(count)d billable timesheet line(s) totalling %(hours).2f hours are '
                    'still awaiting approval.',
                    count=len(project_lines), hours=sum(project_lines.mapped('unit_amount')),
                ))

    @api.model
    def _cron_remind_uninvoiced_hours(self):
        """Notify projects that have approved billable hours sitting
        uninvoiced past the point they'd normally be billed.
        """
        lines = self.search(self._tb_invoiceable_domain())
        if not lines:
            return
        template = self.env.ref(
            'timesheet_billing.mail_template_uninvoiced_hours', raise_if_not_found=False)
        for project in lines.project_id:
            project_lines = lines.filtered(lambda l: l.project_id == project)
            hours = sum(project_lines.mapped('unit_amount'))
            amount = sum(project_lines.mapped('bill_amount'))
            if template:
                template.with_context(
                    tb_hours=hours, tb_amount=amount,
                ).send_mail(project.id, force_send=False)
            else:
                project.message_post(body=_(
                    '%(hours).2f approved billable hours (%(amount).2f) are ready to invoice '
                    'but have not been billed yet.', hours=hours, amount=amount,
                ))
