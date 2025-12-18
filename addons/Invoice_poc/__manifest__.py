# -*- coding: utf-8 -*-
{
    "name": "Invoice POC",
    "summary": "Store payload, create & post customer invoice",
    "version": "18.0.1.0.1",
    "author": "Your Team",
    "license": "LGPL-3",
    "depends": ["base", "account"],
    "data": [
        "data/email_template.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
}
