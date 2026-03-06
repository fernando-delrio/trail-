"""
This module takes care of starting the API Server, Loading the DB and Adding the endpoints
"""
import re
from flask import request, jsonify, Blueprint
from api.models import db, User, Bike, BikePart, BikeModel, SavedRoute
from api.utils import APIException, is_valid_email
from flask_cors import CORS
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from api.services.mistral_client import mistral_chat
from api.services.catalog import load_catalog, rank_bikes
from api.services.overpass_pois import get_nearby_services_for_route
from api.services.osm_trails import (
    is_route_intent, extract_location, geocode_place,
    fetch_osm_trails, build_trails_system_message,
)
from datetime import datetime, timezone, timedelta
from itertools import chain, islice
from typing import Any
from uuid import uuid4


api = Blueprint('api', __name__)
CORS(api)


# ──────────────────────────────────────────────────────────────────────────────
# GENERIC HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _raise(exc: Exception):
    """Raises an exception — used inside and/or chains as a side-effect."""
    raise exc


def current_user_id() -> int:
    return int(get_jwt_identity())


def serialize_all(items) -> list:
    return list(map(lambda x: x.serialize(), items))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_iso_string(raw: str) -> datetime:
    clean = raw.strip()
    candidate = clean.endswith("Z") and (clean[:-1] + "+00:00") or clean
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.tzinfo and parsed or parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return now_utc()


def parse_datetime(raw: Any) -> datetime:
    return (
        isinstance(raw, datetime) and raw
        or isinstance(raw, str) and raw and _normalize_iso_string(raw)
        or now_utc()
    )


# ──────────────────────────────────────────────────────────────────────────────
# BIKE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def build_bike_part(bike_id: int, p: dict) -> BikePart:
    return BikePart(
        bike_id=bike_id,
        part_name=p.get("part_name"),
        brand=p.get("brand"),
        model=p.get("model"),
        km_life=p.get("km_life") or 0,
        km_current=p.get("km_current") or 0,
        wear_percentage=p.get("wear_percentage") or 0,
    )


def replace_bike_parts(bike_id: int, parts_data: list) -> None:
    BikePart.query.filter_by(bike_id=bike_id).delete()
    db.session.add_all(list(map(lambda p: build_bike_part(bike_id, p), parts_data)))


def validate_and_set_bike_model(bike: Bike, new_id: Any) -> None:
    """Validates that bike_model_id exists in DB, then assigns it (or None)."""
    model_obj = new_id and (
        BikeModel.query.get(new_id)
        or _raise(APIException("Modelo de bici no encontrado", status_code=404))
    )
    bike.bike_model_id = model_obj and new_id or None


# ──────────────────────────────────────────────────────────────────────────────
# HOME / STATS HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def weekly_distance_km(user_id: int) -> float:
    week_ago = now_utc() - timedelta(days=7)
    recent = SavedRoute.query.filter(
        SavedRoute.user_id == user_id,
        SavedRoute.created_at >= week_ago,
    ).all()
    return round(sum(map(lambda r: r.distance_km or 0, recent)), 1)


def featured_routes_for_user(user_id: int) -> list:
    return (
        SavedRoute.query
        .filter_by(user_id=user_id)
        .order_by(SavedRoute.created_at.desc())
        .limit(5)
        .all()
    )


# ──────────────────────────────────────────────────────────────────────────────
# GASTACOBRE AI HELPERS
# ──────────────────────────────────────────────────────────────────────────────

_BUY_RX = re.compile(
    r"\b(bici|bicicleta|busco|quiero|comprar|recomienda|presupuesto|precio|trail|xc|enduro|dh|downhill|gravel|carretera|modalidad|terreno|montar|rueda|suspensión|horquilla|cuadro|componentes)\b",
    re.IGNORECASE,
)
_MAINT_RX = re.compile(
    r"\b(mantenimiento|desgaste|revisar|revisión|cambiar|pieza|piezas|estado|cadena|frenos|pastillas|llantas|rodamiento)\b",
    re.IGNORECASE,
)
_SKIP_CONTENT = {"__RECS_BLOCK__", "__QUESTIONS__", "__CHIPS__"}

