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
    'depends': ['account', 'web'],
    'data': [
        # Base report templates should be loaded first as they are likely inherited by other files
        'reports/normal_invoice_templates.xml',
        'reports/modern_invoice_templates.xml',
        'reports/old_standard_invoice_templates.xml',
        'reports/report_invoice_templates.xml',
        'reports/preview_layout_report_templates.xml',
        
        # Files that perform a simple inheritance/patch should be loaded after their parent 
        'views/custom_external_layout.xml',
        'views/custom_external_layout_templates.xml',
        'views/external_layout_patch.xml',
        'reports/override.xml', # Overrides should be loaded last to ensure they apply correctly
    ],
    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}