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

    @api.constrains('company_id', 'counterpart_company_id')
    def _check_different_companies(self):
        for rec in self:
            if rec.company_id == rec.counterpart_company_id:
                raise ValidationError(_(
                    'This Company and Counterpart Company must be different.'
                ))