_GASTACOBRE_SYSTEM_PROMPT = (
    "Eres GASTACOBRE, asistente experto en ciclismo de montaña y compra de bicis.\n"
    "Reglas:\n"
    "- Responde SIEMPRE en español, de forma natural y cercana.\n"
    "- Sé breve, claro y práctico. Sin relleno.\n"
    "- Si el usuario saluda o pregunta algo no relacionado con bicis, responde brevemente y pregunta en qué puedes ayudarle.\n"
    "- NO inventes modelos. SOLO puedes hablar de las RECOMMENDATIONS del catálogo.\n"
    "- Si faltan datos (modalidad o presupuesto), pregunta 1 cosa concreta.\n"
    "- Cuando hay recomendaciones, explica en 1 frase por qué encaja cada una.\n"
    "- Si el usuario pregunta por su garaje o sus bicis, responde SOLO con los datos del PERFIL DEL USUARIO.\n"
    "- Si pide comparar modelos, usa solo los que están en RECOMMENDATIONS. Muestra pros/contras concretos.\n"
    "- Si pregunta por mantenimiento o estado de componentes: analiza el DESGASTE del PERFIL. "
    "Avisa de piezas >= 80% (urgente) o >= 60% (vigilar pronto). Sé específico: pieza, porcentaje, acción.\n"
    "- Si hay una RUTA ANALIZADA: evalúa qué bici del PERFIL DEL USUARIO es más adecuada según terreno, distancia y desnivel. "
    "Sé directo: nombra la bici, explica por qué encaja y advierte si alguna pieza está muy desgastada para esa ruta.\n"
    "- Si el usuario pide recomendaciones de rutas por una zona: usa los datos de RUTAS EN OPENSTREETMAP si están disponibles. "
    "Lista cada ruta con nombre, distancia y dificultad. Si no hay datos OSM, usa tu conocimiento de rutas populares en esa zona. "
    "Siempre recomienda también qué tipo de bici conviene para el terreno pedido.\n"
    "- Al final añade 1 o 2 preguntas de seguimiento en este formato EXACTO (sin emojis en opciones):\n"
    "[Q1] ¿pregunta? | Opción A | Opción B | Opción C\n"
    "[Q2] ¿pregunta? | Opción A | Opción B\n"
    "Las opciones son respuestas de 1-4 palabras que el usuario puede pulsar.\n"
    "Ejemplos terreno: Trail | XC | Enduro | DH | Carretera | Gravel\n"
    "Ejemplos presupuesto: 1000-2000€ | 2000-3500€ | 3500-5000€ | +5000€\n"
    "Ejemplos suspension: Doble suspension | Rigida\n"
    "IMPORTANTE: usa siempre | entre pregunta y opciones.\n"
)


def user_has_bike_intent(messages: list[Any]) -> bool:
    last_user = next(filter(lambda m: m.get("role") == "user", reversed(messages)), {})
    text = str(last_user.get("content") or "")
    return bool(_BUY_RX.search(text) or _MAINT_RX.search(text))


def is_valid_chat_message(m: dict[str, Any]) -> bool:
    return (
        m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m.get("content") not in _SKIP_CONTENT
    )


def to_clean_message(m: dict[str, Any]) -> dict[str, Any]:
    return {"role": m.get("role"), "content": m.get("content")}


def bike_recommendation_line(r: dict) -> str:
    return f"- {r['name']} | type={r.get('type')} | price={r.get('price_eur')}€ | url={r.get('url')}"


def build_catalog_context(recommendations: list) -> dict:
    rec_text = recommendations and (
        "RECOMMENDATIONS (del catálogo, no inventar):\n"
        + "\n".join(map(bike_recommendation_line, recommendations))
    )
    return {
        "role": "system",
        "content": rec_text or "RECOMMENDATIONS: ninguna (el usuario no está buscando bici ahora mismo).",
    }


def bike_summary_line(b: dict) -> str:
    return f"- Bici: {b.get('name')} ({b.get('model') or 'sin modelo'}, {b.get('km') or 0} km)"


def part_wear_line(p: dict) -> str:
    brand_model = " ".join(filter(None, [p.get("brand"), p.get("name")]))
    return f"  · {brand_model}: desgaste {p.get('wear') or 0}% ({p.get('km_current') or 0}/{p.get('km_life') or 0} km)"


def bike_with_parts_lines(b: dict) -> list[str]:
    return [bike_summary_line(b)] + list(map(part_wear_line, b.get("parts") or []))


def build_profile_context(user_profile: dict) -> dict:
    name_lines = user_profile.get("name") and [f"- Nombre: {user_profile['name']}"] or []
    loc_lines = user_profile.get("location") and [f"- Ubicación: {user_profile['location']}"] or []
    bikes = list(islice(user_profile.get("bikes") or [], 5))
    bike_lines = list(chain.from_iterable(map(bike_with_parts_lines, bikes)))
    all_lines = name_lines + loc_lines + bike_lines
    content = all_lines and ("PERFIL DEL USUARIO:\n" + "\n".join(all_lines)) or "PERFIL DEL USUARIO: desconocido"
    return {"role": "system", "content": content}


