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

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <ConfirmProvider>
      <BrowserRouter>
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
            <Route path="/rates" element={<RatesPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
      </ConfirmProvider>
    </AuthProvider>
  );
}
