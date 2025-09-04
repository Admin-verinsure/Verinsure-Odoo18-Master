{
    "name": "N4P Custom Invoice Header (Bold)",
    "summary": "Override only the header of web.external_layout_bold; keep standard report body.",
    "version": "1.0.0",
    "author": "You",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "views/external_layout_bold_header_patch.xml",
    ],
    "installable": True,
    "application": False,
}
