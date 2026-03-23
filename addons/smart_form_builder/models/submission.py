from odoo import api, fields, models
import json


class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date desc"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    data_json = fields.Text(string="Data (JSON)", readonly=True)
    target_model = fields.Char(readonly=True)
    target_res_id = fields.Integer(readonly=True)
    ip = fields.Char(readonly=True)
    user_agent = fields.Char(readonly=True)

    response_html = fields.Html(
        string="Form Responses",
        compute="_compute_response_html",
        sanitize=False,
        store=False,
    )

    def get_data(self):
        """Return parsed JSON data as a dict (safe, single-record)."""
        self.ensure_one()
        try:
            return json.loads(self.data_json or "{}")
        except Exception:
            return {}

    @api.depends("data_json", "form_id", "form_id.field_ids")
    def _compute_response_html(self):
        for rec in self:
            rec.response_html = rec._build_response_html()

    def _build_response_html(self):
        self.ensure_one()

        try:
            data = json.loads(self.data_json or "{}")
        except Exception:
            data = {}

        if not data:
            return (
                '<div style="text-align:center;padding:32px 16px;color:#8c8c8c;">'
                '<p style="margin:8px 0 0;font-size:0.95rem;">No response data available.</p>'
                "</div>"
            )

        # Build label + type lookups from form fields
        label_map = {}
        type_map = {}
        if self.form_id:
            for f in self.form_id.field_ids:
                key = f.name or ("field_%s" % f.id)
                label_map[key] = f.label or key
                type_map[key] = f.field_type

        def _esc(s):
            return (
                str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        def _fmt_value(key, val):
            ftype = type_map.get(key, "text")

            if val is None or val == "":
                return '<span style="color:#b0b0b0;font-style:italic;">&#8212;</span>'

            if isinstance(val, list):
                if not val:
                    return '<span style="color:#b0b0b0;font-style:italic;">&#8212;</span>'
                return "".join(
                    '<span style="display:inline-block;background:#e8f0fe;color:#1a56db;'
                    'border-radius:12px;padding:2px 10px;margin:2px 4px 2px 0;'
                    'font-size:0.85rem;">%s</span>' % _esc(str(v))
                    for v in val
                )

            if isinstance(val, dict):
                label = val.get("label") or val.get("value") or ""
                return '<span style="font-weight:500;">%s</span>' % _esc(str(label))

            str_val = str(val)

            if ftype == "email":
                return '<a href="mailto:%s" style="color:#1a56db;text-decoration:none;">%s</a>' % (
                    _esc(str_val), _esc(str_val))
            if ftype == "phone":
                return '<a href="tel:%s" style="color:#1a56db;text-decoration:none;">%s</a>' % (
                    _esc(str_val), _esc(str_val))
            if ftype == "file":
                return (
                    '<span style="display:inline-flex;align-items:center;gap:6px;">'
                    '&#128206; <span style="color:#555;">%s</span>'
                    '</span>' % _esc(str_val)
                )
            if ftype == "textarea":
                return (
                    '<div style="white-space:pre-wrap;background:#f8f9fa;border-radius:6px;'
                    'padding:8px 12px;font-size:0.9rem;color:#333;'
                    'max-height:120px;overflow-y:auto;">%s</div>' % _esc(str_val)
                )

            return '<span style="color:#222;">%s</span>' % _esc(str_val)

        # Render known fields in form order, then any extra keys
        known_keys = []
        if self.form_id:
            for f in self.form_id.field_ids:
                if f.field_type == "subheading":
                    continue
                known_keys.append(f.name or ("field_%s" % f.id))

        extra_keys = [k for k in data if k not in known_keys]
        all_keys = known_keys + extra_keys

        rows_html = ""
        row_index = 0
        for key in all_keys:
            if key not in data:
                continue
            bg = "#ffffff" if row_index % 2 == 0 else "#f9fafb"
            label = label_map.get(key, key.replace("_", " ").title())
            rows_html += (
                '<tr style="background:%s;border-bottom:1px solid #e9ecef;">'
                '<td style="padding:11px 16px;font-weight:600;color:#495057;'
                'font-size:0.875rem;width:35%%;vertical-align:top;white-space:nowrap;">%s</td>'
                '<td style="padding:11px 16px;color:#212529;font-size:0.9rem;'
                'vertical-align:top;word-break:break-word;">%s</td>'
                '</tr>'
            ) % (bg, _esc(label), _fmt_value(key, data[key]))
            row_index += 1

        return (
            '<div style="font-family:\'Segoe UI\',Roboto,Arial,sans-serif;">'
            '<table style="width:100%;border-collapse:collapse;'
            'border:1px solid #dee2e6;border-radius:8px;overflow:hidden;">'
            '<thead>'
            '<tr style="background:#667eea;">'
            '<th style="padding:11px 16px;text-align:left;color:#fff;'
            'font-size:0.78rem;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;width:35%%;">Field</th>'
            '<th style="padding:11px 16px;text-align:left;color:#fff;'
            'font-size:0.78rem;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;">Response</th>'
            '</tr>'
            '</thead>'
            '<tbody>%s</tbody>'
            '</table>'
            '</div>'
        ) % rows_html
