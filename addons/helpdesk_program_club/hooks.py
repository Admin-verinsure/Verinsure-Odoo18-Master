# -*- coding: utf-8 -*-
"""
post_init_hook — patches view id=6350 arch directly.

The arch is a DB-stored QWeb blob for the ticket.helpdesk form.
We physically insert Program Type and Club <select> nodes before
the s_website_form_submit div inside s_website_form_rows.
"""
import logging
from lxml import etree

_logger = logging.getLogger(__name__)

# Match the exact field structure used in the existing arch
PROGRAM_TYPE_BLOCK = '''\
<div class="form-group col-12 s_website_form_field s_website_form_custom s_website_form_required" data-type="char" data-name="Field">
  <div class="row s_col_no_resize s_col_no_bgcolor">
    <label class="col-form-label col-sm-auto s_website_form_label" style="width: 200px" for="helpdesk_program_type">
      <span class="s_website_form_label_content">Program Type</span>
      <span class="s_website_form_mark"> *</span>
    </label>
    <div class="col-sm">
      <select id="helpdesk_program_type" name="helpdesk_program_type" class="form-control s_website_form_input" required="">
        <option value="">-- Select Program Type --</option>
      </select>
    </div>
  </div>
  <br/>
</div>'''

CLUB_BLOCK = '''\
<div class="form-group col-12 s_website_form_field s_website_form_custom s_website_form_required" data-type="char" data-name="Field">
  <div class="row s_col_no_resize s_col_no_bgcolor">
    <label class="col-form-label col-sm-auto s_website_form_label" style="width: 200px" for="helpdesk_club_id">
      <span class="s_website_form_label_content">Club</span>
      <span class="s_website_form_mark"> *</span>
    </label>
    <div class="col-sm">
      <select id="helpdesk_club_id" name="helpdesk_club_id" class="form-control s_website_form_input" required="">
        <option value="">-- Select Program Type first --</option>
      </select>
    </div>
  </div>
  <br/>
</div>'''


def post_init_hook(env):
    VIEW_ID = 6350

    view = env['ir.ui.view'].browse(VIEW_ID)
    if not view.exists():
        _logger.error("post_init_hook: view %s not found", VIEW_ID)
        return

    # Already patched?
    if 'helpdesk_program_type' in view.arch:
        _logger.info("post_init_hook: fields already present, skipping")
        return

    # Parse — must wrap in a root tag because the arch starts with <t …>
    try:
        root = etree.fromstring(view.arch.encode('utf-8'))
    except etree.XMLSyntaxError as e:
        _logger.error("post_init_hook: XML parse error: %s", e)
        return

    # Find the s_website_form_rows div — parent of all field divs
    rows_divs = root.xpath(
        ".//div[contains(@class,'s_website_form_rows')]"
    )
    if not rows_divs:
        _logger.error("post_init_hook: s_website_form_rows not found in arch")
        return
    rows_div = rows_divs[0]

    # Find the submit div inside it
    submit_divs = rows_div.xpath(
        "./div[contains(@class,'s_website_form_submit')]"
    )
    if not submit_divs:
        _logger.error("post_init_hook: s_website_form_submit not found inside s_website_form_rows")
        return
    submit_div = submit_divs[0]

    idx = list(rows_div).index(submit_div)

    # Parse and insert — club first so program type ends up above it
    club_node    = etree.fromstring(CLUB_BLOCK)
    program_node = etree.fromstring(PROGRAM_TYPE_BLOCK)

    rows_div.insert(idx, club_node)
    rows_div.insert(idx, program_node)

    new_arch = etree.tostring(root, encoding='unicode')
    view.with_context(no_cow=True).write({'arch': new_arch})

    _logger.info(
        "post_init_hook: Program Type + Club fields injected into view %s", VIEW_ID
    )
