import { lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout.jsx";

const Dashboard          = lazy(() => import("./pages/Dashboard.jsx"));
const NetworkGraphPage   = lazy(() => import("./pages/NetworkGraphPage.jsx"));
const Discovery          = lazy(() => import("./pages/Discovery.jsx"));
const Profile            = lazy(() => import("./pages/Profile.jsx"));
const Agent              = lazy(() => import("./pages/Agent.jsx"));
const OutreachPanel      = lazy(() => import("./pages/OutreachPanel.jsx"));
const ExportPage         = lazy(() => import("./pages/Export.jsx"));
const Guilds             = lazy(() => import("./pages/Guilds.jsx"));
const BriefGenerator     = lazy(() => import("./pages/BriefGenerator.jsx"));
const CampaignSimulator  = lazy(() => import("./pages/CampaignSimulator.jsx"));
const LighthouseIntegration = lazy(() => import("./pages/LighthouseIntegration.jsx"));
const OnChainVerification   = lazy(() => import("./pages/OnChainVerification.jsx"));

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/outreach" replace />} />
          <Route path="/dashboard"  element={<Dashboard />} />
          <Route path="/graph"      element={<NetworkGraphPage />} />
          <Route path="/discovery"  element={<Discovery />} />
          <Route path="/profile/:id" element={<Profile />} />
          <Route path="/profile"    element={<Profile />} />
          <Route path="/agent"      element={<Agent />} />
          <Route path="/outreach"   element={<OutreachPanel />} />
          <Route path="/export"     element={<ExportPage />} />
          <Route path="/guilds"     element={<Guilds />} />
          <Route path="/brief"      element={<BriefGenerator />} />
          <Route path="/simulator"  element={<CampaignSimulator />} />
          <Route path="/lighthouse" element={<LighthouseIntegration />} />
          <Route path="/onchain"    element={<OnChainVerification />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
