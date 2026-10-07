# CINEFINITY 2026 — Freshers voting

Flask + Firestore + Firebase Storage. Pages: `/` (landing), `/vote` (QR target), `/admin` (password), `/results` (projector).

## 1. Firebase setup
1. Create a project at console.firebase.google.com.
2. **Firestore Database** → Create database (production mode).
3. **Storage** → Get started. In the Storage rules/bucket settings, allow public reads for `contestants/` (photos are shown on the vote page). Make sure uniform bucket-level access is off so `make_public()` works.
4. Project settings → Service accounts → **Generate new private key**. Keep this file secret.

## 2. Environment variables
Copy `.env.example` to `.env` (never commit it). Set `FLASK_SECRET_KEY` (long random string — required so sessions and duplicate-vote hashes stay stable across restarts), `ADMIN_PASSWORD`, `FIREBASE_STORAGE_BUCKET`, and either `FIREBASE_CREDENTIALS_JSON` (on Render) or `FIREBASE_CREDENTIALS_PATH` (locally).

## 3. Run locally
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)   # or set the variables manually
python app.py                          # http://127.0.0.1:5000
```

## 4. Deploy on Render
- New → Web Service → connect this repo.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app` (also in `Procfile`)
- Add the environment variables above. For `FIREBASE_CREDENTIALS_JSON`, paste the full service-account JSON on one line.
- Render sets `RENDER` automatically, which turns on secure cookies.

## 5. Event day
1. Log in at `/admin/login`. Under **Contestants**, click **+ Add Contestant** (3 per category), then fill in name, category, order, and upload a photo for each. Tick **Enabled** when ready.
2. Test voting on your phone at `/vote`, then reset votes from the admin page.
3. Click **START VOTING** when ready.
4. Generate a QR code pointing to `https://YOUR-DOMAIN/vote` (any QR generator). Do not link it to `/results`.
5. Open `/results` on the projector computer.
6. Click **STOP VOTING**. Winners appear on `/results`.

Do not change a contestant's category after voting has started; existing votes are tied to the old category.

## Checklist
- [ ] Add 12 contestants  - [ ] Upload 12 photos  - [ ] Check names
- [ ] Test voting  - [ ] Start voting  - [ ] Display QR
- [ ] Open /results on projector  - [ ] Stop voting  - [ ] Confirm winners

## Notes and limits
- Duplicate protection uses a cookie token. It stops casual double-voting from the same browser, not determined users. Votes are stored under a hash of the token (one vote doc per token).
- Rate limiting is in memory per Gunicorn worker. It is basic, not a distributed limit.
- Image checks are type and size only; photos are not re-compressed.
