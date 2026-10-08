import hmac
import os
import secrets
import hashlib
import time
from collections import defaultdict, deque
from functools import wraps

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import (Flask, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import SERVER_TIMESTAMP, Increment, FieldFilter
from werkzeug.exceptions import HTTPException

from utils.firebase import get_bucket, get_db
from utils.helpers import CATEGORIES, MAX_PER_CATEGORY, SIGNATURES, validate_image

IS_PROD = bool(os.environ.get("RENDER"))

if IS_PROD:
    missing_config = [
        name for name in ("FLASK_SECRET_KEY", "ADMIN_PASSWORD", "FIREBASE_STORAGE_BUCKET")
        if not os.environ.get(name)
    ]
    credentials_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "./serviceAccountKey.json")
    if not os.environ.get("FIREBASE_CREDENTIALS_JSON") and not os.path.isfile(credentials_path):
        missing_config.append("FIREBASE_CREDENTIALS_JSON or FIREBASE_CREDENTIALS_PATH")
    if missing_config:
        raise RuntimeError(
            "Missing required production configuration: " + ", ".join(missing_config)
        )

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
)
_hits = defaultdict(deque)


def rate_limited(key, limit, window=60):
    """In-memory sliding-window limiter (per process)."""
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def get_status():
    snap = get_db().collection("settings").document("event").get()
    return (snap.to_dict() or {}).get("voting_status", "closed")


def fetch_contestants(active_only=False):
    col = get_db().collection("contestants")
    query = col.where(filter=FieldFilter("active", "==", True)) if active_only else col
    items = [{"id": d.id, **d.to_dict()} for d in query.stream()]
    items.sort(key=lambda c: (c.get("display_order", 0), c.get("name", "")))
    return items


def fetch_tallies():
    return get_db().collection("tallies").document("current").get().to_dict() or {}


def group_by_category(items):
    return [{"key": k, "label": v, "items": [c for c in items if c.get("category") == k]}
            for k, v in CATEGORIES.items()]


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            if request.is_json or request.path.startswith("/api/") or request.headers.get("Accept") == "application/json":
                return fail("Admin login required.", 401)
            return redirect(url_for("index") + "#admin")
        return view(*args, **kwargs)
    return wrapper


def fail(message, code):
    return jsonify(ok=False, error=message), code


# ---------- public (SPA) ----------

