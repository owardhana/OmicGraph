import { useState } from 'react';

import './Landing.css';

// The five omics layers, bottom → top, with their canonical node colours (vision-and-mvp).
const LAYERS = [
  { name: 'Phenotype', sub: 'Disease', color: '#f472b6' },
  { name: 'Metabolomics', sub: 'Metabolite', color: '#22d3ee' },
  { name: 'Proteomics', sub: 'Protein', color: '#c084fc' },
  { name: 'Transcriptomics', sub: 'Transcript', color: '#60a5fa' },
  { name: 'Genomics', sub: 'Gene · Variant', color: '#4ade80' },
];

const STATS = [
  { value: '~622K', label: 'entities' },
  { value: '~2.04M', label: 'relationships' },
  { value: '5', label: 'omics layers' },
  { value: '15+', label: 'curated sources' },
];

function go(hash: string) {
  window.location.hash = hash;
}

export default function Landing() {
  const [adminOpen, setAdminOpen] = useState(false);

  return (
    <div className="landing">
      <header className="landing-nav">
        <span className="landing-wordmark">OmicGraph</span>
        <nav className="landing-nav-links">
          <a href="#/app">Explore</a>
          <a href="#/api">API</a>
          <button className="landing-admin-link" onClick={() => setAdminOpen((v) => !v)}>
            Admin
          </button>
        </nav>
      </header>

      {adminOpen && (
        <div className="admin-popover">
          <p>Admin dashboard is token-gated.</p>
          <button className="btn-primary" onClick={() => go('#/admin')}>
            Open admin →
          </button>
        </div>
      )}

      <main className="landing-hero">
        <div className="hero-copy">
          <h1>
            A navigable map of
            <br />
            <span className="hero-accent">molecular causality</span>
          </h1>
          <p className="hero-lede">
            One multi-omics knowledge graph — from TF binding through transcription,
            splicing, translation and signalling to metabolic output and disease.
            Tissue-segmented, evidence-scored, literature-cited.
          </p>
          <div className="hero-cta">
            <button className="btn-primary" onClick={() => go('#/app')}>
              Launch OmicGraph
            </button>
            <a className="btn-ghost" href="#/api">
              Developer API
            </a>
          </div>
          <div className="hero-stats">
            {STATS.map((s) => (
              <div key={s.label} className="stat">
                <span className="stat-value">{s.value}</span>
                <span className="stat-label">{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="hero-layers" aria-hidden="true">
          {LAYERS.map((l) => (
            <div key={l.name} className="layer-plane">
              <span className="layer-dot" style={{ background: l.color }} />
              <span className="layer-name">{l.name}</span>
              <span className="layer-sub">{l.sub}</span>
            </div>
          ))}
        </div>
      </main>

      <section id="mcp" className="landing-mcp">
        <h2>Programmatic access</h2>
        <p>
          OmicGraph exposes a read-only <strong>Model Context Protocol</strong> server and
          a <strong>REST API</strong> so agents and scripts can query the graph directly:
          entity search, semantic search, signal-decay neighbourhoods, shortest paths, and
          bounded subgraph export.
        </p>
        <ul className="mcp-tools">
          <li><code>search_graph</code></li>
          <li><code>semantic_search</code></li>
          <li><code>get_subgraph</code></li>
          <li><code>shortest_path</code></li>
          <li><code>export_subgraph</code></li>
        </ul>
        <p className="mcp-note">
          Read-only and rate-limited. Raw Cypher is not exposed. Whole-graph downloads are
          served as versioned data releases, not live endpoints.
        </p>
        <a className="btn-ghost" href="#/api">
          Read the API docs →
        </a>
      </section>

      <footer className="landing-footer">
        <span>OmicGraph — multi-omics knowledge graph of human biology</span>
      </footer>
    </div>
  );
}
