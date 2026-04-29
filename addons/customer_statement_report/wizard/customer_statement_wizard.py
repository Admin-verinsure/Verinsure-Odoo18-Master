# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import io
import base64


class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'
    _description = 'Customer Statement Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        readonly=True,
    )
    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.today,
    )
    report_type = fields.Selection(
        selection=[
            ('pdf', 'PDF'),
            ('xlsx', 'Excel (XLSX)'),
        ],
        string='Report Type',
        required=True,
        default='pdf',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='partner_id.currency_id',
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # CORE ACCOUNTING LOGIC
    # ─────────────────────────────────────────────────────────────────────────

    def _get_all_moves(self):
        """Fetch all posted invoices and credit notes for the partner."""
        return self.env['account.move'].search([
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('company_id', '=', self.env.company.id),
        ])

    def _compute_statement_data(self):
        """
        Compute full statement data:
          - opening_balance : sum of amount_total_signed before date_from
          - lines           : list of dicts for period transactions
          - closing_balance : opening + period sum
        """
        date_from = self.date_from
        date_to = self.date_to

        all_moves = self._get_all_moves()

        # Split moves into opening-period and statement-period
        opening_moves = all_moves.filtered(
            lambda m: m.invoice_date and m.invoice_date < date_from
        )
        period_moves = all_moves.filtered(
            lambda m: m.invoice_date
            and date_from <= m.invoice_date <= date_to
        )

        # Opening balance: algebraic sum using amount_total_signed
        # amount_total_signed is already signed:
        #   out_invoice → positive
        #   out_refund  → negative
        opening_balance = sum(opening_moves.mapped('amount_total_signed'))

        # Sort period moves chronologically
        period_moves_sorted = period_moves.sorted(
            key=lambda m: (m.invoice_date, m.id)
        )

        # Build lines with running balance
        lines = []
        running_balance = opening_balance

        for move in period_moves_sorted:
            signed_amount = move.amount_total_signed  # +/- already applied
            running_balance += signed_amount

            # Debit column: invoice amount (positive transactions)
            debit = move.amount_total if move.move_type == 'out_invoice' else 0.0
            # Credit column: credit note amount (absolute value)
            credit = move.amount_total if move.move_type == 'out_refund' else 0.0

            lines.append({
                'date': move.invoice_date,
                'name': move.name,
                'ref': move.ref or '',
                'move_type': move.move_type,
                'type_label': _('Invoice') if move.move_type == 'out_invoice' else _('Credit Note'),
                'debit': debit,
                'credit': credit,
                'balance': running_balance,
                'is_refund': move.move_type == 'out_refund',
                'currency_symbol': move.currency_id.symbol or '',
            })

        closing_balance = running_balance  # equals opening + sum(period signed)

        return {
            'partner': self.partner_id,
            'date_from': date_from,
            'date_to': date_to,
            'opening_balance': opening_balance,
            'lines': lines,
            'closing_balance': closing_balance,
            'currency': self.partner_id.currency_id or self.env.company.currency_id,
            'company': self.env.company,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # REPORT ACTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def action_generate_report(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('Date From must be earlier than or equal to Date To.'))

        if self.report_type == 'pdf':
            return self._generate_pdf()
        else:
            return self._generate_xlsx()

    def _generate_pdf(self):
        """Return PDF report action."""
        return self.env.ref(
            'customer_statement_report.action_customer_statement_pdf'
        ).report_action(self)

    def _generate_xlsx(self):
        """Generate XLSX and return as downloadable attachment."""
        data = self._compute_statement_data()
        xlsx_data = self._build_xlsx(data)

        attachment = self.env['ir.attachment'].create({
            'name': 'Customer_Statement_%s.xlsx' % self.partner_id.name,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'self',
        }

    # ─────────────────────────────────────────────────────────────────────────
    # XLSX BUILDER
    # ─────────────────────────────────────────────────────────────────────────

    def _build_xlsx(self, data):
        """Build XLSX workbook and return raw bytes."""
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_(
                'xlsxwriter library is not installed. '
                'Please install it: pip install xlsxwriter'
            ))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Customer Statement')

        currency = data['currency']
        currency_symbol = currency.symbol or ''

        # ── Formats ──────────────────────────────────────────────────────────
        fmt_title = workbook.add_format({
            'bold': True, 'font_size': 16,
            'font_color': '#1F4E79', 'align': 'left',
        })
        fmt_subtitle = workbook.add_format({
            'font_size': 10, 'font_color': '#595959',
        })
        fmt_header = workbook.add_format({
            'bold': True, 'font_size': 10,
            'bg_color': '#1F4E79', 'font_color': '#FFFFFF',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        fmt_date = workbook.add_format({
            'num_format': 'DD/MM/YYYY', 'border': 1, 'font_size': 10,
        })
        fmt_text = workbook.add_format({'border': 1, 'font_size': 10})
        fmt_money = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1, 'font_size': 10,
        })
        fmt_money_red = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1,
            'font_color': '#FF0000', 'font_size': 10,
        })
        fmt_balance_pos = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1,
            'font_color': '#1F4E79', 'bold': True, 'font_size': 10,
        })
        fmt_balance_neg = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1,
            'font_color': '#FF0000', 'bold': True, 'font_size': 10,
        })
        fmt_opening = workbook.add_format({
            'bold': True, 'bg_color': '#D9E1F2', 'border': 1,
            'num_format': '#,##0.00', 'font_size': 10,
        })
        fmt_opening_label = workbook.add_format({
            'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'font_size': 10,
        })
        fmt_total = workbook.add_format({
            'bold': True, 'bg_color': '#1F4E79', 'font_color': '#FFFFFF',
            'border': 1, 'num_format': '#,##0.00', 'font_size': 11,
        })
        fmt_total_label = workbook.add_format({
            'bold': True, 'bg_color': '#1F4E79', 'font_color': '#FFFFFF',
            'border': 1, 'font_size': 11,
        })

        # ── Column Widths ─────────────────────────────────────────────────────
        worksheet.set_column('A:A', 14)   # Date
        worksheet.set_column('B:B', 22)   # Document No.
        worksheet.set_column('C:C', 14)   # Type
        worksheet.set_column('D:D', 14)   # Reference
        worksheet.set_column('E:E', 15)   # Debit
        worksheet.set_column('F:F', 15)   # Credit
        worksheet.set_column('G:G', 18)   # Running Balance

        # ── Header Section ────────────────────────────────────────────────────
        worksheet.merge_range('A1:G1',
            'CUSTOMER STATEMENT', fmt_title)
        worksheet.merge_range('A2:G2',
            data['partner'].name, fmt_subtitle)
        worksheet.merge_range('A3:G3',
            'Period: %s to %s' % (
                data['date_from'].strftime('%d/%m/%Y'),
                data['date_to'].strftime('%d/%m/%Y'),
            ), fmt_subtitle)
        worksheet.merge_range('A4:G4',
            'Company: %s' % data['company'].name, fmt_subtitle)
        worksheet.merge_range('A5:G5', '', fmt_subtitle)  # spacer

        # ── Table Headers ─────────────────────────────────────────────────────
        headers = ['Date', 'Document No.', 'Type', 'Reference',
                   'Debit (%s)' % currency_symbol,
                   'Credit (%s)' % currency_symbol,
                   'Balance (%s)' % currency_symbol]
        for col, header in enumerate(headers):
            worksheet.write(5, col, header, fmt_header)
        worksheet.set_row(5, 20)

        # ── Opening Balance Row ───────────────────────────────────────────────
        worksheet.merge_range('A7:D7', 'Opening Balance', fmt_opening_label)
        worksheet.write(6, 4, '', fmt_opening)
        worksheet.write(6, 5, '', fmt_opening)
        worksheet.write(6, 6, data['opening_balance'], fmt_opening)

        # ── Transaction Rows ──────────────────────────────────────────────────
        row = 7
        for line in data['lines']:
            worksheet.write(row, 0, line['date'], fmt_date)
            worksheet.write(row, 1, line['name'], fmt_text)
            worksheet.write(row, 2, line['type_label'], fmt_text)
            worksheet.write(row, 3, line['ref'], fmt_text)

            if line['is_refund']:
                worksheet.write(row, 4, 0.0, fmt_money)
                worksheet.write(row, 5, line['credit'], fmt_money_red)
            else:
                worksheet.write(row, 4, line['debit'], fmt_money)
                worksheet.write(row, 5, 0.0, fmt_money)

            bal_fmt = fmt_balance_pos if line['balance'] >= 0 else fmt_balance_neg
            worksheet.write(row, 6, line['balance'], bal_fmt)
            row += 1

        # ── Closing Balance / Total Row ───────────────────────────────────────
        closing = data['closing_balance']
        label = 'AMOUNT DUE' if closing >= 0 else 'CREDIT BALANCE'
        worksheet.merge_range(row, 0, row, 3, label, fmt_total_label)
        worksheet.write(row, 4, '', fmt_total)
        worksheet.write(row, 5, '', fmt_total)
        worksheet.write(row, 6, closing, fmt_total)
        worksheet.set_row(row, 18)

        workbook.close()
        return output.getvalue()

    # ─────────────────────────────────────────────────────────────────────────
    # QWeb Data Provider (called by report action)
    # ─────────────────────────────────────────────────────────────────────────

    def get_report_values(self):
        """Return data dict for the QWeb PDF template."""
        return self._compute_statement_data()
