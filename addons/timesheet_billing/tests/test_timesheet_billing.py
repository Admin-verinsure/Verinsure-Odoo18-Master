# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTimesheetBilling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'ACME Timesheet Billing Co'})
        cls.product = cls.env['product.product'].create({
            'name': 'Consulting',
            'type': 'service',
            'list_price': 100.0,
            'timesheet_hourly_rate': 100.0,
        })
        cls.sale_order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 10,
                'price_unit': 100.0,
            })],
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Test Billing Project',
            'partner_id': cls.partner.id,
            'sale_order_id': cls.sale_order.id,
            'service_product_id': cls.product.id,
            'billing_type': 'hourly',
            'allow_timesheets': True,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Test Task',
            'project_id': cls.project.id,
            'billable': True,
        })
        cls.employee = cls.env['hr.employee'].create({'name': 'Test Employee'})

        # groups
        cls.billing_group = cls.env.ref('timesheet_billing.group_billing_manager')
        cls.timesheet_user_group = cls.env.ref('timesheet_billing.group_timesheet_user')
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Billing Manager',
            'login': 'tb_billing_manager',
            'email': 'tb_billing_manager@example.com',
            'groups_id': [(6, 0, [cls.billing_group.id])],
        })
        cls.basic_user = cls.env['res.users'].create({
            'name': 'Plain User',
            'login': 'tb_plain_user',
            'email': 'tb_plain_user@example.com',
            'groups_id': [(6, 0, [cls.timesheet_user_group.id])],
        })

    def _make_timesheet(self, hours=5.0, approved=True, task=None):
        return self.env['account.analytic.line'].create({
            'name': 'Work done',
            'project_id': self.project.id,
            'task_id': (task or self.task).id,
            'employee_id': self.employee.id,
            'unit_amount': hours,
            'approved': approved,
        })

    # ------------------------------------------------------------------
    # Rate calculation
    # ------------------------------------------------------------------
    def test_rate_resolution_cascade(self):
        # No task/project/timesheet-level rate -> falls back to product rate
        line = self._make_timesheet(hours=2.0)
        self.assertEqual(line.hourly_rate, 100.0)
        self.assertEqual(line.bill_amount, 200.0)

        # Project-level rate overrides product rate
        self.project.hourly_rate = 150.0
        line2 = self._make_timesheet(hours=2.0)
        self.assertEqual(line2.hourly_rate, 150.0)

        # Task-level rate overrides project rate
        self.task.hourly_rate = 175.0
        line3 = self._make_timesheet(hours=2.0)
        self.assertEqual(line3.hourly_rate, 175.0)

        # Explicit timesheet-level rate has highest priority
        line4 = self.env['account.analytic.line'].create({
            'name': 'Explicit rate',
            'project_id': self.project.id,
            'task_id': self.task.id,
            'employee_id': self.employee.id,
            'unit_amount': 1.0,
            'hourly_rate': 999.0,
            'approved': True,
        })
        self.assertEqual(line4.hourly_rate, 999.0)

    # ------------------------------------------------------------------
    # Negative / zero hour validation
    # ------------------------------------------------------------------
    def test_negative_hours_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_timesheet(hours=-1.0)

    # ------------------------------------------------------------------
    # Approval workflow
    # ------------------------------------------------------------------
    def test_approval_workflow(self):
        line = self._make_timesheet(hours=3.0, approved=False)
        self.assertFalse(line.approved)
        line.with_user(self.manager_user).action_approve_timesheets()
        self.assertTrue(line.approved)
        self.assertEqual(line.approved_by, self.manager_user)
        self.assertTrue(line.approved_date)

    def test_approval_requires_manager_group(self):
        line = self._make_timesheet(hours=3.0, approved=False)
        with self.assertRaises(UserError):
            line.with_user(self.basic_user).action_approve_timesheets()

    # ------------------------------------------------------------------
    # Invoice creation & grouping
    # ------------------------------------------------------------------
    def test_invoice_creation_single_line(self):
        self._make_timesheet(hours=4.0)
        self._make_timesheet(hours=6.0)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id,
            'project_id': self.project.id,
            'grouping': 'single',
            'action_after': 'draft',
        })
        action = wizard.action_generate_invoice()
        invoice = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(len(invoice.invoice_line_ids), 1)
        self.assertEqual(invoice.invoice_line_ids.quantity, 10.0)
        self.assertEqual(invoice.timesheet_billing_project_id, self.project)

    def test_invoice_creation_grouped_per_task(self):
        task2 = self.env['project.task'].create({
            'name': 'Second Task', 'project_id': self.project.id, 'billable': True,
        })
        self._make_timesheet(hours=4.0, task=self.task)
        self._make_timesheet(hours=6.0, task=task2)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id,
            'project_id': self.project.id,
            'grouping': 'task',
            'action_after': 'draft',
        })
        action = wizard.action_generate_invoice()
        invoice = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(len(invoice.invoice_line_ids), 2)

    def test_duplicate_invoicing_prevented(self):
        line = self._make_timesheet(hours=4.0)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        wizard.action_generate_invoice()
        self.assertEqual(line.billing_status, 'invoiced')

        # Second run should find nothing left to invoice
        wizard2 = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        with self.assertRaises(UserError):
            wizard2.action_generate_invoice()

    def test_invoiced_line_is_locked(self):
        line = self._make_timesheet(hours=4.0)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        wizard.action_generate_invoice()
        with self.assertRaises(UserError):
            line.write({'unit_amount': 99.0})

    def test_unapproved_lines_excluded(self):
        self._make_timesheet(hours=4.0, approved=False)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        with self.assertRaises(UserError):
            wizard.action_generate_invoice()

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    def test_only_billing_manager_can_generate_invoice(self):
        self._make_timesheet(hours=4.0)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.basic_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        with self.assertRaises(UserError):
            wizard.action_generate_invoice()

    def test_service_product_required(self):
        self.project.service_product_id = False
        self._make_timesheet(hours=4.0)
        wizard = self.env['timesheet.billing.invoice.wizard'].with_user(self.manager_user).create({
            'partner_id': self.partner.id, 'project_id': self.project.id, 'grouping': 'single',
        })
        with self.assertRaises(UserError):
            wizard.action_generate_invoice()
