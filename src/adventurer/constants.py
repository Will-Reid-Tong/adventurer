"""Shared app-layer constants.

``schema.sql`` is the single source of truth for the data model and its
constraints. These constants mirror the same allowed values so the application
layer (validation, templates, upload checks) agrees with the schema without
scattering literals.
"""

from __future__ import annotations

# pages.type CHECK (schema.sql)
PAGE_TYPES = ("choice", "chance", "ending")
ALLOWED_PAGE_TYPES = frozenset(PAGE_TYPES)

# Sentinel value used by the admin forms to mean "create a placeholder
# ending page and point this option at it". The dropdowns expose it as
# ``(blank page)`` so the operator can build options before their targets
# exist.
BLANK_TARGET = "blank"
BLANK_PAGE_TITLE = "(blank)"

# options.weight CHECK plus the chance sum-to-100 rule (schema.sql / Issue #8)
MIN_WEIGHT = 0
MAX_WEIGHT = 100
WEIGHT_TOTAL = 100

# images content types and size cap (Issue #5)
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
ALLOWED_IMAGE_TYPES = frozenset(IMAGE_TYPES)
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Validation messages shared by the admin routes.
ERR_INVALID_PAGE_TYPE = "invalid type"
ERR_ENDING_OPTIONS = "ending pages cannot have options"
ERR_TARGET_REQUIRED = "target_page_id is required"
ERR_TARGET_INTEGER = "target_page_id must be an integer"
ERR_LABEL_REQUIRED = "label is required"
ERR_CHOICE_WEIGHT = "weight must be empty for choice options"
ERR_WEIGHT_REQUIRED = "weight is required for chance options"
ERR_WEIGHT_INTEGER = "weight must be an integer"
ERR_WEIGHT_RANGE = "weight must be between 0 and 100"
ERR_WEIGHT_SUM = "chance page weights must sum to exactly 100"
ERR_IMAGE_REQUIRED = "an image file is required"
ERR_IMAGE_TYPE = "unsupported image type"
ERR_IMAGE_SIZE = "image must be 5 MB or smaller"
