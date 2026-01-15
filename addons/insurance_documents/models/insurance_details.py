from odoo import fields, models

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    dms_doc_count = fields.Integer(string="Documents", compute="_compute_dms_doc_count")

    def _compute_dms_doc_count(self):
        DmsFile = self.env["dms.file"]
        for rec in self:
            rec.dms_doc_count = DmsFile.search_count([
                ("res_model", "=", rec._name),
                ("res_id", "=", rec.id),
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
            ],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_directory_id": 51,
            },
        }
