import "../../styles/featuredRoutes.css";
import { useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { getRoutePreviewImage, getRoutes } from "../../services/routesStorage.js";


const FeaturedRoutes = () => {
  const navigate = useNavigate();
  const [routes, setRoutes] = useState([]);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    const load = async () => {
      try {
        const saved = await getRoutes();
        if (!cancelledRef.current) setRoutes(saved.slice(0, 5));
      } catch {
        if (!cancelledRef.current) setRoutes([]);
      }
    };

    load();

    return () => {
      cancelledRef.current = true;
    };
  }, []);

  return (
    <section className="featured-routes home-section ui-panel">
      <div className="featured-header">
        <h2 className="ui-subtitle">Rutas destacadas</h2>

        <button
          className="ui-btn ui-btn--secondary"
          onClick={() => navigate("/saved-routes")}
        >
          Ver todas
        </button>
      </div>

      <div className="featured-list">
        {routes.map((route) => {
          const previewImage = route.image || getRoutePreviewImage(route);

          return (
            <article key={route.id} className="route-card clickable" onClick={() => navigate(`/saved-routes/${route.id}`)}>
              {previewImage ? (
                <img src={previewImage} alt={route.name} />
              ) : (
                <div className="route-card-image-placeholder" aria-hidden="true" />
              )}

              <div className="route-info">
                <div className="route-tags">
                  <span className="tag">{route.terrain}</span>
                </div>

                <h3>{route.name}</h3>

                <div className="route-stats">
                  <span>{route.distance_km.toFixed(1)} km</span>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
};

export default FeaturedRoutes;
