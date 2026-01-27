from odoo import api, fields, models
import secrets

class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id", string="Submissions", readonly=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id", string="Branch Rules", copy=True)
    logic_rule_ids = fields.One2many("smart.form.logic.rule", "form_id", string="Logic Rules", copy=True)
    # Optional: store submissions into an Odoo model (e.g., Contacts / res.partner)
    store_in_model = fields.Boolean(string='Store in Database Model', default=False)
    target_model_id = fields.Many2one('ir.model', string='Target Model', ondelete='restrict')
    model_field_mapping_ids = fields.One2many('smart.form.model.map', 'form_id', string='Field Mapping', copy=True)

    def _build_target_vals_from_answers(self, answers_by_id):
        """Build create() vals for target_model_id from submitted answers using configured mappings.

        - Only mapped fields are included (unmapped inputs are ignored).
        - Best-effort type conversion based on ir.model.fields.ttype.
        - Never raises: returns {} on any issue.
        """
        self.ensure_one()
        if not (self.store_in_model and self.target_model_id and self.model_field_mapping_ids):
            return {}
        vals = {}
        try:
            for m in self.model_field_mapping_ids.sorted(lambda r: (r.sequence, r.id)):
                if not (m.form_field_id and m.model_field_id):
                    continue
                raw = answers_by_id.get(str(m.form_field_id.id))
                if raw in (None, '', [], {}):
                    continue

                # answers may be dict like {'value':..., 'label':...} in some flows
                if isinstance(raw, dict):
                    value = raw.get('value')
                else:
                    value = raw

                if value in (None, '', [], {}):
                    continue

                mf = m.model_field_id
                t = mf.ttype

                # Basic scalar conversions
                if t in ('char', 'text', 'html'):
                    vals[mf.name] = str(value)
                elif t == 'boolean':
                    if isinstance(value, str):
                        vals[mf.name] = value.strip().lower() in ('1','true','yes','y','on')
                    else:
                        vals[mf.name] = bool(value)
                elif t == 'integer':
                    try:
                        vals[mf.name] = int(value)
                    except Exception:
                        continue
                elif t in ('float', 'monetary'):
                    try:
                        vals[mf.name] = float(value)
                    except Exception:
                        continue
                elif t in ('date','datetime'):
                    # expect web form to send a valid string format; store as-is
                    vals[mf.name] = value
                elif t == 'many2one':
                    # Accept id, else try name search (best-effort, may be ambiguous)
                    rel = mf.relation
                    rid = None
                    if isinstance(value, int):
                        rid = value
                    elif isinstance(value, str) and value.isdigit():
                        rid = int(value)
                    if rid:
                        vals[mf.name] = rid
                    else:
                        rec = self.env[rel].sudo().search([('name','=',str(value))], limit=1)
                        if rec:
                            vals[mf.name] = rec.id
                elif t in ('many2many','one2many'):
                    ids = value if isinstance(value, list) else []
                    ids2 = []
                    for x in ids:
                        try:
                            if isinstance(x, int): ids2.append(x)
                            elif isinstance(x, str) and x.isdigit(): ids2.append(int(x))
                        except Exception:
                            pass
                    if ids2:
                        vals[mf.name] = [(6, 0, ids2)]
                else:
                    # fallback: try direct assign
                    vals[mf.name] = value
        except Exception:
            return {}
        return vals

    submission_count = fields.Integer(compute="_compute_submission_count")

    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}",
            "target": "new",
        }

    def action_open_preview(self):
        # Preview is same as public but with ?preview=1
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}?preview=1",
            "target": "new",
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Submissions",
            "res_model": "smart.form.submission",
            "view_mode": "list,form",
            "domain": [("form_id", "=", self.id)],
            "context": {"default_form_id": self.id},
        }
