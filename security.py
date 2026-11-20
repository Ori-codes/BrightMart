"""Password hashing helpers (passwords are never stored as plain text)."""
import hashlib
import hmac
import os

_ITERATIONS = 100_000


def hash_password(password: str, salt: bytes = None) -> str:
    """Return 'salt$hash' (both hex) using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored 'salt$hash' string."""
    try:
        salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return hmac.compare_digest(digest.hex(), hash_hex)
