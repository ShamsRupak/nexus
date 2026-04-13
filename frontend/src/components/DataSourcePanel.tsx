import { useEffect, useState } from 'react';
import { useApi } from '../hooks/useApi';
import type { Connector } from '../types';

export function DataSourcePanel() {
  const { getConnectors, getHealth } = useApi();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [healthy, setHealthy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getConnectors(), getHealth()])
      .then(([conns, health]) => {
        setConnectors(conns);
        setHealthy(health.status === 'ok');
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between"
           style={{ borderColor: 'var(--border)' }}>
        <span className="text-xs font-semibold uppercase tracking-widest"
              style={{ color: 'var(--text-muted)' }}>
          Data Sources
        </span>
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{
            background: healthy ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
            color: healthy ? 'var(--success)' : 'var(--danger)',
          }}
        >
          {healthy ? 'Online' : 'Offline'}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && (
          <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>
            Loading…
          </p>
        )}
        {!loading && connectors.length === 0 && (
          <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>
            No connectors registered.
          </p>
        )}
        {connectors.map((c) => (
          <ConnectorCard key={c.name} connector={c} />
        ))}
      </div>

      {/* Add Source button */}
      <div className="p-3 border-t" style={{ borderColor: 'var(--border)' }}>
        <button
          className="w-full py-2 rounded-lg text-xs font-medium transition-colors"
          style={{
            background: 'var(--bg-tertiary)',
            color: 'var(--accent)',
            border: '1px solid var(--border)',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--accent)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)';
          }}
        >
          + Add Source
        </button>
      </div>
    </div>
  );
}

function ConnectorCard({ connector }: { connector: Connector }) {
  const [expanded, setExpanded] = useState(false);
  const isHealthy = connector.healthy !== false;

  return (
    <div
      className="rounded-lg p-3 cursor-pointer transition-colors"
      style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={{
            background: isHealthy ? 'var(--success)' : 'var(--danger)',
            boxShadow: isHealthy ? '0 0 6px var(--success)' : '0 0 6px var(--danger)',
          }}
        />
        <span className="text-xs font-medium flex-1" style={{ color: 'var(--text-primary)' }}>
          {connector.name}
        </span>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {connector.description && (
        <p className="text-xs mt-1 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {connector.description}
        </p>
      )}

      {expanded && connector.capabilities?.length > 0 && (
        <div className="mt-2 space-y-1">
          {connector.capabilities.map((cap) => (
            <span
              key={cap}
              className="inline-block text-xs px-2 py-0.5 rounded mr-1 mb-1"
              style={{
                background: 'rgba(99,102,241,0.1)',
                color: 'var(--accent-hover)',
                border: '1px solid rgba(99,102,241,0.2)',
              }}
            >
              {cap}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
