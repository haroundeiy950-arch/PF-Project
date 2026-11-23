import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ThreatScreen from "./pages/ThreatScreen";
import Events from "./pages/Events";
import Alerts from "./pages/Alerts";
import Playback from "./pages/Playback";
import People from "./pages/People";
import Vehicles from "./pages/Vehicles";
import Automations from "./pages/Automations";
import Devices from "./pages/Devices";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";

function Splash() {
  return (
    <div className="boot-screen">
      <div className="boot-screen__mark">
        <span className="boot-screen__radar" />
      </div>
      <h1>SENTINEL AI</h1>
      <p>Establishing secure perimeter link…</p>
    </div>
  );
}

export default function App() {
  const { user, ready } = useAuth();

  if (!ready) return <Splash />;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/dashboard" replace />} />
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/threat" element={<ThreatScreen />} />
        <Route path="/threat/:incidentId" element={<ThreatScreen />} />
        <Route path="/events" element={<Events />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/playback" element={<Playback />} />
        <Route path="/people" element={<People />} />
        <Route path="/vehicles" element={<Vehicles />} />
        <Route path="/automations" element={<Automations />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
