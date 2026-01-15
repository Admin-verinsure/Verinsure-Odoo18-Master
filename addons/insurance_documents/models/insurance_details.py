from odoo import fields, models

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # Link policy visibility to an access group (represents a club/team)
    x_club_group_id = fields.Many2one("res.groups", string="Club (Access Group)", index=True)

    document_count = fields.Integer(string="Documents", compute="_compute_dms_doc_count")

    def _compute_dms_doc_count(self):
        DmsFile = self.env["dms.file"]
        for rec in self:
            rec.document_count = DmsFile.search_count([
                ("res_model", "=", rec._name),
                ("res_id", "=", rec.id),
                ("directory_id", "child_of", 51),
            ])

    def action_open_dms_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Policy Documents",
            "res_model": "dms.file",
            "view_mode": "kanban,list,form",
            "domain": [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("directory_id", "child_of", 51),
            ],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_directory_id": 51,
            },
        }
