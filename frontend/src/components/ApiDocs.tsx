import { useState } from 'react';

import './ApiDocs.css';

// Dedicated developer documentation page (routed at #/api). Two programmatic
// surfaces, both read-only (ADR-0017): the MCP server (the intended external
// surface — leads the page) and the REST API the app itself uses. No auth /
// API-key layer exists yet (YAGNI, ADR-0017), so nothing about keys is documented.
// Host is shown as a placeholder because the deployed stack serves everything
// same-origin behind Caddy, while local dev splits the ports (called out below).

const HOST = '<omicgraph-host>';

const MCP_TOOLS = [
  {
    sig: 'search_graph(query: str, types?: string[])',
    desc: 'Find entities by name / HGNC symbol / rsid / description. Returns canonical ids (ensembl_id · uniprot_id · rsid · ontology_id · hmdb_id) to seed the other tools.',
    ret: '{ results: [{ id, kind, name, … }] }',
  },
  {
    sig: 'semantic_search(query: str, kinds?: string[])',
    desc: 'Find Gene / Protein / Disease by MEANING (embedding similarity) — for concept queries like “enzymes in glucose metabolism” rather than an exact name.',
    ret: '{ results: [{ id, kind, name, score }] }',
  },
  {
    sig: 'get_subgraph(seed_ids: string[], compartment_filter=false)',
    desc: 'Signal-decay neighbourhood around one or more seeds — what an entity connects to. Bounded by the traversal max_nodes cap. compartment_filter keeps only PPIs whose partners share a subcellular compartment (ADR-0015).',
    ret: '{ nodes: [...], edges: [...] }',
  },
  {
    sig: 'shortest_path(from_id, from_type, to_id, to_type)',
    desc: 'Shortest path (≤ 6 hops) between two entities — explains HOW they are connected. Types: gene · protein · transcript · variant · disease · metabolite.',
    ret: '{ path_found, path_quality, nodes, edges }',
  },
  {
    sig: 'export_subgraph(seed_ids: string[], fmt="json"|"csv")',
    desc: 'Bounded export of a seed neighbourhood for download. json = full nodes + edges; csv = edge list (source,rel_type,target). Whole-graph extraction is a separate versioned dump, never a live tool.',
    ret: 'string (JSON or CSV)',
  },
];

const REST_ENDPOINTS = [
  { m: 'GET', p: '/api/search?q=&limit=10', d: 'Mixed-entity search (gene / transcript / protein / disease).' },
  { m: 'GET', p: '/api/entities?q=&types=&limit=&offset=', d: 'Paged, filterable entity browser (chromosome · clinical · pli_min).' },
  { m: 'GET', p: '/api/gene/{symbol}', d: 'One gene by HGNC symbol.' },
  { m: 'GET', p: '/api/gene/{symbol}/graph?max_nodes=&compartment_filter=', d: 'Signal-decay neighbourhood around a gene.' },
  { m: 'GET', p: '/api/gene/{symbol}/cancer', d: 'COSMIC cancer-gene flags for a gene.' },
  { m: 'GET', p: '/api/disease/{ontology_id}/graph?max_nodes=', d: 'Neighbourhood around a disease (EFO id).' },
  { m: 'GET', p: '/api/metabolite/{id}  ·  /api/metabolite/{id}/graph', d: 'Metabolite node / neighbourhood (hmdb_id or chebi_id).' },
  { m: 'GET', p: '/api/transcript/{ensembl_tx_id}', d: 'One transcript by Ensembl id.' },
  { m: 'POST', p: '/api/graph/multi', d: 'Merge signal-decay traversals from many seeds. Body: { seed_ids, seed_types }.' },
  { m: 'GET', p: '/api/graph/path?from_id=&type_a=&to_id=&type_b=', d: 'Shortest path (≤ 6 hops) between two entities.' },
  { m: 'POST', p: '/api/chat/stream', d: 'Agentic chat over the graph (SSE stream). Body: { session_id, message }.' },
  { m: 'GET', p: '/health', d: 'Liveness probe.' },
];

const NODE_KINDS = [
  { kind: 'gene', id: 'ensembl_id (HGNC symbol for display)', color: '#4ade80' },
  { kind: 'transcript', id: 'ensembl_tx_id', color: '#60a5fa' },
  { kind: 'protein', id: 'uniprot_id', color: '#c084fc' },
  { kind: 'variant', id: 'rsid', color: '#2dd4bf' },
  { kind: 'metabolite', id: 'hmdb_id (chebi_id fallback)', color: '#22d3ee' },
  { kind: 'disease', id: 'ontology_id (EFO)', color: '#f472b6' },
];

