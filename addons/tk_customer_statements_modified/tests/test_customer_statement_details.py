# -*- coding: utf-8 -*-
import datetime
from odoo.tests.common import TransactionCase, tagged


@tagged('customer_statement_report')
class TestInvoiceAbstractReport(TransactionCase):
    """
    Test case for the InvoiceAbstractReport to validate customer invoice report functionality,
    including partner selection, invoice filtering, and computed totals.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the test environment, including creating required records like partners, invoices,
        and companies that will be used to test the report's data.
        """
        super().setUpClass()

        cls.company = cls.env['res.company'].create({
            'name': 'Test Company',
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'street': '123 Main St',
            'city': 'Test City',
            'zip': '12345',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 500,
        })
        cls.country = cls.env['res.country'].create({
            'name': 'Test Country',
            'code': 'TestCode1',
        })
        cls.state = cls.env['res.country.state'].create({
            'name': 'Test State',
            'code': 'TestCode2',
            'country_id': cls.country.id,
        })
        cls.invoice1 = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner.id,
            'journal_id': cls.env['account.journal'].search([('type', '=', 'sale')], limit=1).id,
            'invoice_line_ids': [(0, 0, {
                'product_id': cls.product.id,
                'quantity': 1,
                'price_unit': 575.00,
                'tax_ids': [(6, 0, [])],
            })],
        })
        cls.invoice2 = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner.id,
            'journal_id': cls.env['account.journal'].search([('type', '=', 'sale')], limit=1).id,
            'invoice_line_ids': [(0, 0, {
                'product_id': cls.product.id,
                'quantity': 1,
                'price_unit': 575.00,
                'tax_ids': [(6, 0, [])],
            })],
        })
        cls.report_model = cls.env['report.tk_customer_statements.customer_report_template']

    def test_get_report_values(self):
        """
        Test the `_get_report_values` method to validate correct invoice data is retrieved,
        and totals are accurately calculated.
        """
        self.invoice1.write({'invoice_date': '2025-03-10'})
        self.invoice2.write({'invoice_date': '2025-03-15'})
        data = {
            'form_data': {
                'start_date': '2025-03-01',
                'end_date': '2025-03-31',
                'partner_id': [self.partner.id],
            }
        }
        report_values = self.report_model._get_report_values(docids=None, data=data)
        invoices = report_values['docs']
        self.assertGreater(len(invoices), 0, "No invoices found for the given partner!")

        self.assertEqual(report_values['partner_name'], self.partner.name)
        self.assertEqual(report_values['partner_street'], self.partner.street)
        self.assertEqual(report_values['partner_city'], self.partner.city)
        self.assertEqual(report_values['partner_zip'], self.partner.zip)
        self.assertEqual(len(invoices), 2)
        self.assertEqual(invoices[0]['amount'], 575.00)
        self.assertEqual(invoices[0]['balance_due'], 575.00)
        self.assertEqual(invoices[1]['amount'], 575.00)
        self.assertEqual(invoices[1]['balance_due'], 575.00)
        self.assertEqual(report_values['total_amount'], 1150.00)
        self.assertEqual(report_values['total_balance'], 1150.00)
        self.assertEqual(report_values['today_date'], datetime.date.today())
