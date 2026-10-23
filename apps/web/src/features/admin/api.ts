import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";

export interface UsageDay {
  day: string;
  model: string;
  runs: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string; // Decimal as a string
  ttft_p50_ms: number | null;
  ttft_p95_ms: number | null;
  latency_p50_ms: number | null;
}

export interface Usage {
  days: UsageDay[];
  totals: { documents: number; chats: number; questions: number; pending_approvals: number; users: number };
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  locale: string;
  roles: string[];
  created_at: string;
  last_seen_at: string;
}

export interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export function useUsage(days: number) {
  const token = useAccessToken();
  return useQuery({ queryKey: ["admin", "usage", days], queryFn: () => apiGet<Usage>(`/api/admin/usage?days=${String(days)}`, token) });
}

export function useUsers() {
  const token = useAccessToken();
  return useQuery({ queryKey: ["admin", "users"], queryFn: () => apiGet<AdminUser[]>("/api/admin/users", token) });
}

export function useAudit(action: string) {
  const token = useAccessToken();
  const query = action ? `&action=${encodeURIComponent(action)}` : "";
  return useQuery({
    queryKey: ["admin", "audit", action],
    queryFn: () => apiGet<AuditEntry[]>(`/api/audit?limit=200${query}`, token),
  });
}