def build_analyzed_route_context(route_context: dict) -> dict | None:
    has_route = route_context.get("name") or route_context.get("terrain")
    return has_route and {
        "role": "system",
        "content": (
            "RUTA ANALIZADA:\n"
            f"- Nombre: {route_context.get('name', '—')}\n"
            f"- Tipo: {route_context.get('type', '—')}\n"
            f"- Terreno: {route_context.get('terrain', '—')}\n"
            f"- Distancia: {float(route_context.get('distance_km') or 0):.2f} km\n"
            f"- Desnivel: +{round(float(route_context.get('gain_m') or 0))} m\n"
            "Evalúa qué bici del PERFIL DEL USUARIO es más adecuada para esta ruta."
        ),
    } or None


def build_osm_trails_context(last_msg: str, terrain_hint: str) -> dict | None:
    location = is_route_intent(last_msg) and extract_location(last_msg)
    geo = location and geocode_place(location)
    trails = geo and fetch_osm_trails(geo["lat"], geo["lon"], terrain_hint)
    return geo and trails and build_trails_system_message(geo["display"], trails) or None


def parse_question_line(line: str) -> dict:
    parts = list(map(str.strip, line.split("|")))
    return {"question": parts[0], "options": list(filter(None, parts[1:]))}


def _is_user_role(m: dict[str, Any]) -> bool:
    return m.get("role") == "user"

def _get_content(m: dict[str, Any]) -> str:
    return str(m.get("content") or "")

def last_user_message(clean_history: list[dict[str, Any]]) -> str:
    return next(map(_get_content, filter(_is_user_role, reversed(clean_history))), "")


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@api.route('/hello', methods=['POST', 'GET'])
def handle_hello():
    return jsonify({"message": "Hello! I'm a message that came from the backend"}), 200


@api.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@api.route("/signup", methods=["POST"])
def signup():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    is_valid_email(email) or _raise(APIException("Invalid email", status_code=400))
    len(password) >= 8 or _raise(APIException("Password must be at least 8 characters", status_code=400))
    not User.query.filter_by(email=email).first() or _raise(APIException("User already exists", status_code=409))

    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"msg": "User created"}), 201


@api.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    (email and password) or _raise(APIException("Missing email or password", status_code=400))
    user = User.query.filter_by(email=email).first()
    (user and user.check_password(password)) or _raise(APIException("Bad credentials", status_code=401))

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.serialize()}), 200


@api.route("/home", methods=["GET"])
@jwt_required()
def home():
    user_id = current_user_id()
    user = User.query.get(user_id) or _raise(APIException("User not found", status_code=404))
    return jsonify({
        "user": user.serialize(),
        "weekly_kms": weekly_distance_km(user_id),
        "featured_routes": serialize_all(featured_routes_for_user(user_id)),
        "friends_activity": [],
    }), 200


@api.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = current_user_id()
    user = User.query.get(user_id) or _raise(APIException("User not found", status_code=404))
    return jsonify({"msg": "Access granted", "user": user.serialize()}), 200


@api.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user_id = current_user_id()
    user = User.query.get(user_id) or _raise(APIException("User not found", status_code=404))
    body = request.get_json(silent=True) or {}

    "name" in body and setattr(user, "name", (body["name"] or "").strip() or None)
    "location" in body and setattr(user, "location", (body["location"] or "").strip() or None)
    "avatar" in body and setattr(user, "avatar", isinstance(body["avatar"], str) and body["avatar"].strip() or None)

    db.session.commit()
    return jsonify({"msg": "Profile updated", "user": user.serialize()}), 200


# ──────────────────────────────────────────────────────────────────────────────
# SAVED ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@api.route("/saved-routes", methods=["GET"])
@jwt_required()
def list_saved_routes():
    user_id = current_user_id()
    routes = SavedRoute.query.filter_by(user_id=user_id).order_by(SavedRoute.created_at.desc()).all()
    return jsonify(serialize_all(routes)), 200


@api.route("/saved-routes/<string:route_id>", methods=["GET"])
@jwt_required()
def get_saved_route(route_id):
    user_id = current_user_id()
    route = SavedRoute.query.filter_by(id=route_id, user_id=user_id).first()
    return route and (jsonify(route.serialize()), 200) or _raise(APIException("Saved route not found", status_code=404))


