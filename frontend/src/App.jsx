import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Navbar from "./components/Navbar";
import PurgePage from "./pages/PurgePage";
import DashboardPage from "./pages/DashboardPage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";
import SetupGuidePage from "./pages/SetupGuidePage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-8">
          <Routes>
            <Route path="/" element={<Navigate to="/purge" />} />
            <Route path="/purge" element={<PurgePage />} />
            <Route path="/dashboard/:jobId" element={<DashboardPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/setup-guide" element={<SetupGuidePage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
