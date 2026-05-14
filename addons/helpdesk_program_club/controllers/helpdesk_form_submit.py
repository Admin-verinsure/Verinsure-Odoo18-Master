# -*- coding: utf-8 -*-
# controllers/helpdesk_form_submit.py
#
# SAFE: No controller inheritance. The club field is captured entirely
# at the model layer (models/helpdesk_ticket.py create/write overrides).
# Odoo's base website-helpdesk controller forwards all POST kwargs into
# ticket.create(), so our model override is sufficient.
