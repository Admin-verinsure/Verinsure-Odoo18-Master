# -*- coding: utf-8 -*-
{
    'name': 'Timesheet Billing',
    'version': '18.0.1.0.0',
    'category': 'Services/Project',
    'summary': 'Enterprise-like hourly timesheet billing: Sales Order -> Project -> Task -> '
               'Timesheet -> Approval -> Customer Invoice.',
    'description': """
Timesheet Billing
==================
Adds an hourly / time & material billing workflow on top of Project, Sales and
Accounting without touching any core or third-party module.

Key features
------------
* Links Project <-> Sales Order <-> Service Product.
* Rate resolution cascade: Timesheet > Task > Project > Product > Company.
* Timesheet approval workflow with billing status tracking.
* "Generate Timesheet Invoice" wizard with 5 grouping strategies.
* Duplicate-invoicing protection and record locking on invoiced lines.
* Billing dashboard (billable / invoiced / pending hours & revenue).
* Weekly / monthly invoice generation crons + unapproved/uninvoiced reminders.
* Full chatter audit trail (creator, approver, approval history).
* Compatible with the Cybrosys Timesheet module (pure extension, no
  overrides of its files or any core file).

Does not modify any core or third-party module. Pure inheritance/extension
via `_inherit`.
    """,
    'author': 'Nikhil Rana, Verinsure Ltd',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'sale_management',
        'account',
        'product',
        'mail',
        'analytic',
        # hr_timesheet is not in the brief's dependency list, but it is
        # what actually adds account.analytic.line.task_id/project_id and
        # the Timesheets UI in Odoo Community - timesheet billing is not
        # possible without it, and it does not conflict with (or require)
        # sale_timesheet's own separate SO-based invoicing flow, which
        # this module deliberately does NOT depend on so there is only
        # one invoicing path (this module's wizard/crons).
        'hr_timesheet',
    ],
    'data': [
        # security (groups must load before rules/access rights that use them)
        'security/timesheet_billing_security.xml',
        'security/ir.model.access.csv',
        'security/ir_rule_data.xml',
        # data
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        # views
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        'views/account_analytic_line_views.xml',
        'views/account_move_views.xml',
        'views/billing_dashboard_views.xml',
        # wizard
        'wizard/generate_invoice_wizard_views.xml',
        # menus (last: references actions defined above)
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