@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/")
def index():
    status = get_status()
    contestants = fetch_contestants(active_only=True)
    groups = group_by_category(contestants)
    is_admin = bool(session.get("admin"))

    admin_groups = []
    ballots = 0
    total_votes = 0
    if is_admin:
        all_contestants = fetch_contestants(active_only=False)
        admin_groups = group_by_category(all_contestants)
        tallies = fetch_tallies()
        ballots = int(tallies.get("ballots", 0))
        total_votes = ballots * len(CATEGORIES)

    resp = make_response(render_template(
        "index.html",
        status=status,
        groups=groups,
        categories=CATEGORIES,
        max_per=MAX_PER_CATEGORY,
        is_admin=is_admin,
        admin_groups=admin_groups,
        ballots=ballots,
        total_votes=total_votes,
    ))
    token = request.cookies.get("voter_token")
    if not token:
        resp.set_cookie("voter_token", secrets.token_urlsafe(32), max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax", secure=IS_PROD)
    return resp


# Legacy route redirects to root SPA
@app.get("/vote")
def legacy_vote():
    return redirect(url_for("index"))


@app.get("/confirmation")
def legacy_confirmation():
    return redirect(url_for("index") + "#confirmation")


@app.get("/results")
def legacy_results():
    return redirect(url_for("index") + "#results")


@app.get("/admin")
def legacy_admin():
    return redirect(url_for("index") + "#admin")


@app.post("/vote/submit")
def vote_submit():
    if rate_limited(f"vote:{request.remote_addr}", 10):
        return fail("Too many attempts. Please wait a minute and try again.", 429)
    if get_status() != "active":
        return fail("Voting is currently closed.", 403)

    body = request.get_json(silent=True) or {}
    selections = body.get("selections")
    if not isinstance(selections, dict) or set(selections) != set(CATEGORIES):
        return fail("Please pick one contestant in every category.", 400)

    db = get_db()
    valid = {c["id"]: c for c in fetch_contestants(active_only=True)}
    chosen = {}
    for category, cid in selections.items():
        contestant = valid.get(cid) if isinstance(cid, str) else None
        if not contestant or contestant.get("category") != category:
            return fail("One of your selections is no longer valid. Please refresh and try again.", 400)
        chosen[category] = cid

    token = request.cookies.get("voter_token")
    is_new = not token
    if is_new:
        token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # One batch: the vote doc id is the token hash, so a second create() fails atomically.
    batch = db.batch()
    batch.create(db.collection("votes").document(token_hash), {
        "voter_token_hash": token_hash, **chosen, "created_at": SERVER_TIMESTAMP,
    })
    batch.set(db.collection("tallies").document("current"), {
        "ballots": Increment(1),
        **{cat: {cid: Increment(1)} for cat, cid in chosen.items()},
    }, merge=True)
    try:
        batch.commit()
    except AlreadyExists:
        return fail("Your vote has already been recorded.", 409)

    resp = jsonify(ok=True)
    if is_new:
        resp.set_cookie("voter_token", token, max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax", secure=IS_PROD)
    return resp


@app.get("/api/results")
def api_results():
    status = get_status()
    tallies = fetch_tallies()
    contestants = fetch_contestants(active_only=False)
    categories = []
    for key, label in CATEGORIES.items():
        items = [
            {
                "id": c["id"],
                "name": c.get("name", ""),
                "photo_url": c.get("photo_url", ""),
                "category": c.get("category", key),
                "active": bool(c.get("active")),
                "display_order": int(c.get("display_order", 0)),
                "votes": int(tallies.get(key, {}).get(c["id"], 0)),
            }
            for c in contestants if c.get("category") == key
        ]
        winner, tie, leader, leader_tie = None, False, None, False
        if items:
            top = max(i["votes"] for i in items)
            leaders = [i for i in items if i["votes"] == top]
            leader_tie = status == "active" and top > 0 and len(leaders) > 1
            if status == "closed" and top > 0:
                tie = len(leaders) > 1
                winner = None if tie else leaders[0]["name"]
            leader = leaders[0] if top > 0 and not leader_tie else None
        categories.append({"key": key, "label": label, "items": items,
                           "winner": winner, "tie": tie, "leader": leader,
                           "leader_tie": leader_tie})
    return jsonify(status=status, ballots=int(tallies.get("ballots", 0)), categories=categories)


# ---------- admin & admin APIs ----------

@app.route("/admin/login", methods=["GET", "POST"])
@app.post("/api/admin/login")
def admin_login():
    if request.method == "POST":
        if rate_limited(f"login:{request.remote_addr}", 10, 300):
            if request.is_json or request.path.startswith("/api/"):
                return fail("Too many attempts. Please wait a few minutes.", 429)
            flash("Too many attempts. Please wait a few minutes.")
            return redirect(url_for("index") + "#admin")

        expected = os.environ.get("ADMIN_PASSWORD", "")
        data = request.get_json(silent=True) or request.form
        given = data.get("password", "")
        if expected and hmac.compare_digest(given.encode(), expected.encode()):
            session.clear()
            session["admin"] = True
            if request.is_json or request.path.startswith("/api/"):
                return jsonify(ok=True)
            return redirect(url_for("index") + "#admin")

        if request.is_json or request.path.startswith("/api/"):
            return fail("Incorrect password.", 401)
        flash("Incorrect password.")
        return redirect(url_for("index") + "#admin")
    return redirect(url_for("index") + "#admin")


@app.route("/admin/logout", methods=["GET", "POST"])
@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    if request.is_json or request.path.startswith("/api/"):
        return jsonify(ok=True)
    return redirect(url_for("index"))


@app.get("/api/admin/data")
@admin_required
def api_admin_data():
    tallies = fetch_tallies()
    ballots = int(tallies.get("ballots", 0))
    contestants = fetch_contestants(active_only=False)
    return jsonify(
        ok=True,
        status=get_status(),
        ballots=ballots,
        total_votes=ballots * len(CATEGORIES),
        groups=group_by_category(contestants),
        categories=CATEGORIES,
        max_per=MAX_PER_CATEGORY,
    )


@app.post("/admin/voting")
@app.post("/api/admin/voting")
@admin_required
def admin_voting():
    action = (request.get_json(silent=True) or {}).get("action") or request.form.get("action")
    if action not in ("start", "stop"):
        return fail("Unknown action.", 400)
    new_status = "active" if action == "start" else "closed"
    get_db().collection("settings").document("event").set(
        {"voting_status": new_status, "event_name": "CINEFINITY 2026"},
        merge=True)
    if request.is_json or request.path.startswith("/api/"):
        return jsonify(ok=True, status=new_status)
    flash("Voting is now " + ("ACTIVE." if action == "start" else "CLOSED."))
    return redirect(url_for("index") + "#admin")


@app.post("/admin/contestant/new")
@app.post("/api/admin/contestant/new")
@admin_required
def admin_new_contestant():
    if get_status() == "active":
        return fail("Stop voting before adding contestants.", 400)
    category = (request.get_json(silent=True) or {}).get("category") or request.form.get("category")
    db = get_db()
    if category not in CATEGORIES:
        return fail("Invalid category.", 400)
    existing = list(db.collection("contestants").where(filter=FieldFilter("category", "==", category)).stream())
    if len(existing) >= MAX_PER_CATEGORY:
        return fail(f"{CATEGORIES[category]} already has {MAX_PER_CATEGORY} contestants.", 400)
    doc_ref = db.collection("contestants").add({
        "name": "New contestant", "category": category, "photo_url": "",
        "display_order": len(existing) + 1, "active": False,
    })
    cid = doc_ref[1].id
    if request.is_json or request.path.startswith("/api/"):
        return jsonify(ok=True, id=cid)
    flash("Contestant added. Edit the name and photo below.")
    return redirect(url_for("index") + "#admin")


@app.post("/admin/contestant/<cid>")
@app.post("/api/admin/contestant/<cid>")
@admin_required
def admin_update_contestant(cid):
    ref = get_db().collection("contestants").document(cid)
    snapshot = ref.get()
    if not snapshot.exists:
        if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
            return fail("Contestant not found.", 404)
        flash("Contestant not found.")
        return redirect(url_for("index") + "#admin")

    current = snapshot.to_dict() or {}
    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or current.get("name", "")).strip()[:60]
    status = get_status()
    active_voting = status == "active"
    category = payload.get("category", current.get("category"))
    order_raw = payload.get("display_order", current.get("display_order", 1))
    try:
        order = max(1, min(99, int(order_raw)))
    except (TypeError, ValueError):
        order = 1

    if not name or category not in CATEGORIES:
        if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
            return fail("A name and a valid category are required.", 400)
        flash("A name and a valid category are required.")
        return redirect(url_for("index") + "#admin")

    active_raw = payload.get(
        "active",
        current.get("active", False) if active_voting else False,
    )
    active = active_raw in ("on", "true", "1", True)
    if active_voting:
        structural_changes = (
            category != current.get("category")
            or order != int(current.get("display_order", 1))
            or active != bool(current.get("active"))
        )
        if structural_changes:
            return fail(
                "Category, display order and ballot status are locked while voting is active.",
                400,
            )

    data = {"name": name}
    if not active_voting:
        data.update(category=category, display_order=order, active=active)

    photo = request.files.get("photo")
    photo_blob = None
    if photo and photo.filename:
        problem = validate_image(photo)
        if problem:
            if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
                return fail(problem, 400)
            flash(problem)
            return redirect(url_for("index") + "#admin")
        ext = SIGNATURES[photo.mimetype][1]
        photo_blob = get_bucket().blob(f"contestants/{cid}-{secrets.token_hex(4)}.{ext}")
        photo_blob.upload_from_file(photo.stream, content_type=photo.mimetype)
        try:
            photo_blob.make_public()
            data["photo_url"] = photo_blob.public_url
        except Exception:
            # Fallback when uniform bucket-level access is enabled:
            token = secrets.token_urlsafe(32)
            photo_blob.metadata = {"firebaseStorageDownloadTokens": token}
            photo_blob.patch()
            from urllib.parse import quote
            data["photo_url"] = (
                f"https://firebasestorage.googleapis.com/v0/b/{photo_blob.bucket.name}/o/"
                f"{quote(photo_blob.name, safe='')}?alt=media&token={token}"
            )
        data["photo_storage_path"] = photo_blob.name

    # Recheck before writing in case voting started while an image was uploading.
    if get_status() == "active" and (
        category != current.get("category")
        or order != int(current.get("display_order", 1))
        or active != bool(current.get("active"))
    ):
        if photo_blob:
            photo_blob.delete()
        return fail(
            "Category, display order and ballot status are locked while voting is active.",
            400,
        )

    try:
        ref.update(data)
    except Exception:
        if photo_blob:
            try:
                photo_blob.delete()
            except Exception:
                app.logger.exception("Failed to clean up an uncommitted contestant photo")
        raise

    old_photo_path = current.get("photo_storage_path")
    if photo_blob and old_photo_path and old_photo_path.startswith("contestants/"):
        try:
            get_bucket().blob(old_photo_path).delete()
        except Exception:
            app.logger.exception("Failed to remove the replaced contestant photo")

    if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
        return jsonify(ok=True, data=data, id=cid)
    flash(f"Saved {name}.")
    return redirect(url_for("index") + "#admin")


@app.post("/admin/contestant/<cid>/delete")
@app.post("/api/admin/contestant/<cid>/delete")
@admin_required
def admin_delete_contestant(cid):
    if get_status() == "active":
        return fail("Stop voting before deleting contestants.", 400)
    ref = get_db().collection("contestants").document(cid)
    if not ref.get().exists:
        if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
            return fail("Contestant not found.", 404)
        flash("Contestant not found.")
        return redirect(url_for("index") + "#admin")
    ref.delete()
    if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
        return jsonify(ok=True)
    flash("Contestant removed.")
    return redirect(url_for("index") + "#admin")


@app.post("/admin/reset")
@app.post("/api/admin/reset")
@admin_required
def admin_reset():
    if get_status() == "active":
        if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
            return fail("Stop voting before resetting votes.", 400)
        flash("Stop voting before resetting votes.")
        return redirect(url_for("index") + "#admin")
    db = get_db()
    while True:
        docs = list(db.collection("votes").limit(400).stream())
        if not docs:
            break
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    db.collection("tallies").document("current").set({"ballots": 0, **{k: {} for k in CATEGORIES}})
    if request.is_json or request.path.startswith("/api/") or request.headers.get("X-Requested-With"):
        return jsonify(ok=True)
    flash("All votes have been reset.")
    return redirect(url_for("index") + "#admin")


# ---------- errors ----------

@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unhandled error")
    if request.path.startswith("/vote/submit") or request.path.startswith("/api/"):
        return fail("Something went wrong on our side. Please try again.", 500)
    return render_template("error.html", message="Something went wrong on our side. Please try again in a moment."), 500


if __name__ == "__main__":
    app.run(debug=False)
