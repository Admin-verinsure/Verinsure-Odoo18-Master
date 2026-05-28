# -*- coding: utf-8 -*-
{
    'name': 'NZ Bank Reconciliation (Akahu)',
    'version': '18.0.1.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Akahu NZ open banking sync + automatic multi-type reconciliation for Odoo 18',
    'description': """
NZ Bank Reconciliation — Akahu Integration + Auto Reconciliation
================================================================
A single unified module that:

AKAHU SYNC
- Store App Token + App Secret securely per company
- Connect multiple NZ bank accounts via User Access Tokens
- Pull settled transactions → Odoo bank statement lines (hourly cron)
- Paginated sync with cursor support (incremental, no duplicates)
- ACTIVE/INACTIVE account status monitoring

AUTO RECONCILIATION
- Bank Statements vs Journal Entries
- Customer Payments vs Invoices
- Vendor Payments vs Bills
- Inter-company Transactions
- Exact amount matching engine
- Manual trigger + daily scheduled cron
- Multi-company support

UX
- Wizard UI to preview matches before confirming
- Unified dashboard: Akahu account health + reconciliation stats
- Full audit log for both sync and reconciliation runs
    """,
    'author': 'Not4Profit',
    'website': 'https://not4profit.online',
    'depends': [
        'account',
        'base_setup',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        'security/nz_bank_recon_security.xml',
        # Data / Crons
        'data/ir_cron_data.xml',
        # Views — Akahu
        'views/akahu_credential_views.xml',
        'views/akahu_account_views.xml',
        'views/account_journal_dashboard_extend.xml',
        'views/akahu_sync_log_views.xml',
        'views/akahu_company_mapping_views.xml',
        # Views — Reconciliation
        'views/auto_reconciliation_config_views.xml',
        'views/auto_reconciliation_log_views.xml',
        'views/auto_reconciliation_dashboard_views.xml',
        # Wizard
        'wizard/auto_reconciliation_wizard_views.xml',
        'wizard/akahu_credential_revoke_wizard_views.xml',
        # Menu (last — references all actions above)
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nz_bank_reconciliation/static/src/css/dashboard.css',
            'nz_bank_reconciliation/static/src/xml/dashboard.xml',
            'nz_bank_reconciliation/static/src/js/dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'external_dependencies': {'python': ['requests']},
}
