# -*- coding: utf-8 -*-
from odoo import api, models

class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.depends('name', 'parent_id', 'is_company')
    def _compute_display_name(self):
        """Odoo 18 webclient/kanban titles typically rely on display_name.
        Force display_name to be only the person's name for child contacts.
        """
        super()._compute_display_name()
        for p in self:
            if p.parent_id and not p.is_company:
                p.display_name = p.name or ""

    @api.depends('name', 'parent_id', 'is_company')
    def _compute_complete_name(self):
        """Keep complete_name aligned as well (used in some views/reports)."""
        super()._compute_complete_name()
        for p in self:
            if p.parent_id and not p.is_company:
                p.complete_name = p.name or ""

    def name_get(self):
        """Many2one/dropdown display."""
        res = super().name_get()
        by_id = dict(res)
        for p in self:
            if p.parent_id and not p.is_company:
                by_id[p.id] = p.name or by_id.get(p.id) or ""
        return [(pid, by_id[pid]) for pid, _ in res]
