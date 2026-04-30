# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('test_customer_statement_wizard')
class TestCustomerStatementWizard(TransactionCase):
    """
    Tests for the CustomerStatementWizard:
    - PDF action returns correct report action type
    - Excel action returns act_url pointing to controller
    - Date validation raises UserError on invalid range
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Test Customer'})
        # Create a minimal posted invoice
        journal = cls.env['account.journal'].search(
            [('type', '=', 'sale')], limit=1
        )
        product = cls.env['product.product'].create({
            'name': 'Test Product', 'list_price': 100.0,
        })
        inv = cls.env['account.move'].create({
            'partner_id': cls.partner.id,
            'move_type': 'out_invoice',
            'invoice_date': date.today(),
            'journal_id': journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'quantity': 1,
                'price_unit': 100.0,
                'tax_ids': [(6, 0, [])],
            })],
        })
        inv.action_post()
        cls.invoice = inv

        cls.wizard = cls.env['customer.statement.wizard'].create({
            'start_date': date.today(),
            'end_date': date.today(),
            'partner_id': cls.partner.id,
        })

    def test_pdf_action_type(self):
        """PDF method must trigger ir.actions.report."""
        action = self.wizard.customer_statements_pdf_report()
        self.assertEqual(action.get('type'), 'ir.actions.report')

    def test_excel_action_type(self):
        """Excel method must return ir.actions.act_url."""
        action = self.wizard.customer_statements_excel_report()
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        self.assertIn('/customer_statement/excel', action.get('url', ''))

    def test_invalid_date_raises(self):
        """Start date after end date must raise UserError."""
        self.wizard.write({
            'start_date': date.today(),
            'end_date': date.today().replace(year=date.today().year - 1),
        })
        with self.assertRaises(UserError):
            self.wizard.customer_statements_pdf_report()

    def test_statement_data_structure(self):
        """_get_statement_data must return required keys."""
        self.wizard.write({
            'start_date': date.today(),
            'end_date': date.today(),
        })
        data = self.wizard._get_statement_data()
        for key in ('company', 'partner', 'start_date', 'end_date',
                    'opening_balance', 'lines', 'net_balance'):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_invoice_appears_in_lines(self):
        """A posted invoice in the date range must appear as a ledger line."""
        self.wizard.write({
            'start_date': date.today(),
            'end_date': date.today(),
            'include_zero_balance': True,
        })
        data = self.wizard._get_statement_data()
        names = [l['name'] for l in data['lines']]
        self.assertIn(self.invoice.name, names)
