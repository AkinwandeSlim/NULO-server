# Mint an internal JWT for ANY user (incl. Google OAuth users, who have no password).
# Uses the app's own JWT_SECRET_KEY -- validated by get_current_user PATH 2 fallback.
# Usage:
#   ./venv/Scripts/python.exe scripts/mint_test_jwt.py --list
#   ./venv/Scripts/python.exe scripts/mint_test_jwt.py --email someone@gmail.com
#   ./venv/Scripts/python.exe scripts/mint_test_jwt.py --id <user_uuid>
# Rule 17: ASCII only.

import argparse
import json
import os
import subprocess
import sys
import time

# Load .env so JWT_SECRET_KEY / SUPABASE_* are available
for _line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        k, _, v = _line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from jose import jwt  # noqa: E402

SECRET = os.environ["JWT_SECRET_KEY"]
ALG = os.environ.get("JWT_ALGORITHM", "HS256")
TTL_MIN = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", 1440))

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ["SUPABASE_KEY"]
)


def sb_get(path_and_query):
    """GET Supabase REST via curl (Schannel + --ssl-no-revoke) to sidestep the
    local TLS-inspecting proxy that breaks Python's OpenSSL verification."""
    url = f"{SUPABASE_URL}/rest/v1/{path_and_query}"
    out = subprocess.run(
        ["curl", "-s", "--ssl-no-revoke", "-m", "20",
         "-H", f"apikey: {SERVICE_KEY}",
         "-H", f"Authorization: Bearer {SERVICE_KEY}",
         url],
        capture_output=True, text=True,
    ).stdout
    try:
        return json.loads(out)
    except Exception:
        print("Supabase REST error:", out[:300])
        return []


def list_users():
    rows = sb_get("users?select=id,email,user_type,full_name,auth_provider"
                  "&order=created_at.desc&limit=40")
    print(f"{'user_type':10} {'auth':8} {'email':32} id")
    print("-" * 96)
    for r in rows:
        print(f"{(r.get('user_type') or '?'):10} {(r.get('auth_provider') or '?'):8} "
              f"{(r.get('email') or '')[:32]:32} {r.get('id')}")


def mint(user):
    now = int(time.time())
    payload = {
        "sub": user["id"],          # PATH 2 reads sub -> users.id
        "user_id": user["id"],      # belt-and-suspenders
        "email": user.get("email"),
        "user_type": user.get("user_type"),
        "iat": now,
        "exp": now + TTL_MIN * 60,
    }
    token = jwt.encode(payload, SECRET, algorithm=ALG)
    print("=== minted JWT ===")
    print("user :", user.get("email"), "|", user.get("user_type"), "|", user["id"])
    print("ttl  :", TTL_MIN, "min")
    print("\n" + token + "\n")
    print("Paste into Thunder Client env var jwt / landlordJwt (no 'Bearer ' prefix).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--email")
    ap.add_argument("--id")
    a = ap.parse_args()

    if a.list or not (a.email or a.id):
        list_users()
        if not (a.email or a.id):
            print("\nRe-run with --email <email> or --id <uuid> to mint.")
        return

    q = ("users?select=id,email,user_type,full_name&"
         + (f"email=eq.{a.email}" if a.email else f"id=eq.{a.id}"))
    rows = sb_get(q)
    if not rows:
        print("No user found for", a.email or a.id)
        sys.exit(1)
    mint(rows[0])


if __name__ == "__main__":
    main()
