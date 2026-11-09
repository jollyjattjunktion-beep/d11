"""Small, dependency-free admin password and persistent-session helpers."""
import base64
import hashlib
import hmac
import secrets
import time

COOKIE_NAME = "d11_admin_session"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_text, digest_text = encoded.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def issue_session(username: str, secret: str) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(12)
    payload = f"{username}|{expires}|{nonce}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def verify_session(cookie: str | None, secret: str, expected_username: str = "admin") -> bool:
    if not cookie or "." not in cookie or not secret:
        return False
    try:
        payload_part, signature_part = cookie.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)).decode()
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        username, expires_text, _nonce = payload.split("|", 2)
        return (
            hmac.compare_digest(signature, expected)
            and hmac.compare_digest(username, expected_username)
            and int(expires_text) > int(time.time())
        )
    except Exception:
        return False
