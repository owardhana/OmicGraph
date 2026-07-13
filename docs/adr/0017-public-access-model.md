# ADR 0017 — Public access model: open website, key-gated MCP, no public `run_cypher`

Status: Accepted (planned — `feat/omicgraph-next-phase`)

Fixes who can reach what as OmicGraph opens to the public and grows an MCP server for
programmatic / agent access + user-requested export. Builds on the deployment shape
(Neo4j loopback-bound, backend private, Caddy sole public ingress — see
[oracle-runbook](../deploy/oracle-runbook.md)) and the admin gate of
[ADR-0014](0014-literature-review-dashboard.md).

## Context

The ChatAgent already exposes five **read-only** graph tools (`search`, `semantic_search`,
`subgraph`, `shortest_path`, validator-gated `run_cypher`). "MCP integration" is ~90%
re-transport of these + bounded export — not new capability. But a public surface changes
the threat model: arbitrary read-only queries are still a **DoS vector**, and the current
admin gate **fails *open*** when `ADMIN_TOKEN` is unset (`.env.example`: *"Empty=open
(local dev)"*) — dangerous on a public host.

## Decision

1. **Website: open + anonymous**, protected by a per-IP rate limit. (An earlier draft
   gated all browsing behind a key; reversed — adoption friction outweighs the benefit for
   read-only public biology.)
2. **MCP API: free API key required**, with a per-key quota. Keys are **hashed at rest**;
   issuance is self-serve from the landing page.
3. **`run_cypher` is omitted from *every* public surface** (website and MCP). Even
   read-only, an arbitrary Cypher endpoint lets a caller author expensive queries. The
   public tool set is `search`, `semantic_search`, `subgraph`, `shortest_path`, plus
   **bounded export**. `run_cypher` remains internal (validator-gated) only.
4. **Export is bounded** (~`TRAVERSAL_MAX_NODES`); the whole-graph download is a **separate
   pre-baked, versioned dump** (static link), never a live full-graph endpoint (scraping /
   DoS).
5. **Admin fails *closed* in production.** A production flag makes an unset `ADMIN_TOKEN`
   **refuse** admin routes rather than open them. A **statement timeout** applies to all
   public queries. Neo4j stays loopback-bound; the backend stays private; Caddy stays the
   sole public ingress.

## Consequences

- A free-key issuance flow is the **lightest form of "user accounts"** — which
  [vision-and-mvp](../vision-and-mvp.md) lists as out-of-scope. This is a deliberate,
  minimal exception (key + quota, no profiles/saved-queries), and it converges cleanly with
  the **landing page** as the home for both key issuance and the (now discreet) admin access.
- New in-process infra: an API-key store + rate-limiter (kept inside FastAPI — no new
  service, consistent with the "APScheduler-in-FastAPI, no extra services" posture).
- MCP transport = remote HTTP/SSE behind Caddy on the same Oracle box.
- **Live security action item:** verify `ADMIN_TOKEN` is set on the current Oracle host — if
  it is empty today, `#/admin` is already exposed.

## Rejected alternatives

- **Gate the whole website behind a free key.** Rejected mid-design — friction for
  read-only public data; the key belongs on the programmatic surface, not casual browsing.
- **Expose `run_cypher` behind a key + statement timeout.** Rejected — still an abuse /
  DoS vector, and the four structured tools + bounded export cover legitimate needs.
- **A live whole-graph dump endpoint.** Rejected — trivial scraping / DoS; a pre-baked
  versioned dump serves the same need safely.
- **Keep the empty-`ADMIN_TOKEN`=open default on public hosts.** Rejected — fail-open on a
  public surface is the wrong default; production fails closed.
