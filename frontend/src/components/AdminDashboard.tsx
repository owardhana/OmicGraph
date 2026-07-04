import { useCallback, useEffect, useState } from 'react';

import './AdminDashboard.css';
import {
  AdminAuthError,
  adminApi,
  getAdminToken,
  setAdminToken,
} from '../api/client';
import type {
  CandidateDetail,
  CandidateStatus,
  CandidateSummary,
} from '../types/graph';

const TABS: CandidateStatus[] = ['pending', 'promoted', 'rejected'];
const SORTS: { key: string; label: string }[] = [
  { key: 'confidence', label: 'Confidence' },
  { key: 'n_affirm', label: 'Affirming papers' },
  { key: 'recent', label: 'Most recent' },
];

const arrow = (symmetric: boolean) => (symmetric ? '↔' : '→');
const conf = (c: number | null | undefined) => (c == null ? '—' : c.toFixed(2));

/** Token gate — shown when the API returns 401. Saves to localStorage, then retries. */
function TokenGate({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(getAdminToken());
  return (
    <div className="admin-gate">
      <div className="admin-gate-card">
        <h2>Admin access</h2>
        <p className="admin-muted">
          This surface promotes trusted topology. Enter the <code>ADMIN_TOKEN</code>{' '}
          configured on the server.
        </p>
        <input
          className="admin-input"
          type="password"
          placeholder="ADMIN_TOKEN"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              setAdminToken(value);
              onSaved();
            }
          }}
        />
        <button
          className="admin-btn admin-btn-primary"
          onClick={() => {
            setAdminToken(value);
            onSaved();
          }}
        >
          Unlock
        </button>
      </div>
    </div>
  );
}

function PolarityTag({ polarity }: { polarity: string | null }) {
  const p = polarity ?? 'unknown';
  return <span className={`admin-pol admin-pol-${p}`}>{p}</span>;
}

