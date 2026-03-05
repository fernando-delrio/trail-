import React from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import Footer from "../components/Footer";
import { Loader } from "../components/Loader/Loader";
import { useLoader } from "../context/loaderContext";
import MainHeader from "../components/Header/MainHeader";
import ScrollToTop from "../components/ScrollToTop";
import { session } from "../services/session";
import { useUser } from "../context/UserContext";
import "../styles/footer.css";

export const Layout = () => {
  const { isLoading } = useLoader();
  const { isUserReady } = useUser();
  const location = useLocation();
  const navigate = useNavigate();

  const isLoggedIn = session.isLoggedIn();

  useEffect(() => {
    if (!isUserReady) return;

    if (location.pathname === "/") {
      navigate(isLoggedIn ? "/home" : "/login", { replace: true });
      return;
    }

    if (isLoggedIn && (location.pathname === "/login" || location.pathname === "/signup")) {
      navigate("/home", { replace: true });
    }
  }, [isLoggedIn, isUserReady, location.pathname, navigate]);

  if (!isUserReady) return null;

  const hideHeader =
    location.pathname === "/login" ||
    location.pathname === "/signup" ||
    location.pathname === "/about" ||
    location.pathname === "/explore" ||
    location.pathname === "/route-registration";

  const hideFooter =
    location.pathname === "/route-registration" ||
    location.pathname === "/explore" ||
    location.pathname === "/about";

  return (
    <>
      {isLoading && <Loader />}

      <div className={`app-root ${isLoading ? "is-loading" : ""}`}>
        {isLoggedIn && !hideHeader && <MainHeader />}

        <ScrollToTop location={location}>
          <Outlet />
        </ScrollToTop>

        {!hideFooter && <Footer />}
      </div>
    </>
  );
};
