import json
import csv
import io
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SmartFormTable(http.Controller):

    def _get_form_and_check(self, form_id):
        """Return form if user is internal, else None."""
        form = request.env["smart.form"].sudo().browse(int(form_id))
        if not form.exists():
            return None
        # Only allow internal (logged-in) users
        if request.env.user._is_public():
            return None
        return form

    def _build_columns(self, form):
        """Return ordered list of {key, label, is_key} for all non-subheading fields."""
        cols = []
        for f in form.field_ids:
            if f.field_type == "subheading":
                continue
            cols.append({
                "key": f.name or ("field_%s" % f.id),
                "label": f.label or f.name or ("field_%s" % f.id),
                "is_key": f.is_key_field,
                "ftype": f.field_type,
            })
        return cols

    def _cell_value(self, raw, ftype):
        """Convert raw JSON value to a clean display string."""
        if raw is None or raw == "":
            return ""
        if isinstance(raw, list):
            return ", ".join(str(v) for v in raw if v != "")
        if isinstance(raw, dict):
            return str(raw.get("label") or raw.get("value") or "")
        return str(raw)

    # ----------------------------------------------------------
    # HTML table view
    # ----------------------------------------------------------
    @http.route(
        "/smart_form/table/<int:form_id>",
        type="http", auth="user", website=False
    )
    def submission_table(self, form_id, **kw):
        form = self._get_form_and_check(form_id)
        if not form:
            return request.not_found()

        cols = self._build_columns(form)
        submissions = request.env["smart.form.submission"].sudo().search(
            [("form_id", "=", form.id)], order="create_date desc"
        )

        def esc(s):
            return (str(s)
                    .replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

        # Build header
        th_date = '<th style="white-space:nowrap;">Submitted On</th>'
        th_cols = ""
        for c in cols:
            style = 'style="background:#5a67d8;white-space:nowrap;"' if c["is_key"] else ""
            th_cols += "<th %s>%s</th>" % (style, esc(c["label"]))

        # Build rows
        rows_html = ""
        for sub in submissions:
            try:
                data = json.loads(sub.data_json or "{}")
            except Exception:
                data = {}

            dt = sub.create_date.strftime("%d/%m/%Y %H:%M:%S") if sub.create_date else ""
            row = "<tr>"
            row += "<td style='white-space:nowrap;color:#555;font-size:0.85rem;'>%s</td>" % esc(dt)
            for c in cols:
                raw = data.get(c["key"], "")
                val = self._cell_value(raw, c["ftype"])
                cell_style = "font-weight:600;color:#4c51bf;" if c["is_key"] else ""
                row += "<td style='%s'>%s</td>" % (cell_style, esc(val))
            row += "</tr>"
            rows_html += row

        no_data = ""
        if not submissions:
            span = len(cols) + 1
            no_data = '<tr><td colspan="%d" style="text-align:center;color:#aaa;padding:32px;">No submissions yet.</td></tr>' % span

        col_count = len(cols) + 1  # +1 for date
        export_url = "/smart_form/table/%d/export.csv" % form.id

        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>%(form_name)s — Submissions Table</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Roboto, Arial, sans-serif; background: #f4f5f7; color: #333; }

    .sfb-header {
      background: linear-gradient(135deg, #667eea 0%%, #764ba2 100%%);
      padding: 20px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .sfb-header h1 {
      color: #fff;
      font-size: 1.25rem;
      font-weight: 700;
    }
    .sfb-header .sfb-sub {
      color: rgba(255,255,255,0.75);
      font-size: 0.85rem;
      margin-top: 2px;
    }
    .sfb-actions { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
    .btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 18px; border-radius: 6px; font-size: 0.875rem;
      font-weight: 600; cursor: pointer; text-decoration: none; border: none;
      transition: opacity 0.15s;
    }
    .btn:hover { opacity: 0.88; }
    .btn-export {
      background: #fff; color: #667eea;
    }
    .btn-back {
      background: rgba(255,255,255,0.15); color: #fff;
      border: 1px solid rgba(255,255,255,0.35);
    }

    .sfb-wrap { padding: 24px 32px; overflow-x: auto; }

    .sfb-meta {
      display: flex; align-items: center; gap: 16px;
      margin-bottom: 16px; font-size: 0.85rem; color: #666;
    }
    .sfb-badge {
      background: #667eea; color: #fff;
      border-radius: 12px; padding: 2px 10px; font-size: 0.8rem; font-weight: 600;
    }

    table {
      width: 100%%; border-collapse: collapse;
      background: #fff; border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 6px rgba(0,0,0,0.08);
      min-width: %(min_width)s;
    }
    thead tr {
      background: #667eea;
    }
    thead th {
      padding: 11px 14px; text-align: left;
      color: #fff; font-size: 0.78rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    tbody tr { border-bottom: 1px solid #eef0f3; transition: background 0.1s; }
    tbody tr:hover { background: #f0f4ff; cursor: pointer; }
    tbody tr:last-child { border-bottom: none; }
    tbody td { padding: 11px 14px; font-size: 0.9rem; vertical-align: top; }

    .sfb-key-badge {
      display: inline-block;
      background: #e8eaff; color: #4c51bf;
      border-radius: 4px; padding: 1px 7px;
      font-size: 0.7rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.04em;
      margin-left: 6px; vertical-align: middle;
    }

    @media (max-width: 700px) {
      .sfb-header { padding: 14px 16px; flex-direction: column; align-items: flex-start; }
      .sfb-wrap { padding: 12px 10px; }
    }
  </style>
</head>
<body>

<div class="sfb-header">
  <div>
    <h1>%(form_name)s</h1>
    <div class="sfb-sub">Submissions Table</div>
  </div>
  <div class="sfb-actions">
    <a href="%(export_url)s" class="btn btn-export">&#11123; Export CSV</a>
    <a href="javascript:history.back()" class="btn btn-back">&#8592; Back</a>
  </div>
</div>

<div class="sfb-wrap">
  <div class="sfb-meta">
    <span><strong>%(total)s</strong> submission%(plural)s</span>
    %(key_hint)s
  </div>

  <table>
    <thead>
      <tr>
        %(th_date)s
        %(th_cols)s
      </tr>
    </thead>
    <tbody>
      %(rows_html)s%(no_data)s
    </tbody>
  </table>
</div>

</body>
</html>""" % {
            "form_name": esc(form.name),
            "export_url": export_url,
            "total": len(submissions),
            "plural": "s" if len(submissions) != 1 else "",
            "key_hint": (
                '<span class="sfb-badge">Key: %s</span>' % esc(
                    next((c["label"] for c in cols if c["is_key"]), ""))
                if any(c["is_key"] for c in cols) else ""
            ),
            "th_date": th_date,
            "th_cols": th_cols,
            "rows_html": rows_html,
            "no_data": no_data,
            "min_width": "%dpx" % max(700, col_count * 160),
        }

        return request.make_response(
            html, [("Content-Type", "text/html; charset=utf-8")]
        )

    # ----------------------------------------------------------
    # CSV export
    # ----------------------------------------------------------
    @http.route(
        "/smart_form/table/<int:form_id>/export.csv",
        type="http", auth="user", website=False
    )
    def export_csv(self, form_id, **kw):
        form = self._get_form_and_check(form_id)
        if not form:
            return request.not_found()

        cols = self._build_columns(form)
        submissions = request.env["smart.form.submission"].sudo().search(
            [("form_id", "=", form.id)], order="create_date desc"
        )

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow(
            ["Submitted On"] + [c["label"] for c in cols]
        )

        # Data rows
        for sub in submissions:
            try:
                data = json.loads(sub.data_json or "{}")
            except Exception:
                data = {}
            dt = sub.create_date.strftime("%d/%m/%Y %H:%M:%S") if sub.create_date else ""
            row = [dt] + [
                self._cell_value(data.get(c["key"], ""), c["ftype"])
                for c in cols
            ]
            writer.writerow(row)

        csv_content = output.getvalue()
        filename = "submissions_%s.csv" % (form.name or str(form.id)).replace(" ", "_")

        return request.make_response(
            csv_content,
            [
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", 'attachment; filename="%s"' % filename),
            ],
        )
