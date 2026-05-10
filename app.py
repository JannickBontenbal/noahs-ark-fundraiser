import hashlib
import io
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
_SETTINGS_CACHE = None
_SETTINGS_CACHE_AT = 0
SETTINGS_CACHE_SECONDS = 5
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
_SUPABASE_ADMIN_CLIENT = None

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")


def load_settings():
    """Load settings from persistent Supabase storage, then local file."""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_AT

    import time

    if _SETTINGS_CACHE is not None and time.time() - _SETTINGS_CACHE_AT < SETTINGS_CACHE_SECONDS:
        return dict(_SETTINGS_CACHE)

    if has_admin_config():
        try:
            response = supabase_admin().table("site_settings").select("key, value").execute()
            settings = {}
            for row in response.data or []:
                settings[str(row.get("key"))] = row.get("value")
            if settings:
                _SETTINGS_CACHE = settings
                _SETTINGS_CACHE_AT = time.time()
                return dict(settings)
        except Exception as error:
            print("Supabase settings load failed:", error)

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                _SETTINGS_CACHE = settings
                _SETTINGS_CACHE_AT = time.time()
                return dict(settings)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_settings(settings):
    """Save settings to Supabase and local file fallback."""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_AT

    saved_anywhere = False
    if has_admin_config():
        try:
            rows = [{"key": str(key), "value": value} for key, value in settings.items()]
            if rows:
                supabase_admin().table("site_settings").upsert(rows, on_conflict="key").execute()
                saved_anywhere = True
        except Exception as error:
            print("Supabase settings save failed:", error)

    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        saved_anywhere = True
    except IOError:
        pass

    if saved_anywhere:
        import time

        _SETTINGS_CACHE = dict(settings)
        _SETTINGS_CACHE_AT = time.time()
    return saved_anywhere


def get_setting(key, default=None):
    """Get a setting value, checking file first then environment."""
    settings = load_settings()
    if key in settings:
        return settings[key]
    return os.environ.get(key, default)


def setting_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "nee", "no", "off", "uit"}


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
            "id": str(item.get("id", "")).strip()[:80],
            "title": title or "Nieuwe actie",
            "description": description,
            "status_label": str(item.get("status_label", "Status")).strip() or "Status",
            "status": str(item.get("status", "")).strip() or "Open",
            "tags": [str(tag).strip() for tag in raw_tags if str(tag).strip()][:4],
            "variant": variant,
            "created_by": clean_text(item.get("created_by"), 120),
            "created_at": clean_text(item.get("created_at"), 80),
            "updated_by": clean_text(item.get("updated_by"), 120),
            "updated_at": clean_text(item.get("updated_at"), 80),
        })

    return actions or DEFAULT_ACTIONS


def iso_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def action_signature(action):
    return {
        "title": action.get("title", ""),
        "description": action.get("description", ""),
        "status_label": action.get("status_label", ""),
        "status": action.get("status", ""),
        "tags": action.get("tags", []),
        "variant": action.get("variant", ""),
    }


def describe_value_change(label, before, after):
    before_text = clean_text(before, 160) or "leeg"
    after_text = clean_text(after, 160) or "leeg"
    return label + ": '" + before_text + "' -> '" + after_text + "'"


def describe_action_delta(previous_action, next_action):
    if not previous_action:
        return "Nieuwe actie met status '" + next_action.get("status", "Open") + "'."
    if not next_action:
        return "Actie is verwijderd."

    labels = {
        "title": "Titel",
        "description": "Beschrijving",
        "status_label": "Status label",
        "status": "Status",
        "tags": "Tags",
        "variant": "Visuele stijl",
    }
    changes = []
    for key, label in labels.items():
        before = previous_action.get(key, [])
        after = next_action.get(key, [])
        if before == after:
            continue
        if isinstance(before, list):
            before = ", ".join(before)
        if isinstance(after, list):
            after = ", ".join(after)
        changes.append(describe_value_change(label, before, after))
    return " | ".join(changes) or "Metadata bijgewerkt."


