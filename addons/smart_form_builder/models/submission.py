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

    def data(self):
        for rec in self:
            try:
                return json.loads(rec.data_json or "{}")
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
                '<div class="sfb-empty-state" style="'
                "text-align:center;padding:32px 16px;color:#8c8c8c;"
                '">'
                '<span style="font-size:2rem;">&#128229;</span>'
                '<p style="margin:8px 0 0;font-size:0.95rem;">No response data available.</p>'
                "</div>"
            )

        # Build a label-lookup from the form fields (technical_name -> label)
        label_map = {}
        type_map = {}
        if self.form_id:
            for f in self.form_id.field_ids:
                key = f.name or "field_%s" % f.id
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
                items = "".join(
                    '<span style="display:inline-block;background:#e8f0fe;color:#1a56db;'
                    'border-radius:12px;padding:2px 10px;margin:2px 4px 2px 0;'
                    'font-size:0.85rem;">%s</span>' % _esc(str(v))
                    for v in val
                )
                return items

            if isinstance(val, dict):
                label = val.get("label") or val.get("value") or ""
                return '<span style="font-weight:500;">%s</span>' % _esc(str(label))

            str_val = str(val)

            if ftype == "email":
                return '<a href="mailto:%s" style="color:#1a56db;">%s</a>' % (
                    _esc(str_val), _esc(str_val))
            if ftype == "phone":
                return '<a href="tel:%s" style="color:#1a56db;">%s</a>' % (
                    _esc(str_val), _esc(str_val))
            if ftype == "file":
                return (
                    '<span style="display:inline-flex;align-items:center;gap:6px;">'
                    '<span style="font-size:1.1rem;">&#128206;</span>'
                    '<span style="color:#555;">%s</span>'
                    '</span>' % _esc(str_val)
                )
            if ftype == "textarea":
                return (
                    '<div style="white-space:pre-wrap;background:#f8f9fa;border-radius:6px;'
                    'padding:8px 12px;font-size:0.9rem;color:#333;max-height:120px;overflow-y:auto;">%s</div>'
                    % _esc(str_val)
                )

            return '<span style="color:#222;">%s</span>' % _esc(str_val)

        # Show known fields in form order first, then any extra keys
        known_keys = []
        if self.form_id:
            for f in self.form_id.field_ids:
                if f.field_type == "subheading":
                    continue
                key = f.name or "field_%s" % f.id
                known_keys.append(key)

        extra_keys = [k for k in data.keys() if k not in known_keys]
        all_keys = known_keys + extra_keys

        rows_html = ""
        row_index = 0
        for key in all_keys:
            if key not in data:
                continue
            val = data[key]
            label = label_map.get(key, key.replace("_", " ").title())
            bg = "#ffffff" if row_index % 2 == 0 else "#f9fafb"
            formatted = _fmt_value(key, val)
            row_index += 1

            rows_html += (
                '<tr style="background:%s;border-bottom:1px solid #e9ecef;">'
                '<td style="padding:12px 16px;font-weight:600;color:#495057;'
                'font-size:0.875rem;width:35%%;vertical-align:top;white-space:nowrap;">%s</td>'
                '<td style="padding:12px 16px;color:#212529;font-size:0.9rem;'
                'vertical-align:top;word-break:break-word;">%s</td>'
                '</tr>'
            ) % (bg, _esc(label), formatted)

        html = (
            '<div style="font-family:\'Segoe UI\',Roboto,Arial,sans-serif;max-width:900px;">'
            '<table style="width:100%;border-collapse:collapse;border-radius:8px;'
            'overflow:hidden;border:1px solid #dee2e6;box-shadow:0 1px 4px rgba(0,0,0,0.06);">'
            '<thead>'
            '<tr style="background:linear-gradient(135deg,#667eea 0%%,#764ba2 100%%);">'
            '<th style="padding:12px 16px;text-align:left;color:#ffffff;font-size:0.8rem;'
            'font-weight:600;text-transform:uppercase;letter-spacing:0.06em;width:35%%;">Field</th>'
            '<th style="padding:12px 16px;text-align:left;color:#ffffff;font-size:0.8rem;'
            'font-weight:600;text-transform:uppercase;letter-spacing:0.06em;">Response</th>'
            '</tr>'
            '</thead>'
            '<tbody>%s</tbody>'
            '</table>'
            '</div>'
        ) % rows_html

        return html
