import ClarusLogo from "./ClarusLogo";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function AppLayout() {
  const { user, logout } = useAuth();

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
      <main>
        <Outlet />
      </main>
    </div>
  );
}
