import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar.jsx";

export default function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg-base">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-y-auto flex flex-col">
        <Outlet />
      </main>
    </div>
  );
}
