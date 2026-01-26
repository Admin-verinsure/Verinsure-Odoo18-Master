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

    first_name = fields.Char(string="First Name")
    last_name = fields.Char(string="Last Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")

    data_source = fields.Selection(
        [
            ("partner", "Fetched from Partner"),
            ("form", "Submitted via Form"),
        ],
        string="Data Source",
    )

    data_json = fields.Text(string="Raw Data")
    ip = fields.Char()
    user_agent = fields.Char()

    # --------------------------------------------------
    # READABLE DATA (AUTO-GENERATED FROM FORM FIELDS)
    # --------------------------------------------------
    readable_data = fields.Json(
        string="Readable Data",
        compute="_compute_readable_data",
        store=False,
    )

    # --------------------------------------------------
    # COMPUTE METHODS
    # --------------------------------------------------
    @api.depends("data_json", "form_id")
    def _compute_readable_data(self):
        for rec in self:
            readable = {}

            if not rec.data_json or not rec.form_id:
                rec.readable_data = readable
                continue

            try:
                submitted_data = json.loads(rec.data_json)
            except Exception:
                submitted_data = {}

            # Build mapping: field_key -> field label
            field_label_map = {}
            for field in rec.form_id.field_ids:
                key = field.name or f"field_{field.id}"
                field_label_map[key] = field.label or field.name or key

            # Replace technical keys with labels
            for key, value in submitted_data.items():
                label = field_label_map.get(key, key)

                # Normalize values
                if isinstance(value, list):
                    value = ", ".join([str(v) for v in value if v])

                readable[label] = value

            rec.readable_data = readable
