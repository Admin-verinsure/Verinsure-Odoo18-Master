# -*- coding: utf-8 -*-
"""
post_init_hook:
  1. Patches website form arch (view 6350) — injects Program Type + Club selects
     if not already present (idempotent).
  2. Patches backend form view (id=2253) — adds club_id field after email field.
"""
import logging
from lxml import etree

_logger = logging.getLogger(__name__)

# ── HTML blocks to inject into website form arch ─────────────────────────────

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


def _patch_website_form(env):
    """Inject Program Type + Club selects into website form arch (view 6350)."""
    view = env['ir.ui.view'].browse(6350)
    if not view.exists():
        _logger.warning("post_init_hook: website form view 6350 not found")
        return

    if 'helpdesk_program_type' in view.arch:
        _logger.info("post_init_hook: website form already patched, skipping")
        return

    try:
        root = etree.fromstring(view.arch.encode('utf-8'))
        rows_div = root.xpath(".//div[contains(@class,'s_website_form_rows')]")[0]
        submit_div = rows_div.xpath("./div[contains(@class,'s_website_form_submit')]")[0]
        idx = list(rows_div).index(submit_div)
        rows_div.insert(idx, etree.fromstring(CLUB_BLOCK))
        rows_div.insert(idx, etree.fromstring(PROGRAM_TYPE_BLOCK))
        view.with_context(no_cow=True).write({'arch': etree.tostring(root, encoding='unicode')})
        _logger.info("post_init_hook: website form patched successfully")
    except Exception as e:
        _logger.exception("post_init_hook: website form patch failed: %s", e)


def _patch_backend_form(env):
    """Add club_id field after email in the backend ticket form (view 2253)."""
    view = env['ir.ui.view'].browse(2253)
    if not view.exists():
        _logger.warning("post_init_hook: backend form view 2253 not found")
        return

    if 'club_id' in view.arch:
        _logger.info("post_init_hook: backend form already has club_id, skipping")
        return

    try:
        root = etree.fromstring(view.arch.encode('utf-8'))

        # Find the email field node
        email_fields = root.xpath(".//field[@name='email']")
        if not email_fields:
            _logger.warning("post_init_hook: email field not found in backend form arch")
            return

        email_field = email_fields[0]
        parent = email_field.getparent()
        idx = list(parent).index(email_field)

        # Build: <field name="club_id" string="Club" readonly="1"/>
        club_field = etree.Element('field')
        club_field.set('name', 'club_id')
        club_field.set('string', 'Club')
        club_field.set('readonly', '1')

        parent.insert(idx + 1, club_field)

        view.with_context(no_cow=True).write({'arch': etree.tostring(root, encoding='unicode')})
        _logger.info("post_init_hook: backend form patched with club_id field")
    except Exception as e:
        _logger.exception("post_init_hook: backend form patch failed: %s", e)


def post_init_hook(env):
    _patch_website_form(env)
    _patch_backend_form(env)
