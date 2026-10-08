# CINEFINITY Voting

CINEFINITY Voting is a Flask web application backed by Firebase Cloud
Firestore and Firebase Storage. Flask serves the voting and admin single-page
application, and provides the voting, contestant-management, and live-results
APIs.

## Local development

Use Python 3.13 and install the project dependencies from this directory:

```text
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set `FLASK_SECRET_KEY`,
`ADMIN_PASSWORD`, and `FIREBASE_STORAGE_BUCKET` to local values. For Firebase
credentials, either set `FIREBASE_CREDENTIALS_JSON` to the service-account
JSON or set `FIREBASE_CREDENTIALS_PATH` to a local key file. The default
local key path is `./serviceAccountKey.json`.

Start the Flask development server:

```text
python app.py
```

The application is available at `http://127.0.0.1:5000`. Never commit `.env`
or a Firebase service-account key. The optional `setup_firebase.py` helper
checks Firebase connectivity and may create the initial event and tally
documents if they do not exist; run it only against the Firebase project you
intend to initialize.

## Render deployment

Create a Render **Web Service** connected to this repository and configure:

- **Root Directory:** `cinefinity-voting`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --workers 2 --threads 4 --timeout 60`
- **Health Check Path:** `/health`
- **Python version:** `3.13.5`

Set these environment variables in Render:

- `FLASK_SECRET_KEY` — a long, random secret.
- `ADMIN_PASSWORD` — a strong, unique admin password.
- `FIREBASE_STORAGE_BUCKET` — the exact Firebase Storage bucket name.
- `FIREBASE_CREDENTIALS_JSON` — the complete Firebase service-account JSON.

Alternatively, store the key as a Render Secret File and set
`FIREBASE_CREDENTIALS_PATH` to its mounted path. Do not commit credentials,
private keys, or production `.env` files to GitHub. The `/health` endpoint
confirms that the web process is responding; it does not test Firebase
connectivity.

## Tests

Run the isolated contestant-editor unit tests with:

```text
python -m unittest -v test_realtime
```

`test_smoke.py` performs read-only checks against the configured Firebase
project. `test_integration.py` changes voting state, submits ballots, and
resets votes; run it only against an isolated test Firebase project, never
against production.
