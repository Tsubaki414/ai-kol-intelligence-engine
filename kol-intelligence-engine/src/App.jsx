import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import NetworkGraphPage from "./pages/NetworkGraphPage.jsx";
import Discovery from "./pages/Discovery.jsx";
import Profile from "./pages/Profile.jsx";
import Agent from "./pages/Agent.jsx";
import OutreachPanel from "./pages/OutreachPanel.jsx";
import ExportPage from "./pages/Export.jsx";
import Guilds from "./pages/Guilds.jsx";
import BriefGenerator from "./pages/BriefGenerator.jsx";
import CampaignSimulator from "./pages/CampaignSimulator.jsx";
import LighthouseIntegration from "./pages/LighthouseIntegration.jsx";
import OnChainVerification from "./pages/OnChainVerification.jsx";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/graph" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/graph" element={<NetworkGraphPage />} />
          <Route path="/discovery" element={<Discovery />} />
          <Route path="/profile/:id" element={<Profile />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/agent" element={<Agent />} />
          <Route path="/outreach" element={<OutreachPanel />} />
          <Route path="/export" element={<ExportPage />} />
          <Route path="/guilds" element={<Guilds />} />
          <Route path="/brief" element={<BriefGenerator />} />
          <Route path="/simulator" element={<CampaignSimulator />} />
          <Route path="/lighthouse" element={<LighthouseIntegration />} />
          <Route path="/onchain" element={<OnChainVerification />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
