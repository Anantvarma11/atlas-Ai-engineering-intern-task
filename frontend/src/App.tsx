import { Route, Routes, useLocation } from "react-router-dom";
import { Header } from "./components/Header";
import { ScrollToTop } from "./components/ScrollToTop";
import { Landing } from "./pages/Landing";
import { HotelList } from "./pages/HotelList";
import { HotelDetail } from "./pages/HotelDetail";
import { AdminPage } from "./pages/AdminPage";

function NotFound() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-24 text-center">
      <p className="text-4xl">🧭</p>
      <h1 className="mt-4 text-xl font-semibold text-ink-900">Page not found</h1>
    </div>
  );
}

function App() {
  const location = useLocation();
  const inApp = location.pathname.startsWith("/app");

  return (
    <div className={inApp ? "min-h-screen bg-ink-50" : "min-h-screen"}>
      <ScrollToTop />
      {inApp && <Header />}
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/app" element={<HotelList />} />
        <Route path="/app/hotels/:id" element={<HotelDetail />} />
        <Route path="/app/admin" element={<AdminPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  );
}

export default App;
