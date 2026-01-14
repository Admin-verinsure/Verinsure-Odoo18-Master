{
    "name": "Insurance Documents",
    "version": "18.0.1.0.6",
    "category": "Insurance",
    "summary": "Insurance-only documents (global + per policy)",
    "depends": ["base", "mail", "insurance_management_cybro"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/insurance_documents_views.xml"
    ],
    "installable": True,
    "application": False
}