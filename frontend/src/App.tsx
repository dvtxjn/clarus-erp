import CustomsMailPage from "./CustomsMailPage";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { lazy, Suspense, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { ConfirmProvider } from "./ConfirmDialog";
import LoginPage from "./LoginPage";
import AppLayout from "./AppLayout";
import DashboardPage from "./DashboardPage";
import ShipmentGridPage from "./ShipmentGridPage";
import MobileShipmentList from "./MobileShipmentList";
import { usePhone } from "./usePhone";
import ShipmentDetailPage from "./ShipmentDetailPage";
import NotFoundPage from "./NotFoundPage";
import { UploadQueueProvider } from "./uploadQueue";

// admin-only pages load on first visit, so staff logins never download them
const InvoicesPage = lazy(() => import("./InvoicesPage"));
const RatesPage = lazy(() => import("./RatesPage"));
const UsersPage = lazy(() => import("./UsersPage"));
const SettingsPage = lazy(() => import("./SettingsPage"));
const HistoryPage = lazy(() => import("./HistoryPage"));
const DeletedPage = lazy(() => import("./DeletedPage"));

/** The tracker grid on a desk, shipment cards on a phone. */
function ShipmentsRoute() {
  return usePhone() ? <MobileShipmentList /> : <ShipmentGridPage />;
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Invoicing and Recently deleted are admin-only (the API refuses everyone else too). */
function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/shipments" replace />;
  return <Suspense fallback={<div className="tracker-empty">Loading…</div>}>{children}</Suspense>;
}

export default function App() {
  return (
    <AuthProvider>
      <ConfirmProvider>
      <BrowserRouter>
        <UploadQueueProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/shipments" element={<ShipmentsRoute />} />
            <Route path="/shipments/:id" element={<ShipmentDetailPage />} />
            <Route path="/customs-mail" element={<CustomsMailPage />} />
            <Route path="/invoices" element={<AdminRoute><InvoicesPage /></AdminRoute>} />
            <Route path="/rates" element={<AdminRoute><RatesPage /></AdminRoute>} />
            <Route path="/settings" element={<AdminRoute><SettingsPage /></AdminRoute>} />
            <Route path="/deleted" element={<AdminRoute><DeletedPage /></AdminRoute>} />
            <Route path="/history" element={<AdminRoute><HistoryPage /></AdminRoute>} />
            <Route path="/users" element={<AdminRoute><UsersPage /></AdminRoute>} />
            <Route path="/" element={<Navigate to="/shipments" replace />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
        </UploadQueueProvider>
      </BrowserRouter>
      </ConfirmProvider>
    </AuthProvider>
  );
}
