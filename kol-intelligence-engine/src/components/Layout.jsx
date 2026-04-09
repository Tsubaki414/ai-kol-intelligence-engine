import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar.jsx";

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-64 text-text-muted font-mono text-xs">
      <span className="animate-pulse">Loading…</span>
    </div>
  );
}

export default function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg-base">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-y-auto flex flex-col">
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
