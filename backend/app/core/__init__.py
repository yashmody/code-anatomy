"""Shared infrastructure for the modular monolith.

Holds config, db, models, auth, encryption, plus seams (security, cache, deps,
users, roles). No domain logic lives here — modules import from core, never
the reverse.
"""
