# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    billable = fields.Boolean(
        string='Billable Task',
        default=True,
        tracking=True,
        help='When enabled, timesheet lines logged against this task '
             'default to billable and are picked up by the Timesheet '
             'Billing invoice wizard.',
    )
    hourly_rate = fields.Monetary(
        string='Task Hourly Rate',
        currency_field='currency_id',
        help='Overrides the project hourly rate for timesheets logged on '
             'this task. Leave empty to fall back to the project rate.',
    )
    currency_id = fields.Many2one(
        related='project_id.currency_id',
        string='Currency',
        store=True,
        readonly=True,
    )
    estimated_hours = fields.Float(
        string='Estimated Hours',
        digits=(16, 2),
        help='Manually entered estimate for this task, independent of the '
             'built-in Planned Hours field, kept for billing comparisons.',
    )
    actual_hours = fields.Float(
        string='Actual Hours (Billable)',
        compute='_compute_actual_hours',
        store=True,
        digits=(16, 2),
        help='Sum of hours logged on billable timesheet lines for this task.',
    )
    remaining_hours = fields.Float(
        string='Remaining Hours',
        compute='_compute_actual_hours',
        store=True,
        digits=(16, 2),
        help='Estimated Hours minus Actual (Billable) Hours. Can go '
             'negative if the task ran over estimate.',
    )

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.billable', 'estimated_hours')
    def _compute_actual_hours(self):
        AnalyticLine = self.env['account.analytic.line']
        groups = AnalyticLine._read_group(
            domain=[('task_id', 'in', self.ids), ('billable', '=', True)],
            groupby=['task_id'],
            aggregates=['unit_amount:sum'],
        )
        actual_map = {task.id: total for task, total in groups}
        for task in self:
            actual = actual_map.get(task.id, 0.0)
            task.actual_hours = actual
            task.remaining_hours = task.estimated_hours - actual

    def _tb_resolve_hourly_rate(self):
        """Rate resolution cascade, task level: Task rate -> Project rate ->
        Product list price -> Company default rate. The Timesheet-level
        override (highest priority) is applied in account.analytic.line.
        """
        self.ensure_one()
        if self.hourly_rate:
            return self.hourly_rate
        return self.project_id._tb_resolve_hourly_rate() if self.project_id else 0.0
