import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore, storage

_initialized = False


def _init():
    global _initialized
    if not _initialized:
        raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        else:
            cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "./serviceAccountKey.json")
            p = Path(cred_path)
            if not p.is_absolute() and not p.exists():
                alt_p = Path(__file__).resolve().parent.parent / cred_path
                if alt_p.exists():
                    cred_path = str(alt_p)
            if not os.path.exists(cred_path):
                raise FileNotFoundError(
                    f"Firebase credentials not found at '{cred_path}'. "
                    "Please download your service account key from Firebase Console and save it as 'serviceAccountKey.json', "
                    "or set FIREBASE_CREDENTIALS_PATH / FIREBASE_CREDENTIALS_JSON in .env."
                )
            cred = credentials.Certificate(cred_path)

        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
        options = {}
        if bucket_name:
            options["storageBucket"] = bucket_name
        firebase_admin.initialize_app(cred, options)
        _initialized = True


def get_db():
    _init()
    return fb_firestore.client()


def get_bucket():
    _init()
    return storage.bucket()
