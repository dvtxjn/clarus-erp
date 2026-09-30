import { Link, useLocation } from "react-router-dom";

/** Unknown address (UX pass 2026-09-30): say so and offer a way back instead of silently jumping to the dashboard. */
export default function NotFoundPage() {
  const { pathname } = useLocation();
  return (
    <div className="not-found">
      <h1>Page not found</h1>
      <p>
        Nothing lives at <code translate="no">{pathname}</code>. The link may be old, or the shipment may have been deleted.
      </p>
      <div className="not-found-links">
        <Link to="/dashboard">Dashboard</Link>
        <Link to="/shipments">Shipments</Link>
      </div>
    </div>
  );
}
