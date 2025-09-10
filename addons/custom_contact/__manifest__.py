{
    "name": "Contacts – Hide Org/Membership tabs by type",
    "version": "1.0",
    "depends": [
        "contacts",
        # also depend on the modules that ADD the tabs so our view loads after them:
        # e.g. "membership" (or "association") for the Membership tab,
        # and your custom module that adds "Rotary Org Info"
        # "membership",
        # "your_rotary_module",
    ],
    "data": ["views/res_partner_form.xml"],
    "installable": True,
}
