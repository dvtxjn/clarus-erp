import ClarusLogo from "./ClarusLogo";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getBackupHealth } from "./api";
import { useAuth } from "./AuthContext";
import { ACCENTS, THEMES, savedAccent, savedTheme, setAccent, setTheme, type AccentId, type ThemeId } from "./accent";
import { SidebarSlotContext } from "./sidebarSlot";

// 16px line icons (stroke follows the text colour)
const icon = (d: ReactNode) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {d}
  </svg>
);
const ICONS = {
  dashboard: icon(<><rect x="2" y="2" width="5" height="5" rx="1" /><rect x="9" y="2" width="5" height="5" rx="1" /><rect x="2" y="9" width="5" height="5" rx="1" /><rect x="9" y="9" width="5" height="5" rx="1" /></>),
  shipments: icon(<><rect x="2" y="3" width="12" height="10" rx="1.5" /><path d="M2 6.5h12M6 6.5V13" /></>),
  rates: icon(<><path d="M3 2.5h7l3 3v8H3z" /><path d="M6 8h4M6 10.5h4" /></>),
  deleted: icon(<><path d="M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.7 9h6.6l.7-9" /></>),
  users: icon(<><circle cx="6" cy="5.5" r="2.5" /><path d="M1.5 13.5c.6-2.4 2.3-3.5 4.5-3.5s3.9 1.1 4.5 3.5M11 3.5a2.2 2.2 0 0 1 0 4.2M12.5 10.3c1 .5 1.7 1.6 2 3.2" /></>),
};

function Item({ to, label, i }: { to: string; label: string; i: keyof typeof ICONS }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")} title={label}>
      {ICONS[i]}
      <span className="nav-label">{label}</span>
    </NavLink>
  );
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const [accent, pickAccent] = useState<AccentId>(savedAccent);
  const [theme, pickTheme] = useState<ThemeId>(savedTheme);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  // sidebar can shrink to icons (more room for the tracker); remembered per browser
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("clarus.sidebar") === "collapsed";
    } catch {
      return false;
    }
  });
  const toggleSidebar = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem("clarus.sidebar", c ? "open" : "collapsed");
      } catch {
        /* private window */
      }
      return !c;
    });
  // admin: red banner when backups are late, shrank or failed (checked every 10 minutes)
  const [backupWarnings, setBackupWarnings] = useState<string[]>([]);
  useEffect(() => {
    if (user?.role !== "admin") return;
    const check = () => getBackupHealth().then((h) => setBackupWarnings(h.warnings)).catch(() => undefined);
    check();
    const id = window.setInterval(check, 600_000);
    return () => window.clearInterval(id);
  }, [user?.role]);

  const initials = (user?.full_name || user?.email || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="app-sidebar">
        <div className="app-brand">
          <span className="app-brand-logo">
            <ClarusLogo height={20} title="Clarus Logistics" />
          </span>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={toggleSidebar}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {icon(<><rect x="2" y="2.5" width="12" height="11" rx="1.5" /><path d="M6 2.5v11" /></>)}
          </button>
        </div>
        <nav className="app-nav">
          <Item to="/dashboard" label="Dashboard" i="dashboard" />
          <Item to="/shipments" label="Shipments" i="shipments" />
          {/* Invoicing is admin-only (client, 2026-09-29) */}
          {user?.role === "admin" && (
            <>
              <div className="app-nav-section">Admin</div>
              <Item to="/rates" label="Rates" i="rates" />
              <Item to="/users" label="Users" i="users" />
              <Item to="/deleted" label="Recently deleted" i="deleted" />
            </>
          )}
        </nav>
        {/* page tools (see sidebarSlot.tsx) */}
        <div className="app-sidebar-slot" ref={setSlot} />
        <div className="app-sidebar-foot">
          <div className="theme-switch" role="radiogroup" aria-label="Theme">
            {THEMES.map((t) => (
              <button
                key={t.id}
                type="button"
                role="radio"
                aria-checked={theme === t.id}
                className={theme === t.id ? "on" : ""}
                onClick={() => {
                  setTheme(t.id);
                  pickTheme(t.id);
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="accent-picker" title="Accent colour">
            Accent
            {ACCENTS.map((a) => (
              <button
                key={a.id}
                type="button"
                className={a.id === accent ? "on" : ""}
                style={{ background: a.color }}
                aria-label={a.label}
                title={a.label}
                onClick={() => {
                  setAccent(a.id);
                  pickAccent(a.id);
                }}
              />
            ))}
          </div>
          <div className="app-user">
            <span className="app-avatar">{initials}</span>
            <span className="app-user-text">
              <span className="app-user-name">{user?.full_name}</span>
              <span className="app-user-role">{user?.role.replace("_", " ")}</span>
            </span>
          </div>
          <button className="secondary app-logout" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="app-main">
        {backupWarnings.length > 0 && (
          <div className="backup-banner" role="alert">
            <strong>Backups:</strong> {backupWarnings.join(" ")}
          </div>
        )}
        {/* collapsed: page tools stay in the page itself */}
        <SidebarSlotContext.Provider value={collapsed ? null : slot}>
          <Outlet />
        </SidebarSlotContext.Provider>
      </main>
    </div>
  );
}