const EDGE_TYPES =
  'REGULATES · PRODUCES · TRANSLATES_TO / ENCODES · INTERACTS_WITH · IN_GENE · ' +
  'ASSOCIATED_WITH · IMPLICATED_IN · DIFFERENTIALLY_EXPRESSED · CATALYSES · GENE_DISEASE_ASSOC';

const MCP_STDIO = `{
  "mcpServers": {
    "omicgraph": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"]
    }
  }
}`;

const MCP_REMOTE = `{
  "mcpServers": {
    "omicgraph": {
      "url": "https://${HOST}/mcp/sse"
    }
  }
}`;

const MCP_PYTHON = `import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("https://${HOST}/mcp/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print([t.name for t in tools.tools])

            hit = await session.call_tool("search_graph", {"query": "TP53"})
            print(hit)

            graph = await session.call_tool(
                "get_subgraph", {"seed_ids": ["ENSG00000141510"]}
            )
            print(graph)

asyncio.run(main())`;

const REST_CURL = `# Search across entities
curl "https://${HOST}/api/search?q=TP53&limit=5"

# One gene
curl "https://${HOST}/api/gene/TP53"

# Signal-decay neighbourhood around a gene
curl "https://${HOST}/api/gene/TP53/graph?max_nodes=150"

# Shortest path between two entities (gene seeds accept the HGNC symbol)
curl "https://${HOST}/api/graph/path?from_id=TP53&type_a=gene&to_id=EGFR&type_b=gene"

# Multi-seed merge (POST)
curl -X POST "https://${HOST}/api/graph/multi" \\
  -H "Content-Type: application/json" \\
  -d '{"seed_ids": ["TP53", "EGFR"], "seed_types": ["gene", "gene"]}'`;

const REST_PYTHON = `import requests

BASE = "https://${HOST}"

# neighbourhood around a gene
g = requests.get(f"{BASE}/api/gene/TP53/graph", params={"max_nodes": 150}).json()
print(len(g["nodes"]), "nodes", len(g["edges"]), "edges")

# shortest path (gene seeds take the HGNC symbol; other kinds take the machine id)
p = requests.get(f"{BASE}/api/graph/path", params={
    "from_id": "TP53", "type_a": "gene",
    "to_id": "EGFR", "type_b": "gene",
}).json()
print(p["path_quality"])`;

