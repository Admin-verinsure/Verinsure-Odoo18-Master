import json
import csv
import io
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SmartFormTable(http.Controller):

    def _get_form_and_check(self, form_id):
        form = request.env["smart.form"].sudo().browse(int(form_id))
        if not form.exists():
            return None
        if request.env.user._is_public():
            return None
        return form

    def _build_columns(self, form):
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

    def _fmt_date(self, dt, fmt="%d/%m/%Y %H:%M:%S"):
        """Safely format an Odoo datetime field — handles False, None, and datetime."""
        if not dt:
            return ""
        try:
            return dt.strftime(fmt)
        except Exception:
            return str(dt)

    def _cell_value(self, raw, ftype):
        if raw is None or raw == "":
            return ""
        if isinstance(raw, list):
            return ", ".join(str(v) for v in raw if v != "")
        if isinstance(raw, dict):
            return str(raw.get("label") or raw.get("value") or "")
        return str(raw)

    @http.route("/smart_form/table/<int:form_id>", type="http", auth="user", website=False)
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

        # Build header cells
        th_date = '''<th class="col-date">
            <div class="th-inner">
                <span class="th-icon">&#128197;</span>
                <span class="th-label">Submitted On</span>
            </div>
        </th>'''

        th_cols = ""
        for c in cols:
            icon = {
                "email": "&#9993;", "phone": "&#128222;", "number": "&#35;",
                "select": "&#9660;", "radio": "&#9673;", "checkbox": "&#9745;",
                "file": "&#128206;", "textarea": "&#128195;",
            }.get(c["ftype"], "&#9632;")
            key_pip = '<span class="key-pip" title="Key field">K</span>' if c["is_key"] else ""
            extra_class = " col-key" if c["is_key"] else ""
            th_cols += '''<th class="col-field%s" title="%s">
                <div class="th-inner">
                    <span class="th-icon">%s</span>
                    <span class="th-label">%s</span>
                    %s
                </div>
            </th>''' % (extra_class, esc(c["label"]), icon, esc(c["label"]), key_pip)

        # Build data rows
        rows_html = ""
        for i, sub in enumerate(submissions):
            try:
                data = json.loads(sub.data_json or "{}")
            except Exception:
                data = {}

            dt = self._fmt_date(sub.create_date, "%d %b %Y, %H:%M")
            row_class = "row-even" if i % 2 == 0 else "row-odd"
            row = '<tr class="%s">' % row_class
            row += '<td class="cell-date">%s</td>' % esc(dt)
            for c in cols:
                raw = data.get(c["key"], "")
                val = self._cell_value(raw, c["ftype"])
                empty_class = " cell-empty" if not val else ""
                key_class = " cell-key" if c["is_key"] else ""
                display = val if val else "—"
                row += '<td class="cell-field%s%s" title="%s">%s</td>' % (
                    key_class, empty_class, esc(val), esc(display))
            row += "</tr>"
            rows_html += row

        if not submissions:
            span = len(cols) + 1
            rows_html = '<tr><td colspan="%d" class="cell-empty-state">No submissions yet.</td></tr>' % span

        total = len(submissions)
        key_col = next((c for c in cols if c["is_key"]), None)
        export_url = "/smart_form/table/%d/export.csv" % form.id

        html = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>%(form_name)s — Submissions</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif;
      background: #f0f2f8;
      color: #1a202c;
      min-height: 100vh;
    }

    /* ── TOP BAR ── */
    .topbar {
      background: linear-gradient(135deg, #4f46e5 0%%, #7c3aed 100%%);
      padding: 0 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 64px;
      box-shadow: 0 2px 12px rgba(79,70,229,0.35);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .topbar-left { display: flex; align-items: center; gap: 14px; }
    .topbar-icon {
      width: 38px; height: 38px;
      background: rgba(255,255,255,0.18);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 1.2rem;
    }
    .topbar-title { color: #fff; font-size: 1.05rem; font-weight: 700; }
    .topbar-sub { color: rgba(255,255,255,0.65); font-size: 0.78rem; margin-top: 1px; }
    .topbar-right { display: flex; gap: 10px; align-items: center; }

    .btn {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 8px 16px; border-radius: 8px;
      font-size: 0.82rem; font-weight: 600;
      cursor: pointer; text-decoration: none; border: none;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .btn-export {
      background: #fff; color: #4f46e5;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12);
    }
    .btn-export:hover { background: #f0f0ff; transform: translateY(-1px); }
    .btn-back {
      background: rgba(255,255,255,0.15); color: #fff;
      border: 1px solid rgba(255,255,255,0.3);
    }
    .btn-back:hover { background: rgba(255,255,255,0.25); }

    /* ── STATS BAR ── */
    .statsbar {
      padding: 16px 32px;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .stat-card {
      background: #fff;
      border-radius: 10px;
      padding: 10px 18px;
      display: flex; align-items: center; gap: 10px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
      font-size: 0.85rem;
    }
    .stat-icon { font-size: 1.1rem; }
    .stat-label { color: #6b7280; }
    .stat-value { font-weight: 700; color: #1a202c; margin-left: 4px; }
    .stat-key-badge {
      background: linear-gradient(135deg, #4f46e5, #7c3aed);
      color: #fff;
      border-radius: 6px; padding: 3px 10px;
      font-size: 0.75rem; font-weight: 700;
      letter-spacing: 0.03em;
    }

    /* ── TABLE WRAPPER ── */
    .table-wrap {
      padding: 0 32px 32px;
      overflow-x: auto;
    }
    .table-card {
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 2px 16px rgba(0,0,0,0.08);
      overflow: hidden;
    }

    /* ── TABLE ── */
    table {
      width: 100%%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }

    /* Header */
    thead {
      background: linear-gradient(135deg, #4f46e5 0%%, #6d28d9 100%%);
    }
    thead th {
      padding: 0;
      vertical-align: bottom;
      border-right: 1px solid rgba(255,255,255,0.12);
      position: relative;
    }
    thead th:last-child { border-right: none; }

    .th-inner {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 4px;
      padding: 14px 14px 12px;
      min-width: 110px;
      max-width: 180px;
    }
    .th-icon {
      font-size: 0.95rem;
      opacity: 0.75;
      line-height: 1;
    }
    .th-label {
      color: #fff;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      line-height: 1.3;
      word-break: break-word;
      /* clamp to 2 lines max */
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .key-pip {
      background: #fbbf24;
      color: #1a202c;
      border-radius: 4px;
      padding: 1px 6px;
      font-size: 0.65rem;
      font-weight: 800;
      letter-spacing: 0.06em;
    }

    /* Key column header */
    th.col-key { background: rgba(251,191,36,0.18); }
    th.col-date .th-inner { min-width: 130px; }

    /* Body rows */
    tbody tr { transition: background 0.1s; }
    tbody tr.row-even { background: #fff; }
    tbody tr.row-odd  { background: #f8f9ff; }
    tbody tr:hover    { background: #eef0ff !important; }
    tbody tr:last-child td { border-bottom: none; }

    tbody td {
      padding: 11px 14px;
      border-bottom: 1px solid #e8eaf0;
      border-right: 1px solid #f0f1f7;
      color: #374151;
      vertical-align: middle;
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    tbody td:last-child { border-right: none; }

    td.cell-date {
      color: #6b7280;
      font-size: 0.82rem;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    td.cell-key {
      font-weight: 600;
      color: #4f46e5;
    }
    td.cell-empty {
      color: #d1d5db;
      font-style: italic;
    }
    td.cell-empty-state {
      text-align: center;
      padding: 48px 16px;
      color: #9ca3af;
      font-size: 0.95rem;
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 768px) {
      .topbar { padding: 0 16px; }
      .statsbar, .table-wrap { padding-left: 16px; padding-right: 16px; }
      .topbar-sub { display: none; }
    }
  </style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-icon">&#128203;</div>
    <div>
      <div class="topbar-title">%(form_name)s</div>
      <div class="topbar-sub">Submissions Table</div>
    </div>
  </div>
  <div class="topbar-right">
    <a href="%(export_url)s" class="btn btn-export">
      <span>&#11123;</span> Export CSV
    </a>
    <a href="javascript:history.back()" class="btn btn-back">
      <span>&#8592;</span> Back
    </a>
  </div>
</div>

<!-- STATS BAR -->
<div class="statsbar">
  <div class="stat-card">
    <span class="stat-icon">&#128203;</span>
    <span class="stat-label">Total Submissions</span>
    <span class="stat-value">%(total)s</span>
  </div>
  <div class="stat-card">
    <span class="stat-icon">&#9635;</span>
    <span class="stat-label">Fields</span>
    <span class="stat-value">%(col_count)s</span>
  </div>
  %(key_stat)s
</div>

<!-- TABLE -->
<div class="table-wrap">
  <div class="table-card">
    <table>
      <thead>
        <tr>
          %(th_date)s
          %(th_cols)s
        </tr>
      </thead>
      <tbody>
        %(rows_html)s
      </tbody>
    </table>
  </div>
</div>

</body>
</html>""" % {
            "form_name": esc(form.name),
            "export_url": export_url,
            "total": total,
            "col_count": len(cols),
            "key_stat": (
                '<div class="stat-card"><span class="stat-icon">&#128273;</span>'
                '<span class="stat-label">Key Field</span>'
                '<span class="stat-key-badge">%s</span></div>' % esc(key_col["label"])
            ) if key_col else "",
            "th_date": th_date,
            "th_cols": th_cols,
            "rows_html": rows_html,
        }

        return request.make_response(
            html, [("Content-Type", "text/html; charset=utf-8")]
        )

    @http.route("/smart_form/table/<int:form_id>/export.csv", type="http", auth="user", website=False)
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
        writer.writerow(["Submitted On"] + [c["label"] for c in cols])
        for sub in submissions:
            try:
                data = json.loads(sub.data_json or "{}")
            except Exception:
                data = {}
            dt = self._fmt_date(sub.create_date, "%d/%m/%Y %H:%M:%S")
            writer.writerow([dt] + [
                self._cell_value(data.get(c["key"], ""), c["ftype"]) for c in cols
            ])

        filename = "submissions_%s.csv" % (form.name or str(form.id)).replace(" ", "_")
        return request.make_response(
            output.getvalue(),
            [
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", 'attachment; filename="%s"' % filename),
            ],
        )
