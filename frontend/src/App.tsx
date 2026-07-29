import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { ScrollToTop } from "./components/ScrollToTop";
import { HotelList } from "./pages/HotelList";
import { HotelDetail } from "./pages/HotelDetail";

function App() {
  return (
    <div className="min-h-screen bg-ink-50">
      <ScrollToTop />
      <Header />
      <Routes>
        <Route path="/" element={<HotelList />} />
        <Route path="/hotels/:id" element={<HotelDetail />} />
        <Route
          path="*"
          element={
            <div className="mx-auto max-w-5xl px-4 py-24 text-center">
              <p className="text-4xl">🧭</p>
              <h1 className="mt-4 text-xl font-semibold text-ink-900">Page not found</h1>
            </div>
          }
        />
      </Routes>
    </div>
  );
}

export default App;
