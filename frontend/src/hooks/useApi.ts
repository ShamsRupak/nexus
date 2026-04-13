import { useCallback } from 'react';
import type { AuditEntry, Connector, HealthStatus, Plan } from '../types';

const BASE = import.meta.env.VITE_API_URL ?? '';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function useApi() {
  const submitPrompt = useCallback(
    (prompt: string, userId?: string) =>
      apiFetch<{
        status: string;
        plan_id: string;
        result?: { answer: string; trace_id: string; latency_ms: number };
        steps?: unknown[];
        message?: string;
      }>('/api/v1/prompt', {
        method: 'POST',
        body: JSON.stringify({ prompt, user_id: userId }),
      }),
    []
  );

  const approvePlan = useCallback(
    (planId: string) =>
      apiFetch<{ status: string; plan_id: string; result?: unknown }>(
        `/api/v1/approve/${planId}`,
        { method: 'POST' }
      ),
    []
  );

  const getPlans = useCallback(
    (limit = 20) => apiFetch<Plan[]>(`/api/v1/plans?limit=${limit}`),
    []
  );

  const getAudit = useCallback(
    (params?: { limit?: number; action_type?: string }) => {
      const qs = new URLSearchParams();
      if (params?.limit) qs.set('limit', String(params.limit));
      if (params?.action_type) qs.set('action_type', params.action_type);
      return apiFetch<AuditEntry[]>(`/api/v1/audit?${qs.toString()}`);
    },
    []
  );

  const exportAudit = useCallback(
    (fmt: 'json' | 'csv') =>
      apiFetch<{ format: string; content: string; entry_count: number }>(
        `/api/v1/audit/export?fmt=${fmt}`
      ),
    []
  );

  const getConnectors = useCallback(() => apiFetch<Connector[]>('/api/v1/connectors'), []);

  const getHealth = useCallback(() => apiFetch<HealthStatus>('/api/v1/health'), []);

  return { submitPrompt, approvePlan, getPlans, getAudit, exportAudit, getConnectors, getHealth };
}
