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
          <div className="rr-card-title">{routeName.toUpperCase()}</div>
          <div className="rr-card-sub">
            Terreno: <b>{activeFilter.toUpperCase()}</b>{" "}
            {isRecording ? "· Grabando…" : "· Listo"}
          </div>


          <div className="rr-actions">
            <button
              className={`ui-btn ${isRecording ? "ui-btn--danger" : "ui-btn--primary"}`}
              onClick={toggle}
            >
              {isRecording ? "■ DETENER" : "▶ INICIAR"}
            </button>

            <button
              className="ui-btn ui-btn--secondary"
              onClick={() => navigate("/explore")}
            >
              Planificar
            </button>

            <span className="rr-link" onClick={() => navigate("/saved-routes")}>
              RUTAS
            </span>
          </div>

          <div className="rr-card-metrics">

            {/* labels */}
            <div className="rr-m-label">DIST.</div>
            <div className="rr-m-label">DESNIVEL</div>
            <div className="rr-m-label">TIEMPO</div>
            <div className="rr-m-label">PUNTOS</div>

            {/* valores */}
            <div className="rr-m-val">{metrics.distanceKm.toFixed(2)} km</div>
            <div className="rr-m-val">{metrics.gainM} m</div>
            <div className="rr-m-val">—</div>
            <div className="rr-m-val">{points.length}</div>


          </div>



          {error && (
            <div className="rr-error">⚠️ GPS: {error}</div>
          )}

          <div style={{ display: "none" }}>
            {JSON.stringify({ points: points.length, geojsonLine })}
          </div>
        </div>
      </div>

    </div>
  );
}