def stamp_action_metadata(previous_actions, incoming_actions, actor):
    previous = normalize_actions(previous_actions)
    incoming = normalize_actions(incoming_actions)
    previous_by_id = {action.get("id"): action for action in previous if action.get("id")}
    used_previous_ids = set()
    used_previous_indexes = set()
    timestamp = iso_now()
    stamped = []
    events = []

    for index, action in enumerate(incoming):
        previous_action = None
        action_id = action.get("id")
        if action_id and action_id in previous_by_id:
            previous_action = previous_by_id[action_id]
            used_previous_ids.add(action_id)
        elif index < len(previous) and index not in used_previous_indexes:
            previous_action = previous[index]
            used_previous_indexes.add(index)

        if previous_action:
            action["id"] = previous_action.get("id") or action_id or str(uuid.uuid4())
            action["created_by"] = previous_action.get("created_by") or actor
            action["created_at"] = previous_action.get("created_at") or timestamp
            if action_signature(action) != action_signature(previous_action):
                action["updated_by"] = actor
                action["updated_at"] = timestamp
                events.append(("actie bewerkt", action.get("title", "Nieuwe actie"), describe_action_delta(previous_action, action)))
            else:
                action["updated_by"] = previous_action.get("updated_by") or previous_action.get("created_by") or actor
                action["updated_at"] = previous_action.get("updated_at") or previous_action.get("created_at") or timestamp
        else:
            action["id"] = action_id or str(uuid.uuid4())
            action["created_by"] = actor
            action["created_at"] = timestamp
            action["updated_by"] = actor
            action["updated_at"] = timestamp
            events.append(("actie toegevoegd", action.get("title", "Nieuwe actie"), describe_action_delta(None, action)))

        stamped.append(action)

    incoming_ids = {action.get("id") for action in stamped if action.get("id")}
    for previous_index, previous_action in enumerate(previous):
        if previous_index in used_previous_indexes:
            continue
        previous_id = previous_action.get("id")
        if previous_id and previous_id in incoming_ids:
            continue
        if previous_id and previous_id in used_previous_ids:
            continue
        title = previous_action.get("title", "Nieuwe actie")
        if title and title not in [action.get("title") for action in stamped]:
            events.append(("actie verwijderd", title, describe_action_delta(previous_action, None)))

    return stamped, events


def supabase_admin():
    global _SUPABASE_ADMIN_CLIENT
    if _SUPABASE_ADMIN_CLIENT is not None:
        return _SUPABASE_ADMIN_CLIENT

    from supabase import create_client

    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    _SUPABASE_ADMIN_CLIENT = create_client(SUPABASE_URL, key)
    return _SUPABASE_ADMIN_CLIENT


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


def current_admin_name():
    return clean_text(session.get("admin_name"), 120) or "Admin"


PRESENCE_COLORS = [
    "#d9ff3f",
    "#ff5a3d",
    "#77e7ff",
    "#f7b84b",
    "#caa7ff",
    "#72e6a5",
    "#ff8bd1",
    "#9be7d8",
]


def current_admin_session_id():
    if not session.get("admin_session_id"):
        session["admin_session_id"] = str(uuid.uuid4())
    return session["admin_session_id"]


def current_admin_device_id():
    if not session.get("admin_device_id"):
        session["admin_device_id"] = str(uuid.uuid4())
    return session["admin_device_id"]


def color_for_admin(name, device_id=""):
    source = (name or "") + (device_id or "")
    index = int(hashlib.sha256(source.encode("utf-8")).hexdigest(), 16) % len(PRESENCE_COLORS)
    return PRESENCE_COLORS[index]


def choose_presence_color(name, device_id):
    preferred = color_for_admin(name, device_id)
    if not has_admin_config():
        return preferred

    from datetime import datetime, timedelta, timezone

    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    try:
        response = (
            supabase_admin()
            .table("admin_presence")
            .select("admin_color, device_id")
            .gte("last_seen", stale_before)
            .execute()
        )
    except Exception:
        return preferred

    used = {
        row.get("admin_color")
        for row in (response.data or [])
        if row.get("admin_color") and row.get("device_id") != device_id
    }
    if preferred not in used:
        return preferred
    for color in PRESENCE_COLORS:
        if color not in used:
            return color
    return preferred


def current_admin_color():
    if not session.get("admin_color"):
        session["admin_color"] = color_for_admin(current_admin_name(), current_admin_device_id())
    return session["admin_color"]


