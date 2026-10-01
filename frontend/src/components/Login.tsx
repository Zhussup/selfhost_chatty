import { useState } from "react";
import { useStore } from "../state";

export default function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      await useStore.getState().login(password);
    } catch (err) {
      setError(err instanceof Error && err.message === "unauthorized" ? "Wrong password" : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>Chat</h1>
        <p className="muted">Self-hosted · powered by Ollama Cloud</p>
        <input
          type="password"
          autoFocus
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !password}>
          {busy ? "Logging in…" : "Log in"}
        </button>
        {error && <div className="form-error">{error}</div>}
      </form>
    </div>
  );
}