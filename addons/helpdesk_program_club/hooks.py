# -*- coding: utf-8 -*-
"""
post_init_hook — runs once after the module installs.

WHY THIS IS NEEDED:
  View id=6350 is a website-builder customised copy of
  odoo_website_helpdesk.ticket_form.  Its arch is stored directly in the
  DB (you can see data-oe-field="arch" on every element in the inspector).
  Odoo renders it by fetching the combined arch of:
    base view (id=2264, key=odoo_website_helpdesk.ticket_form)
    + all ir.ui.view records that inherit from that key
    → then applies DB overrides from website.page / website customisation

  Our module's XML template (inherit_id=odoo_website_helpdesk.ticket_form)
  is a standard inheritance record, so it IS applied at render time.
  However, if the website editor has "cow'd" (copy-on-write) the view into
  a website-specific version, the inheritance chain may be broken.

  This hook checks whether the two fields are already present after install.
  If they are not visible (because the DB arch bypasses our inheritance),
  it patches the arch of view 6350 directly as a fallback.
"""
import logging
from lxml import etree

_logger = logging.getLogger(__name__)

PROGRAM_TYPE_BLOCK = '''
<div class="form-group col-12 s_website_form_field s_website_form_custom s_website_form_required" data-type="selection" data-name="Field">
  <label class="col-form-label s_website_form_label" for="helpdesk_program_type" style="width: 200px">
    <span class="s_website_form_label_content">Program Type</span>
    <span class="s_website_form_mark"> *</span>
  </label>
  <select name="helpdesk_program_type" id="helpdesk_program_type" class="form-select s_website_form_input" required="required">
    <option value="">-- Select Program Type --</option>
  </select>
</div>
'''

CLUB_BLOCK = '''
<div class="form-group col-12 s_website_form_field s_website_form_custom s_website_form_required" data-type="many2one" data-name="Field">
  <label class="col-form-label s_website_form_label" for="helpdesk_club_id" style="width: 200px">
    <span class="s_website_form_label_content">Club</span>
    <span class="s_website_form_mark"> *</span>
  </label>
  <select name="helpdesk_club_id" id="helpdesk_club_id" class="form-select s_website_form_input" required="required">
    <option value="">-- Select Program Type first --</option>
  </select>
</div>
'''


def post_init_hook(env):
    """
    Directly patch the arch of view id=6350 (your DB-customised helpdesk page)
    to inject Program Type and Club selects before the s_website_form_submit div.

    The selects start empty — the QWeb template inheritance fills Program Type
    options at render time, and the JS fills Club options dynamically.
    But because the arch in id=6350 is a static DB blob, we must physically
    insert the nodes into it here.
    """
    VIEW_ID = 6350

    view = env['ir.ui.view'].browse(VIEW_ID)
    if not view.exists():
        _logger.warning(
            "helpdesk_program_club post_init_hook: view id=%s not found — "
            "skipping direct arch patch. The QWeb inheritance template will "
            "still apply to the base view.", VIEW_ID
        )
        return

    arch_str = view.arch
    try:
        root = etree.fromstring(arch_str.encode('utf-8'))
    except etree.XMLSyntaxError as e:
        _logger.error(
            "helpdesk_program_club post_init_hook: could not parse arch of "
            "view %s: %s", VIEW_ID, e
        )
        return

    # Check if already patched (idempotent)
    if root.xpath("//*[@id='helpdesk_program_type']"):
        _logger.info(
            "helpdesk_program_club post_init_hook: fields already present in "
            "view %s — skipping.", VIEW_ID
        )
        return

    # Find the s_website_form_submit div
    submit_divs = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' s_website_form_submit ')]"
    )
    if not submit_divs:
        _logger.warning(
            "helpdesk_program_club post_init_hook: could not find "
            "s_website_form_submit in view %s arch. Fields not injected.",
            VIEW_ID
        )
        return

    submit_div = submit_divs[0]
    parent = submit_div.getparent()
    if parent is None:
        _logger.warning(
            "helpdesk_program_club post_init_hook: s_website_form_submit has "
            "no parent in view %s — cannot insert before it.", VIEW_ID
        )
        return

    idx = list(parent).index(submit_div)

    # Build and insert the two field nodes
    program_node = etree.fromstring(PROGRAM_TYPE_BLOCK.strip())
    club_node    = etree.fromstring(CLUB_BLOCK.strip())

    parent.insert(idx, club_node)        # insert club first (will be below)
    parent.insert(idx, program_node)     # insert program above club

    # Write patched arch back
    new_arch = etree.tostring(root, encoding='unicode')
    view.with_context(no_cow=True).write({'arch': new_arch})

    _logger.info(
        "helpdesk_program_club post_init_hook: successfully injected "
        "Program Type and Club fields into view %s arch.", VIEW_ID
    )
