# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError
from datetime import date


@tagged('test_customer_statement_wizard')
class TestCustomerStatementWizard(TransactionCase):
    """
    Test case for the Customer Statement Wizard functionality.
    This test case ensures that the wizard correctly generates PDF and Excel reports,
    handles date constraints appropriately, and validates expected actions.
    """

    def setUp(self):
        """
        Set up the test environment by creating a test customer, an invoice,
        and initializing the Customer Statement Wizard.
        """
        super(TestCustomerStatementWizard, self).setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test Customer'})
        self.invoice = self.env['account.move'].create({
            'partner_id': self.partner.id,
            'move_type': 'out_invoice',
            'invoice_date': date.today(),
            'amount_total': 100.0,
        })

        self.wizard = self.env['customer.statement.wizard'].create({
            'start_date': date.today(),
            'end_date': date.today(),
            'partner_id': self.partner.id,
        })

    def test_generate_pdf(self):
        """
        Validate that the PDF report action is correctly triggered.
        Ensures that the wizard returns the expected action type and report name.
        """
        action = self.wizard.btn_pdf_action()
        self.assertEqual(action['type'], 'ir.actions.report', "PDF report action is not triggered correctly!")
        self.assertEqual(action['report_name'], 'tk_customer_statements.customer_report_template',
                         "Incorrect report template!")

    def test_generate_pdf_invalid_date(self):
        """
        Validate that a UserError is raised when the start date is later than the end date.
        This ensures that invalid date ranges are properly handled.
        """
        self.wizard.start_date = date.today()
        self.wizard.end_date = date.today().replace(year=date.today().year - 1)
        with self.assertRaises(UserError, msg="Start date cannot be after the end date."):
            self.wizard.btn_pdf_action()

    def test_generate_excel(self):
        """
        Validate that the Excel report action is correctly triggered.
        Ensures that the wizard returns the correct action type and generates a valid URL
        for downloading the Excel report.
        """
        action = self.wizard.btn_excel_action()
        self.assertEqual(action['type'], 'ir.actions.act_url', "Excel report action is not triggered correctly!")
        self.assertIn('/web/content/', action['url'], "Generated Excel report URL is incorrect!")
