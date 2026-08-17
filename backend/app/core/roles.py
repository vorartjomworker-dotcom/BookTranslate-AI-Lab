"""Centralized RBAC role definitions.

Role capabilities (see README Authentication & Roles section for the full matrix):
- viewer: read-only access to books/chapters/segments/jobs/quality/benchmarks.
- editor: viewer permissions plus create/update on books/chapters/segments,
  manual translation edits, running translation jobs and QA checks.
- admin: editor permissions plus destructive operations (delete) and benchmark
  run administration.
"""

from __future__ import annotations

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

ALL_ROLES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER)

# Roles allowed to perform editor-level write operations (create/update, run jobs/QA).
EDITOR_ROLES = (ROLE_ADMIN, ROLE_EDITOR)

# Roles allowed to perform destructive/administrative operations.
ADMIN_ROLES = (ROLE_ADMIN,)
