import { useEffect, useRef, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useWebSocket } from '../hooks/useWebSocket';
import type { ChatMessage, Step, WsEvent } from '../types';
import { PlanPreview } from './PlanPreview';

let _msgCounter = 0;
function msgId() { return `msg-${++_msgCounter}`; }

export function ChatInterface({ onStepsChange }: { onStepsChange?: (steps: Step[], planId?: string) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { events, connectionStatus, sendMessage, clearEvents } = useWebSocket();
  const { approvePlan } = useApi();

  // Track current plan steps from WS events
  const currentStepsRef = useRef<Step[]>([]);
  const currentPlanId = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Process incoming WS events
  useEffect(() => {
    const latest = events[events.length - 1];
    if (!latest) return;
    handleWsEvent(latest);
  }, [events]);

  const handleWsEvent = (evt: WsEvent) => {
    switch (evt.event) {
      case 'classifying':
        setIsProcessing(true);
        appendSystemMsg('Classifying intent…');
        break;

      case 'intent_classified':
        appendSystemMsg(`Intent: ${evt.intent ?? 'unknown'}`);
        break;

      case 'planning':
        appendSystemMsg('Decomposing plan…');
        break;

      case 'plan_created': {
        currentPlanId.current = evt.plan_id;
        const steps: Step[] = ((evt.steps ?? []) as Step[]).map((s: Step) => ({
          ...s,
          status: 'pending',
        }));
        currentStepsRef.current = steps;
        onStepsChange?.(steps, evt.plan_id);
        break;
      }

      case 'step_started': {
        const updated = currentStepsRef.current.map((s) =>
          s.id === evt.step_id ? { ...s, status: 'running' as const } : s
        );
        currentStepsRef.current = updated;
        onStepsChange?.(updated, currentPlanId.current);
        break;
      }

      case 'step_completed': {
        const updated = currentStepsRef.current.map((s) =>
          s.id === evt.step_id
            ? { ...s, status: 'completed' as const, duration_ms: evt.duration_ms }
            : s
        );
        currentStepsRef.current = updated;
        onStepsChange?.(updated, currentPlanId.current);
        break;
      }

      case 'step_failed': {
        const updated = currentStepsRef.current.map((s) =>
          s.id === evt.step_id
            ? { ...s, status: 'failed' as const, error: evt.error }
            : s
        );
        currentStepsRef.current = updated;
        onStepsChange?.(updated, currentPlanId.current);
        break;
      }

      case 'plan_completed':
        setIsProcessing(false);
        if (evt.answer) {
          addAgentMessage(evt.answer, evt.plan_id);
        }
        clearEvents();
        break;

      case 'approval_required':
        setIsProcessing(false);
        addApprovalMessage(evt);
        clearEvents();
        break;

      case 'error':
        setIsProcessing(false);
        addAgentMessage(`Error: ${evt.error ?? 'Unknown error'}`, undefined);
        clearEvents();
        break;
    }
  };

  const appendSystemMsg = (content: string) => {
    setMessages((prev) => {
      // Replace last system message if it's also a system msg
      if (prev[prev.length - 1]?.role === 'system') {
        return [...prev.slice(0, -1), { id: msgId(), role: 'system', content, timestamp: new Date() }];
      }
      return [...prev, { id: msgId(), role: 'system', content, timestamp: new Date() }];
    });
  };

  const addAgentMessage = (content: string, planId?: string) => {
    setMessages((prev) => {
      // Remove trailing system messages
      const clean = prev.filter((m) => m.role !== 'system');
      return [...clean, { id: msgId(), role: 'agent', content, timestamp: new Date(), plan_id: planId }];
    });
  };

  const addApprovalMessage = (evt: WsEvent) => {
    const steps = (evt.steps ?? []) as Step[];
    setMessages((prev) => {
      const clean = prev.filter((m) => m.role !== 'system');
      return [
        ...clean,
        {
          id: msgId(),
          role: 'agent',
          content: evt.message as string ?? 'This plan requires approval.',
          timestamp: new Date(),
          plan_id: evt.plan_id,
          requires_approval: true,
          steps,
        },
      ];
    });
  };

  const handleApprove = async (planId: string) => {
    try {
      setIsProcessing(true);
      const result = await approvePlan(planId);
      const answer = (result.result as { answer?: string })?.answer ?? 'Plan executed successfully.';
      addAgentMessage(answer, planId);
    } catch (err) {
      addAgentMessage(`Approval failed: ${(err as Error).message}`);
    } finally {
      setIsProcessing(false);
      // Remove approval message
      setMessages((prev) =>
        prev.map((m) =>
          m.plan_id === planId && m.requires_approval ? { ...m, requires_approval: false } : m
        )
      );
    }
  };

  const handleReject = (planId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.plan_id === planId && m.requires_approval
          ? { ...m, requires_approval: false, content: 'Plan rejected.' }
          : m
      )
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isProcessing) return;

    // Add user message
    setMessages((prev) => [
      ...prev,
      { id: msgId(), role: 'user', content: text, timestamp: new Date() },
    ]);

    // Reset steps
    currentStepsRef.current = [];
    currentPlanId.current = undefined;
    onStepsChange?.([], undefined);

    sendMessage({ prompt: text });
    setInput('');
    setIsProcessing(true);
  };

  const isConnected = connectionStatus === 'connected';

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full" style={{ color: 'var(--text-muted)' }}>
            <div className="text-4xl mb-4 opacity-20">⬡</div>
            <p className="text-sm">Ask Nexus anything about your enterprise data.</p>
            <div className="mt-6 grid grid-cols-1 gap-2 w-full max-w-md">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="text-xs px-4 py-2.5 rounded-lg text-left transition-colors"
                  style={{
                    background: 'var(--bg-tertiary)',
                    color: 'var(--text-secondary)',
                    border: '1px solid var(--border)',
                  }}
                  onClick={() => setInput(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        ))}

        {isProcessing && !messages.some((m) => m.role === 'system') && (
          <div className="flex justify-start">
            <div
              className="rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1.5"
              style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}
            >
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="typing-dot w-1.5 h-1.5 rounded-full"
                  style={{ background: 'var(--text-muted)' }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-4 border-t" style={{ borderColor: 'var(--border)' }}>
        <form onSubmit={handleSubmit} className="flex gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={isConnected ? 'Ask anything about your enterprise data…' : 'Connecting to server…'}
              disabled={!isConnected || isProcessing}
              className="w-full px-4 py-3 rounded-xl text-sm outline-none transition-colors"
              style={{
                background: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
            />
          </div>
          <button
            type="submit"
            disabled={!isConnected || !input.trim() || isProcessing}
            className="px-5 py-3 rounded-xl font-medium text-sm transition-all"
            style={{
              background: input.trim() && isConnected ? 'var(--accent)' : 'var(--bg-tertiary)',
              color: input.trim() && isConnected ? '#fff' : 'var(--text-muted)',
              cursor: input.trim() && isConnected && !isProcessing ? 'pointer' : 'not-allowed',
            }}
          >
            Send
          </button>
        </form>
        <div className="mt-2 flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: isConnected ? 'var(--success)' : 'var(--danger)',
              boxShadow: isConnected ? '0 0 4px var(--success)' : 'none',
            }}
          />
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {connectionStatus}
          </span>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  onApprove,
  onReject,
}: {
  message: ChatMessage;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  if (message.role === 'system') {
    return (
      <div className="flex justify-center">
        <span
          className="text-xs px-3 py-1 rounded-full"
          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-muted)' }}
        >
          {message.content}
        </span>
      </div>
    );
  }

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[75%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  // Agent message
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] space-y-2">
        <div
          className="rounded-2xl rounded-bl-sm px-4 py-3 text-sm leading-relaxed"
          style={{
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
          }}
        >
          <ResponseContent content={message.content} />
        </div>

        {message.requires_approval && message.plan_id && message.steps && (
          <PlanPreview
            planId={message.plan_id}
            steps={message.steps}
            onApprove={onApprove}
            onReject={onReject}
          />
        )}
      </div>
    </div>
  );
}

function ResponseContent({ content }: { content: string }) {
  // Detect and render tables (markdown-style)
  if (content.includes('|') && content.includes('\n')) {
    const lines = content.split('\n');
    const tableLines = lines.filter((l) => l.trim().startsWith('|'));
    if (tableLines.length >= 2) {
      const headers = tableLines[0].split('|').filter(Boolean).map((h) => h.trim());
      const rows = tableLines.slice(2).map((l) =>
        l.split('|').filter(Boolean).map((c) => c.trim())
      );
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                {headers.map((h, i) => (
                  <th key={i} className="px-3 py-1.5 text-left font-semibold"
                      style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-1.5" style={{ color: 'var(--text-secondary)' }}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  }

  return <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>;
}

const SUGGESTIONS = [
  'Show me all deals in the Negotiation stage',
  'How many customers are on the Enterprise plan?',
  'Analyze revenue trends by region',
  'Create a new customer record',
];
