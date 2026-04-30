# -*- coding: utf-8 -*-
import io
import json
from datetime import date, datetime

from odoo import http
from odoo.http import request, content_disposition
from odoo.exceptions import AccessError


class CustomerStatementController(http.Controller):
    """
    HTTP controller for serving the Customer Statement Excel report.
    Uses a POST route with JSON payload to avoid 414 URI Too Long errors
    that occur when passing large data in URL query strings.
    """

    @http.route(
        '/customer_statement/excel',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def download_excel(self, **kwargs):
        """
        Generate and stream the Excel (.xlsx) customer statement report.

        Expects POST body fields:
            wizard_id (int): ID of the customer.statement.wizard record.

        The wizard record holds start_date, end_date, partner_id.
        We re-fetch statement data from the wizard's helper so there is
        a single source of truth for the business logic.
        """
        try:
            wizard_id = int(kwargs.get('wizard_id', 0))
        except (ValueError, TypeError):
            return request.make_response(
                'Invalid wizard_id', status=400
            )

        wizard = request.env['customer.statement.wizard'].browse(wizard_id)
        if not wizard.exists():
            return request.make_response('Wizard not found', status=404)

        # Build report data using the shared helper
        data = wizard._get_statement_data()

        # --- Build workbook with openpyxl ---
        try:
            import openpyxl
            from openpyxl.styles import (
                Font, Alignment, PatternFill, Border, Side, numbers
            )
            from openpyxl.utils import get_column_letter
        except ImportError:
            return request.make_response(
                'openpyxl is required. Install it via: pip install openpyxl',
                status=500,
            )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Customer Statement"

        # ---------- Styles ----------
        DARK_BLUE = "1F3864"
        MID_BLUE  = "2E75B6"
        LIGHT_BLUE = "D6E4F0"
        LIGHT_GREY = "F2F2F2"
        RED_FONT   = "C00000"
        GREEN_FONT = "375623"

        def _font(bold=False, size=10, color="000000", italic=False):
            return Font(bold=bold, size=size, color=color, italic=italic)

        def _fill(hex_color):
            return PatternFill("solid", fgColor=hex_color)

        def _align(h="left", v="center", wrap=False):
            return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

        def _border(style="thin"):
            s = Side(style=style)
            return Border(left=s, right=s, top=s, bottom=s)

        def _num_fmt(ws_cell, fmt='#,##0.00'):
            ws_cell.number_format = fmt

        # ---------- Column widths ----------
        col_widths = [16, 22, 18, 16, 16, 18]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # ---------- Row 1: Company name ----------
        company = data['company']
        ws.merge_cells('A1:F1')
        c = ws['A1']
        c.value = company['name']
        c.font = _font(bold=True, size=14, color="FFFFFF")
        c.fill = _fill(DARK_BLUE)
        c.alignment = _align("center")
        ws.row_dimensions[1].height = 28

        # ---------- Row 2: Company address ----------
        ws.merge_cells('A2:F2')
        c = ws['A2']
        c.value = company['address']
        c.font = _font(size=9, color="FFFFFF", italic=True)
        c.fill = _fill(MID_BLUE)
        c.alignment = _align("center")
        ws.row_dimensions[2].height = 16

        # ---------- Row 3: blank ----------
        ws.row_dimensions[3].height = 6

        # ---------- Row 4: Statement title + customer block ----------
        ws.merge_cells('A4:C5')
        c = ws['A4']
        c.value = "STATEMENT OF ACCOUNT"
        c.font = _font(bold=True, size=13)
        c.alignment = _align("left", "center")

        ws['D4'].value = "Customer:"
        ws['D4'].font = _font(bold=True, size=10)
        ws['D4'].alignment = _align("right")

        ws.merge_cells('E4:F4')
        c = ws['E4']
        c.value = data['partner']['name']
        c.font = _font(bold=True, size=10)
        c.alignment = _align("left")

        ws['D5'].value = "Period:"
        ws['D5'].font = _font(bold=True, size=10)
        ws['D5'].alignment = _align("right")

        ws.merge_cells('E5:F5')
        c = ws['E5']
        c.value = f"{data['start_date']}  →  {data['end_date']}"
        c.font = _font(size=10)
        c.alignment = _align("left")

        ws['D6'].value = "As of:"
        ws['D6'].font = _font(bold=True, size=10)
        ws['D6'].alignment = _align("right")

        ws.merge_cells('E6:F6')
        c = ws['E6']
        c.value = date.today().strftime("%d/%m/%Y")
        c.font = _font(size=10)
        c.alignment = _align("left")

        ws.row_dimensions[4].height = 18
        ws.row_dimensions[5].height = 18
        ws.row_dimensions[6].height = 18

        # ---------- Row 7: blank ----------
        ws.row_dimensions[7].height = 6

        # ---------- Row 8: Opening balance ----------
        ws.merge_cells('A8:E8')
        c = ws['A8']
        c.value = "Opening Balance (before period)"
        c.font = _font(bold=True, size=10, color=DARK_BLUE)
        c.fill = _fill(LIGHT_BLUE)
        c.alignment = _align("left")
        c.border = _border()

        ob_cell = ws['F8']
        ob_cell.value = data['opening_balance']
        ob_cell.font = _font(bold=True, size=10, color=DARK_BLUE)
        ob_cell.fill = _fill(LIGHT_BLUE)
        ob_cell.alignment = _align("right")
        ob_cell.border = _border()
        _num_fmt(ob_cell)
        ws.row_dimensions[8].height = 18

        # ---------- Row 9: Header ----------
        headers = ["Date", "Document No.", "Type", "Debit", "Credit", "Balance"]
        for col, hdr in enumerate(headers, 1):
            c = ws.cell(row=9, column=col, value=hdr)
            c.font = _font(bold=True, size=10, color="FFFFFF")
            c.fill = _fill(DARK_BLUE)
            c.alignment = _align("center")
            c.border = _border()
        ws.row_dimensions[9].height = 20

        # ---------- Data rows ----------
        row = 10
        for i, line in enumerate(data['lines']):
            fill = _fill(LIGHT_GREY) if i % 2 == 0 else _fill("FFFFFF")
            border = _border()

            # Date
            c = ws.cell(row=row, column=1, value=line['date'])
            c.font = _font(size=10)
            c.fill = fill; c.border = border
            c.alignment = _align("center")

            # Doc number
            c = ws.cell(row=row, column=2, value=line['name'])
            c.font = _font(size=10)
            c.fill = fill; c.border = border
            c.alignment = _align("left")

            # Type
            c = ws.cell(row=row, column=3, value=line['type_label'])
            is_cn = line['move_type'] == 'out_refund'
            c.font = _font(size=10, color=(RED_FONT if is_cn else GREEN_FONT))
            c.fill = fill; c.border = border
            c.alignment = _align("center")

            # Debit
            c = ws.cell(row=row, column=4, value=line['debit'] or '')
            c.font = _font(size=10)
            c.fill = fill; c.border = border
            c.alignment = _align("right")
            if line['debit']:
                _num_fmt(c)

            # Credit
            c = ws.cell(row=row, column=5, value=line['credit'] or '')
            c.font = _font(size=10, color=RED_FONT if line['credit'] else "000000")
            c.fill = fill; c.border = border
            c.alignment = _align("right")
            if line['credit']:
                _num_fmt(c)

            # Running balance
            bal = line['running_balance']
            c = ws.cell(row=row, column=6, value=bal)
            c.font = _font(size=10, bold=True,
                           color=(RED_FONT if bal < 0 else "000000"))
            c.fill = fill; c.border = border
            c.alignment = _align("right")
            _num_fmt(c)

            ws.row_dimensions[row].height = 17
            row += 1

        # ---------- Closing balance row ----------
        ws.row_dimensions[row].height = 22
        ws.merge_cells(f'A{row}:E{row}')
        c = ws.cell(row=row, column=1, value="NET BALANCE DUE")
        c.font = _font(bold=True, size=11, color="FFFFFF")
        c.fill = _fill(DARK_BLUE)
        c.alignment = _align("right")
        c.border = _border()

        nb = data['net_balance']
        c = ws.cell(row=row, column=6, value=nb)
        c.font = _font(bold=True, size=11,
                       color=(RED_FONT if nb < 0 else "FFFFFF"))
        c.fill = _fill(DARK_BLUE)
        c.alignment = _align("right")
        c.border = _border()
        _num_fmt(c)

        # Freeze panes below header
        ws.freeze_panes = 'A10'

        # ---------- Stream response ----------
        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)

        partner_name = data['partner']['name'].replace(' ', '_')
        filename = f"Customer_Statement_{partner_name}_{date.today()}.xlsx"

        return request.make_response(
            stream.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ]
        )
