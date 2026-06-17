# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Bhagyadev KP (<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
import json

from odoo import http
from odoo.http import content_disposition, request, Response


class DynamicAccountsReportController(http.Controller):
    """Controller for handling XLSX report downloads for all dynamic
    accounting reports."""

    @http.route('/xlsx_report', type='http', auth='user', methods=['POST'],
                csrf=False)
    def get_xlsx_report(self, model, data, output_format, report_name,
                        report_action=False, **kw):
        """
        Handle POST requests to generate and download XLSX reports.

        :param model: The Odoo model name to call get_xlsx_report on.
        :param data: JSON-encoded report data string.
        :param output_format: Expected to be 'xlsx'.
        :param report_name: The display name used as the downloaded filename.
        :param report_action: The XML ID of the action (used to branch logic
                              inside models).
        """
        uid = request.session.uid
        report_obj = request.env[model].with_user(uid)

        if output_format == 'xlsx':
            response = Response(
                headers=[
                    ('Content-Type',
                     'application/vnd.openxmlformats-officedocument'
                     '.spreadsheetml.sheet'),
                    ('Content-Disposition',
                     content_disposition(report_name + '.xlsx')),
                ]
            )
            report_obj.get_xlsx_report(data, response, report_name,
                                       report_action)
            response.make_conditional(request.httprequest)
            return response

        return Response(
            json.dumps({'error': 'Unsupported output format'}),
            status=400,
            content_type='application/json',
        )