def log_admin_change(action, entity_type, entity_id=None, details=None, admin_name=None):
    if not has_admin_config():
        return

    row = {
        "admin_name": clean_text(admin_name, 120) or current_admin_name(),
        "action": clean_text(action, 120),
        "entity_type": clean_text(entity_type, 80),
        "entity_id": clean_text(entity_id, 120) or None,
        "details": clean_text(details, 700) or None,
    }
    try:
        supabase_admin().table("admin_changelog").insert(row).execute()
    except Exception as error:
        print("Admin changelog insert failed:", error)


def insert_with_optional_created_by(table_name, row):
    try:
        return supabase_admin().table(table_name).insert(row).execute()
    except Exception as error:
        if "created_by" not in row:
            raise error
        fallback = dict(row)
        fallback.pop("created_by", None)
        return supabase_admin().table(table_name).insert(fallback).execute()


@app.get("/")
@app.get("/index.html")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/admin")
@app.get("/admin.html")
def admin_page():
    return send_from_directory(BASE_DIR, "admin.html")


@app.get("/changelog")
@app.get("/changelog.html")
def changelog_page():
    return send_from_directory(BASE_DIR, "changelog.html")


@app.get("/contact")
@app.get("/contact.html")
def contact_page():
    return send_from_directory(BASE_DIR, "contact.html")


@app.get("/legal")
@app.get("/legal.html")
def legal_page():
    return send_from_directory(BASE_DIR, "legal.html")


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
        "LARGE_DONATIONS_ENABLED": setting_bool(get_setting("LARGE_DONATIONS_ENABLED", "true"), True),
        "ACTIONS": normalize_actions(get_setting("ACTIONS", DEFAULT_ACTIONS)),
    }
    body = "window.NAF_CONFIG = " + json.dumps(config, ensure_ascii=True) + ";\n"
    return Response(body, mimetype="application/javascript")


@app.get("/favicon.svg")
def favicon():
    return send_from_directory(BASE_DIR, "favicon.svg")


@app.get("/images/<path:filename>")
def images(filename):
    return send_from_directory(BASE_DIR / "images", filename, max_age=86400)


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    admin_name = clean_text(payload.get("name"), 120)
    device_id = clean_text(payload.get("device_id"), 120) or str(uuid.uuid4())
    password = str(payload.get("password", ""))

    if not admin_name:
        return jsonify({"error": "Vul je naam in."}), 400

    if not ADMIN_PASSWORD_HASH:
        return jsonify({"error": "ADMIN_PASSWORD_HASH ontbreekt in .env."}), 500

    if password_hash(password) != ADMIN_PASSWORD_HASH.lower():
        return jsonify({"error": "Wachtwoord klopt niet."}), 401

    session["admin"] = True
    session["admin_name"] = admin_name
    session["admin_session_id"] = str(uuid.uuid4())
    session["admin_device_id"] = device_id
    session["admin_color"] = choose_presence_color(admin_name, device_id)
    if has_admin_config():
        try:
            supabase_admin().table("admin_presence").delete().eq("device_id", device_id).execute()
        except Exception as error:
            print("Admin presence device cleanup failed:", error)
    log_admin_change("ingelogd", "session", details=admin_name + " opende het adminpaneel.")
    return jsonify({
        "ok": True,
        "admin_name": admin_name,
        "admin_color": session["admin_color"],
        "admin_session_id": session["admin_session_id"],
        "admin_device_id": session["admin_device_id"],
    })


@app.post("/api/logout")
def logout():
    if session.get("admin"):
        if has_admin_config() and (session.get("admin_device_id") or session.get("admin_session_id")):
            try:
                if session.get("admin_device_id"):
                    supabase_admin().table("admin_presence").delete().eq("device_id", session["admin_device_id"]).execute()
                else:
                    supabase_admin().table("admin_presence").delete().eq("session_id", session["admin_session_id"]).execute()
            except Exception as error:
                print("Admin presence cleanup failed:", error)
        log_admin_change("uitgelogd", "session", details=current_admin_name() + " sloot het adminpaneel.")
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    blocked = admin_required()
    if blocked:
        return blocked
    return jsonify({
        "admin_name": current_admin_name(),
        "admin_color": current_admin_color(),
        "admin_session_id": current_admin_session_id(),
        "admin_device_id": current_admin_device_id(),
    })


