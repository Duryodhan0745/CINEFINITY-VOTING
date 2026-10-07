import hmac
import os
import secrets
import hashlib
import time
from collections import defaultdict, deque
from functools import wraps

from flask import (Flask, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import SERVER_TIMESTAMP, Increment
from werkzeug.exceptions import HTTPException

from utils.firebase import get_bucket, get_db
from utils.helpers import CATEGORIES, MAX_PER_CATEGORY, SIGNATURES, validate_image

IS_PROD = bool(os.environ.get("RENDER"))

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
    query = col.where("active", "==", True) if active_only else col
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
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


def fail(message, code):
    return jsonify(ok=False, error=message), code


# ---------- public ----------

@app.get("/")
def index():
    return render_template("index.html", status=get_status(), labels=list(CATEGORIES.values()))


@app.get("/vote")
def vote():
    status = get_status()
    groups = group_by_category(fetch_contestants(active_only=True))
    resp = make_response(render_template("vote.html", groups=groups, status=status))
    token = request.cookies.get("voter_token")
    if not token:
        resp.set_cookie("voter_token", secrets.token_urlsafe(32), max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax", secure=IS_PROD)
    return resp


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


@app.get("/confirmation")
def confirmation():
    return render_template("confirmation.html")


@app.get("/results")
def results():
    return render_template("results.html")


@app.get("/api/results")
def api_results():
    status = get_status()
    tallies = fetch_tallies()
    contestants = fetch_contestants(active_only=True)
    categories = []
    for key, label in CATEGORIES.items():
        items = [{"id": c["id"], "name": c.get("name", ""), "votes": int(tallies.get(key, {}).get(c["id"], 0))}
                 for c in contestants if c.get("category") == key]
        winner, tie = None, False
        if status == "closed" and items:
            top = max(i["votes"] for i in items)
            leaders = [i for i in items if i["votes"] == top]
            tie = len(leaders) > 1
            winner = None if tie else leaders[0]["name"]
        categories.append({"key": key, "label": label, "items": items, "winner": winner, "tie": tie})
    return jsonify(status=status, ballots=int(tallies.get("ballots", 0)), categories=categories)


# ---------- admin ----------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if rate_limited(f"login:{request.remote_addr}", 5, 300):
            flash("Too many attempts. Please wait a few minutes.")
        else:
            expected = os.environ.get("ADMIN_PASSWORD", "")
            given = request.form.get("password", "")
            if expected and hmac.compare_digest(given.encode(), expected.encode()):
                session.clear()
                session["admin"] = True
                return redirect(url_for("admin_dashboard"))
            flash("Incorrect password.")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    tallies = fetch_tallies()
    ballots = int(tallies.get("ballots", 0))
    return render_template(
        "admin.html",
        groups=group_by_category(fetch_contestants()),
        categories=CATEGORIES,
        status=get_status(),
        ballots=ballots,
        total_votes=ballots * len(CATEGORIES),
        max_per=MAX_PER_CATEGORY,
    )


@app.post("/admin/voting")
@admin_required
def admin_voting():
    action = request.form.get("action")
    if action not in ("start", "stop"):
        flash("Unknown action.")
    else:
        get_db().collection("settings").document("event").set(
            {"voting_status": "active" if action == "start" else "closed", "event_name": "CINEFINITY 2026"},
            merge=True)
        flash("Voting is now " + ("ACTIVE." if action == "start" else "CLOSED."))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/contestant/new")
@admin_required
def admin_new_contestant():
    category = request.form.get("category")
    db = get_db()
    if category not in CATEGORIES:
        flash("Invalid category.")
    else:
        existing = list(db.collection("contestants").where("category", "==", category).stream())
        if len(existing) >= MAX_PER_CATEGORY:
            flash(f"{CATEGORIES[category]} already has {MAX_PER_CATEGORY} contestants.")
        else:
            db.collection("contestants").add({
                "name": "New contestant", "category": category, "photo_url": "",
                "display_order": len(existing) + 1, "active": False,
            })
            flash("Contestant added. Edit the name and photo below.")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/contestant/<cid>")
@admin_required
def admin_update_contestant(cid):
    ref = get_db().collection("contestants").document(cid)
    if not ref.get().exists:
        flash("Contestant not found.")
        return redirect(url_for("admin_dashboard"))

    name = (request.form.get("name") or "").strip()[:60]
    category = request.form.get("category")
    if not name or category not in CATEGORIES:
        flash("A name and a valid category are required.")
        return redirect(url_for("admin_dashboard"))
    try:
        order = max(1, min(99, int(request.form.get("display_order", 1))))
    except ValueError:
        order = 1

    data = {"name": name, "category": category, "display_order": order,
            "active": request.form.get("active") == "on"}

    photo = request.files.get("photo")
    if photo and photo.filename:
        problem = validate_image(photo)
        if problem:
            flash(problem)
            return redirect(url_for("admin_dashboard"))
        ext = SIGNATURES[photo.mimetype][1]
        blob = get_bucket().blob(f"contestants/{cid}-{secrets.token_hex(4)}.{ext}")
        blob.upload_from_file(photo.stream, content_type=photo.mimetype)
        blob.make_public()
        data["photo_url"] = blob.public_url

    ref.update(data)
    flash(f"Saved {name}.")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/reset")
@admin_required
def admin_reset():
    if get_status() == "active":
        flash("Stop voting before resetting votes.")
        return redirect(url_for("admin_dashboard"))
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
    flash("All votes have been reset.")
    return redirect(url_for("admin_dashboard"))


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
