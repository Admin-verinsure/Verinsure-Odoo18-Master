# -*- coding: utf-8 -*-
import datetime
from odoo.tests.common import TransactionCase, tagged


@tagged('customer_statement_report')
class TestCustomerStatementData(TransactionCase):
    """
    Tests for _get_statement_data():
    - Opening balance calculated from pre-period invoices
    - Period invoices and credit notes form correct ledger lines
    - Running balance and net balance are accurate
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'street': '123 Main St',
            'city': 'Test City',
            'zip': '12345',
        })
        journal = cls.env['account.journal'].search(
            [('type', '=', 'sale')], limit=1
        )
        product = cls.env['product.product'].create({
            'name': 'Test Product', 'list_price': 500.0,
        })

        def make_invoice(move_type, invoice_date, price):
            inv = cls.env['account.move'].create({
                'move_type': move_type,
                'partner_id': cls.partner.id,
                'journal_id': journal.id,
                'invoice_date': invoice_date,
                'invoice_line_ids': [(0, 0, {
                    'product_id': product.id,
                    'quantity': 1,
                    'price_unit': price,
                    'tax_ids': [(6, 0, [])],
                })],
            })
            inv.action_post()
            return inv

        # Pre-period invoice (should be in opening balance)
        cls.pre_invoice = make_invoice('out_invoice', '2025-02-15', 300.0)
        # Period invoices
        cls.inv1 = make_invoice('out_invoice', '2025-03-10', 500.0)
        cls.inv2 = make_invoice('out_invoice', '2025-03-20', 200.0)
        # Period credit note
        cls.cn1 = make_invoice('out_refund',  '2025-03-25', 100.0)

        cls.wizard = cls.env['customer.statement.wizard'].create({
            'start_date': datetime.date(2025, 3, 1),
            'end_date':   datetime.date(2025, 3, 31),
            'partner_id': cls.partner.id,
            'include_zero_balance': True,
        })

    def test_opening_balance(self):
        """Pre-period invoice residual must be in opening balance."""
        data = self.wizard._get_statement_data()
        self.assertAlmostEqual(
            data['opening_balance'],
            self.pre_invoice.amount_residual,
            places=2,
        )

    def test_line_count(self):
        """3 period documents (2 invoices + 1 credit note) should appear."""
        data = self.wizard._get_statement_data()
        self.assertEqual(len(data['lines']), 3)

    def test_invoice_debit_credit_note_credit(self):
        """Invoices must have debit; credit notes must have credit."""
        data = self.wizard._get_statement_data()
        for line in data['lines']:
            if line['move_type'] == 'out_invoice':
                self.assertIsNotNone(line['debit'])
            else:
                self.assertIsNotNone(line['credit'])

    def test_running_balance_progression(self):
        """Running balance on last line must equal net_balance."""
        data = self.wizard._get_statement_data()
        self.assertAlmostEqual(
            data['lines'][-1]['running_balance'],
            data['net_balance'],
            places=2,
        )

    def test_net_balance_arithmetic(self):
        """net_balance = opening + inv1 + inv2 - cn1 (residuals)."""
        data = self.wizard._get_statement_data()
        expected = (
            self.pre_invoice.amount_residual
            + self.inv1.amount_residual
            + self.inv2.amount_residual
            - self.cn1.amount_residual
        )
        self.assertAlmostEqual(data['net_balance'], round(expected, 2), places=2)
