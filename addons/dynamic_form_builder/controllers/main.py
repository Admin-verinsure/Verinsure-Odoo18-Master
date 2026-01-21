import json

from odoo import http
from odoo.http import request


class DynamicFormBuilderController(http.Controller):
    # NOTE:
    # We expose this endpoint as type='http' (not json) so it can be called via normal fetch()
    # from public pages and also tested directly in browser.

    @http.route(
        '/form_builder/dynamic_options/<int:field_id>',
        type='http',
        auth='public',
        website=True,
        csrf=False,
        methods=['GET'],
    )
    def dynamic_options(self, field_id, token=None, **kwargs):
        """Return dynamic options for a field (public-safe)."""
        field = request.env['form.builder.field'].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(
                json.dumps({'success': False, 'options': []}),
                headers=[('Content-Type', 'application/json')],
            )

        # Optional safety: ensure field belongs to shared form token (if provided)
        if token:
            form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(
                    json.dumps({'success': False, 'options': []}),
                    headers=[('Content-Type', 'application/json')],
                )

        options = field.sudo().get_dynamic_options() or []
        return request.make_response(
            json.dumps({'success': True, 'options': options}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route(
        '/form_builder/branching/<string:token>',
        type='http',
        auth='public',
        website=True,
        csrf=False,
        methods=['POST'],
    )
    def branching(self, token, **kwargs):
        """Given current answers, decide next form token (branching)."""
        form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
        if not form:
            return request.make_response(
                json.dumps({'success': False, 'next_token': None}),
                headers=[('Content-Type', 'application/json')],
            )

        # answers come as JSON body: {answers: {...}}
        try:
            payload = request.get_json_data(silent=True) or {}
        except Exception:
            payload = {}
        answers = payload.get('answers') or {}

        rules = request.env['form.builder.branch.rule'].sudo().search(
            [('form_id', '=', form.id)],
            order='sequence,id',
        )

        def _match(rule, val):
            v = (val or '').strip() if isinstance(val, str) else val
            want = (rule.value_text or '').strip()

            if rule.operator in ('in', 'not in'):
                wanted = [x.strip() for x in want.split(',') if x.strip()]
                ok = str(v) in wanted
                return ok if rule.operator == 'in' else (not ok)

            if rule.operator == 'contains':
                return want in str(v)

            if rule.operator == '!=':
                return str(v) != want

            # default '='
            return str(v) == want

        next_form = None
        for r in rules:
            key = str(r.trigger_field_id.id)
            if key in answers and _match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        if not next_form and rules and rules[0].fallback_form_id:
            next_form = rules[0].fallback_form_id

        next_token = next_form.share_token if next_form else None
        return request.make_response(
            json.dumps({'success': True, 'next_token': next_token}),
            headers=[('Content-Type', 'application/json')],
        )
