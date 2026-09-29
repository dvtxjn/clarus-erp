import ClarusLogo from "./ClarusLogo";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "./AuthContext";
import { forgotPassword } from "./api";
import { useSandbox } from "./sandboxInfo";

export default function LoginPage() {
  const sandbox = useSandbox();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const [resetNote, setResetNote] = useState<string | null>(null);

  // Passwords are set by the admin: this only tells them (client, 2026-09-29)
  async function requestReset() {
    if (!email.trim()) {
      setResetNote("Type your email above first, then press Forgot password.");
      return;
    }
    try {
      await forgotPassword(email.trim());
    } catch {
      /* same answer either way */
    }
    setResetNote("Your admin has been told — they'll set a new password and give it to you.");
  }
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" && err && axios.isAxiosError(err) && err.response?.status !== 401
        ? detail // locked out / too many attempts / switched off
        : "Incorrect email or password.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1 className="auth-logo">
          <ClarusLogo height={40} title="Clarus Logistics" />
        </h1>
        <p className="auth-subtitle">Sign in to your ERP</p>
        {sandbox.sandbox && (
          <div className="sandbox-login">
            <strong>Sandbox — sample data</strong>
            <span>Nothing here is real. Ask the admin for the sandbox login.</span>
          </div>
        )}

        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoFocus
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && <div className="auth-error">{error}</div>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <button type="button" className="link-btn auth-forgot" onClick={requestReset}>
          Forgot password?
        </button>
        {resetNote && <div className="field-note">{resetNote}</div>}
      </form>
    </div>
  );
}
