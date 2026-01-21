import json
from odoo import http
from odoo.http import request

class DynamicFormBuilderController(http.Controller):

    @http.route('/form_builder/dynamic_options/<int:field_id>', type='json', auth='public', website=True, csrf=False)
    def dynamic_options(self, field_id, token=None, **kwargs):
        """Return dynamic options for a field (public-safe)."""
        field = request.env['form.builder.field'].sudo().browse(field_id)
        if not field.exists():
            return {'success': False, 'options': []}

        # Optional safety: ensure field belongs to shared form token (if provided)
        if token:
            form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
            if not form or field.form_id.id != form.id:
                return {'success': False, 'options': []}

        return {'success': True, 'options': field.get_dynamic_options()}

    @http.route('/form_builder/branching/<string:token>', type='json', auth='public', website=True, csrf=False)
    def branching(self, token, answers=None, **kwargs):
        """Given current answers, decide next form token (branching)."""
        form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
        if not form:
            return {'success': False}

        answers = answers or {}
        rules = request.env['form.builder.branch.rule'].sudo().search([('form_id', '=', form.id)], order='sequence,id')

        def _match(rule, val):
            v = (val or '').strip() if isinstance(val, str) else val
            want = (rule.value_text or '').strip()
            if rule.operator in ('in','not in'):
                wanted = [x.strip() for x in want.split(',') if x.strip()]
                ok = str(v) in wanted
                return ok if rule.operator == 'in' else (not ok)
            if rule.operator == 'contains':
                return want in str(v)
            if rule.operator == '!=':
                return str(v) != want
            return str(v) == want

        next_form = None
        for r in rules:
            key = str(r.trigger_field_id.id)
            if key in answers and _match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        if not next_form and rules and rules[0].fallback_form_id:
            next_form = rules[0].fallback_form_id

        if not next_form:
            return {'success': True, 'next_token': None}

        return {'success': True, 'next_token': next_form.share_token}
