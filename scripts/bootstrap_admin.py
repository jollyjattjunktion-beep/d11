"""Run once on the Windows server: python -m scripts.bootstrap_admin."""
import base64
import hashlib
import secrets
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE, override=False)

existing = (ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else "")
if "ADMIN_PASSWORD_HASH=" in existing or "ADMIN_SESSION_SECRET=" in existing:
    raise SystemExit("Admin password/session already configured. Refusing to overwrite it.")

password = secrets.token_urlsafe(18)
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
encoded = base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()
session_secret = secrets.token_urlsafe(48)

with ENV_FILE.open("a", encoding="utf-8", newline="\n") as handle:
    if existing and not existing.endswith(("\n", "\r")):
        handle.write("\n")
    handle.write("ADMIN_USERNAME=admin\n")
    handle.write("ADMIN_PASSWORD_HASH=" + encoded + "\n")
    handle.write("ADMIN_SESSION_SECRET=" + session_secret + "\n")

print("\nD11 ADMIN LOGIN CREATED")
print("Login ID: admin")
print("One-time password: " + password)
print("\nSave this password in a password manager. It will not be displayed again.")
print("The password is stored as a scrypt hash in .env; the session secret is stored privately.")
