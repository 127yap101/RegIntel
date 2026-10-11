"""Sanitized authentication failures; never attach secrets or database diagnostics."""


class InvalidAuthentication(Exception):
    """Credentials or bearer token are not valid."""


class AuthUnavailable(Exception):
    """Authentication cannot safely access its configured authority."""


class SeedConflict(Exception):
    """Existing accounts conflict with the explicitly selected seed configuration."""
