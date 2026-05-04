import hashlib
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session
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


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def clean_text(value, limit=500):
    return str(value or "").strip()[:limit]


def format_dutch_date(value=None):
    from datetime import datetime

    if not value:
        date = datetime.now()
    elif isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            date = datetime.now()
    else:
        date = value
    return date.strftime("%d-%m-%Y")


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


@app.get("/grote-donatie")
@app.get("/grote-donatie.html")
def large_donation_page():
    return send_from_directory(BASE_DIR, "large-donation.html")


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


@app.post("/api/large-donation-forms")
def create_large_donation_form():
    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Bedrag is ongeldig."}), 400

    if amount <= 0:
        return jsonify({"error": "Bedrag moet groter zijn dan 0."}), 400

    donor_type = clean_text(payload.get("donor_type"), 20) or "particulier"
    if donor_type not in {"particulier", "bedrijf"}:
        donor_type = "particulier"

    donor_name = clean_text(payload.get("donor_name"), 160)
    company_name = clean_text(payload.get("company_name"), 180)
    contact_person = clean_text(payload.get("contact_person"), 160)
    description_primary = clean_text(payload.get("description_primary"), 220)
    if donor_type == "bedrijf":
        if not company_name:
            return jsonify({"error": "Bedrijfsnaam is verplicht."}), 400
        if not contact_person:
            return jsonify({"error": "Contactpersoon is verplicht."}), 400
        donor_name = company_name

    if not donor_name:
        return jsonify({"error": "Naam is verplicht."}), 400
    if not description_primary:
        return jsonify({"error": "Omschrijving 1 is verplicht."}), 400
    if not bool(payload.get("confirmed_transfer")):
        return jsonify({"error": "Bevestig dat je het bedrag direct overmaakt."}), 400

    donation_row = {
        "amount": amount,
        "donor_name": donor_name,
        "note": "Groot bedrag formulier 2027: " + description_primary,
    }
    try:
        donation_response = supabase_admin().table("donations").insert(donation_row).execute()
    except Exception as error:
        return jsonify({"error": "Kon donatie niet opslaan. Controleer Supabase en SUPABASE_SERVICE_KEY. " + str(error)}), 500
    donation = donation_response.data[0] if donation_response.data else donation_row
    donation_id = donation.get("id")

    form_row = {
        "donation_id": donation_id,
        "donor_type": donor_type,
        "company_name": company_name or None,
        "contact_person": contact_person or None,
        "amount": amount,
        "donor_name": donor_name,
        "email": clean_text(payload.get("email"), 180) or None,
        "phone": clean_text(payload.get("phone"), 80) or None,
        "street": clean_text(payload.get("street"), 180) or None,
        "postal_code": clean_text(payload.get("postal_code"), 40) or None,
        "city": clean_text(payload.get("city"), 120) or None,
        "country": clean_text(payload.get("country"), 120) or "Nederland",
        "description_primary": description_primary,
        "description_secondary": clean_text(payload.get("description_secondary"), 220) or "Guido de Bres Uganda reis 2027",
        "tax_year": 2027,
    }

    try:
        form_response = supabase_admin().table("large_donation_forms").insert(form_row).execute()
    except Exception as error:
        if donation_id:
            supabase_admin().table("donations").delete().eq("id", donation_id).execute()
        return jsonify({"error": "Kon formulier niet opslaan. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500

    created = form_response.data[0] if form_response.data else form_row
    return jsonify({
        "form": created,
        "donation": donation,
        "pdf_url": "/api/large-donation-forms/" + created["id"] + "/pdf",
    }), 201


@app.get("/api/large-donation-forms")
def list_large_donation_forms():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("large_donation_forms")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return jsonify({"forms": response.data or []})


@app.get("/api/large-donation-forms/<form_id>/pdf")
def large_donation_form_pdf(form_id):
    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("large_donation_forms")
        .select("*")
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return jsonify({"error": "Formulier niet gevonden."}), 404

    pdf = build_large_donation_pdf(response.data[0])
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": "inline; filename=grote-donatie-2027.pdf"},
    )


@app.delete("/api/large-donation-forms/<form_id>")
def delete_large_donation_form(form_id):
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("large_donation_forms")
        .select("id, donation_id")
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return jsonify({"error": "Formulier niet gevonden."}), 404

    donation_id = response.data[0].get("donation_id")
    if donation_id:
        supabase_admin().table("donations").delete().eq("id", donation_id).execute()
    else:
        supabase_admin().table("large_donation_forms").delete().eq("id", form_id).execute()
    return jsonify({"ok": True})


def build_large_donation_pdf(row):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 20 * mm
    line = height - 22 * mm

    def draw_line(label, value="", size=10, bold=False):
        nonlocal line
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(left, line, str(label))
        if value:
            pdf.setFont("Helvetica", size)
            pdf.drawString(left + 58 * mm, line, str(value))
        line -= 9 * mm

    def draw_wrapped(text, size=10):
        nonlocal line
        pdf.setFont("Helvetica", size)
        words = str(text).split()
        current = ""
        for word in words:
            next_line = (current + " " + word).strip()
            if pdf.stringWidth(next_line, "Helvetica", size) > (width - (2 * left)):
                pdf.drawString(left, line, current)
                line -= 6 * mm
                current = word
            else:
                current = next_line
        if current:
            pdf.drawString(left, line, current)
            line -= 6 * mm

    pdf.setFillColor(colors.HexColor("#080806"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#f8efd8"))
    pdf.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#080806"))
    pdf.setStrokeColor(colors.HexColor("#080806"))
    pdf.setLineWidth(1.2)
    pdf.rect(18 * mm, 18 * mm, width - 36 * mm, height - 36 * mm, fill=0, stroke=1)

    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(left, line, "FACTUUR UGANDA")
    line -= 9 * mm
    pdf.setFillColor(colors.HexColor("#ff5a3d"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(left, line, "Noah's Ark donatieformulier 2027")
    line -= 14 * mm
    pdf.setFillColor(colors.HexColor("#080806"))

    draw_line("Naam afzender", "Noah's Ark Children and Youth Ministry Uganda")
    draw_line("Adres", "Batelier 14")
    draw_line("Postcode + woonplaats", "3323 JS Sliedrecht")
    draw_line("E-mail", "nederland@nacmu.org")
    draw_line("Overgemaakt op", format_dutch_date(row.get("created_at")))
    line -= 3 * mm

    draw_line("Formuliernummer", str(row.get("id", ""))[:18])
    draw_line("Type", "Bedrijf" if row.get("donor_type") == "bedrijf" else "Particulier")
    if row.get("donor_type") == "bedrijf":
        draw_line("Naam bedrijf", row.get("company_name", ""))
        draw_line("Contactpersoon", row.get("contact_person", ""))
    else:
        draw_line("Naam", row.get("donor_name", ""))
    draw_line("E-mail", row.get("email", ""))
    draw_line("Telefoon", row.get("phone", ""))
    draw_line("Adres", row.get("street", ""))
    draw_line("Postcode / plaats", (row.get("postal_code") or "") + " " + (row.get("city") or ""))
    draw_line("Land", row.get("country", ""))
    draw_line("Bedrag", "EUR " + str(row.get("amount", "")), bold=True)
    draw_line("Omschrijving donateur", row.get("description_primary", ""), bold=True)
    draw_line("Omschrijving betaling", "Actie Guido 2027")
    draw_line("Jaar", str(row.get("tax_year", 2027)))

    line -= 4 * mm
    pdf.setStrokeColor(colors.HexColor("#080806"))
    pdf.line(left, line, width - left, line)
    line -= 9 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(left, line, "Betaalinstructie")
    line -= 7 * mm
    draw_line("Bankrekeningnummer", "NL 59 RABO 0362 4439 55")
    draw_line("Ten name van", "Noah's Ark Children's Ministry")
    draw_line("Omschrijving", "Actie Guido 2027")
    line -= 9 * mm
    draw_wrapped("Dit formulier voert geen bankbetaling uit. Maak het bedrag zelf over via je bank. Hartelijk dank voor uw steun aan dit project!")
    line -= 3 * mm
    draw_wrapped("Deze directe donatie kan fiscaal aftrekbaar zijn. Bewaar dit formulier bij je administratie.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@app.delete("/api/donations/<donation_id>")
def delete_donation(donation_id):
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    supabase_admin().table("donations").delete().eq("id", donation_id).execute()
    return jsonify({"ok": True})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
