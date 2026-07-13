import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AdminDashboard from './components/AdminDashboard'

// Hash-routed root: `#/admin` (Feature 2 P3 review dashboard, ADR-0014) vs the graph
// app. Switching HERE (not inside App) means the 3D graph + its hooks never mount for
// the admin view — no router dependency, no conditional-hooks trap.
function Root() {
  const [isAdmin, setIsAdmin] = useState(() =>
    window.location.hash.startsWith('#/admin'),
  );
  useEffect(() => {
    const onHash = () => setIsAdmin(window.location.hash.startsWith('#/admin'));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  return isAdmin ? <AdminDashboard /> : <App />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
