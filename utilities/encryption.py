"""
Optional at-rest encryption for pipeline result files.

Gated behind ``ENCRYPT_RESULTS=true`` env var.  Uses Fernet (AES-128-CBC +
HMAC-SHA256) from the ``cryptography`` library for symmetric encryption.

Key sourced from ``ENCRYPTION_KEY`` env var or auto-generated and persisted
to ``.kyc_key`` (which should be gitignored).
"""

from __future__ import annotations

import os
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)

_KEY_FILE = Path(__file__).resolve().parent.parent / ".kyc_key"


def encryption_enabled() -> bool:
    """Return True if at-rest encryption is turned on."""
    return os.environ.get("ENCRYPT_RESULTS", "").lower() in ("true", "1", "yes")


def _get_or_create_key() -> bytes:
    """Retrieve the Fernet key from env or keyfile, creating if necessary."""
    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()

    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()

    # Auto-generate
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package required for encryption — pip install cryptography"
        ) from exc

    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    # Restrict permissions — owner-only read/write
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        # On Windows, POSIX chmod is a no-op.  Use icacls to restrict access.
        import getpass
        import subprocess
        try:
            user = getpass.getuser()
            subprocess.run(
                ["icacls", str(_KEY_FILE), "/inheritance:r",
                 "/grant:r", f"{user}:(R,W)"],
                capture_output=True, check=True,
            )
        except Exception:
            logger.warning(
                "Could not restrict permissions on %s — ensure this file "
                "is not readable by other users", _KEY_FILE,
            )
    logger.info("Generated new encryption key at %s", _KEY_FILE)
    return key


def encrypt_file(path: Path | str) -> None:
    """Encrypt *path* in place using Fernet.  A ``.enc`` suffix is appended."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package required for encryption — pip install cryptography"
        ) from exc

    path = Path(path)
    key = _get_or_create_key()
    f = Fernet(key)
    plaintext = path.read_bytes()
    ciphertext = f.encrypt(plaintext)
    enc_path = path.with_suffix(path.suffix + ".enc")
    # Write encrypted file atomically, then remove plaintext.
    # Use try/finally to ensure we don't leave plaintext on disk if unlink
    # fails (e.g. file locked on Windows).
    from utilities.file_ops import atomic_write_bytes
    atomic_write_bytes(enc_path, ciphertext)
    try:
        path.unlink()
    except OSError as exc:
        # Encrypted copy exists but plaintext could not be removed.
        # Remove the encrypted copy to avoid ambiguity, then re-raise.
        enc_path.unlink(missing_ok=True)
        raise OSError(
            f"Could not remove plaintext {path} after encryption — "
            f"encrypted copy rolled back for safety: {exc}"
        ) from exc


def decrypt_file(path: Path | str) -> bytes:
    """Decrypt *path* (must end in ``.enc``) and return plaintext bytes."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package required for encryption — pip install cryptography"
        ) from exc

    path = Path(path)
    key = _get_or_create_key()
    f = Fernet(key)
    ciphertext = path.read_bytes()
    return f.decrypt(ciphertext)
