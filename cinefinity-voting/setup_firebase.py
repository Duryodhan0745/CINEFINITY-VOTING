"""Firebase Setup & Verification Script for CINEFINITY Voting.

This script checks credentials, creates the .env configuration, tests
Firestore and Cloud Storage connectivity, and initializes required collections.
"""

import json
import os
import secrets
import shutil
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

# Try to load existing .env
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

CATEGORIES = {
    "mr_freshers": "Mr Freshers",
    "mrs_freshers": "Mrs Freshers",
    "mr_stylist": "Mr Stylist",
    "mrs_stylist": "Mrs Stylist",
}


def find_service_account():
    # 1. Check configured path
    env_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.is_file():
            return p

    # 2. Check standard locations
    candidates = [
        BASE_DIR / "serviceAccountKey.json",
        ROOT_DIR / "serviceAccountKey.json",
    ]
    for c in candidates:
        if c.is_file():
            return c

    # 3. Search for any downloaded firebase service account json
    for folder in [BASE_DIR, ROOT_DIR]:
        for f in folder.glob("*.json"):
            if f.name in ("package.json", "package-lock.json", "tsconfig.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("type") == "service_account" and "project_id" in data:
                    target = BASE_DIR / "serviceAccountKey.json"
                    if f != target:
                        print(f"[*] Detected service account key at '{f.name}'. Copying to 'serviceAccountKey.json'...")
                        shutil.copy2(f, target)
                    return target
            except Exception:
                continue

    return None


def create_or_update_env(project_id=None):
    env_file = BASE_DIR / ".env"
    existing_vars = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing_vars[k.strip()] = v.strip()

    secret_key = existing_vars.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
    admin_pw = existing_vars.get("ADMIN_PASSWORD") or secrets.token_urlsafe(24)
    cred_path = existing_vars.get("FIREBASE_CREDENTIALS_PATH") or "./serviceAccountKey.json"

    # Default bucket name based on project_id if not set
    bucket = existing_vars.get("FIREBASE_STORAGE_BUCKET")
    if not bucket or "your-project-id" in bucket:
        if project_id:
            # Modern Firebase projects use .firebasestorage.app; older use .appspot.com
            bucket = f"{project_id}.firebasestorage.app"
        else:
            bucket = "your-project-id.firebasestorage.app"

    content = f"""# Cinefinity Voting Environment Configuration
FLASK_SECRET_KEY={secret_key}
ADMIN_PASSWORD={admin_pw}

# Firebase Configuration
FIREBASE_CREDENTIALS_PATH={cred_path}
FIREBASE_STORAGE_BUCKET={bucket}
"""
    env_file.write_text(content, encoding="utf-8")
    print(f"[+] Environment file ready at: {env_file}")
    return existing_vars


def main():
    print("=" * 60)
    print("   CINEFINITY 2026 — FIREBASE SETUP & HEALTH CHECK")
    print("=" * 60)

    key_path = find_service_account()

    if not key_path:
        print("\n[!] Service account key file (serviceAccountKey.json) was NOT found.")
        print("\nPlease follow these 4 quick steps in Firebase Console:")
        print("  1. Open Firebase Console: https://console.firebase.google.com")
        print("  2. Create a new project (e.g., 'cinefinity-voting') or select existing.")
        print("  3. Enable services:")
        print("     - Firestore Database: Build -> Firestore Database -> Create database (production mode).")
        print("     - Storage: Build -> Storage -> Get started.")
        print("  4. Download your Service Account Key:")
        print("     - Go to Project Settings (gear icon) -> 'Service accounts' tab.")
        print("     - Click 'Generate new private key' -> confirm.")
        print(f"     - Save the downloaded .json file to:")
        print(f"       {BASE_DIR / 'serviceAccountKey.json'}\n")
        print("  Then run this script again: python setup_firebase.py\n")

        # Create placeholder .env anyway
        create_or_update_env()
        return 1

    # Key is present!
    try:
        key_data = json.loads(key_path.read_text(encoding="utf-8"))
        project_id = key_data.get("project_id")
        client_email = key_data.get("client_email")
        print(f"[+] Found Service Account Key for Project: '{project_id}'")
        print(f"    Service Email: {client_email}")
    except Exception as e:
        print(f"[!] Error reading '{key_path}': {e}")
        return 1

    # Update .env with project_id
    create_or_update_env(project_id)

    # Initialize Firebase Admin
    print("\n[*] Initializing Firebase Admin SDK...")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
    except ImportError:
        print("[!] Missing dependencies. Please run:")
        print("    pip install -r requirements.txt")
        return 1

    # Reload environment to pick up updated .env
    if "dotenv" in sys.modules:
        load_dotenv(BASE_DIR / ".env", override=True)

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET") or f"{project_id}.firebasestorage.app"

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
        db = firestore.client()
        print("[+] Firestore connected successfully!")
    except Exception as e:
        print(f"[!] Firestore connection failed: {e}")
        print("    Ensure Firestore Database is created in your Firebase Console.")
        return 1

    # Check and initialize default documents
    print("\n[*] Checking initial Firestore documents...")
    try:
        event_ref = db.collection("settings").document("event")
        event_doc = event_ref.get()
        if not event_doc.exists:
            event_ref.set({
                "event_name": "CINEFINITY 2026",
                "voting_status": "closed",
            })
            print("[+] Initialized settings/event document (status: closed).")
        else:
            print(f"[+] settings/event document exists (status: {event_doc.to_dict().get('voting_status')}).")

        tallies_ref = db.collection("tallies").document("current")
        tallies_doc = tallies_ref.get()
        if not tallies_doc.exists:
            tallies_ref.set({
                "ballots": 0,
                **{k: {} for k in CATEGORIES},
            })
            print("[+] Initialized tallies/current document.")
        else:
            print(f"[+] tallies/current document exists (ballots: {tallies_doc.to_dict().get('ballots', 0)}).")
    except Exception as e:
        print(f"[!] Error initializing Firestore documents: {e}")
        return 1

    # Check Storage Bucket
    print(f"\n[*] Checking Firebase Storage bucket '{bucket_name}'...")
    try:
        bucket = storage.bucket()
        # Test bucket accessibility
        if bucket.exists():
            print(f"[+] Storage bucket '{bucket_name}' exists and is accessible!")
        else:
            # Maybe modern vs legacy bucket suffix
            alt_bucket = f"{project_id}.appspot.com"
            print(f"[-] Bucket '{bucket_name}' not found. Checking alternate '{alt_bucket}'...")
            alt_b = storage.bucket(alt_bucket)
            if alt_b.exists():
                print(f"[+] Storage bucket '{alt_bucket}' exists and is accessible!")
                # Update .env
                env_path = BASE_DIR / ".env"
                txt = env_path.read_text(encoding="utf-8")
                txt = txt.replace(bucket_name, alt_bucket)
                env_path.write_text(txt, encoding="utf-8")
                print(f"[+] Updated .env with bucket: {alt_bucket}")
            else:
                print(f"[!] Storage bucket not initialized yet.")
                print(f"    Go to Firebase Console -> Build -> Storage -> Get started.")
    except Exception as e:
        print(f"[!] Storage check note: {e}")
        print("    If Storage is not yet enabled, click 'Get started' under Build -> Storage in Firebase Console.")

    print("\n" + "=" * 60)
    print("   FIREBASE SETUP CHECK COMPLETE")
    print("=" * 60)
    print("To start the app:")
    print("  python app.py")
    print("Admin login: /admin/login (password from .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
