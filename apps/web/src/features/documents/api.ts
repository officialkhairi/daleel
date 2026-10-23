import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDelete, apiGet, apiRequest } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";

export type Role = "viewer" | "editor" | "approver" | "admin";
export const ROLES: Role[] = ["viewer", "editor", "approver", "admin"];

export interface DocumentInfo {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  lang: string | null;
  status: "uploaded" | "processing" | "ready" | "failed";
  progress: number;
  error: string | null;
  page_count: number | null;
  chunk_count: number | null;
  acl_roles: Role[];
  created_at: string;
  updated_at: string;
}

export const documentKeys = {
  list: ["documents"] as const,
  file: (id: string) => ["documents", id, "file"] as const,
};

export function useDocuments() {
  const token = useAccessToken();
  return useQuery({ queryKey: documentKeys.list, queryFn: () => apiGet<DocumentInfo[]>("/api/documents", token) });
}

export interface UploadInput {
  file: File;
  title: string;
  roles: Role[];
}

export function useUpload() {
  const token = useAccessToken();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, title, roles }: UploadInput) => {
      const form = new FormData();
      form.append("file", file);
      if (title.trim()) form.append("title", title.trim());
      for (const role of roles) form.append("acl_roles", role);
      const response = await apiRequest("/api/documents", token, { method: "POST", body: form });
      return (await response.json()) as DocumentInfo;
    },
    onSuccess: (document) => {
      queryClient.setQueryData<DocumentInfo[]>(documentKeys.list, (list = []) => [
        document,
        ...list.filter((d) => d.id !== document.id),
      ]);
    },
  });
}

export function useUpdateAccess() {
  const token = useAccessToken();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, roles }: { id: string; roles: Role[] }) => {
      const response = await apiRequest(`/api/documents/${id}`, token, {
        method: "PATCH",
        body: { acl_roles: roles },
      });
      return (await response.json()) as DocumentInfo;
    },
    onSuccess: (document) => {
      queryClient.setQueryData<DocumentInfo[]>(documentKeys.list, (list = []) =>
        list.map((d) => (d.id === document.id ? document : d)),
      );
    },
  });
}

export function useDeleteDocument() {
  const token = useAccessToken();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/documents/${id}`, token),
    onSuccess: (_, id) => {
      queryClient.setQueryData<DocumentInfo[]>(documentKeys.list, (list = []) => list.filter((d) => d.id !== id));
    },
  });
}

/** The original file as bytes, for the citation viewer. Cached per document. */
export function useDocumentFile(id: string | null) {
  const token = useAccessToken();
  return useQuery({
    queryKey: documentKeys.file(id ?? "none"),
    queryFn: async () => {
      const response = await apiRequest(`/api/documents/${id ?? ""}/file`, token, {
        headers: { Accept: "application/pdf, */*" },
      });
      return new Uint8Array(await response.arrayBuffer());
    },
    enabled: id !== null,
    staleTime: Infinity,
  });
}
