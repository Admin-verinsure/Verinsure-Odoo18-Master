# -*- coding: utf-8 -*-
from . import models
from . import wizard
from .models.akahu_credential import _read_or_create_file_key


def post_init_hook(cr, registry):
	"""Create the Akahu key file at module install time.

	This fails fast on filesystem permission issues instead of delaying
	key creation until the first credential/token operation.
	"""
	_read_or_create_file_key()
