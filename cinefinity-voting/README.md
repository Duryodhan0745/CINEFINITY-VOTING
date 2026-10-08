# CINEFINITY 2026 — Freshers Voting (Unified Single-Page App)

Flask + Cloud Firestore + Firebase Storage.
The entire public experience is a **Single-Page Application (SPA)** hosted at `/`.

- **Root Route `/`**: Landing & voting page in one seamless view. QR codes point directly to `https://YOUR-DOMAIN/`.
- **Public Flow**: Visual Header → BOLLYWOOD "Lights ★ Camera ★ Fun" → 4 Categories → 12 Contestant Cards → Single-click Submit → In-page confirmation modal (no redirects).
- **Subtle Admin Access**: Discrete `Admin ↗` button in top corner opens login modal without disrupting normal voters.
- **Admin Dashboard**: SPA overlay for managing contestants, uploading headshots, starting/stopping voting, and resetting votes.
- **Live Results (Projector View)**: Fullscreen auditorium projector mode with live auto-refreshing animated bars every 2.5s and `[ ← BACK TO ADMIN ]` return button.

## 1. Firebase Setup
1. Create a project at console.firebase.google.com.
2. **Firestore Database** → Create database (production mode).
3. **Storage** → Get started (bucket name e.g. `<project-id>.firebasestorage.app`).
4. Project settings → Service accounts → **Generate new private key** → save as `serviceAccountKey.json` in project root.

## 2. Environment Variables & Setup
Run the automated setup tool:
```
python setup_firebase.py
```
This automatically verifies Firestore, checks Cloud Storage, seeds default collections, and generates your `.env` configuration.

## 3. Run Locally
```
python app.py       # http://127.0.0.1:5000
```

## 4. Deploy on Render
The Flask server runs on Render; Firebase provides Firestore and Storage. The
repository stores the app in the `cinefinity-voting` subdirectory.

- **Root Directory:** `cinefinity-voting`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --workers 2 --threads 4 --timeout 60`
- **Python version:** `3.13.5`
- **Health Check Path:** `/health`

Set these in the Render service's environment settings. Never commit their
values or the service-account key:

- `FLASK_SECRET_KEY`: a long random value (at least 32 characters).
- `ADMIN_PASSWORD`: a strong, unique admin password.
- `FIREBASE_STORAGE_BUCKET`: the exact bucket name shown in Firebase.
- `FIREBASE_CREDENTIALS_JSON`: the complete service-account JSON, or use a
  Render Secret File and set `FIREBASE_CREDENTIALS_PATH` to its mounted path.

The app refuses to start on Render if required secrets or Firebase
configuration are missing. `/health` checks that the web process is responding;
it does not make a Firebase connectivity check.

## 5. Event Day Flow
1. Open `http://YOUR-DOMAIN/` and click the discrete `Admin ↗` button in the top corner.
2. Log in with your admin password.
3. Under **Contestants**, click **+ Add Contestant** (3 per category: Mr Freshers, Mrs Freshers, Mr Stylist, Mrs Stylist). Set names, upload photos, and toggle **Enabled on ballot**.
4. Test voting on mobile at `http://YOUR-DOMAIN/`, then click **Reset All Votes** from the admin panel if needed.
5. Click **START VOTING**.
6. Generate and project a QR code pointing directly to `https://YOUR-DOMAIN/`.
7. Click **Live Results ↗** to open the full-screen projector view for the auditorium screen.
8. When voting ends, click **STOP VOTING**. Winners or ties will automatically be announced on the projector display.