@api.route("/saved-routes", methods=["POST"])
@jwt_required()
def create_or_update_saved_route():
    user_id = current_user_id()
    body = request.get_json(silent=True) or {}

    preview_coords = body.get("preview_coords")
    preview_coords is not None and not isinstance(preview_coords, list) and _raise(
        APIException("preview_coords must be an array", status_code=400)
    )

    route_id = str(body.get("id") or uuid4())
    name = (body.get("name") or "Ruta guardada").strip()
    route_type = (body.get("type") or body.get("route_type") or "planned").strip().lower()
    terrain = (body.get("terrain") or "").strip() or None

    owned = SavedRoute.query.filter_by(id=route_id).first()
    existing = owned and owned.user_id == user_id and owned or None
    route_id = existing and route_id or str(uuid4())

    route = existing or SavedRoute(id=route_id, user_id=user_id)
    existing or db.session.add(route)

    route.name = name
    route.route_type = route_type
    route.terrain = terrain
    route.distance_km = body.get("distance_km")
    route.duration_min = body.get("duration_min")
    route.gain_m = body.get("gain_m")
    route.preview_coords = preview_coords
    route.bbox = body.get("bbox")
    route.created_at = parse_datetime(body.get("created_at"))

    db.session.commit()
    return jsonify(route.serialize()), existing and 200 or 201


@api.route("/saved-routes/<string:route_id>", methods=["DELETE"])
@jwt_required()
def delete_saved_route(route_id):
    user_id = current_user_id()
    route = SavedRoute.query.filter_by(id=route_id, user_id=user_id).first()
    route or _raise(APIException("Saved route not found", status_code=404))
    db.session.delete(route)
    db.session.commit()
    return jsonify({"msg": "Saved route deleted"}), 200


# ──────────────────────────────────────────────────────────────────────────────
# BIKE MODELS
# ──────────────────────────────────────────────────────────────────────────────

@api.route("/bike-models", methods=["GET"])
@jwt_required()
def get_bike_models():
    bike_type = request.args.get("type")
    query = BikeModel.query
    query = bike_type and query.filter_by(bike_type=bike_type) or query
    models = query.order_by(BikeModel.brand, BikeModel.model_name).all()
    return jsonify(serialize_all(models)), 200


@api.route("/bike-models/search", methods=["GET"])
@jwt_required()
def search_bike_models():
    search_term = request.args.get("q", "").strip()
    (search_term and len(search_term) >= 2) or _raise(
        APIException("Search term must be at least 2 characters", status_code=400)
    )
    pattern = f"%{search_term}%"
    models = BikeModel.query.filter(
        db.or_(BikeModel.brand.ilike(pattern), BikeModel.model_name.ilike(pattern))
    ).limit(20).all()
    return jsonify(serialize_all(models)), 200


@api.route("/bike-models/types", methods=["GET"])
@jwt_required()
def get_bike_types():
    types = db.session.query(BikeModel.bike_type).distinct().all()
    return jsonify({"types": list(map(lambda t: t[0], types))}), 200


@api.route("/bike-models", methods=["POST"])
@jwt_required()
def create_bike_model():
    body = request.get_json(silent=True) or {}
    brand = (body.get("brand") or "").strip()
    model_name = (body.get("model_name") or "").strip()
    bike_type = (body.get("bike_type") or "").strip()
    model_year = body.get("model_year")
    description = body.get("description")

    all([brand, model_name, bike_type]) or _raise(
        APIException("Brand, model_name, and bike_type are required", status_code=400)
    )
    not BikeModel.query.filter_by(brand=brand, model_name=model_name, model_year=model_year).first() or _raise(
        APIException("This bike model already exists", status_code=409)
    )

    bike_model = BikeModel(
        brand=brand, model_name=model_name, model_year=model_year,
        bike_type=bike_type, description=description,
    )
    db.session.add(bike_model)
    db.session.commit()
    return jsonify(bike_model.serialize()), 201


# ──────────────────────────────────────────────────────────────────────────────
# BIKES
# ──────────────────────────────────────────────────────────────────────────────

@api.route("/bikes", methods=["GET"])
@jwt_required()
def get_bikes():
    user_id = current_user_id()
    return jsonify(serialize_all(Bike.query.filter_by(user_id=user_id).all())), 200


