import { useState } from 'react';
import { AuditPanel } from './components/AuditPanel';
import { ChatInterface } from './components/ChatInterface';
import { DataSourcePanel } from './components/DataSourcePanel';
import { ExecutionTimeline } from './components/ExecutionTimeline';
import type { Step } from './types';
import './index.css';

export default function App() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [currentPlanId, setCurrentPlanId] = useState<string | undefined>();

  const handleStepsChange = (newSteps: Step[], planId?: string) => {
    setSteps(newSteps);
    setCurrentPlanId(planId);
  };

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        overflow: 'hidden',
        background: 'var(--bg-primary)',
        color: 'var(--text-primary)',
      }}
    >
      {/* ── Left Sidebar ── */}
      <aside
        style={{
          width: 250,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-secondary)',
          borderRight: '1px solid var(--border)',
        }}
      >
        {/* Logo */}
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: 'var(--accent)',
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: 14,
            }}
          >
            N
          </div>
          <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>
            Nexus
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 99,
              background: 'rgba(99,102,241,0.15)',
              color: 'var(--accent)',
            }}
          >
            v0.1
          </span>
        </div>

        {/* Nav */}
        <nav style={{ padding: '10px 12px' }}>
          {NAV_ITEMS.map((item) => (
            <div
              key={item.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 12px',
                borderRadius: 8,
                marginBottom: 2,
                cursor: 'pointer',
                fontSize: 13,
                background: item.active ? 'rgba(99,102,241,0.12)' : 'transparent',
                color: item.active ? 'var(--accent)' : 'var(--text-secondary)',
              }}
            >
              <span>{item.icon}</span>
              {item.label}
            </div>
          ))}
        </nav>

        <div style={{ flex: 1, overflow: 'hidden' }}>
          <DataSourcePanel />
        </div>

        <div
          style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          Enterprise AI Agent Platform
        </div>
      </aside>

      {/* ── Center: Chat ── */}
      <main
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
        }}
      >
        {/* Header */}
        <header
          style={{
            flexShrink: 0,
            padding: '10px 20px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <h1 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              Chat
            </h1>
            <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
              Natural language queries across all connected data sources
            </p>
          </div>
          <span
            style={{
              fontSize: 11,
              padding: '3px 10px',
              borderRadius: 99,
              background: 'rgba(34,197,94,0.1)',
              color: 'var(--success)',
              border: '1px solid rgba(34,197,94,0.2)',
            }}
          >
            ● Live
          </span>
        </header>

        <div style={{ flex: 1, minHeight: 0 }}>
          <ChatInterface onStepsChange={handleStepsChange} />
        </div>
      </main>

      {/* ── Right Sidebar ── */}
      <aside
        style={{
          width: 300,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-secondary)',
          borderLeft: '1px solid var(--border)',
        }}
      >
        {/* Execution Timeline */}
        <div style={{ borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <div
            style={{
              padding: '10px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--text-muted)',
              }}
            >
              Execution
            </span>
            {steps.length > 0 && (
              <span
                style={{
                  fontSize: 11,
                  padding: '2px 7px',
                  borderRadius: 99,
                  background: 'rgba(99,102,241,0.15)',
                  color: 'var(--accent)',
                }}
              >
                {steps.length}
              </span>
            )}
          </div>
          <div style={{ maxHeight: '40vh', overflowY: 'auto' }}>
            <ExecutionTimeline steps={steps} currentPlanId={currentPlanId} />
          </div>
        </div>

        {/* Audit Panel */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <AuditPanel />
        </div>
      </aside>
    </div>
  );
}

const NAV_ITEMS = [
  { label: 'Chat', icon: '💬', active: true },
  { label: 'Plans', icon: '📋', active: false },
  { label: 'Analytics', icon: '📊', active: false },
  { label: 'Settings', icon: '⚙️', active: false },
];
