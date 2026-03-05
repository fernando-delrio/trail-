import React from "react";
import { useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { saveRoute } from "../services/routesStorage";
import useRouteRecorder from "../hooks/useRouteRecorder";

import MapView from "../components/Map/MapView";
import RouteRegistrationHeader from "../components/RouteRegistration/RouteRegistrationHeader";

import "../styles/routeRegistration.css";

export default function RouteRegistration() {
  const navigate = useNavigate();
  const [searchValue, setSearchValue] = useState("");
  const [activeFilter, setActiveFilter] = useState("gravel");
  const [routeName] = useState("Ruta");
  const [routeSaved, setRouteSaved] = useState(false);



  const mapRef = useRef(null);


  const { isRecording, points, currentPos, metrics, geojsonLine, toggle, onMapReady, error } =
    useRouteRecorder(mapRef);


  // guardar la ruta cuando se deja de grabar

  const prevIsRecording = useRef(false);

  useEffect(() => {

    if (prevIsRecording.current && !isRecording) {
      const coords = geojsonLine?.geometry?.coordinates;


      if (Array.isArray(coords) && coords.length >= 2) {
        const makeId = () => {
          try {
            return crypto.randomUUID();
          } catch {
            return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
          }
        };

        const payload = {
          id: makeId(),
          type: "recorded",
          name: routeName,
          terrain: activeFilter,
          distance_km: metrics.distanceKm,
          duration_min: null,
          gain_m: metrics.gainM,
          preview_coords: coords,
          created_at: new Date().toISOString(),
        };

        saveRoute(payload)
          .then(() => {
            setRouteSaved(true);
            setTimeout(() => setRouteSaved(false), 2500);
          })
          .catch((error) => {
            console.error("Error saving recorded route:", error);
          });

      }
    }

    prevIsRecording.current = isRecording;
  }, [isRecording, geojsonLine, metrics.distanceKm, metrics.gainM, routeName, activeFilter]);


  return (
    <div className="rr-page">
      <MapView
        className="rr-map"
        center={[-0.52, 42.51]}
        zoom={12}
        onMapLoad={(map) => {
          mapRef.current = map;
          onMapReady(map);
          requestAnimationFrame(() => map.resize());
          setTimeout(() => map.resize(), 150);
        }}
      />

      <button
        className="rr-back-btn"
        onClick={() => navigate("/home")}
        aria-label="Volver al inicio"
      >
        ← Home
      </button>

      <div className="rr-overlay-top">
        <RouteRegistrationHeader
          searchValue={searchValue}
          onSearchChange={setSearchValue}
          onSearchSubmit={() => { }}
          activeFilter={activeFilter}
          onFilterChange={setActiveFilter}
        />

      </div>

      <div className="rr-overlay-cards">
        <div className="rr-card">

          <div className="rr-card-head">
            <div className="rr-card-title">{routeName.toUpperCase()}</div>
            <div className="rr-card-badge">
              {activeFilter.toUpperCase()} · {isRecording ? "Grabando…" : "Listo"}
            </div>
          </div>

          <div className="rr-metrics-sport">
            <div className="rr-metric-box">
              <div className="rr-metric-box-label">Distancia</div>
              <div className="rr-metric-box-val">{metrics.distanceKm.toFixed(2)}</div>
              <div className="rr-metric-box-unit">km</div>
            </div>
            <div className="rr-metric-box">
              <div className="rr-metric-box-label">Desnivel</div>
              <div className="rr-metric-box-val">{metrics.gainM}</div>
              <div className="rr-metric-box-unit">m</div>
            </div>
          </div>

          <div className="rr-metrics-secondary">
            <div className="rr-metric-mini">
              <span className="rr-metric-mini-label">Puntos GPS</span>
              <span className="rr-metric-mini-val">{points.length}</span>
            </div>
            <div className="rr-metric-mini">
              <span className="rr-metric-mini-label">Tiempo</span>
              <span className="rr-metric-mini-val">—</span>
            </div>
          </div>

          <button
            className={`rr-record-btn-sport ${isRecording ? "rr-record-btn-sport--stop" : "rr-record-btn-sport--start"}`}
            onClick={toggle}
          >
            {isRecording ? "■ Detener grabación" : "▶ Iniciar grabación"}
          </button>

          <div className="rr-actions-row">
            <button
              className="ui-btn ui-btn--secondary"
              style={{ flex: 1, padding: "8px 6px", fontSize: 11, minHeight: "auto", borderRadius: 10 }}
              onClick={() => navigate("/explore")}
            >
              Planificar ruta
            </button>
            <span className="rr-link" onClick={() => navigate("/saved-routes")}>
              RUTAS →
            </span>
          </div>

          {error && (
            <div className="rr-error" style={{ marginTop: 8 }}>⚠️ GPS: {error}</div>
          )}

          <div style={{ display: "none" }}>
            {JSON.stringify({ points: points.length, geojsonLine })}
          </div>
        </div>
      </div>

    </div>
  );
}