@api.route("/bikes", methods=["POST"])
@jwt_required()
def create_bike():
    user_id = current_user_id()
    user = User.query.get(user_id) or _raise(APIException("User not found", status_code=404))
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    model = (body.get("model") or "").strip()
    bike_model_id = body.get("bike_model_id")

    name or _raise(APIException("Nombre es requerido", status_code=400))
    model or _raise(APIException("Model es requerido", status_code=400))
    bike_model_id and (
        BikeModel.query.get(bike_model_id)
        or _raise(APIException("Modelo no encontrado", status_code=404))
    )

    bike = Bike(
        user_id=user.id,
        name=name,
        bike_model_id=bike_model_id,
        model=model,
        specs=body.get("specs"),
        image_url=body.get("image_url"),
        video_url=body.get("video_url"),
        is_active=False,
    )
    db.session.add(bike)
    db.session.flush()
    db.session.add_all(list(map(lambda p: build_bike_part(bike.id, p), body.get("parts") or [])))
    db.session.commit()
    return jsonify(bike.serialize()), 201


@api.route("/bikes/<int:bike_id>", methods=["PUT"])
@jwt_required()
def update_bike(bike_id):
    user_id = current_user_id()
    bike = Bike.query.filter_by(id=bike_id, user_id=user_id).first()
    bike or _raise(APIException("Bike not found", status_code=404))
    body = request.get_json(silent=True) or {}

    "name" in body and setattr(bike, "name", body["name"].strip())
    "specs" in body and setattr(bike, "specs", body["specs"])
    "image_url" in body and setattr(bike, "image_url", body["image_url"])
    "video_url" in body and setattr(bike, "video_url", body["video_url"])
    "bike_model_id" in body and validate_and_set_bike_model(bike, body["bike_model_id"])
    "parts" in body and replace_bike_parts(bike.id, body["parts"])

    db.session.commit()
    return jsonify(bike.serialize()), 200


@api.route("/bikes/<int:bike_id>", methods=["DELETE"])
@jwt_required()
def delete_bike(bike_id):
    user_id = current_user_id()
    bike = Bike.query.filter_by(id=bike_id, user_id=user_id).first()
    bike or _raise(APIException("Bike not found", status_code=404))
    db.session.delete(bike)
    db.session.commit()
    return jsonify({"msg": "Bike deleted successfully"}), 200


# ──────────────────────────────────────────────────────────────────────────────
# GASTACOBRE AI CHAT
# ──────────────────────────────────────────────────────────────────────────────

@api.route("/ai/chat", methods=["POST"])
@jwt_required()
def ai_chat():
    try:
        body = request.get_json(silent=True) or {}
        messages: list[Any] = body.get("messages") or []
        context: dict = body.get("context") or {}
        user_profile: dict = body.get("user_profile") or {}
        route_context: dict = body.get("route_context") or {}

        (isinstance(messages, list) and len(messages) > 0) or _raise(
            APIException("messages debe ser una lista no vacía", status_code=400)
        )
        context = isinstance(context, dict) and context or {}

        recommendations = user_has_bike_intent(messages) and rank_bikes(context, load_catalog(), limit=3) or []
        clean_history = list(map(to_clean_message, filter(is_valid_chat_message, messages)))
        terrain_hint = route_context.get("terrain") or body.get("terrain") or "mtb"

        extra_context_messages = list(filter(None, [
            build_analyzed_route_context(route_context),
            build_osm_trails_context(last_user_message(clean_history), terrain_hint),
        ]))

        prompt = [
            {"role": "system", "content": _GASTACOBRE_SYSTEM_PROMPT},
            build_catalog_context(recommendations),
            build_profile_context(user_profile),
            *extra_context_messages,
            *clean_history,
        ]

        result = mistral_chat(prompt, temperature=0.4)
        raw_text = result.get("assistant_message", "").strip()

        raw_q_lines = re.findall(r"\[Q\d+\]\s*(.+)", raw_text)
        clean_text = re.sub(r"\[Q\d+\]\s*.+", "", raw_text).strip()
        clean_text = re.sub(r"__RECS_BLOCK__|__QUESTIONS__|__CHIPS__", "", clean_text).strip()
        next_questions = list(map(parse_question_line, raw_q_lines))

        return jsonify({
            "assistant_message": clean_text,
            "recommendations": recommendations,
            "next_questions": next_questions,
            "context": context,
        }), 200

    except APIException:
        raise
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# NEARBY SERVICES
# ──────────────────────────────────────────────────────────────────────────────

@api.route("/nearby-services", methods=["POST"])
def nearby_services():
    body = request.get_json(silent=True) or {}
    try:
        data = get_nearby_services_for_route(
            geojson_feature=body.get("geojson"),
            radius_m=int(body.get("radius_m") or 300),
            cache_ttl=60,
        )
        return jsonify(data), 200
    except Exception as e:
        msg = str(e)
        return (
            "429" in msg and (jsonify({"error": "Overpass rate limited (429). Espera unos segundos y prueba otra vez."}), 429)
            or (jsonify({"error": msg}), 500)
        )
