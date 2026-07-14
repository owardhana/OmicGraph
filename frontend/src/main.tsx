import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AdminDashboard from './components/AdminDashboard'
import Landing from './components/Landing'

// Hash-routed root (no router dependency, deployment-safe with static serving):
//   default        -> Landing (front door, Pillar 3b)
//   #/app          -> the 3D graph app
//   #/admin        -> Feature 2 P3 review dashboard (ADR-0014)
// Switching HERE (not inside App) means the 3D graph + its hooks never mount for the
// landing/admin views — no conditional-hooks trap.
type View = 'landing' | 'app' | 'admin';
function currentView(): View {
  const h = window.location.hash;
  if (h.startsWith('#/admin')) return 'admin';
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
  if (view === 'app') return <App />;
  return <Landing />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
