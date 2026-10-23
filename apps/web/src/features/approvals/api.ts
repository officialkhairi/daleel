import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";
import { chatKeys } from "../chat/api";
import type { ApprovalOut, DecisionOut } from "./types";

export const approvalKeys = { pending: ["approvals", "pending"] as const };

export function usePendingApprovals(enabled: boolean) {
  const token = useAccessToken();
  return useQuery({
    queryKey: approvalKeys.pending,
    queryFn: () => apiGet<ApprovalOut[]>("/api/approvals?status=pending", token),
    enabled,
  });
}

export interface DecisionInput {
  approvalId: string;
  decision: "approve" | "edit" | "reject";
  args?: Record<string, unknown>;
  reason?: string;
}

export function useDecide() {
  const token = useAccessToken();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, ...body }: DecisionInput) =>
      apiPost<DecisionOut>(`/api/approvals/${approvalId}`, token, body),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: approvalKeys.pending });
      void queryClient.invalidateQueries({ queryKey: chatKeys.detail(result.approval.chat_id) });
    },
  });
}