export default function AdminDashboard() {
  const [tab, setTab] = useState<CandidateStatus>('pending');
  const [sort, setSort] = useState('confidence');
  const [list, setList] = useState<CandidateSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [authNeeded, setAuthNeeded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const handleErr = (e: unknown) => {
    if (e instanceof AdminAuthError) setAuthNeeded(true);
    else setError(String(e instanceof Error ? e.message : e));
  };

  const loadList = useCallback(async () => {
    setError(null);
    try {
      const rows = await adminApi.listCandidates(tab, sort);
      setList(rows);
    } catch (e) {
      handleErr(e);
    }
  }, [tab, sort]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let live = true;
    adminApi
      .candidateDetail(selected)
      .then((d) => live && setDetail(d))
      .catch(handleErr);
    return () => {
      live = false;
    };
  }, [selected]);

  const act = async (
    fn: (tk: string) => Promise<{ status: string }>,
    tk: string,
    confirmMsg: string,
  ) => {
    if (!window.confirm(confirmMsg)) return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await fn(tk);
      setFlash(`${tk.split(':')[0]} → ${res.status}`);
      await loadList();
      // the candidate likely changed status (left this tab) — refresh its detail so the
      // action set (approve/reject vs revert) reflects the new status.
      const fresh = await adminApi.candidateDetail(tk).catch(() => null);
      setDetail(fresh);
    } catch (e) {
      handleErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (authNeeded) {
    return (
      <TokenGate
        onSaved={() => {
          setAuthNeeded(false);
          setError(null);
          loadList();
        }}
      />
    );
  }

  const pc = detail?.proposed_change;
  const sc = detail?.scoring;

  return (
    <div className="admin">
      <header className="admin-top">
        <div className="admin-top-left">
          <a className="admin-back" href="#/">
            ← Graph
          </a>
          <span className="admin-title">Literature Review</span>
          <span className="admin-sub">candidate promotion queue · ADR-0014</span>
        </div>
        {flash && <span className="admin-flash">{flash}</span>}
      </header>

      <div className="admin-body">
        {/* ---- Left: queue ---- */}
        <aside className="admin-queue">
          <div className="admin-tabs">
            {TABS.map((t) => (
              <button
                key={t}
                className={`admin-tab ${t === tab ? 'active' : ''}`}
                onClick={() => {
                  setTab(t);
                  setSelected(null);
                }}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="admin-sortbar">
            <span className="admin-muted">sort</span>
            <select
              className="admin-select"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-list">
            {error && <div className="admin-error">{error}</div>}
            {!error && list.length === 0 && (
              <div className="admin-empty">No {tab} candidates.</div>
            )}
            {list.map((c) => (
              <button
                key={c.triple_key}
                className={`admin-card ${c.triple_key === selected ? 'active' : ''}`}
                onClick={() => setSelected(c.triple_key)}
              >
                <div className="admin-card-edge">
                  <span className="admin-ent">{c.subject.name}</span>
                  <span className="admin-rel">
                    {arrow(c.symmetric)} {c.rel_type}
                  </span>
                  <span className="admin-ent">{c.object.name}</span>
                </div>
                <div className="admin-card-meta">
                  <span className="admin-conf">conf {conf(c.confidence)}</span>
                  <span className="admin-affirm">▲ {c.n_affirm ?? 0}</span>
                  {(c.n_negate ?? 0) > 0 && (
                    <span className="admin-negate">▼ {c.n_negate}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* ---- Right: detail ---- */}
        <main className="admin-detail">
          {!detail || !pc || !sc ? (
            <div className="admin-detail-empty">
              Select a candidate to review its evidence.
            </div>
          ) : (
            <>
              <div className="admin-proposed">
                <div className="admin-proposed-edge">
                  <span className="admin-ent-lg">{pc.subject.name}</span>
                  <span className="admin-rel-lg">
                    {arrow(pc.symmetric)} {pc.rel_type}
                  </span>
                  <span className="admin-ent-lg">{pc.object.name}</span>
                </div>
                {pc.would_be_action && (
                  <span
                    className={`admin-action-badge ${pc.would_be_action.toLowerCase()}`}
                    title={
                      pc.would_be_action === 'MINT'
                        ? 'Approve → creates a NEW literature-tier edge (rendered "proposed")'
                        : 'Approve → appends citations to an EXISTING canonical edge (no new topology)'
                    }
                  >
                    {pc.would_be_action === 'MINT'
                      ? 'would mint a new edge'
                      : 'would enrich a canonical edge'}
                  </span>
                )}
                {sc.status !== 'pending' && (
                  <span className="admin-status-badge">
                    {sc.status}
                    {sc.promotion_kind ? ` · ${sc.promotion_kind}` : ''}
                  </span>
                )}
              </div>

              {/* actions — deliberate, confirm-gated (ADR-0014 §1: gate, don't edit) */}
              <div className="admin-actions">
                {sc.status === 'pending' && (
                  <>
                    <button
                      className="admin-btn admin-btn-approve"
                      disabled={busy}
                      onClick={() =>
                        act(
                          adminApi.approve,
                          selected!,
                          pc.would_be_action === 'ENRICH'
                            ? `Approve: append supporting PMIDs to the existing canonical ${pc.rel_type} edge (${pc.subject.name} ${arrow(pc.symmetric)} ${pc.object.name})?`
                            : `Approve: mint a new literature-tier ${pc.rel_type} edge (${pc.subject.name} ${arrow(pc.symmetric)} ${pc.object.name})? It renders as "proposed" in the graph.`,
                        )
                      }
                    >
                      Approve
                    </button>
                    <button
                      className="admin-btn admin-btn-reject"
                      disabled={busy}
                      onClick={() =>
                        act(
                          adminApi.reject,
                          selected!,
                          `Reject this proposal? It is kept + flagged and never re-proposed.`,
                        )
                      }
                    >
                      Reject
                    </button>
                  </>
                )}
                {sc.status === 'promoted' && (
                  <button
                    className="admin-btn admin-btn-revert"
                    disabled={busy}
                    onClick={() =>
                      act(
                        adminApi.revert,
                        selected!,
                        sc.promotion_kind === 'enrich'
                          ? `Revert enrichment: remove the exact PMIDs this proposal added to the canonical edge (canonical citations are preserved)?`
                          : `Revert: delete the minted literature-tier edge and return the candidate to pending?`,
                      )
                    }
                  >
                    Revert promotion
                  </button>
                )}
              </div>

              <div className="admin-scoring">
                <span>
                  confidence <strong>{conf(sc.confidence)}</strong>
                </span>
                <span className="admin-affirm">
                  ▲ {sc.n_affirm ?? 0} affirming
                </span>
                <span className={(sc.n_negate ?? 0) > 0 ? 'admin-negate' : 'admin-muted'}>
                  ▼ {sc.n_negate ?? 0} contradicting
                </span>
              </div>

              {/* evidence — one row per PMID, contradicting surfaced first */}
              <section className="admin-section">
                <h3>Evidence ({detail.evidence.length})</h3>
                {detail.evidence.map((e, i) => (
                  <div
                    key={`${e.pmid}-${i}`}
                    className={`admin-evi ${e.polarity === 'negate' ? 'contra' : ''}`}
                  >
                    <div className="admin-evi-head">
                      <PolarityTag polarity={e.polarity} />
                      <a
                        href={`https://pubmed.ncbi.nlm.nih.gov/${e.pmid}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        PMID {e.pmid}
                      </a>
                      {e.model_conf != null && (
                        <span className="admin-muted">
                          model conf {e.model_conf.toFixed(2)}
                        </span>
                      )}
                    </div>
                    {e.sentence_span && (
                      <p className="admin-span">“{e.sentence_span}”</p>
                    )}
                    {e.model && <div className="admin-evi-model">{e.model}</div>}
                  </div>
                ))}
              </section>

              {/* endpoint context */}
              <section className="admin-section">
                <h3>Endpoint context</h3>
                <div className="admin-ctx-grid">
                  {[
                    { end: pc.subject, ctx: detail.endpoint_context.subject },
                    { end: pc.object, ctx: detail.endpoint_context.object },
                  ].map(({ end, ctx }) => (
                    <div key={end.id} className="admin-ctx">
                      <div className="admin-ctx-name">
                        {end.name} <span className="admin-muted">{end.kind}</span>
                      </div>
                      <div className="admin-muted">
                        degree {ctx.degree ?? '—'} · <code>{end.id}</code>
                      </div>
                      {ctx.summary && <p className="admin-ctx-sum">{ctx.summary}</p>}
                    </div>
                  ))}
                </div>
              </section>

              {/* agent profiling */}
              <section className="admin-section admin-profiling">
                <h3>Agent profiling</h3>
                <div className="admin-muted">
                  {detail.agent_profiling.source_agent} v
                  {detail.agent_profiling.agent_version} · tier{' '}
                  {detail.agent_profiling.provenance_tier}
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
