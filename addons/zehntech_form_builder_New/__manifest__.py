{
    'name': 'Odoo Form Builder New',
    'version': '18.0.1.0.0',
    'author': 'Zehntech Technologies Inc.',
    'summary': 'This Odoo Form Builder Odoo App allows users to create, customize, and publish professional online forms and surveys using a no-code, drag-and-drop interface. It supports all necessary field types (Text, Email, Dropdown, File Upload, Captcha, Rating, etc.) with full control over validation and labels. Forms are instantly shareable via public links, QR codes, or embed codes without requiring an Odoo login. The Odoo Form Builder Odoo module includes a dashboard for managing form submissions, exporting data (CSV), and tracking performance with regional analytics. Essential features like email notifications and real-time styling ensure a smooth, integrated data collection experience within Odoo. Odoo Form Builder | Form Builder | Odoo Online Form Creator | Odoo Website Form | Contact Form for Odoo | Feedback Form | Survey Form | Registration Form | Application Form | Drag and Drop Form Builder | No-Code Form Builder | Odoo Form Designer | Dynamic Form Builder | Custom Form Builder for Odoo | Responsive Form Builder | Public Form Builder | QR Code Form Sharing | Embed Form in Website | Form Analytics Dashboard | Form Response Management | Email Notification Forms | Data Collection Form | Odoo Form Customization | Odoo Form Creator Module | Odoo Website Form Tool | | Odoo Form Integration | Smart Form Builder | Field Configuration Form Builder | Odoo Form Automation | Online Submission Form | Odoo Website Data Form',
    'description': "The Odoo Form Builder Odoo app is the essential solution for effortless digital data collection and surveying, fully integrated with your Odoo instance. Empowering users with a no-code form designer, it's perfect for gathering feedback, managing registrations, and conducting internal surveys. Key features include dynamic field configuration, customizable vertical/horizontal layouts, and options for setting form availability and response limits. Beyond creation, the Odoo Form Builder Odoo module offers robust tools for response management, including the ability to export data and gain insights through visual analytics. The real-time style editor allows quick branding adjustments (colors, fonts), ensuring all your custom forms are fully responsive and professional. This simplifies workflows, provides actionable data, and enhances collaboration across your organization.",
    "company": "Zehntech Technologies Inc.",
    'category': 'Productivity, Tools, Extra Tools',
    "maintainer": "Zehntech Technologies Inc.",
    "contributor": "Zehntech Technologies Inc.",
    'website': 'https://www.zehntech.com/',
    'support': 'odoo-support@zehntech.com',
    'depends': ['base','web','mail',],
    "live_test_url": "https://zehntechodoo.com/app_name=zehntech_form_builder/app_version=18.0",
    'assets': {
        'web.assets_frontend': [
            'zehntech_form_builder/static/src/css/response_page.css',
        ],
    },
    "images": [
        "static/description/banner.gif"
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/field_config_wizard_views.xml',
        'views/form_builder_views.xml',
        'views/menu.xml',
        'views/form_preview_template.xml',
        'views/public_form_template.xml',
        'views/thank_you.xml',
        'views/form_response_table_template.xml',
        'views/form_expired_template.xml',
        'views/form_error_template.xml',
        
    ],
    'license': 'OPL-1',
    'application': True,
    'installable': True,
    'auto_install': False,
    "price": 60.00,
    "currency": "USD"
}
