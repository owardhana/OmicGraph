import { useState } from 'react';

import ChatPanel from './ChatPanel';
import EntityBrowser from './EntityBrowser';
import SearchBar from './SearchBar';
import type { SearchResult } from '../types/graph';

type Seed = { id: string; node_type: string };

interface Props {
  onSelect: (result: SearchResult) => void;
  onMultiLoad: (seeds: Seed[]) => void;
  onClear: () => void;
  tissue: string;
}

// The single left dock (unified sidebar): a pinned "jump to entity" search on top,
// a Browse | Ask mode toggle, and the two panes below.
//
// Both panes stay MOUNTED and are hidden with the `hidden` attribute when inactive,
// rather than conditionally rendered — switching modes must never drop the Browse
// pane's staged multi-selection or the Ask pane's chat thread. Chat state lives in
// useChat (component-local useState + a sessionId ref); unmounting would clear the
// visible thread and rotate the server-side session.
export default function LeftRail({ onSelect, onMultiLoad, onClear, tissue }: Props) {
  const [mode, setMode] = useState<'browse' | 'ask'>('browse');
  const [collapsed, setCollapsed] = useState(false);

  // When collapsed, the rail is HIDDEN (not unmounted) so the Browse pane's staged
  // selection and the Ask pane's chat thread survive a collapse/reopen — same
  // mount-preservation reason the Browse/Ask panes are hidden rather than swapped.
  return (
    <>
      {collapsed && (
        <button
          className="rail-reopen"
          onClick={() => setCollapsed(false)}
          aria-label="Open sidebar"
        >
          SEARCH · BROWSE · ASK
        </button>
      )}
      <aside className="left-rail" hidden={collapsed}>
      <div className="rail-head">
        <div className="rail-search-row">
          <SearchBar onSelect={onSelect} />
          <button
            className="rail-collapse"
            onClick={() => setCollapsed(true)}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            ‹
          </button>
        </div>
        <div className="rail-seg" role="tablist">
          <button
            role="tab"
            aria-selected={mode === 'browse'}
            className={mode === 'browse' ? 'active' : ''}
            onClick={() => setMode('browse')}
          >
            Browse
          </button>
          <button
            role="tab"
            aria-selected={mode === 'ask'}
            className={mode === 'ask' ? 'active' : ''}
            onClick={() => setMode('ask')}
          >
            Ask
          </button>
        </div>
      </div>

      <div className="rail-body">
        <div className="rail-pane" hidden={mode !== 'browse'}>
          <EntityBrowser onMultiLoad={onMultiLoad} onClear={onClear} />
        </div>
        <div className="rail-pane" hidden={mode !== 'ask'}>
          <ChatPanel tissue={tissue} />
        </div>
      </div>
      </aside>
    </>
  );
}
