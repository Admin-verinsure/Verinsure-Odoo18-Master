
{
    'name': 'format editor',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Invoice Report, Report Editor, Customise Invoice Report, '
               'Invoice Report Templates, Account Reports, Odoo18, '
               'Odoo Apps, Report Templates, Odoo18, Odoo Apps',
    'description': """Invoice Format Editor For Configuring the Invoice Templates""",
    'author': 'not4profit',
    'company': 'not4profit',
    'maintainer': 'not4profit',
    'website': 'https://www.not4profit.online',
    'depends': ['account', 'web', ],
    'data': [
        
             'views/custom_external_layout_templates.xml',
             'reports/normal_invoice_templates.xml',
             'reports/modern_invoice_templates.xml',
             'reports/override.xml',
             'reports/old_standard_invoice_templates.xml',
             'reports/report_invoice_templates.xml',
             'reports/preview_layout_report_templates.xml',
             'views/external_layout_patch.xml',
             ],
    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
