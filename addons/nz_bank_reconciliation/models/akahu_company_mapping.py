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

    def _get_current_user_allowed_company_ids(self):
        return set(self.env.companies.ids)

    def _validate_create_company_scope(self, company_id, counterpart_company_id):
        allowed_company_ids = self._get_current_user_allowed_company_ids()

        if company_id not in allowed_company_ids:
            raise ValidationError(_(
                'You are not allowed to create mappings for company id %(company_id)s.'
            ) % {
                'company_id': company_id,
            })

        if counterpart_company_id not in allowed_company_ids:
            raise ValidationError(_(
                'You are not allowed to use counterpart company id %(company_id)s.'
            ) % {
                'company_id': counterpart_company_id,
            })

        if company_id == counterpart_company_id:
            raise ValidationError(_(
                'This Company and Counterpart Company must be different.'
            ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_id = vals.get('company_id') or self.env.company.id
            if 'counterpart_company_id' in vals:
                self._validate_create_company_scope(
                    company_id,
                    vals['counterpart_company_id'],
                )
        return super().create(vals_list)

    def _assert_runtime_security(
        self,
        allowed_company_ids=None,
        expected_company_id=None,
        expected_partner_id=None,
        expected_counterpart_company_id=None,
    ):
        """
        Validate runtime integrity and authorization for inter-company mappings.

        In addition to structural integrity checks, this method optionally enforces:

        - allowed company scope
        - expected source company
        - expected partner
        - expected counterpart company

        when those expectations are supplied by runtime callers.
        """
        allowed_ids = set(allowed_company_ids) if allowed_company_ids is not None else None
        for rec in self:
            if not rec.company_id:
                raise ValidationError(_(
                    'Inter-company mapping is invalid: company is required.'
                ))
            if not rec.partner_id:
                raise ValidationError(_(
                    'Inter-company mapping is invalid: partner is required.'
                ))
            if not rec.counterpart_company_id:
                raise ValidationError(_(
                    'Inter-company mapping is invalid: counterpart company is required.'
                ))
            if rec.company_id == rec.counterpart_company_id:
                raise ValidationError(_(
                    'Inter-company mapping is invalid: company and counterpart company must be different.'
                ))

            if allowed_ids is not None:
                if rec.company_id.id not in allowed_ids:
                    raise ValidationError(_(
                        'Inter-company mapping is invalid for the current company scope.'
                    ))
                if rec.counterpart_company_id.id not in allowed_ids:
                    raise ValidationError(_(
                        'Inter-company mapping is invalid for the current company scope.'
                    ))

            if expected_company_id is not None and rec.company_id.id != expected_company_id:
                raise ValidationError(_(
                    'Inter-company mapping does not match the expected company.'
                ))

            if expected_partner_id is not None and rec.partner_id.id != expected_partner_id:
                raise ValidationError(_(
                    'Inter-company mapping does not match the expected partner.'
                ))

            if (
                expected_counterpart_company_id is not None
                and rec.counterpart_company_id.id != expected_counterpart_company_id
            ):
                raise ValidationError(_(
                    'Inter-company mapping does not match the expected counterpart company.'
                ))
        return True

    def unlink(self):
        if not self.env.user.has_group('base.group_system'):
            raise ValidationError(_(
                'Only System Administrators can delete inter-company mappings.'
            ))
        return super().unlink()

    def write(self, vals):
        protected_fields = {'company_id', 'partner_id', 'counterpart_company_id'}
        if protected_fields.intersection(vals):
            raise ValidationError(_(
                'Inter-company mappings cannot be modified after creation. '
                'Create a new mapping instead.'
            ))
        return super().write(vals)

    @api.constrains('company_id', 'counterpart_company_id')
    def _check_different_companies(self):
        for rec in self:
            if rec.company_id == rec.counterpart_company_id:
                raise ValidationError(_(
                    'This Company and Counterpart Company must be different.'
                ))
