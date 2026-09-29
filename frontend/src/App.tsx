import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { ConfirmProvider } from "./ConfirmDialog";
import LoginPage from "./LoginPage";
import AppLayout from "./AppLayout";
import DashboardPage from "./DashboardPage";
import ShipmentGridPage from "./ShipmentGridPage";
import ShipmentDetailPage from "./ShipmentDetailPage";
import RatesPage from "./RatesPage";
import DeletedPage from "./DeletedPage";
import UsersPage from "./UsersPage";
import InvoicesPage from "./InvoicesPage";
import SettingsPage from "./SettingsPage";
import { UploadQueueProvider } from "./uploadQueue";

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Invoicing and Recently deleted are admin-only (the API refuses everyone else too). */
function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
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
            <Route path="/shipments" element={<ShipmentGridPage />} />
            <Route path="/shipments/:id" element={<ShipmentDetailPage />} />
            <Route path="/invoices" element={<AdminRoute><InvoicesPage /></AdminRoute>} />
            <Route path="/rates" element={<AdminRoute><RatesPage /></AdminRoute>} />
            <Route path="/settings" element={<AdminRoute><SettingsPage /></AdminRoute>} />
            <Route path="/deleted" element={<AdminRoute><DeletedPage /></AdminRoute>} />
            <Route path="/users" element={<AdminRoute><UsersPage /></AdminRoute>} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
        </UploadQueueProvider>
      </BrowserRouter>
      </ConfirmProvider>
    </AuthProvider>
  );
}
