import json
from odoo import models, fields, api


class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date asc"

    # --------------------------------------------------
    # CORE FIELDS
    # --------------------------------------------------
    form_id = fields.Many2one("smart.form", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")

    first_name = fields.Char()
    last_name = fields.Char()
    email = fields.Char()
    phone = fields.Char()

    data_source = fields.Selection(
        [
            ("partner", "Fetched from Partner"),
            ("form", "Submitted via Form"),
        ]
    )

    data_json = fields.Text(string="Raw Data")
    ip = fields.Char()
    user_agent = fields.Char()

    # --------------------------------------------------
    # READABLE DATA (FINAL)
    # --------------------------------------------------
    readable_data = fields.Json(
        string="Readable Data",
        readonly=True,
    )

    # --------------------------------------------------
    # CREATE / WRITE (FORCE COMPUTE)
    # --------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._compute_readable_data()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "data_json" in vals or "form_id" in vals:
            self._compute_readable_data()
        return res

    # --------------------------------------------------
    # COMPUTE METHOD
    # --------------------------------------------------
    def _compute_readable_data(self):
        for rec in self:
            readable = {}

            if not rec.data_json or not rec.form_id:
                rec.readable_data = {}
                continue

            try:
                submitted = json.loads(rec.data_json)
            except Exception:
                submitted = {}

            # Map technical keys → labels
            label_map = {}
            for field in rec.form_id.sudo().field_ids:
                key = field.name or f"field_{field.id}"
                label_map[key] = field.label or field.name or key

            for key, value in submitted.items():
                label = label_map.get(key, key)

                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value if v)

                readable[label] = value

            rec.readable_data = readable
