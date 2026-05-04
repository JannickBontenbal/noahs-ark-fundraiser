import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session
import stripe
from supabase import Client, create_client

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
DEFAULT_ACTIONS = [
    {
        "title": "Sponsorloop",
        "description": "Leerlingen laten zich sponsoren per ronde en verzamelen zo direct donaties voor de reis en het project.",
        "status_label": "Status",
        "status": "Actief",
        "tags": ["Loopt nu", "Schoolactie"],
        "variant": "featured",
    },
    {
        "title": "Actiemarkt",
        "description": "Een middag met kleine verkoopacties, eten, drinken en creatieve manieren om geld op te halen.",
        "status_label": "Status",
        "status": "In voorbereiding",
        "tags": ["Binnenkort", "Samen"],
        "variant": "coral",
    },
    {
        "title": "Flessenactie",
        "description": "Statiegeldflessen worden ingezameld en omgezet in concrete steun voor Noah's Ark.",
        "status_label": "Impact",
        "status": "Elk bonnetje telt",
        "tags": ["Loopt nu"],
        "variant": "",
    },
    {
        "title": "Persoonlijke sponsors",
        "description": "Familie, vrienden en bekenden kunnen leerlingen persoonlijk sponsoren of direct bijdragen aan het gezamenlijke doel.",
        "status_label": "Status",
        "status": "Open",
        "tags": ["Doorlopend"],
        "variant": "",
    },
    {
        "title": "Lokale verkoop",
        "description": "Kleine verkoopacties in de buurt en op school maken het makkelijk om laagdrempelig mee te doen.",
        "status_label": "Status",
        "status": "Wordt gepland",
        "tags": ["Team"],
        "variant": "",
    },
]

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_FEE_CENTS = int(os.environ.get("STRIPE_FEE_CENTS", "50"))

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")


def load_settings():
    """Load settings from file or environment variables."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_settings(settings):
    """Save settings to file."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except IOError:
        return False


def get_setting(key, default=None):
    """Get a setting value, checking file first then environment."""
    settings = load_settings()
    if key in settings:
        return settings[key]
    return os.environ.get(key, default)


def normalize_actions(value):
    """Return a compact, safe actions list for config/admin use."""
    if not isinstance(value, list):
        return DEFAULT_ACTIONS

    actions = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        if not title and not description:
            continue

        raw_tags = item.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [tag.strip() for tag in raw_tags.split(",")]
        if not isinstance(raw_tags, list):
            raw_tags = []

        variant = str(item.get("variant", "")).strip()
        if variant not in {"featured", "coral"}:
            variant = ""

        actions.append({
            "title": title or "Nieuwe actie",
            "description": description,
            "status_label": str(item.get("status_label", "Status")).strip() or "Status",
            "status": str(item.get("status", "")).strip() or "Open",
            "tags": [str(tag).strip() for tag in raw_tags if str(tag).strip()][:4],
            "variant": variant,
        })

    return actions or DEFAULT_ACTIONS


def supabase_admin() -> Client:
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    return create_client(SUPABASE_URL, key)


def has_supabase_config() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def has_admin_config() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def has_stripe_config() -> bool:
    return bool(STRIPE_SECRET_KEY)


def site_url() -> str:
    configured = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return request.host_url.rstrip("/")


def euros_to_cents(value) -> int:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Bedrag is ongeldig.")

    cents = int(round(amount * 100))
    if cents < 100:
        raise ValueError("Bedrag moet minimaal €1 zijn.")
    if cents > 500000:
        raise ValueError("Bedrag mag maximaal €5.000 zijn.")
    return cents


def donation_from_checkout_session(session_id: str):
    if not has_stripe_config():
        raise RuntimeError("STRIPE_SECRET_KEY ontbreekt in .env.")
    if not has_admin_config():
        raise RuntimeError("SUPABASE_SERVICE_KEY ontbreekt in .env.")

    checkout_session = stripe.checkout.Session.retrieve(session_id)
    if checkout_session.get("payment_status") != "paid":
        return {"inserted": False, "status": checkout_session.get("payment_status") or "unpaid"}

    existing = (
        supabase_admin()
        .table("donations")
        .select("id")
        .eq("stripe_session_id", checkout_session.id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"inserted": False, "status": "already_recorded"}

    metadata = checkout_session.get("metadata") or {}
    customer_details = checkout_session.get("customer_details") or {}
    donor_name = metadata.get("donor_name") or customer_details.get("name") or None
    note = metadata.get("note") or None
    try:
        donation_cents = int(metadata.get("donation_amount_cents") or 0)
    except (TypeError, ValueError):
        donation_cents = 0
    amount = (donation_cents or checkout_session.get("amount_total") or 0) / 100
    payment_intent = checkout_session.get("payment_intent")

    row = {
        "amount": amount,
        "donor_name": donor_name,
        "note": note,
        "stripe_session_id": checkout_session.id,
        "stripe_payment_intent": payment_intent,
    }
    supabase_admin().table("donations").insert(row).execute()
    return {"inserted": True, "status": "paid"}


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
        "GOAL_EUR": int(get_setting("GOAL_EUR", "10000")),
        "TARGET_DATE": get_setting("TARGET_DATE", "2027-02-01"),
        "IBAN": get_setting("IBAN", "[IBAN invullen]"),
        "IBAN_NAME": get_setting("IBAN_NAME", "Stichting [naam invullen]"),
        "TIKKIE_URL": get_setting("TIKKIE_URL", "[Tikkie link invullen]"),
        "ACTIONS": normalize_actions(get_setting("ACTIONS", DEFAULT_ACTIONS)),
        "STRIPE_PUBLISHABLE_KEY": STRIPE_PUBLISHABLE_KEY,
        "STRIPE_ENABLED": has_stripe_config(),
        "STRIPE_FEE_CENTS": STRIPE_FEE_CENTS,
    }
    body = "window.NAF_CONFIG = " + json.dumps(config, ensure_ascii=True) + ";\n"
    return Response(body, mimetype="application/javascript")


