"""
Servicio para buscar rutas ciclistas en OpenStreetMap (Overpass API)
y geocodificar lugares con Mapbox.
"""
import os
import re
import requests
from itertools import islice
from operator import itemgetter
from typing import Any, cast
from urllib.parse import quote

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK = "https://overpass.kumi.systems/api/interpreter"

_TERRAIN_ROUTES = {
    "gravel":    ["bicycle"],
    "xc":        ["mtb"],
    "trail":     ["mtb"],
    "enduro":    ["mtb"],
    "downhill":  ["mtb"],
    "carretera": ["bicycle"],
}

_ROUTE_INTENT_WORDS = [
    "recomienda", "recomendar", "sugi", "ruta", "rutas",
    "trail", "sendero", "por dónde", "dónde ir", "dónde puedo",
    "itinerario", "circuito",
]

_LOCATION_RE = re.compile(
    r"\b(?:por|en|cerca\s+de|alrededor\s+de|en\s+la\s+zona\s+de|en\s+el)\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s\-]{2,40}?)(?=[,.\n]|$)",
    re.IGNORECASE,
)


def is_route_intent(message: str) -> bool:
    low = message.lower()
    return any(map(low.__contains__, _ROUTE_INTENT_WORDS))


def extract_location(message: str) -> str | None:
    m = _LOCATION_RE.search(message)
    return m and m.group(1).strip()


def geocode_place(name: str) -> dict | None:
    token = os.environ.get("MAPBOX_TOKEN", "")
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(name)}.json"
    try:
        features = (token and requests.get(
            url,
            params={"access_token": token, "limit": 1, "language": "es"},
            timeout=6,
        ).json().get("features", [])) or []
        first = next(iter(features), None)
        return first and {
            "lon": first["center"][0],
            "lat": first["center"][1],
            "display": first.get("place_name", name),
        }
    except Exception:
        return None


def _trail_from_element(el: dict) -> dict:
    tags = el.get("tags", {})
    from_to = (
        tags.get("from") and tags.get("to") and f"{tags['from']} → {tags['to']}"
        or tags.get("from") and f"desde {tags['from']}"
    )
    extras = dict(filter(itemgetter(1), [
        ("distance_km", tags.get("distance")),
        ("difficulty",  tags.get("mtb:scale") and f"escala {tags['mtb:scale']}/6"),
        ("ascent_m",    tags.get("ascent")),
        ("from_to",     from_to),
    ]))
    return {"name": tags.get("name", "").strip(), **extras}


def _try_fetch(url: str, query: str) -> list[Any] | None:
    try:
        r = requests.post(url, data={"data": query}, timeout=22)
        return cast(list | None, r.ok and r.json().get("elements", []) or None)
    except Exception:
        return None


def fetch_osm_trails(lat: float, lon: float, terrain: str, radius_m: int = 40000) -> list[dict]:
    route_types = _TERRAIN_ROUTES.get(terrain.lower(), ["mtb", "bicycle"])

    def _query_part(rt: str) -> str:
        return f'  relation["route"="{rt}"]["name"](around:{radius_m},{lat},{lon});'

    union_parts = "\n".join(map(_query_part, route_types))
    query = f"[out:json][timeout:20];\n(\n{union_parts}\n);\nout body;"

    elements = next(
        filter(None, map(lambda u: _try_fetch(u, query), (OVERPASS_URL, OVERPASS_FALLBACK))),
        [],
    )

    seen: set[str] = set()

    def _unique(el: dict) -> bool:
        name = el.get("tags", {}).get("name", "").strip()
        return bool(name) and name not in seen and not seen.add(name)

    return list(islice(map(_trail_from_element, filter(_unique, elements)), 12))


def _trail_line(t: dict) -> str:
    return " | ".join(filter(None, [
        f"• {t['name']}",
        t.get("distance_km") and f"{t['distance_km']} km",
        t.get("difficulty"),
        t.get("ascent_m") and f"+{t['ascent_m']}m desnivel",
        t.get("from_to"),
    ]))


def build_trails_system_message(location_name: str, trails: list[dict]) -> dict:
    lines = list(map(_trail_line, trails)) or [
        "(No se encontraron rutas en OSM para esta zona. Responde con tu conocimiento general.)"
    ]
    return {
        "role": "system",
        "content": (
            f"RUTAS EN OPENSTREETMAP CERCA DE {location_name.upper()}:\n"
            + "\n".join(lines)
            + "\n\nUsa estos datos reales para tu recomendación. "
            "Menciona el nombre exacto de cada ruta y sus características. "
            "Si hay pocas, complementa con conocimiento general de la zona."
        ),
    }