@app.post("/api/presence")
def update_presence():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"users": []})

    from datetime import datetime, timedelta, timezone

    payload = request.get_json(silent=True) or {}
    section = clean_text(payload.get("section"), 80) or "Dashboard"
    device_id = clean_text(payload.get("device_id"), 120) or current_admin_device_id()
    if session.get("admin_device_id") != device_id:
        session["admin_color"] = choose_presence_color(current_admin_name(), device_id)
    session["admin_device_id"] = device_id
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(seconds=45)).isoformat()
    row = {
        "session_id": current_admin_session_id(),
        "device_id": current_admin_device_id(),
        "admin_name": current_admin_name(),
        "admin_color": current_admin_color(),
        "section": section,
        "last_seen": now.isoformat(),
    }

    try:
        supabase_admin().table("admin_presence").delete().lt("last_seen", stale_before).execute()
        supabase_admin().table("admin_presence").upsert(row, on_conflict="device_id").execute()
    except Exception as error:
        return jsonify({"error": "Kon online gebruikers niet bijwerken. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500

    return list_presence()


@app.get("/api/presence")
def list_presence():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"users": []})

    from datetime import datetime, timedelta, timezone

    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    try:
        supabase_admin().table("admin_presence").delete().lt("last_seen", stale_before).execute()
        response = (
            supabase_admin()
            .table("admin_presence")
            .select("session_id, device_id, admin_name, admin_color, section, last_seen")
            .gte("last_seen", stale_before)
            .order("last_seen", desc=True)
            .execute()
        )
    except Exception as error:
        return jsonify({"error": "Kon online gebruikers niet laden. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500

    return jsonify({
        "current_session_id": current_admin_session_id(),
        "current_device_id": current_admin_device_id(),
        "users": response.data or [],
    })


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
        "LARGE_DONATIONS_ENABLED": setting_bool(settings.get("LARGE_DONATIONS_ENABLED", os.environ.get("LARGE_DONATIONS_ENABLED", "true")), True),
        "ACTIONS": normalize_actions(settings.get("ACTIONS", DEFAULT_ACTIONS)),
    })