// In-page section jump. Plain `#mcp` anchors can't be used: the app is hash-routed
// (#/api, #/app, …), so setting the hash to `#mcp` would route away to the landing.
// Scroll the section into view instead, without touching the hash.
function jump(e: React.MouseEvent, id: string) {
  e.preventDefault();
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    });
  };
  return (
    <div className="code-block">
      {lang && <span className="code-lang">{lang}</span>}
      <button className="code-copy" onClick={copy}>
        {copied ? '✓ Copied' : 'Copy'}
      </button>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function ApiDocs() {
  return (
    <div className="apidocs">
      <header className="apidocs-nav">
        <a className="apidocs-wordmark" href="#/">
          OmicGraph
        </a>
        <nav className="apidocs-nav-links">
          <a href="#mcp" onClick={(e) => jump(e, 'mcp')}>MCP</a>
          <a href="#rest" onClick={(e) => jump(e, 'rest')}>REST</a>
          <a href="#model" onClick={(e) => jump(e, 'model')}>Data model</a>
          <a href="#/app">Launch app →</a>
        </nav>
      </header>

      <main className="apidocs-main">
        {/* --- intro ------------------------------------------------------ */}
        <section className="apidocs-hero">
          <span className="apidocs-eyebrow">Developer API</span>
          <h1>Query the graph programmatically</h1>
          <p className="apidocs-lede">
            OmicGraph exposes two read-only surfaces over the same multi-omics graph:
            a <strong>Model Context Protocol</strong> server for agents and MCP clients,
            and a <strong>REST API</strong> for scripts and services. Both are
            rate-limited and capped by a 60&nbsp;second query timeout. Raw Cypher is
            never exposed; whole-graph extraction is a separate versioned data release.
          </p>
          <div className="apidocs-callout">
            <strong>Base URL.</strong> The deployed stack serves the app,{' '}
            <code>/api</code> and <code>/mcp</code> same-origin behind Caddy — replace{' '}
            <code>https://{HOST}</code> below with the site origin. In local
            development the backend runs on <code>http://localhost:8000</code> (REST at{' '}
            <code>/api</code>, MCP at <code>/mcp/sse</code>) and browser cross-origin
            calls are restricted by CORS — drive REST from curl, Python, or another
            server rather than browser JavaScript.
          </div>
        </section>

        {/* --- MCP -------------------------------------------------------- */}
        <section id="mcp" className="apidocs-section">
          <h2>MCP server</h2>
          <p>
            The intended surface for agents. Point any MCP client at OmicGraph over
            stdio (local) or SSE (remote) and it gains five typed graph tools — no
            glue code, no Cypher.
          </p>

          <h3>Connect</h3>
          <div className="apidocs-cols">
            <div>
              <p className="apidocs-mini">Local — stdio</p>
              <CodeBlock code={MCP_STDIO} lang="json" />
            </div>
            <div>
              <p className="apidocs-mini">Remote — SSE</p>
              <CodeBlock code={MCP_REMOTE} lang="json" />
            </div>
          </div>

          <h3>Tools</h3>
          <div className="tool-list">
            {MCP_TOOLS.map((t) => (
              <div key={t.sig} className="tool">
                <code className="tool-sig">{t.sig}</code>
                <p className="tool-desc">{t.desc}</p>
                <span className="tool-ret">
                  returns <code>{t.ret}</code>
                </span>
              </div>
            ))}
          </div>

          <h3>Example — Python</h3>
          <CodeBlock code={MCP_PYTHON} lang="python" />
        </section>

        {/* --- REST ------------------------------------------------------- */}
        <section id="rest" className="apidocs-section">
          <h2>REST API</h2>
          <p>
            The same endpoints the OmicGraph frontend uses. All responses are JSON;
            all traversal endpoints are bounded by the <code>max_nodes</code> guardrail.
          </p>

          <div className="endpoint-table">
            {REST_ENDPOINTS.map((e) => (
              <div key={e.p} className="endpoint">
                <span className={`method method-${e.m.toLowerCase()}`}>{e.m}</span>
                <code className="endpoint-path">{e.p}</code>
                <span className="endpoint-desc">{e.d}</span>
              </div>
            ))}
          </div>

          <h3>Example — curl</h3>
          <CodeBlock code={REST_CURL} lang="bash" />

          <h3>Example — Python</h3>
          <CodeBlock code={REST_PYTHON} lang="python" />
        </section>

        {/* --- data model ------------------------------------------------- */}
        <section id="model" className="apidocs-section">
          <h2>Data model</h2>
          <p>
            Six entity kinds, each with a canonical machine id you pass to the tools
            and endpoints above. Seed with a gene’s HGNC symbol; every other kind takes
            its machine id.
          </p>
          <div className="kind-grid">
            {NODE_KINDS.map((k) => (
              <div key={k.kind} className="kind">
                <span className="kind-dot" style={{ background: k.color }} />
                <span className="kind-name">{k.kind}</span>
                <code className="kind-id">{k.id}</code>
              </div>
            ))}
          </div>
          <p className="apidocs-mini" style={{ marginTop: 20 }}>
            Edge types
          </p>
          <p className="edge-types">{EDGE_TYPES}</p>
        </section>

        {/* --- limits ----------------------------------------------------- */}
        <section className="apidocs-section">
          <h2>Limits &amp; bulk data</h2>
          <ul className="limit-list">
            <li>Read-only. No write, no raw Cypher, no authentication key required (today).</li>
            <li>Every query is capped by a 60&nbsp;second Neo4j transaction timeout.</li>
            <li>
              Traversal responses are bounded by the <code>max_nodes</code> cap — there
              is no unbounded neighbourhood or whole-graph tool.
            </li>
            <li>
              Need the whole graph? That ships as a pre-baked, versioned dump (a static
              download), not a live endpoint.
            </li>
          </ul>
        </section>
      </main>

      <footer className="apidocs-footer">
        <span>OmicGraph — read-only developer API · ADR-0017</span>
        <a href="#/">← Back to home</a>
      </footer>
    </div>
  );
}
