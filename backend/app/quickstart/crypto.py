"""Envelope encryption for credentials the operator pastes into the web UI.

Quickstart persists provider API keys so a redeploy on an ephemeral filesystem
does not lose them. Those rows live in the same database as everything else, so
they are encrypted at rest whenever a secret is available.

The secret comes from ``DEER_FLOW_QUICKSTART_SECRET`` (or ``BETTER_AUTH_SECRET``
as a fallback, which one-click templates already generate). Without one,
credentials are stored as plaintext and a warning is logged once - that keeps a
bare ``docker compose up`` working rather than failing closed on a missing env
var, which is the whole point of this fork.

Decryption never raises: a ciphertext that cannot be opened (rotated secret,
restored backup) is reported as ``None`` so the UI shows the provider as
"needs a key again" instead of the Gateway failing to boot.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENCRYPTED_PREFIX = "enc:v1:"
_SECRET_ENV_VARS = ("DEER_FLOW_QUICKSTART_SECRET", "BETTER_AUTH_SECRET")

_warned_plaintext = False


def _secret() -> str | None:
    for name in _SECRET_ENV_VARS:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _fernet() -> Fernet | None:
    global _warned_plaintext
    secret = _secret()
    if not secret:
        if not _warned_plaintext:
            _warned_plaintext = True
            logger.warning(
                "No DEER_FLOW_QUICKSTART_SECRET (or BETTER_AUTH_SECRET) set; quickstart provider credentials are stored unencrypted. Set one to encrypt them at rest.",
            )
        return None
    # A plain SHA-256 of the secret is a deterministic 32-byte key, which is what
    # Fernet wants. No salt on purpose: the same secret must open the same rows
    # on every replica and after every restart, and there is no per-row context
    # to bind to.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt(value: str | None) -> str | None:
    """Encrypt a credential for storage; returns plaintext when no secret is set."""
    if value is None or value == "":
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    return _ENCRYPTED_PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """Decrypt a stored credential. Returns ``None`` when it cannot be opened."""
    if value is None or value == "":
        return value
    if not value.startswith(_ENCRYPTED_PREFIX):
        # Written before a secret was configured, or by an operator editing the
        # row by hand. Pass it through unchanged.
        return value
    fernet = _fernet()
    if fernet is None:
        logger.warning("Stored credential is encrypted but no secret is configured; treating it as missing.")
        return None
    try:
        return fernet.decrypt(value[len(_ENCRYPTED_PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("Stored credential could not be decrypted with the current secret; treating it as missing.")
        return None


def mask(value: str | None) -> str | None:
    """Render a credential for display: last four characters, nothing else."""
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * 8}{value[-4:]}"
