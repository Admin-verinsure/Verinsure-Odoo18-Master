# -*- coding: utf-8 -*-
from odoo import api, models

class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.depends('name', 'parent_id', 'is_company')
    def _compute_complete_name(self):
        """Odoo uses complete_name in many views (including Contacts kanban).
        If a partner is a PERSON linked to a parent company, force complete_name
        to be only the person's own name.
        """
        super()._compute_complete_name()
        for p in self:
            if p.parent_id and not p.is_company:
                p.complete_name = p.name or ""

    def name_get(self):
        """Also adjust many2one/dropdown display names."""
        res = super().name_get()
        by_id = dict(res)
        for p in self:
            if p.parent_id and not p.is_company:
                by_id[p.id] = p.name or by_id.get(p.id) or ""
        return [(pid, by_id[pid]) for pid, _ in res]
