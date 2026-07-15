import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AdminDashboard from './components/AdminDashboard'
import ApiDocs from './components/ApiDocs'
import Landing from './components/Landing'

// Hash-routed root (no router dependency, deployment-safe with static serving):
//   default        -> Landing (front door, Pillar 3b)
//   #/app          -> the 3D graph app
//   #/api          -> developer API documentation
//   #/admin        -> Feature 2 P3 review dashboard (ADR-0014)
// Switching HERE (not inside App) means the 3D graph + its hooks never mount for the
// landing/admin/docs views — no conditional-hooks trap.
type View = 'landing' | 'app' | 'api' | 'admin';
function currentView(): View {
  const h = window.location.hash;
  if (h.startsWith('#/admin')) return 'admin';
  if (h.startsWith('#/api')) return 'api';
  if (h.startsWith('#/app')) return 'app';
  return 'landing';
}
function Root() {
  const [view, setView] = useState<View>(currentView);
  useEffect(() => {
    const onHash = () => setView(currentView());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  if (view === 'admin') return <AdminDashboard />;
  if (view === 'api') return <ApiDocs />;
  if (view === 'app') return <App />;
  return <Landing />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
