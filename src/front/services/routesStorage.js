import { session } from "./session";

const backendUrl = import.meta.env.VITE_BACKEND_URL;
const mapboxToken = import.meta.env.VITE_MAPBOX_TOKEN;

const getRouteCoords = (route) =>
  route?.preview_coords ||
  route?.coords ||
  route?.coordinates ||
  route?.geojson?.geometry?.coordinates ||
  route?.geojsonFeature?.geometry?.coordinates ||
  route?.geojsonLine?.geometry?.coordinates ||
  null;

const sanitizeCoords = (coords) => {
  if (!Array.isArray(coords)) return [];

  return coords
    .filter((point) => Array.isArray(point) && point.length >= 2)
    .map((point) => [Number(point[0]), Number(point[1])])
    .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
};

const sampleCoords = (coords, maxPoints = 120) => {
  if (coords.length <= maxPoints) return coords;
  const step = Math.ceil(coords.length / maxPoints);
  return coords.filter((_, index) => index % step === 0 || index === coords.length - 1);
};

const normalizeRoute = (route) => {
  if (!route || typeof route !== "object") return null;

  const id = route.id || route._id || String(Date.now());
  const name = route.name || route.title || "Ruta sin nombre";

  const createdAt =
    route.createdAt ||
    route.created_at ||
    route.date ||
    new Date().toISOString();

  const coords = getRouteCoords(route);

  return {
    id,
    type: route.type || route.route_type || "planned",
    name,
    terrain: route.terrain || null,
    distance_km: route.distance_km ?? route.distance ?? null,
    duration_min: route.duration_min ?? route.duration ?? null,
    gain_m: route.gain_m ?? null,
    bbox: route.bbox ?? null,
    preview_coords: Array.isArray(coords) ? coords : null,
    created_at: createdAt,
  };
};

const apiFetch = async (path, options = {}) => {
  const token = session.getToken();
  if (!token) throw new Error("No autenticado");
  if (!backendUrl) throw new Error("Falta VITE_BACKEND_URL");

  const headers = {
    Authorization: `Bearer ${token}`,
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const resp = await fetch(`${backendUrl}${path}`, {
    ...options,
    headers,
  });

  const data = await resp.json().catch(() => null);

  if (!resp.ok) {
    throw new Error(data?.msg || `HTTP ${resp.status}`);
  }

  return data;
};

export const getRoutePreviewImage = (route, size = { width: 640, height: 320 }) => {
  if (!mapboxToken) return null;

  const width = Number(size?.width) || 640;
  const height = Number(size?.height) || 320;
  const coords = sampleCoords(sanitizeCoords(getRouteCoords(route)));
  if (coords.length < 2) return null;

  const feature = {
    type: "Feature",
    properties: {
      stroke: "#3b82f6",
      "stroke-width": 5,
      "stroke-opacity": 0.9,
    },
    geometry: {
      type: "LineString",
      coordinates: coords,
    },
  };

  const overlay = `geojson(${encodeURIComponent(JSON.stringify(feature))})`;
  return `https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/${overlay}/auto/${width}x${height}?padding=24,24,24,24&access_token=${mapboxToken}`;
};

export const getRoutes = async () => {
  const data = await apiFetch("/api/saved-routes");
  return Array.isArray(data) ? data : [];
};

export const getRouteById = async (routeId) => {
  if (!routeId) return null;
  return apiFetch(`/api/saved-routes/${encodeURIComponent(routeId)}`);
};

export const saveRoute = async (route) => {
  const summary = normalizeRoute(route);
  if (!summary) return null;

  return apiFetch("/api/saved-routes", {
    method: "POST",
    body: JSON.stringify(summary),
  });
};

export const deleteRoute = async (routeId) => {
  if (!routeId) return;
  await apiFetch(`/api/saved-routes/${encodeURIComponent(routeId)}`, {
    method: "DELETE",
  });
};

export const clearRoutes = async () => {
  const routes = await getRoutes();
  await Promise.all(routes.map((route) => deleteRoute(route.id)));
  return [];
};
