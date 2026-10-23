export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export type Risk = "low" | "medium" | "high";

/** A JSON Schema as Pydantic generates it for a tool's arguments (the subset the form needs). */
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  format?: string;
  enum?: string[];
  maxLength?: number;
  minLength?: number;
  minItems?: number;
  maxItems?: number;
  default?: unknown;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  anyOf?: JsonSchema[];
  /** Field order (the API adds it: jsonb doesn't preserve object key order). */
  "x-order"?: string[];
}

/** What the card needs: either the live `approval.required` event or a saved approval. */
export interface ApprovalView {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  edited_args?: Record<string, unknown> | null;
  json_schema: JsonSchema;
  risk: Risk;
  status: ApprovalStatus;
  expires_at: string;
  decided_by_name?: string | null;
  reason?: string | null;
}

export interface ApprovalOut extends ApprovalView {
  run_id: string;
  chat_id: string;
  chat_title: string;
  call_id: string;
  requested_by: string | null;
  requested_by_name: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface DecisionOut {
  approval: ApprovalOut;
  resumed: boolean;
  run_id: string;
  resume_from: string | null;
}
