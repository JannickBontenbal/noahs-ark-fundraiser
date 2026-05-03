import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session
from supabase import Client, create_client

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")


def supabase_admin() -> Client:
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    return create_client(SUPABASE_URL, key)


def has_supabase_config() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def has_admin_config() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def admin_required():
    if not session.get("admin"):
        return jsonify({"error": "Niet ingelogd."}), 401
    return None


@app.get("/")
@app.get("/index.html")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/admin")
@app.get("/admin.html")
def admin_page():
    return send_from_directory(BASE_DIR, "admin.html")


@app.get("/config.js")
def config_js():
    config = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_ANON_KEY": SUPABASE_KEY,
        "SUPABASE_PUBLISHABLE_KEY": SUPABASE_KEY,
        "SUPABASE_SERVICE_KEY": "",
        "ADMIN_API_URL": os.environ.get("ADMIN_API_URL", ""),
        "ADMIN_PASSWORD_HASH": "",
        "GOAL_EUR": int(os.environ.get("GOAL_EUR", "10000")),
        "TARGET_DATE": os.environ.get("TARGET_DATE", "2026-02-01"),
        "IBAN": os.environ.get("IBAN", "[IBAN invullen]"),
        "IBAN_NAME": os.environ.get("IBAN_NAME", "Stichting [naam invullen]"),
        "TIKKIE_URL": os.environ.get("TIKKIE_URL", "[Tikkie link invullen]"),
    }
    body = "window.NAF_CONFIG = " + json.dumps(config, ensure_ascii=True) + ";\n"
    return Response(body, mimetype="application/javascript")


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    password = str(payload.get("password", ""))

    if not ADMIN_PASSWORD_HASH:
        return jsonify({"error": "ADMIN_PASSWORD_HASH ontbreekt in .env."}), 500

    if password_hash(password) != ADMIN_PASSWORD_HASH.lower():
        return jsonify({"error": "Wachtwoord klopt niet."}), 401

    session["admin"] = True
    return jsonify({"ok": True})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/donations")
def list_donations():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_supabase_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("donations")
        .select("id, amount, donor_name, note, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return jsonify({"donations": response.data or []})


@app.post("/api/donations")
def add_donation():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    payload = request.get_json(silent=True) or {}
    amount = payload.get("amount")

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Bedrag is ongeldig."}), 400

    if amount <= 0:
        return jsonify({"error": "Bedrag moet groter zijn dan 0."}), 400

    row = {
        "amount": amount,
        "donor_name": payload.get("donor_name") or None,
        "note": payload.get("note") or None,
    }
    response = supabase_admin().table("donations").insert(row).execute()
    return jsonify({"donation": response.data[0] if response.data else row}), 201


@app.delete("/api/donations/<donation_id>")
def delete_donation(donation_id):
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    supabase_admin().table("donations").delete().eq("id", donation_id).execute()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
