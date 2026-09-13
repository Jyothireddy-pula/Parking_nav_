import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

type HealthStatus = "loading" | "ok" | "unreachable";

function useHealthCheck(): HealthStatus {
  const [status, setStatus] = useState<HealthStatus>("loading");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/health")
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`);
        return res.json();
      })
      .then(() => {
        if (!cancelled) setStatus("ok");
      })
      .catch(() => {
        if (!cancelled) setStatus("unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}

function PublicHome() {
  const health = useHealthCheck();
  const label =
    health === "loading" ? "Checking API…" : health === "ok" ? "API foundation online" : "API unreachable";

  return (
    <main className="shell">
      <p className="eyebrow">ParkingNav-X / Foundation</p>
      <h1>Campus parking, built on evidence.</h1>
      <p className="lede">The public application shell is ready. Operational modules will arrive in later releases.</p>
      <div className="status-row">
        <span className={`status-dot status-dot--${health}`} />
        <span>{label}</span>
      </div>
      <Link className="admin-link" to="/admin">Open admin</Link>
    </main>
  );
}

function AdminRouteGuard() {
  const isAuthenticated = false;
  return isAuthenticated ? <div>Admin workspace</div> : <Navigate replace to="/" />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PublicHome />} />
      <Route path="/admin/*" element={<AdminRouteGuard />} />
      <Route path="*" element={<Navigate replace to="/" />} />
    </Routes>
  );
}
