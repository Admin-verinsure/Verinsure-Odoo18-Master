# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AkahuCompanyMapping(models.Model):
    """
    FIX 4 — Explicit inter-company partner mapping.

    Tells the reconciliation engine: "when we see this partner on a journal
    entry in Company A, its counterpart entry lives in Company B."

    Example setup for 2 companies:
      Company A  |  Partner "Company B (IC)"  →  counterpart: Company B
      Company B  |  Partner "Company A (IC)"  →  counterpart: Company A

    This is more reliable than relying on partner_id.company_id which is
    often not set correctly in Odoo 18 Community multi-company setups.
    """
    _name = 'akahu.company.mapping'
    _description = 'Inter-company Partner Mapping'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Mapping',
        compute='_compute_display_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='This Company',
        required=True,
        default=lambda self: self.env.company,
        help='The company whose journal entries we are scanning.',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Inter-company Partner',
        required=True,
        help='The partner used on journal entries for inter-company transactions.',
    )
    counterpart_company_id = fields.Many2one(
        'res.company',
        string='Counterpart Company',
        required=True,
        help='The Odoo company that holds the mirror journal entry.',
    )
    allowed_counterpart_company_ids = fields.Many2many(
        'res.company',
        string='Allowed Counterpart Companies',
        compute='_compute_allowed_counterpart_company_ids',
        compute_sudo=False,
        help='Companies the current user is allowed to map as counterpart.',
    )
    active = fields.Boolean(default=True)
    notes = fields.Char(string='Notes')

    _sql_constraints = [
        (
            'unique_company_partner',
            'UNIQUE(company_id, partner_id)',
            'A partner can only be mapped once per company.',
        ),
    ]

    @api.depends('company_id', 'partner_id', 'counterpart_company_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s | %s → %s' % (
                rec.company_id.name if rec.company_id else '?',
                rec.partner_id.name if rec.partner_id else '?',
                rec.counterpart_company_id.name if rec.counterpart_company_id else '?',
            )

    @api.depends_context('allowed_company_ids')
    def _compute_allowed_counterpart_company_ids(self):
        allowed_companies = self.env.companies
        for rec in self:
            if rec.company_id:
                rec.allowed_counterpart_company_ids = allowed_companies - rec.company_id
            else:
                rec.allowed_counterpart_company_ids = allowed_companies

    def _get_allowed_counterpart_company_ids(self):
        return set(self.env.companies.ids)

    def _validate_mapping_chain(
        self,
        company_id,
        partner_id,
        counterpart_company_id,
        allowed_company_ids=None,
        expected_company_id=None,
        expected_partner_id=None,
        expected_counterpart_company_id=None,
        mapping_label=None,
    ):
        """Single source of truth for mapping security validation."""
        if not company_id or not partner_id or not counterpart_company_id:
            raise ValidationError(_(
                'Mapping must define company, partner and counterpart company.'
            ))

        if allowed_company_ids is None:
            allowed_ids = self._get_allowed_counterpart_company_ids()
        else:
            allowed_ids = set(allowed_company_ids)

        label = mapping_label or _('%s | %s → %s') % (
            company_id,
            partner_id,
            counterpart_company_id,
        )

        if company_id not in allowed_ids:
            raise ValidationError(_(
                'Mapping %(mapping)s uses source company id %(company_id)s outside allowed companies.'
            ) % {
                'mapping': label,
                'company_id': company_id,
            })

        if counterpart_company_id not in allowed_ids:
            raise ValidationError(_(
                'Mapping %(mapping)s uses counterpart company id %(company_id)s outside allowed companies.'
            ) % {
                'mapping': label,
                'company_id': counterpart_company_id,
            })

        if company_id == counterpart_company_id:
            raise ValidationError(_(
                'This Company and Counterpart Company must be different.'
            ))

        if expected_company_id and company_id != expected_company_id:
            raise ValidationError(_(
                'Mapping %(mapping)s does not belong to expected company id %(company_id)s.'
            ) % {
                'mapping': label,
                'company_id': expected_company_id,
            })

        if expected_partner_id and partner_id != expected_partner_id:
            raise ValidationError(_(
                'Mapping %(mapping)s does not match expected partner id %(partner_id)s.'
            ) % {
                'mapping': label,
                'partner_id': expected_partner_id,
            })

        if expected_counterpart_company_id and counterpart_company_id != expected_counterpart_company_id:
            raise ValidationError(_(
                'Mapping %(mapping)s does not match expected counterpart company id %(company_id)s.'
            ) % {
                'mapping': label,
                'company_id': expected_counterpart_company_id,
            })

    def _assert_runtime_security(
        self,
        allowed_company_ids=None,
        expected_company_id=None,
        expected_partner_id=None,
        expected_counterpart_company_id=None,
    ):
        """Validate mapping safety when consumed by engine/wizard runtime paths.

        This blocks sudo()-based paths from using mappings that point to
        companies outside the caller/scope allowed company set.

        If expected_* values are provided, this method also validates the
        exact configured mapping chain:
            source company -> mapped partner -> counterpart company
        """
        if allowed_company_ids is None:
            allowed_ids = set(self.env.companies.ids)
        else:
            allowed_ids = set(allowed_company_ids)

        for rec in self:
            self._validate_mapping_chain(
                company_id=rec.company_id.id,
                partner_id=rec.partner_id.id,
                counterpart_company_id=rec.counterpart_company_id.id,
                allowed_company_ids=allowed_ids,
                expected_company_id=expected_company_id,
                expected_partner_id=expected_partner_id,
                expected_counterpart_company_id=expected_counterpart_company_id,
                mapping_label=rec.display_name,
            )

    @api.model_create_multi
    def create(self, vals_list):
        allowed_ids = self._get_allowed_counterpart_company_ids()
        for vals in vals_list:
            company_id = vals.get('company_id') or self.env.company.id
            partner_id = vals.get('partner_id')
            counterpart_company_id = vals.get('counterpart_company_id')
            self._validate_mapping_chain(
                company_id=company_id,
                partner_id=partner_id,
                counterpart_company_id=counterpart_company_id,
                allowed_company_ids=allowed_ids,
            )
        return super().create(vals_list)

    def write(self, vals):
        allowed_ids = self._get_allowed_counterpart_company_ids()
        for rec in self:
            current_company_id = rec.company_id.id
            current_partner_id = rec.partner_id.id
            current_counterpart_company_id = rec.counterpart_company_id.id

            next_company_id = vals.get('company_id', current_company_id)
            next_partner_id = vals.get('partner_id', current_partner_id)
            next_counterpart_company_id = vals.get(
                'counterpart_company_id', current_counterpart_company_id
            )

            rec._validate_mapping_chain(
                company_id=next_company_id,
                partner_id=next_partner_id,
                counterpart_company_id=next_counterpart_company_id,
                allowed_company_ids=allowed_ids,
                expected_company_id=current_company_id,
                expected_partner_id=current_partner_id,
                expected_counterpart_company_id=current_counterpart_company_id,
                mapping_label=rec.display_name,
            )
        return super().write(vals)

    def action_confirm(self):
        allowed_ids = self._get_allowed_counterpart_company_ids()
        for rec in self:
            rec._validate_mapping_chain(
                company_id=rec.company_id.id,
                partner_id=rec.partner_id.id,
                counterpart_company_id=rec.counterpart_company_id.id,
                allowed_company_ids=allowed_ids,
                expected_company_id=rec.company_id.id,
                expected_partner_id=rec.partner_id.id,
                expected_counterpart_company_id=rec.counterpart_company_id.id,
                mapping_label=rec.display_name,
            )
        return True

    @api.constrains('company_id', 'counterpart_company_id')
    def _check_different_companies(self):
        for rec in self:
            if rec.company_id == rec.counterpart_company_id:
                raise ValidationError(_(
                    'This Company and Counterpart Company must be different.'
                ))