@app.get("/favicon.svg")
def favicon():
    return send_from_directory(BASE_DIR, "favicon.svg")


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


@app.get("/api/settings")
def get_settings():
    blocked = admin_required()
    if blocked:
        return blocked
    
    settings = load_settings()
    return jsonify({
        "GOAL_EUR": int(settings.get("GOAL_EUR", os.environ.get("GOAL_EUR", "10000"))),
        "IBAN": settings.get("IBAN", os.environ.get("IBAN", "[IBAN invullen]")),
        "IBAN_NAME": settings.get("IBAN_NAME", os.environ.get("IBAN_NAME", "Stichting [naam invullen]")),
        "TIKKIE_URL": settings.get("TIKKIE_URL", os.environ.get("TIKKIE_URL", "[Tikkie link invullen]")),
        "ACTIONS": normalize_actions(settings.get("ACTIONS", DEFAULT_ACTIONS)),
    })


@app.post("/api/settings")
def update_settings():
    blocked = admin_required()
    if blocked:
        return blocked
    
    payload = request.get_json(silent=True) or {}
    
    settings = load_settings()
    settings.update({
        "GOAL_EUR": str(payload.get("GOAL_EUR", settings.get("GOAL_EUR", "10000"))),
        "IBAN": payload.get("IBAN", settings.get("IBAN", "")),
        "IBAN_NAME": payload.get("IBAN_NAME", settings.get("IBAN_NAME", "")),
        "TIKKIE_URL": payload.get("TIKKIE_URL", settings.get("TIKKIE_URL", "")),
        "ACTIONS": normalize_actions(payload.get("ACTIONS", settings.get("ACTIONS", DEFAULT_ACTIONS))),
    })
    
    if save_settings(settings):
        return jsonify({"ok": True})
    else:
        return jsonify({"error": "Kon instellingen niet opslaan."}), 500


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


@app.post("/api/stripe/checkout-session")
def create_stripe_checkout_session():
    if not has_stripe_config():
        return jsonify({"error": "STRIPE_SECRET_KEY ontbreekt in .env."}), 500

    payload = request.get_json(silent=True) or {}
    try:
        cents = euros_to_cents(payload.get("amount"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    if not bool(payload.get("cover_fees")):
        return jsonify({"error": "Ga akkoord met de Stripe betaalkosten om door te gaan."}), 400

    donor_name = str(payload.get("donor_name") or "").strip()[:120]
    note = str(payload.get("note") or "").strip()[:500]
    base_url = site_url()
    line_items = [{
        "price_data": {
            "currency": "eur",
            "product_data": {
                "name": "Donatie Noah's Ark Uganda",
                "description": "Guido de Bres fundraiser",
            },
            "unit_amount": cents,
        },
        "quantity": 1,
    }]
    if STRIPE_FEE_CENTS > 0:
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {
                    "name": "Stripe betaalkosten",
                    "description": "Bijdrage zodat je donatiebedrag volledig meetelt.",
                },
                "unit_amount": STRIPE_FEE_CENTS,
            },
            "quantity": 1,
        })

    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["ideal", "card"],
        submit_type="donate",
        success_url=base_url + "/?payment=success&session_id={CHECKOUT_SESSION_ID}",
        cancel_url=base_url + "/?payment=cancelled#doneer",
        line_items=line_items,
        metadata={
            "donor_name": donor_name,
            "note": note,
            "source": "website",
            "donation_amount_cents": str(cents),
            "stripe_fee_cents": str(STRIPE_FEE_CENTS),
            "cover_fees": "true",
        },
        payment_intent_data={
            "metadata": {
                "donor_name": donor_name,
                "note": note,
                "source": "website",
                "donation_amount_cents": str(cents),
                "stripe_fee_cents": str(STRIPE_FEE_CENTS),
                "cover_fees": "true",
            }
        },
    )
    return jsonify({"url": checkout_session.url})


@app.post("/api/stripe/sync-session")
def sync_stripe_checkout_session():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "Stripe sessie ontbreekt."}), 400

    try:
        result = donation_from_checkout_session(session_id)
    except Exception as error:
        return jsonify({"error": str(error)}), 500
    return jsonify({"ok": True, **result})


@app.post("/api/stripe/webhook")
def stripe_webhook():
    if not has_stripe_config():
        return jsonify({"error": "STRIPE_SECRET_KEY ontbreekt in .env."}), 500
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "STRIPE_WEBHOOK_SECRET ontbreekt in .env."}), 500

    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return jsonify({"error": "Ongeldige payload."}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Ongeldige Stripe signature."}), 400

    if event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session_object = event["data"]["object"]
        try:
            donation_from_checkout_session(session_object["id"])
        except Exception as error:
            return jsonify({"error": str(error)}), 500

    return jsonify({"received": True})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