@app.post("/api/settings")
def update_settings():
    blocked = admin_required()
    if blocked:
        return blocked
    
    payload = request.get_json(silent=True) or {}
    
    settings = load_settings()
    previous_settings = {
        "GOAL_EUR": str(settings.get("GOAL_EUR", os.environ.get("GOAL_EUR", "10000"))),
        "IBAN": settings.get("IBAN", os.environ.get("IBAN", "")),
        "IBAN_NAME": settings.get("IBAN_NAME", os.environ.get("IBAN_NAME", "")),
        "LARGE_DONATIONS_ENABLED": setting_bool(settings.get("LARGE_DONATIONS_ENABLED", os.environ.get("LARGE_DONATIONS_ENABLED", "true")), True),
        "ACTIONS": normalize_actions(settings.get("ACTIONS", DEFAULT_ACTIONS)),
    }
    incoming_actions, action_events = stamp_action_metadata(
        previous_settings["ACTIONS"],
        payload.get("ACTIONS", settings.get("ACTIONS", DEFAULT_ACTIONS)),
        current_admin_name(),
    )

    settings.update({
        "GOAL_EUR": str(payload.get("GOAL_EUR", settings.get("GOAL_EUR", "10000"))),
        "IBAN": payload.get("IBAN", settings.get("IBAN", "")),
        "IBAN_NAME": payload.get("IBAN_NAME", settings.get("IBAN_NAME", "")),
        "TIKKIE_URL": payload.get("TIKKIE_URL", settings.get("TIKKIE_URL", "")),
        "LARGE_DONATIONS_ENABLED": "true" if setting_bool(payload.get("LARGE_DONATIONS_ENABLED", settings.get("LARGE_DONATIONS_ENABLED", "true")), True) else "false",
        "ACTIONS": incoming_actions,
    })
    
    if save_settings(settings):
        changed = []
        detail_lines = []
        if previous_settings["GOAL_EUR"] != str(settings.get("GOAL_EUR", "")):
            changed.append("doel")
            detail_lines.append(describe_value_change("Doel", previous_settings["GOAL_EUR"], settings.get("GOAL_EUR", "")))
        if previous_settings["IBAN"] != settings.get("IBAN", ""):
            changed.append("IBAN")
            detail_lines.append(describe_value_change("IBAN", previous_settings["IBAN"], settings.get("IBAN", "")))
        if previous_settings["IBAN_NAME"] != settings.get("IBAN_NAME", ""):
            changed.append("rekeninghouder")
            detail_lines.append(describe_value_change("Rekeninghouder", previous_settings["IBAN_NAME"], settings.get("IBAN_NAME", "")))
        if previous_settings["LARGE_DONATIONS_ENABLED"] != setting_bool(settings.get("LARGE_DONATIONS_ENABLED", "true"), True):
            changed.append("grote donaties")
            detail_lines.append(describe_value_change(
                "Grote donaties",
                "aan" if previous_settings["LARGE_DONATIONS_ENABLED"] else "uit",
                "aan" if setting_bool(settings.get("LARGE_DONATIONS_ENABLED", "true"), True) else "uit",
            ))
        if previous_settings["ACTIONS"] != settings.get("ACTIONS", []) and not action_events:
            changed.append("lopende acties")
            detail_lines.append("Lopende acties zijn bijgewerkt.")
        if changed:
            log_admin_change(
                "bijgewerkt",
                "settings",
                details=current_admin_name() + " wijzigde " + ", ".join(changed) + ". " + " | ".join(detail_lines),
            )
        for action, title, delta in action_events:
            verb = {
                "actie toegevoegd": "voegde toe",
                "actie bewerkt": "bewerkte",
                "actie verwijderd": "verwijderde",
            }.get(action, "wijzigde")
            log_admin_change(
                action,
                "action",
                details=current_admin_name() + " " + verb + " actie '" + title + "'. " + delta,
            )
        return jsonify({
            "ok": True,
            "settings": {
                "GOAL_EUR": int(settings.get("GOAL_EUR", os.environ.get("GOAL_EUR", "10000"))),
                "IBAN": settings.get("IBAN", os.environ.get("IBAN", "")),
                "IBAN_NAME": settings.get("IBAN_NAME", os.environ.get("IBAN_NAME", "")),
                "LARGE_DONATIONS_ENABLED": setting_bool(settings.get("LARGE_DONATIONS_ENABLED", "true"), True),
                "ACTIONS": normalize_actions(settings.get("ACTIONS", DEFAULT_ACTIONS)),
            },
        })
    else:
        return jsonify({"error": "Kon instellingen niet opslaan."}), 500


@app.get("/api/donations")
def list_donations():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_supabase_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    try:
        response = (
            supabase_admin()
            .table("donations")
            .select("id, amount, donor_name, note, created_at, created_by")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
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
        "created_by": current_admin_name(),
    }
    response = insert_with_optional_created_by("donations", row)
    donation = response.data[0] if response.data else row
    log_admin_change(
        "donatie toegevoegd",
        "donation",
        donation.get("id"),
        current_admin_name() + " voegde " + str(amount) + " EUR toe voor " + (row["donor_name"] or "Anoniem") + ".",
    )
    return jsonify({"donation": donation}), 201


