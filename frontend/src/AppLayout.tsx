import ClarusLogo from "./ClarusLogo";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getBackupHealth } from "./api";
import { useAuth } from "./AuthContext";

export default function AppLayout() {
  const { user, logout } = useAuth();
  // admin: red banner when backups are late, shrank or failed (checked every 10 minutes)
  const [backupWarnings, setBackupWarnings] = useState<string[]>([]);
  useEffect(() => {
    if (user?.role !== "admin") return;
    const check = () => getBackupHealth().then((h) => setBackupWarnings(h.warnings)).catch(() => undefined);
    check();
    const id = window.setInterval(check, 600_000);
    return () => window.clearInterval(id);
  }, [user?.role]);

  return (
    <div className="app-shell">
      <header className="app-topnav">
        <div className="app-topnav-left">
          <span className="app-brand">
            <ClarusLogo height={22} title="Clarus Logistics" />
          </span>
          <nav>
            <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
              Dashboard
            </NavLink>
            <NavLink to="/shipments" className={({ isActive }) => (isActive ? "active" : "")}>
              Shipments
            </NavLink>
            {/* Invoicing is admin-only (client, 2026-09-29) */}
            {user?.role === "admin" && (
              <>
                <NavLink to="/rates" className={({ isActive }) => (isActive ? "active" : "")}>
                  Rates
                </NavLink>
                <NavLink to="/deleted" className={({ isActive }) => (isActive ? "active" : "")}>
                  Recently deleted
                </NavLink>
              </>
            )}
          </nav>
        </div>
        <div className="app-topnav-right">
          <span className="app-user">
            {user?.full_name} · {user?.role.replace("_", " ")}
          </span>
          <button className="secondary" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      {backupWarnings.length > 0 && (
        <div className="backup-banner" role="alert">
          <strong>Backups:</strong> {backupWarnings.join(" ")}
        </div>
      )}
      <main>
        <Outlet />
      </main>
    </div>
  );
}
