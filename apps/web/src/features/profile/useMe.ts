import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../../lib/api";
import { useAccessToken } from "../auth/AuthProvider";

export type Role = "viewer" | "editor" | "approver" | "admin";

export interface Me {
  id: string;
  sub: string;
  username: string;
  name: string | null;
  email: string | null;
  locale: string;
  tenant: string;
  roles: Role[];
}

export function useMe() {
  const token = useAccessToken();
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/api/me", token),
  });
}
