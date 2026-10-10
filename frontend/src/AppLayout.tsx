import { useDismiss } from "./useDismiss";
import IdleLogout from "./IdleLogout";
import UpdateCheck from "./UpdateCheck";
import OverflowTip from "./OverflowTip";
import ClarusLogo from "./ClarusLogo";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { getBackupHealth } from "./api";
import { useAuth } from "./AuthContext";
import { setPresenceEnabled } from "./live";
import { ACCENTS, THEMES, savedAccent, savedTheme, setAccent, setTheme, type AccentId, type ThemeId } from "./accent";
import { SidebarSlotContext } from "./sidebarSlot";
import { useSandbox } from "./sandboxInfo";

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
  invoices: icon(<><path d="M4 1.5h8v13l-2-1.3-2 1.3-2-1.3-2 1.3z" /><path d="M6 5h4M6 7.5h4M6 10h2.5" /></>),
  deleted: icon(<><path d="M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.7 9h6.6l.7-9" /></>),
  settings: icon(<><circle cx="8" cy="8" r="2.2" /><path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1" /></>),
  mail: icon(<><rect x="1.5" y="3" width="13" height="10" rx="1.5" /><path d="M2 4l6 5 6-5" /></>),
  history: icon(<><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></>),
  users: icon(<><circle cx="6" cy="5.5" r="2.5" /><path d="M1.5 13.5c.6-2.4 2.3-3.5 4.5-3.5s3.9 1.1 4.5 3.5M11 3.5a2.2 2.2 0 0 1 0 4.2M12.5 10.3c1 .5 1.7 1.6 2 3.2" /></>),
};

// where each page was left (path + ?peek / ?tab / filters): going to the Dashboard and back reopens the
// shipment exactly as it was (client, 2026-10-10). Clicking the page you're already on starts it fresh.
const lastUrl = new Map<string, string>();
const sectionOf = (path: string) => path.split("/").filter(Boolean)[0] ?? "";

function useBackTo(to: string): string {
  const { pathname } = useLocation();
  const section = sectionOf(to);
  return sectionOf(pathname) === section ? to : lastUrl.get(section) ?? to;
}

function Item({ to, label, i }: { to: string; label: string; i: keyof typeof ICONS }) {
  const back = useBackTo(to);
  return (
    <NavLink to={back} className={({ isActive }) => (isActive ? "active" : "")} title={label}>
      {ICONS[i]}
      <span className="nav-label">{label}</span>
    </NavLink>
  );
}

function TabLink({ to, label, i }: { to: string; label: string; i: keyof typeof ICONS }) {
  const back = useBackTo(to);
  return (
    <NavLink to={back}>
      {ICONS[i]}
      <span>{label}</span>
    </NavLink>
  );
}

// browser tab title per page, e.g. "Shipments · Clarus ERP"
const PAGE_TITLES: Record<string, string> = {
  dashboard: "Dashboard", shipments: "Shipments", "customs-mail": "Customs mail", invoices: "Invoicing", rates: "Rates",
  users: "Users", history: "Change history", deleted: "Recently deleted", settings: "Settings",
};

