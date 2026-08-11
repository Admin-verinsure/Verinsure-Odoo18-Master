# Timesheet Billing

Enterprise-like hourly timesheet billing for **Odoo 18 Community Edition**.

```
Customer -> Sales Order -> Service Product -> Project -> Task -> Timesheets
         -> Generate Bill -> Customer Invoice
```

This module is a pure extension: it does not modify any file belonging to
`project`, `sale_management`, `account`, `hr_timesheet`, or any third-party
module such as Cybrosys Timesheet. Everything is done through Odoo's model
inheritance (`_inherit`) and additive views (`inherit_id` + `xpath`).

## Dependencies

`project`, `sale_management`, `account`, `product`, `mail`, `analytic`, and
`hr_timesheet`.

`hr_timesheet` is not in the original dependency brief, but it is the
Community module that actually adds `account.analytic.line.task_id` /
`project_id` and the Timesheets UI — timesheet billing cannot function
without it. The module deliberately does **not** depend on `sale_timesheet`,
so there is only one invoicing path in the database (this module's wizard
and scheduled actions), avoiding any conflict with Sales' own "Create
Invoice from timesheets" flow.

It is compatible with the Cybrosys Timesheet module: this module never
inherits Cybrosys's views or overrides its models, so it can be installed
alongside it safely. If Cybrosys Timesheet is not installed, everything
still works against the stock `hr_timesheet` UI.

## Installation

1. Copy the `timesheet_billing` folder into your Odoo `addons` path.
2. Restart the Odoo server.
3. Activate developer mode, go to **Apps**, remove the "Apps" filter, search
   for **Timesheet Billing**, and click **Install**.
   (Or from the command line: `./odoo-bin -d your_db -i timesheet_billing
   --stop-after-init`.)
4. Assign users to the relevant groups from **Settings > Users > Timesheet
   Billing**: *Timesheet User*, *Timesheet Manager*, or *Billing Manager*.
5. (Optional) Load demo data with `-i timesheet_billing --without-demo=False`
   or tick "Demo Data" on a new database to see a working example project.

## Configuration

* **Settings > General Settings > Timesheet Billing** (via `res.company`
  fields `timesheet_billing_default_rate` and
  `timesheet_billing_auto_email` — expose them on a Settings view if you
  want a UI, they are usable as-is via the field on the company record)
  lets you set the last-resort hourly rate and whether posted invoices are
  auto-emailed.
* On each **Project**, open the new **Timesheet Billing** section: set the
  Sales Order, Service Product (must be `type = service`), Billing Type,
  and an optional project-level hourly rate.
* On a **Task**, the **Billing** tab lets you mark it non-billable or set a
  task-specific hourly rate/estimate.
* **Rate resolution cascade** (highest priority first): Timesheet line
  `hourly_rate` -> Task `hourly_rate` -> Project `hourly_rate` -> Product
  `timesheet_hourly_rate` -> Product `list_price` -> Company
  `timesheet_billing_default_rate`.

## Using it

1. Log timesheets against a billable task as usual.
2. A **Timesheet Manager** or **Billing Manager** approves them from
   **Project > Billing > Billable Timesheets** (or via
   `action_approve_timesheets`).
3. A **Billing Manager** opens **Project > Billing > Generate Invoice**,
   picks the Customer/Project/Sales Order and date range, chooses a
   grouping (Single Line / Per Task / Per Employee / Per Day / Per
   Product), and clicks **Generate Invoice**. The resulting draft (or
   posted, if "Validate/Post" was chosen) customer invoice is opened
   automatically.
4. Once invoiced, timesheet lines are locked (`billing_status = invoiced`)
   and cannot be edited or deleted — raise a credit note on the invoice
   instead.
5. **Project > Billing > Invoice History** and **Billing Dashboard** give
   you the audit trail and the pivot/graph KPIs (billable / invoiced /
   pending hours and revenue, sliceable by project, customer, employee).

## Scheduled actions

Four crons ship **disabled by default** (enable them from **Settings >
Technical > Scheduled Actions**):

* Weekly / Monthly Invoice Generation — auto-drafts one invoice per
  eligible project (`billing_type` hourly/time & material, with a Sales
  Order and Service Product set) that has approved, uninvoiced hours.
* Unapproved Timesheets Reminder / Uninvoiced Hours Reminder — notify via
  email template (falls back to a chatter note on the project if the
  template was removed) so the run never fails silently.

Any single project that fails validation (e.g. missing rate) during a
scheduled run is logged and skipped; it never aborts the whole batch.

## Security

* **Timesheet User** — logs and sees only their own timesheets.
* **Timesheet Manager** — sees/approves everyone's timesheets, sees
  Invoice History and the Billing Dashboard.
* **Billing Manager** — everything above, plus the only group allowed to
  run **Generate Invoice** (enforced in code, not just the menu).

## Notes on views

A few view extensions target well-known, long-standing Odoo XML ids
(`project.edit_project`, `project.view_project`, `project.view_task_form2`,
`project.view_task_tree2`, `account.view_move_form`,
`project.menu_main_pm`). These are stable across recent Community releases;
if your build has renamed one of them, disable that specific view record
from **Settings > Technical > Views** rather than uninstalling the module —
all business logic (models, security, the wizard, crons) is fully
independent of these cosmetic patches. The Billing menu's own list/pivot/
form views are all module-owned (not inherited), so they are never at risk
of breaking on install.

## Tests

Run with:

```
./odoo-bin -d your_db -i timesheet_billing --test-enable \
    --test-tags timesheet_billing --stop-after-init
```

Covers: rate resolution cascade, negative-hours validation, the approval
workflow (and its group restriction), invoice creation (single-line and
per-task grouping), duplicate-invoicing prevention, invoiced-line locking,
exclusion of unapproved lines, the Billing Manager-only restriction on
invoice generation, and the required-service-product validation.

## Performance notes

* All KPI/aggregate fields (`billable_hours`, `invoiced_hours`,
  `remaining_hours`, `actual_hours`, invoice counts) are computed with
  `_read_group` (SQL-side aggregation), not Python loops over recordsets.
* The invoice wizard fetches the candidate timesheet lines once, then
  aggregates them into invoice-line groups in a single Python pass
  (`_build_invoice_line_groups`) — no N+1 queries per line.
* Marking lines as invoiced after invoice creation is done with batched
  `write()` calls per invoice-line group, not one write per timesheet line.