@app.post("/api/large-donation-forms")
def create_large_donation_form():
    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    if not setting_bool(get_setting("LARGE_DONATIONS_ENABLED", "true"), True):
        return jsonify({"error": "Grote donaties zijn op dit moment tijdelijk niet beschikbaar."}), 403

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
        return jsonify({"error": "Omschrijving is verplicht."}), 400
    if not bool(payload.get("confirmed_transfer")):
        return jsonify({"error": "Bevestig dat je het bedrag direct overmaakt."}), 400

    donation_row = {
        "amount": amount,
        "donor_name": donor_name,
        "note": "Groot bedrag formulier 2027: " + description_primary,
        "created_by": "Website formulier",
    }
    try:
        donation_response = insert_with_optional_created_by("donations", donation_row)
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
        "created_by": "Website formulier",
    }

    try:
        form_response = insert_with_optional_created_by("large_donation_forms", form_row)
    except Exception as error:
        if donation_id:
            supabase_admin().table("donations").delete().eq("id", donation_id).execute()
        return jsonify({"error": "Kon formulier niet opslaan. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500

    created = form_response.data[0] if form_response.data else form_row
    log_admin_change(
        "formulier voltooid",
        "large_donation_form",
        created.get("id"),
        donor_name + " vulde een groot-bedrag formulier in voor " + str(amount) + " EUR.",
        admin_name="Website formulier",
    )
    return jsonify({
        "form": created,
        "donation": donation,
        "pdf_url": "/api/large-donation-forms/" + created["id"] + "/pdf",
    }), 201


@app.post("/api/contact-messages")
def create_contact_message():
    if not has_admin_config():
        return jsonify({"error": "Contactformulier is tijdelijk niet beschikbaar."}), 500

    payload = request.get_json(silent=True) or {}
    name = clean_text(payload.get("name"), 140)
    email = clean_text(payload.get("email"), 180)
    subject = clean_text(payload.get("subject"), 180)
    message = clean_text(payload.get("message"), 1200)

    if not name:
        return jsonify({"error": "Naam is verplicht."}), 400
    if not message:
        return jsonify({"error": "Bericht is verplicht."}), 400

    row = {
        "name": name,
        "email": email or None,
        "subject": subject or None,
        "message": message,
    }
    try:
        response = supabase_admin().table("contact_messages").insert(row).execute()
    except Exception as error:
        return jsonify({"error": "Kon bericht niet opslaan. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500

    created = response.data[0] if response.data else row
    log_admin_change(
        "contactbericht ontvangen",
        "contact_message",
        created.get("id"),
        name + " stuurde een contactbericht" + ((" over '" + subject + "'") if subject else "") + ".",
        admin_name="Website contact",
    )
    return jsonify({"message": created}), 201


@app.get("/api/contact-messages")
def list_contact_messages():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("contact_messages")
        .select("id, name, email, subject, message, created_at")
        .order("created_at", desc=True)
        .limit(80)
        .execute()
    )
    return jsonify({"messages": response.data or []})


@app.delete("/api/contact-messages/<message_id>")
def delete_contact_message(message_id):
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    response = (
        supabase_admin()
        .table("contact_messages")
        .select("id, name, subject")
        .eq("id", message_id)
        .limit(1)
        .execute()
    )
    message = response.data[0] if response.data else {}
    supabase_admin().table("contact_messages").delete().eq("id", message_id).execute()
    log_admin_change(
        "contactbericht verwijderd",
        "contact_message",
        message_id,
        current_admin_name() + " verwijderde contactbericht van " + (message.get("name") or "Onbekend") + ".",
    )
    return jsonify({"ok": True})


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

    form_row = response.data[0]
    viewer_name = current_admin_name() if session.get("admin") else "Website gebruiker"
    log_admin_change(
        "PDF geopend",
        "large_donation_form",
        form_id,
        viewer_name + " opende PDF voor " + (form_row.get("company_name") or form_row.get("donor_name") or "Onbekend") + " (" + str(form_row.get("amount", "")) + " EUR).",
        admin_name=viewer_name,
    )

    pdf = build_large_donation_pdf(form_row)
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
        .select("id, donation_id, amount, donor_name, company_name, donor_type")
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return jsonify({"error": "Formulier niet gevonden."}), 404

    donation_id = response.data[0].get("donation_id")
    form_row = response.data[0]
    if donation_id:
        supabase_admin().table("donations").delete().eq("id", donation_id).execute()
    else:
        supabase_admin().table("large_donation_forms").delete().eq("id", form_id).execute()
    log_admin_change(
        "formulier verwijderd",
        "large_donation_form",
        form_id,
        current_admin_name() + " verwijderde formulier van " + (form_row.get("company_name") or form_row.get("donor_name") or "Onbekend") + ".",
    )
    return jsonify({"ok": True})


def build_large_donation_pdf(row):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 14 * mm
    right = width - 14 * mm
    label_width = 48 * mm
    line = height - 16 * mm

    def draw_line(label, value="", size=10, bold=False):
        nonlocal line
        pdf.setFillColor(colors.HexColor("#080806"))
        pdf.setFont("Helvetica-Bold", size)
        pdf.drawString(left, line, str(label))
        if value:
            draw_wrapped_at(left + label_width, line, str(value), right - left - label_width, size, bold)
        line -= 7 * mm

    def draw_section(title):
        nonlocal line
        line -= 4 * mm
        pdf.setStrokeColor(colors.HexColor("#d7c9a6"))
        pdf.setLineWidth(0.7)
        pdf.line(left, line, right, line)
        line -= 6 * mm
        pdf.setFillColor(colors.HexColor("#ff5a3d"))
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(left, line, title.upper())
        line -= 8 * mm

    def draw_wrapped(text, size=10):
        nonlocal line
        line = draw_wrapped_at(left, line, str(text), right - left, size, False)
        line -= 1 * mm

    def draw_wrapped_at(x, y, text, max_width, size=10, bold=False):
        font = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFillColor(colors.HexColor("#080806"))
        pdf.setFont(font, size)
        current_y = y
        pdf.setFont("Helvetica", size)
        words = str(text).split()
        current = ""
        for word in words:
            next_line = (current + " " + word).strip()
            if pdf.stringWidth(next_line, font, size) > max_width and current:
                pdf.setFont(font, size)
                pdf.drawString(x, current_y, current)
                current_y -= 5 * mm
                current = word
            else:
                current = next_line
        if current:
            pdf.setFont(font, size)
            pdf.drawString(x, current_y, current)
            current_y -= 5 * mm
        return current_y

    pdf.setFillColor(colors.HexColor("#f8efd8"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#080806"))

    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawString(left, line, "FACTUUR UGANDA")
    line -= 8 * mm
    pdf.setFillColor(colors.HexColor("#ff5a3d"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(left, line, "Noah's Ark donatieformulier 2027")
    line -= 5 * mm
    pdf.setStrokeColor(colors.HexColor("#080806"))
    pdf.setLineWidth(1)
    pdf.line(left, line, right, line)
    line -= 9 * mm
    pdf.setFillColor(colors.HexColor("#080806"))

    draw_section("Afzender")
    draw_line("Naam afzender", "Noah's Ark Children and Youth Ministry Uganda")
    draw_line("Adres", "Batelier 14")
    draw_line("Postcode + woonplaats", "3323 JS Sliedrecht")
    draw_line("E-mail", "nederland@nacmu.org")
    draw_line("Overgemaakt op", format_dutch_date(row.get("created_at")))

    draw_section("Donateur")
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

    draw_section("Donatie")
    draw_line("Bedrag", "EUR " + str(row.get("amount", "")), bold=True)
    draw_line("Omschrijving", row.get("description_primary", ""), bold=True)
    draw_line("Omschrijving betaling", "Actie Guido 2027")
    draw_line("Jaar", str(row.get("tax_year", 2027)))

    draw_section("Betaalinstructie")
    draw_line("Bankrekeningnummer", "NL 59 RABO 0362 4439 55")
    draw_line("Ten name van", "Noah's Ark Children's Ministry")
    draw_line("Omschrijving", "Actie Guido 2027")
    draw_wrapped("Dit formulier voert geen bankbetaling uit. Maak het bedrag zelf over via je bank. Hartelijk dank voor uw steun aan dit project!")
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

    response = (
        supabase_admin()
        .table("donations")
        .select("id, amount, donor_name")
        .eq("id", donation_id)
        .limit(1)
        .execute()
    )
    donation = response.data[0] if response.data else {}
    supabase_admin().table("donations").delete().eq("id", donation_id).execute()
    log_admin_change(
        "donatie verwijderd",
        "donation",
        donation_id,
        current_admin_name() + " verwijderde " + str(donation.get("amount", "")) + " EUR van " + (donation.get("donor_name") or "Anoniem") + ".",
    )
    return jsonify({"ok": True})


@app.get("/api/changelog")
def list_changelog():
    blocked = admin_required()
    if blocked:
        return blocked

    if not has_admin_config():
        return jsonify({"error": "SUPABASE_SERVICE_KEY ontbreekt in .env."}), 500

    try:
        response = (
            supabase_admin()
            .table("admin_changelog")
            .select("id, admin_name, action, entity_type, entity_id, details, created_at")
            .order("created_at", desc=True)
            .limit(80)
            .execute()
        )
    except Exception as error:
        return jsonify({"error": "Kon changelog niet laden. Run supabase-schema.sql opnieuw in Supabase. " + str(error)}), 500
    return jsonify({"changes": response.data or []})


@app.post("/api/changelog/viewed")
def changelog_viewed():
    blocked = admin_required()
    if blocked:
        return blocked

    log_admin_change(
        "changelog geopend",
        "changelog",
        details=current_admin_name() + " opende de changelog pagina.",
    )
    return jsonify({"ok": True})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
