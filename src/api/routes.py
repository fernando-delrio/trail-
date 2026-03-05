"""
This module takes care of starting the API Server, Loading the DB and Adding the endpoints
"""
from flask import Flask, request, jsonify, url_for, Blueprint
from api.models import db, User, Bike, BikePart, BikeModel, SavedRoute
from api.utils import generate_sitemap, APIException, is_valid_email
from flask_cors import CORS
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from api.services.mistral_client import mistral_chat
from api.services.catalog import load_catalog, rank_bikes
from api.services.overpass_pois import get_nearby_services_for_route
from api.services.osm_trails import (
    is_route_intent, extract_location, geocode_place,
    fetch_osm_trails, build_trails_system_message,
)
from datetime import datetime, timezone
from uuid import uuid4


api = Blueprint('api', __name__)


# Allow CORS requests to this API
CORS(api)



@api.route('/hello', methods=['POST', 'GET'])
def handle_hello():

    response_body = {
        "message": "Hello! I'm a message that came from the backend, check the network tab on the google inspector and you will see the GET request"
    }

    return jsonify(response_body), 200


@api.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200



@api.route("/signup", methods=["POST"])
def signup():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email"}), 400
    if len(password) < 8:
        return jsonify({"msg": "Password must be at least 8 characters"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "User already exists"}), 409

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

    if not email or not password:
        return jsonify({"msg": "Missing email or password"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"msg": "Bad credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.serialize()}), 200



@api.route("/home", methods=["GET"])
@jwt_required()
def home():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    if not user:
        return jsonify({"msg": "user not found"}), 404

    home_data = {
        "user": user.serialize(),
        "weekly_kms": 42,
        "featured_routes": [
            {
                "id": 1,
                "name": "Ruta del Bosque",
                "Kms": 12
            },
            {
                "id": 2,
                "name": "Costa Norte",
                "Kms": 18
            },
        ],
        "friends_activity": [
            {
                "user": "Alex",
                "kms": 10
            },
            {
                "user": "Pablo",
                "kms": 25
            }
        ]
    }
    return jsonify(home_data), 200


@api.route("/profile", methods=["GET"])
@jwt_required()
def profile():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    return jsonify({"msg": "Access granted", "user": user.serialize()}), 200


@api.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    body = request.get_json(silent=True) or {}

    if "name" in body:
        name = (body.get("name") or "").strip()
        user.name = name or None

    if "location" in body:
        location = (body.get("location") or "").strip()
        user.location = location or None

    if "avatar" in body:
        avatar = body.get("avatar")
        user.avatar = avatar if isinstance(avatar, str) and avatar.strip() else None

    db.session.commit()
    return jsonify({"msg": "Profile updated", "user": user.serialize()}), 200


def _parse_created_at(raw_value):
    if not raw_value:
        return datetime.now(timezone.utc)

    if isinstance(raw_value, datetime):
        return raw_value

    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.now(timezone.utc)

    return datetime.now(timezone.utc)


@api.route("/saved-routes", methods=["GET"])
@jwt_required()
def list_saved_routes():
    user_id = int(get_jwt_identity())
    routes = SavedRoute.query.filter_by(user_id=user_id).order_by(SavedRoute.created_at.desc()).all()
    return jsonify([r.serialize() for r in routes]), 200


@api.route("/saved-routes/<string:route_id>", methods=["GET"])
@jwt_required()
def get_saved_route(route_id):
    user_id = int(get_jwt_identity())
    route = SavedRoute.query.filter_by(id=route_id, user_id=user_id).first()
    if not route:
        return jsonify({"msg": "Saved route not found"}), 404
    return jsonify(route.serialize()), 200


@api.route("/saved-routes", methods=["POST"])
@jwt_required()
def create_or_update_saved_route():
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    route_id = str(body.get("id") or uuid4())
    name = (body.get("name") or "Ruta guardada").strip()
    route_type = (body.get("type") or body.get("route_type") or "planned").strip().lower()
    terrain = (body.get("terrain") or "").strip() or None

    preview_coords = body.get("preview_coords")
    if preview_coords is not None and not isinstance(preview_coords, list):
        return jsonify({"msg": "preview_coords must be an array"}), 400

    route = SavedRoute.query.filter_by(id=route_id).first()
    if route and route.user_id != user_id:
        route = None
        route_id = str(uuid4())

    created = route is None
    if created:
        route = SavedRoute(id=route_id, user_id=user_id)
        db.session.add(route)

    route.name = name
    route.route_type = route_type
    route.terrain = terrain
    route.distance_km = body.get("distance_km")
    route.duration_min = body.get("duration_min")
    route.gain_m = body.get("gain_m")
    route.preview_coords = preview_coords
    route.bbox = body.get("bbox")
    route.created_at = _parse_created_at(body.get("created_at"))

    db.session.commit()
    return jsonify(route.serialize()), 201 if created else 200


@api.route("/saved-routes/<string:route_id>", methods=["DELETE"])
@jwt_required()
def delete_saved_route(route_id):
    user_id = int(get_jwt_identity())
    route = SavedRoute.query.filter_by(id=route_id, user_id=user_id).first()
    if not route:
        return jsonify({"msg": "Saved route not found"}), 404

    db.session.delete(route)
    db.session.commit()
    return jsonify({"msg": "Saved route deleted"}), 200


# ============================================
# BIKE MODELS ENDPOINTS
# ============================================

# GET todos los modelos
@api.route("/bike-models", methods=["GET"])
@jwt_required()
def get_bike_models():
    """Obtiene todos los modelos de bicicletas disponibles"""
    bike_type = request.args.get("type")
    
    query = BikeModel.query
    
    if bike_type:
        query = query.filter_by(bike_type=bike_type)
    
    models = query.order_by(BikeModel.brand, BikeModel.model_name).all()
    return jsonify([m.serialize() for m in models]), 200


# SEARCH - Buscar modelos
@api.route("/bike-models/search", methods=["GET"])
@jwt_required()
def search_bike_models():
    """Busca modelos por término (marca o nombre)"""
    search_term = request.args.get("q", "").strip()
    
    if not search_term or len(search_term) < 2:
        return jsonify({"msg": "Search term must be at least 2 characters"}), 400
    
    search_pattern = f"%{search_term}%"
    models = BikeModel.query.filter(
        db.or_(
            BikeModel.brand.ilike(search_pattern),
            BikeModel.model_name.ilike(search_pattern)
        )
    ).limit(20).all()
    
    return jsonify([m.serialize() for m in models]), 200


# GET tipos disponibles
@api.route("/bike-models/types", methods=["GET"])
@jwt_required()
def get_bike_types():
    """Obtiene todos los tipos de bicicleta disponibles"""
    types = db.session.query(BikeModel.bike_type).distinct().all()
    return jsonify({"types": [t[0] for t in types]}), 200


# POST crear nuevo modelo
@api.route("/bike-models", methods=["POST"])
@jwt_required()
def create_bike_model():
    """Crea un nuevo modelo de bicicleta (solo admin)"""
    body = request.get_json(silent=True) or {}
    
    brand = (body.get("brand") or "").strip()
    model_name = (body.get("model_name") or "").strip()
    bike_type = (body.get("bike_type") or "").strip()
    model_year = body.get("model_year")
    description = body.get("description")
    
    if not all([brand, model_name, bike_type]):
        return jsonify({"msg": "Brand, model_name, and bike_type are required"}), 400
    
    # Evitar duplicados
    existing = BikeModel.query.filter_by(
        brand=brand,
        model_name=model_name,
        model_year=model_year
    ).first()
    
    if existing:
        return jsonify({"msg": "This bike model already exists"}), 409
    
    bike_model = BikeModel(
        brand=brand,
        model_name=model_name,
        model_year=model_year,
        bike_type=bike_type,
        description=description
    )
    
    db.session.add(bike_model)
    db.session.commit()
    
    return jsonify(bike_model.serialize()), 201


# ============================================
# BIKES ENDPOINTS
# ============================================

# POST crear bike (ACTUALIZADO con bike_model_id)
@api.route("/bikes", methods=["POST"])
@jwt_required()
def create_bike():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    bike_model_id = body.get("bike_model_id")  # NUEVO
    model = (body.get("model") or "").strip()
    specs = body.get("specs")
    image_url = body.get("image_url")
    video_url = body.get("video_url")
    parts = body.get("parts") or []

    if not name:
        return jsonify({"msg": "Nombre es requerido"}), 400
    
    if not model:
        return jsonify({"msg": "Model es requerido"}), 400

    

    # Validar modelo si se proporciona
    if bike_model_id:
        bike_model = BikeModel.query.get(bike_model_id)
        if not bike_model:
            return jsonify({"msg": "Modelo no encontrado"}), 404

    bike = Bike(
        user_id=user.id,
        name=name,
        bike_model_id=bike_model_id,  # NUEVO
        model=model,
        specs=specs,
        image_url=image_url,
        video_url=video_url,
        is_active=False,
    )
    db.session.add(bike)
    db.session.flush()

    for p in parts:
        part = BikePart(
            bike_id=bike.id,
            part_name=p.get("part_name"),
            brand=p.get("brand"),
            model=p.get("model"),
            km_life=p.get("km_life") or 0,
            km_current=p.get("km_current") or 0,
            wear_percentage=p.get("wear_percentage") or 0,
        )
        db.session.add(part)

    db.session.commit()
    return jsonify(bike.serialize()), 201


# GET get bike
@api.route("/bikes", methods=["GET"])
@jwt_required()
def get_bikes():
    user_id = int(get_jwt_identity())
    bikes = Bike.query.filter_by(user_id=user_id).all()
    return jsonify([b.serialize() for b in bikes]), 200

# DELETE eliminar bike
@api.route("/bikes/<int:bike_id>", methods=["DELETE"])
@jwt_required()
def delete_bike(bike_id):
    user_id = int(get_jwt_identity())
    
    bike = Bike.query.filter_by(id=bike_id, user_id=user_id).first()
    if not bike:
        return jsonify({"msg": "Bike not found"}), 404
    
    db.session.delete(bike)
    db.session.commit()
    
    return jsonify({"msg": "Bike deleted successfully"}), 200

# PUT actualizar bike
@api.route("/bikes/<int:bike_id>", methods=["PUT"])
@jwt_required()
def update_bike(bike_id):
    user_id = int(get_jwt_identity())
    
    bike = Bike.query.filter_by(id=bike_id, user_id=user_id).first()
    if not bike:
        return jsonify({"msg": "Bike not found"}), 404
    
    body = request.get_json(silent=True) or {}

    model = (body.get("model") or "").strip() if "model" in body else None
    
    # Actualizar campos
    if "name" in body:
        bike.name = body["name"].strip()
    
    if "bike_model_id" in body:
        bike_model_id = body["bike_model_id"]
        if bike_model_id:
            bike_model = BikeModel.query.get(bike_model_id)
            if not bike_model:
                return jsonify({"msg": "Modelo de bici no encontrado"}), 404
            bike.bike_model_id = bike_model_id
        else:
            bike.bike_model_id = None

    
    if "specs" in body:
        bike.specs = body["specs"]
    
    if "image_url" in body:
        bike.image_url = body["image_url"]
    
    if "video_url" in body:
        bike.video_url = body["video_url"]
    
    # Actualizar partes si se envían
    if "parts" in body:
        # Eliminar partes antiguas
        BikePart.query.filter_by(bike_id=bike.id).delete()
        
        # Añadir nuevas partes
        for p in body["parts"]:
            part = BikePart(
                bike_id=bike.id,
                part_name=p.get("part_name"),
                brand=p.get("brand"),
                model=p.get("model"),
                km_life=p.get("km_life") or 0,
                km_current=p.get("km_current") or 0,
                wear_percentage=p.get("wear_percentage") or 0,
            )
            db.session.add(part)
    
    db.session.commit()
    return jsonify(bike.serialize()), 200


import re as _re

_BUY_RX = _re.compile(
    r"\b(bici|bicicleta|busco|quiero|comprar|recomienda|presupuesto|precio|trail|xc|enduro|dh|downhill|gravel|carretera|modalidad|terreno|montar|rueda|suspensión|horquilla|cuadro|componentes)\b",
    _re.IGNORECASE,
)
_MAINT_RX = _re.compile(
    r"\b(mantenimiento|desgaste|revisar|revisión|cambiar|pieza|piezas|estado|cadena|frenos|pastillas|llantas|rodamiento)\b",
    _re.IGNORECASE,
)

def _is_bike_intent(messages):
    """Devuelve True si el último mensaje del usuario habla de compra o mantenimiento de bicis."""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = m.get("content") or ""
            return bool(_BUY_RX.search(text) or _MAINT_RX.search(text))
    return False


@api.route("/ai/chat", methods=["POST"])
@jwt_required()
def ai_chat():
    try:
        import re
        body = request.get_json(silent=True) or {}
        messages = body.get("messages") or []
        context = body.get("context") or {}
        user_profile = body.get("user_profile") or {}
        route_context = body.get("route_context") or {}

        if not isinstance(messages, list) or len(messages) == 0:
            return jsonify({"error": "messages debe ser una lista no vacía"}), 400
        if not isinstance(context, dict):
            context = {}

        # 1) Rankear bicis solo cuando el usuario pregunta algo relacionado con bicis
        bike_intent = _is_bike_intent(messages)
        catalog = load_catalog()
        recommendations = rank_bikes(context, catalog, limit=3) if bike_intent else []

        # 2) Construir prompt para Mistral
        system = {
            "role": "system",
            "content": (
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
            ),
        }

        if recommendations:
            catalog_context = {
                "role": "system",
                "content": (
                    "RECOMMENDATIONS (del catálogo, no inventar):\n"
                    + "\n".join(
                        f"- {r['name']} | type={r.get('type')} | price={r.get('price_eur')}€ | url={r.get('url')}"
                        for r in recommendations
                    )
                ),
            }
        else:
            catalog_context = {
                "role": "system",
                "content": "RECOMMENDATIONS: ninguna (el usuario no está buscando bici ahora mismo).",
            }

        profile_lines = []
        if user_profile.get("name"):
            profile_lines.append(f"- Nombre: {user_profile['name']}")
        if user_profile.get("location"):
            profile_lines.append(f"- Ubicación: {user_profile['location']}")
        bikes = user_profile.get("bikes") or []
        for b in bikes[:5]:
            bike_label = f"{b.get('name')} ({b.get('model') or 'sin modelo'}, {b.get('km') or 0} km)"
            profile_lines.append(f"- Bici: {bike_label}")
            for p in (b.get("parts") or []):
                wear = p.get("wear") or 0
                km_c = p.get("km_current") or 0
                km_l = p.get("km_life") or 0
                brand_model = " ".join(filter(None, [p.get("brand"), p.get("name")]))
                profile_lines.append(f"  · {brand_model}: desgaste {wear}% ({km_c}/{km_l} km)")

        profile_context = {
            "role": "system",
            "content": "PERFIL DEL USUARIO:\n" + "\n".join(profile_lines) if profile_lines else "PERFIL DEL USUARIO: desconocido",
        }

        # Filtrar del historial los mensajes especiales antes de enviar a Mistral
        _SKIP = {"__RECS_BLOCK__", "__QUESTIONS__", "__CHIPS__"}
        clean_history = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in messages
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m.get("content") not in _SKIP
        ]

        # --- Contexto de ruta analizada ---
        extra_sys_messages = []

        if route_context.get("name") or route_context.get("terrain"):
            extra_sys_messages.append({
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
            })

        # --- Recomendación de rutas OSM ---
        last_user_msg = next(
            (m["content"] for m in reversed(clean_history) if m.get("role") == "user"),
            "",
        )
        if is_route_intent(last_user_msg):
            location_name = extract_location(last_user_msg)
            if location_name:
                terrain_hint = route_context.get("terrain") or body.get("terrain") or "mtb"
                geo = geocode_place(location_name)
                if geo:
                    trails = fetch_osm_trails(geo["lat"], geo["lon"], terrain_hint)
                    extra_sys_messages.append(
                        build_trails_system_message(geo["display"], trails)
                    )

        prompt = [system, catalog_context, profile_context] + extra_sys_messages + clean_history

        # 3) Llamar a Mistral
        result = mistral_chat(prompt, temperature=0.4)

        raw_text = result.get("assistant_message", "").strip()

        raw_q_lines = re.findall(r"\[Q\d+\]\s*(.+)", raw_text)
        clean_text = re.sub(r"\[Q\d+\]\s*.+", "", raw_text).strip()
        clean_text = re.sub(r"__RECS_BLOCK__|__QUESTIONS__|__CHIPS__", "", clean_text).strip()

        next_questions = []
        for line in raw_q_lines:
            parts = [p.strip() for p in line.split("|")]
            question_text = parts[0]
            options = [o for o in parts[1:] if o]
            next_questions.append({"question": question_text, "options": options})

        return jsonify(
            {
                "assistant_message": clean_text,
                "recommendations": recommendations,
                "next_questions": next_questions,
                "context": context,
            }
        ), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

from api.services.overpass_pois import get_nearby_services_for_route

@api.route("/nearby-services", methods=["POST"])
def nearby_services():
    body = request.get_json(silent=True) or {}

    geojson = body.get("geojson")
    radius_m = int(body.get("radius_m") or 300)

    try:
        data = get_nearby_services_for_route(
            geojson_feature=geojson,
            radius_m=radius_m,
            cache_ttl=60
        )
        return jsonify(data), 200

    except Exception as e:
        msg = str(e)

        
        if "429" in msg:
            return jsonify({"error": "Overpass rate limited (429). Espera unos segundos y prueba otra vez."}), 429

        return jsonify({"error": msg}), 500
import requests     