export default function AppLayout() {
  const { user, logout } = useAuth();
  useEffect(() => setPresenceEnabled(!user?.read_only), [user?.read_only]);
  const { pathname, search } = useLocation();
  useEffect(() => {
    lastUrl.set(sectionOf(pathname), pathname + search);
  }, [pathname, search]);
  const [moreOpen, setMoreOpen] = useState(false); // phone: the "More" sheet
  useEffect(() => setMoreOpen(false), [pathname]);
  useDismiss(null, moreOpen, () => setMoreOpen(false));
  useEffect(() => {
    const [section, id] = pathname.split("/").filter(Boolean);
    const name = section === "shipments" && id ? "Shipment" : PAGE_TITLES[section ?? ""];
    document.title = name ? `${name} · Clarus ERP` : "Page not found · Clarus ERP";
  }, [pathname]);
  const [accent, pickAccent] = useState<AccentId>(savedAccent);
  const [theme, pickTheme] = useState<ThemeId>(savedTheme);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const appearanceBtn = useRef<HTMLButtonElement>(null);
  const appearancePop = useRef<HTMLDivElement>(null);
  const [appearanceAt, setAppearanceAt] = useState<{ left: number; bottom: number } | null>(null);
  // the menu sits on the page (portal), 6px above the ··· button; Esc, a click elsewhere or a page change closes it
  useLayoutEffect(() => {
    if (!appearanceOpen) return;
    const r = appearanceBtn.current?.getBoundingClientRect();
    if (r) setAppearanceAt({ left: Math.max(8, r.right - 220), bottom: window.innerHeight - r.top + 6 });
  }, [appearanceOpen]);
  useEffect(() => {
    if (!appearanceOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      setAppearanceOpen(false);
      appearanceBtn.current?.focus();
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!appearancePop.current?.contains(t) && !appearanceBtn.current?.contains(t)) setAppearanceOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [appearanceOpen]);
  useEffect(() => setAppearanceOpen(false), [pathname]);
  const sandbox = useSandbox();
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

  // browser chrome (mobile address bar) follows the theme background
  useEffect(() => {
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--color-bg").trim();
    let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.appendChild(meta);
    }
    if (bg) meta.content = bg;
  }, [theme]);

  const initials = (user?.full_name || user?.email || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
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
        <nav className="app-nav" aria-label="Main">
          {/* the tracker is the main screen (client, 2026-10-01); the dashboard comes second */}
          <Item to="/shipments" label="Shipments" i="shipments" />
          <Item to="/dashboard" label="Dashboard" i="dashboard" />
          <Item to="/customs-mail" label="Customs mail" i="mail" />
          {/* Invoicing is admin-only (client, 2026-09-29) */}
          {user?.role === "admin" && (
            <>
              <div className="app-nav-section">Admin</div>
              <Item to="/invoices" label="Invoicing" i="invoices" />
              <Item to="/rates" label="Rates" i="rates" />
              <Item to="/users" label="Users" i="users" />
              <Item to="/history" label="Change history" i="history" />
              <Item to="/deleted" label="Recently deleted" i="deleted" />
              <Item to="/settings" label="Settings" i="settings" />
            </>
          )}
        </nav>
        {/* page tools (see sidebarSlot.tsx) */}
        <div className="app-sidebar-slot" ref={setSlot} />
        {/* red alerts sit in the sidebar, where they are seen, not as a strip on top (client, 2026-10-08) */}
        {backupWarnings.length > 0 && (
          <div className="sidebar-alert" role="alert" title={`Backups: ${backupWarnings.join(" ")}`}>
            <span className="sidebar-alert-icon" aria-hidden="true">!</span>
            <span className="sidebar-alert-text">
              <strong>Backups</strong>
              {backupWarnings.join(" ")}
            </span>
          </div>
        )}
        <div className="app-sidebar-foot">
          {appearanceOpen && appearanceAt && createPortal(
            <div className="appearance-pop" id="appearance-pop" ref={appearancePop} role="dialog" aria-label="Appearance" style={appearanceAt}>
              <span className="appearance-pop-title">Appearance</span>
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
                    aria-pressed={a.id === accent}
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
            </div>,
            document.body,
          )}
          <div className="app-foot-row">
            <div className="app-user">
              <span className="app-avatar" aria-hidden="true">{initials}</span>
              <span className="app-user-text">
                <span className="app-user-name">{user?.full_name}</span>
                <span className="app-user-role">{user?.role.replace("_", " ")}</span>
              </span>
            </div>
            <button
              type="button"
              ref={appearanceBtn}
              className="appearance-toggle"
              aria-label="Appearance"
              title="Appearance"
              aria-expanded={appearanceOpen}
              aria-controls="appearance-pop"
              onClick={() => setAppearanceOpen((o) => !o)}
            >
              ···
            </button>
          </div>
          <button className="secondary app-logout" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      {/* phones: bottom tabs instead of the sidebar (thumb reach); the rest sits under "More" */}
      <nav className="m-tabbar" aria-label="Main">
        <TabLink to="/shipments" i="shipments" label="Shipments" />
        <TabLink to="/dashboard" i="dashboard" label="Dashboard" />
        {user?.role === "admin" && <TabLink to="/invoices" i="invoices" label="Invoicing" />}
        <button type="button" className={moreOpen ? "active" : ""} aria-expanded={moreOpen} onClick={() => setMoreOpen((o) => !o)}>
          {icon(<><circle cx="3.5" cy="8" r="1.1" /><circle cx="8" cy="8" r="1.1" /><circle cx="12.5" cy="8" r="1.1" /></>)}
          <span>More</span>
        </button>
      </nav>
      {moreOpen && (
        <div className="m-sheet-backdrop" onClick={() => setMoreOpen(false)}>
          <div className="m-sheet" role="dialog" aria-modal="true" aria-label="More" onClick={(e) => e.stopPropagation()}>
            <nav className="m-sheet-links" aria-label="More pages">
              <NavLink to="/customs-mail">{ICONS.mail}Customs mail</NavLink>
              {user?.role === "admin" && (
                <>
                  <NavLink to="/rates">{ICONS.rates}Rates</NavLink>
                  <NavLink to="/users">{ICONS.users}Users</NavLink>
                  <NavLink to="/history">{ICONS.history}Change history</NavLink>
                  <NavLink to="/deleted">{ICONS.deleted}Recently deleted</NavLink>
                  <NavLink to="/settings">{ICONS.settings}Settings</NavLink>
                </>
              )}
            </nav>
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
            <div className="m-sheet-user">
              <span>
                <strong>{user?.full_name}</strong> · {user?.role.replace("_", " ")}
              </span>
              <button className="secondary" onClick={logout}>
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
      <main className="app-main" id="main" tabIndex={-1}>
        {user?.read_only && (
          <div className="readonly-banner" role="status">
            View-only login — you can look at everything, but changes are switched off.
          </div>
        )}
        {sandbox.sandbox && (
          <div className="sandbox-banner" role="note">
            <strong>Sandbox</strong> — sample data to try the ERP. Nothing here is real; changes stay in the sandbox.
          </div>
        )}
        {backupWarnings.length > 0 && (
          // narrow screens have no side column: the strip on top stays there
          <div className="backup-banner" role="alert">
            <strong>Backups:</strong> {backupWarnings.join(" ")}
          </div>
        )}
        {/* collapsed: page tools stay in the page itself */}
        <SidebarSlotContext.Provider value={collapsed ? null : slot}>
          <Outlet />
          <IdleLogout />
          <UpdateCheck />
          <OverflowTip />
        </SidebarSlotContext.Provider>
      </main>
    </div>
  );
}
