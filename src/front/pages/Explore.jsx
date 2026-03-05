import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import { useNavigate } from "react-router-dom";

import MapView from "../components/Map/MapView";
import RouteRegistrationHeader from "../components/RouteRegistration/RouteRegistrationHeader";
import NearbyServicesDropdown from "../components/Map/NearbyServicesDropdown";
import AiChatDialog from "../components/AiChatDialog";

import useRoutePlanner from "../hooks/useRoutePlanner";
import { saveRoute } from "../services/routesStorage";
import { geocodePlace, reverseGeocodeLocality } from "../services/geocoding";
import {upsertNearbyServicesLayers,removeNearbyServicesLayers,} from "../utils/mapPois";

import "../styles/routeRegistration.css";


export default function Explore() {
  const navigate = useNavigate();

  const mapRef = useRef(null);
  const searchMarkerRef = useRef(null);

  const [hasSaved, setHasSaved] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);

  const [searchValue, setSearchValue] = useState("");
  const [searchError, setSearchError] = useState(null);
  const [savedMsg, setSavedMsg] = useState(null);

  const [activeFilter, setActiveFilter] = useState("gravel");
  const [routeName] = useState("RUTA");

  const [analyzeRoute, setAnalyzeRoute] = useState(null);
  const [servicesOpen, setServicesOpen] = useState(false);
  const [services, setServices] = useState(null);
  const [servicesError, setServicesError] = useState(null);
  const [enabledServiceKeys, setEnabledServiceKeys] = useState([
    "fuel",
    "food",
    "hospital",
    "bike",
  ]);

  const {
    waypoints,
    summary,
    error: planError,
    clear,
    attachMapClick,
    detachMapClick,
  } = useRoutePlanner(mapRef, "cycling");

  const canSave = useMemo(() => {
    const coords = summary?.geojsonLine?.geometry?.coordinates;
    return Array.isArray(coords) && coords.length >= 2;
  }, [summary]);

  useEffect(() => {
    return () => {
      detachMapClick();
      if (searchMarkerRef.current) searchMarkerRef.current.remove();
      if (mapRef.current) removeNearbyServicesLayers(mapRef.current);
    };
  }, [detachMapClick]);

  const runSearch = async () => {
    const q = (searchValue || "").trim();
    if (!q) return;

    try {
      setSearchError(null);
      const map = mapRef.current;
      if (!map) return;

      const c = map.getCenter?.();
      const proximity = c ? [c.lng, c.lat] : undefined;

      const result = await geocodePlace(q, {
        limit: 1,
        language: "es",
        country: "es",
        proximity,
      });

      if (!result) {
        setSearchError("No se encontraron resultados.");
        return;
      }

      const [lng, lat] = result.center;
      map.flyTo({ center: [lng, lat], zoom: 12, essential: true });

      if (searchMarkerRef.current) searchMarkerRef.current.remove();
      searchMarkerRef.current = new mapboxgl.Marker({ color: "#111827" })
        .setLngLat([lng, lat])
        .addTo(map);
    } catch (e) {
      setSearchError(String(e?.message ?? e));
    }
  };

  const toggleServices = async () => {
    if (!canSave) return;

    const map = mapRef.current;
    if (!map) return;

    if (servicesOpen) {
      setServicesOpen(false);
      setServicesError(null);
      removeNearbyServicesLayers(map);
      return;
    }

    if (services) {
      setServicesOpen(true);
      upsertNearbyServicesLayers(map, services, enabledServiceKeys);
      return;
    }

    try {
      setServicesError(null);

      const base = import.meta.env.VITE_BACKEND_URL;
      if (!base) throw new Error("Falta VITE_BACKEND_URL");

      const res = await fetch(`${base}/api/nearby-services`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          geojson: summary.geojsonLine,
          radius_m: 300,
          sample_every_m: 800,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);

      setServices(data);
      setServicesOpen(true);
      upsertNearbyServicesLayers(map, data, enabledServiceKeys);
    } catch (e) {
      setServicesError(String(e?.message ?? e));
      setServicesOpen(true);
    }
  };

  useEffect(() => {
    if (!servicesOpen || !services) return;
    const map = mapRef.current;
    if (!map) return;

    upsertNearbyServicesLayers(map, services, enabledServiceKeys);
  }, [enabledServiceKeys, servicesOpen, services]);

  const savePlannedRoute = async () => {
    if (!canSave) return;

    const coords = summary.geojsonLine.geometry.coordinates;
    const [sLng, sLat] = coords[0];
    const [eLng, eLat] = coords[coords.length - 1];

    const [startLoc, endLoc] = await Promise.all([
      reverseGeocodeLocality(sLng, sLat, { language: "es", country: "es" }),
      reverseGeocodeLocality(eLng, eLat, { language: "es", country: "es" }),
    ]);

    const autoName =
      startLoc && endLoc
        ? `${startLoc} → ${endLoc}`
        : startLoc
        ? `Desde ${startLoc}`
        : endLoc
        ? `Hasta ${endLoc}`
        : "Ruta planificada";

    const plannedRoute = {
      id: crypto.randomUUID?.() ?? `${Date.now()}`,
      type: "planned",
      name: autoName,
      terrain: activeFilter,
      distance_km: summary.distanceKm,
      duration_min: summary.durationMin,
      gain_m: null,
      preview_coords: coords,
      geojsonFeature: {
        type: "Feature",
        geometry: summary.geojsonLine.geometry,
        properties: {
          name: autoName,
          distanceKm: summary.distanceKm,
          durationMin: summary.durationMin,
          terrain: activeFilter,
        },
      },
      created_at: new Date().toISOString(),
    };

    try {
      await saveRoute(plannedRoute);
    } catch (e) {
      setSavedMsg(`Error guardando ruta: ${String(e?.message || e)}`);
      window.clearTimeout(savePlannedRoute._t);
      savePlannedRoute._t = window.setTimeout(() => setSavedMsg(null), 2200);
      return;
    }

    setHasStarted(false);
    setHasSaved(true);
    setServicesOpen(false);
    setServices(null);
    setServicesError(null);
    if (mapRef.current) removeNearbyServicesLayers(mapRef.current);

    clear();

    setSavedMsg("Ruta guardada");
    window.clearTimeout(savePlannedRoute._t);
    savePlannedRoute._t = window.setTimeout(() => setSavedMsg(null), 1200);
  };

  const distKm = summary?.distanceKm ?? 0;
  const durMin = summary?.durationMin ?? 0;

  return (
    <div className="rr-page">
      <MapView
        className="rr-map"
        center={[-0.52, 42.51]}
        zoom={12}
        onMapLoad={(map) => {
          mapRef.current = map;
          setTimeout(() => {
            map.doubleClickZoom?.disable?.();
            attachMapClick();
          }, 0);
        }}
      />

      <div className="rr-overlay-top">
        <RouteRegistrationHeader
          searchValue={searchValue}
          onSearchChange={setSearchValue}
          onSearchSubmit={runSearch}
          activeFilter={activeFilter}
          onFilterChange={setActiveFilter}
        />
      </div>

      <div className="rr-overlay-cards">
        {savedMsg && <div className="rr-toast">✅ {savedMsg}</div>}

        <div className="rr-card">
          <div className="rr-card-title">{routeName}</div>
          <div className="rr-card-subtitle">
            Terreno: {activeFilter.toUpperCase()} ·{" "}
            {hasStarted && !canSave ? "Haz clic en el mapa para añadir puntos" : canSave ? "Ruta lista" : "Listo"}
          </div>

          <div className="rr-card-metrics">
            <div className="rr-actions">
              <button
                className="ui-btn ui-btn--secondary"
                disabled={hasStarted}
                onClick={() => {
                  attachMapClick();
                  setHasStarted(true);
                  setHasSaved(false);
                }}
              >
                INICIAR
              </button>

              <button
                className="ui-btn ui-btn--secondary"
                onClick={() => navigate("/route-registration")}
              >
                ▶ GRABAR
              </button>

              <button
                className="ui-btn ui-btn--secondary"
                onClick={() => {
                  setServicesOpen(false);
                  setServices(null);
                  if (mapRef.current)
                    removeNearbyServicesLayers(mapRef.current);
                  clear();
                }}
              >
                LIMPIAR
              </button>

              <button
                className="ui-btn ui-btn--secondary"
                onClick={toggleServices}
                disabled={!canSave}
              >
                SERVICIOS
              </button>

              <button
                className="ui-btn ui-btn--secondary"
                onClick={savePlannedRoute}
                disabled={!canSave || hasSaved}
              >
                GUARDAR
              </button>

              <button
                className="ui-btn ui-btn--primary"
                disabled={!canSave}
                onClick={() =>
                  setAnalyzeRoute({
                    name: routeName,
                    type: "planned",
                    terrain: activeFilter,
                    distance_km: summary?.distanceKm ?? 0,
                    duration_min: summary?.durationMin ?? null,
                    gain_m: null,
                  })
                }
              >
                ANALIZAR
              </button>
            </div>

            <div className="rr-m-label">DIST.</div>
            <div className="rr-m-label">DESNIVEL</div>
            <div className="rr-m-label">TIEMPO</div>
            <div className="rr-m-label">RUTAS</div>

            <div className="rr-m-val">{distKm.toFixed(2)} km</div>
            <div className="rr-m-val">—</div>
            <div className="rr-m-val">{durMin.toFixed(0)} min</div>

            <span className="rr-link" onClick={() => navigate("/saved-routes")}>
              RUTAS
            </span>
          </div>

          {planError && (
            <div className="rr-error">
              Plan: {String(planError.message ?? planError)}
            </div>
          )}
        </div>
      </div>

      <NearbyServicesDropdown
        open={servicesOpen}
        data={services}
        error={servicesError}
        enabledKeys={enabledServiceKeys}
        onChangeEnabledKeys={setEnabledServiceKeys}
        onClose={() => {
          setServicesOpen(false);
          if (mapRef.current) removeNearbyServicesLayers(mapRef.current);
        }}
      />

      <AiChatDialog routeContext={analyzeRoute} />
    </div>
  );
}
