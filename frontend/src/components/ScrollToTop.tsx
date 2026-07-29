import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/** Resets scroll position on every route change — client-side routing doesn't do this by default. */
export function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}
