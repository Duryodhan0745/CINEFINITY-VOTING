import json
import os

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
            cred = credentials.Certificate(os.environ["FIREBASE_CREDENTIALS_PATH"])
        firebase_admin.initialize_app(cred, {"storageBucket": os.environ["FIREBASE_STORAGE_BUCKET"]})
        _initialized = True


def get_db():
    _init()
    return fb_firestore.client()


def get_bucket():
    _init()
    return storage.bucket()
