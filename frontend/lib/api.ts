import type {
  Batch, BatchProgress, CurrentUser, Discrepancy, PagedResponse,
  ReconciliationRun, SourceType, Summary, Transaction,
} from "@/lib/types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
export const PUBLIC_DEMO = process.env.NEXT_PUBLIC_DEMO === "1";
export const SESSION_EXPIRED_EVENT = "ledger-session-expired";
type Tokens = { access: string; refresh: string };
let refreshing: Promise<string> | null = null;
let sessionVersion = 0;

export function getAccessToken(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem("ledger_access");
}

export function saveTokens(tokens: Tokens): void {
  localStorage.setItem("ledger_access", tokens.access);
  localStorage.setItem("ledger_refresh", tokens.refresh);
}

export function clearAccessToken(): void {
  sessionVersion += 1;
  localStorage.removeItem("ledger_access");
  localStorage.removeItem("ledger_refresh");
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const value = body as { error?: { message?: string }; detail?: string };
  if (value.error?.message) return value.error.message;
  if (typeof value.detail === "string") return value.detail;
  const fields = Object.entries(body).flatMap(([key, message]) =>
    Array.isArray(message) ? [`${key}: ${message.join(" ")}`] : [],
  );
  return fields.join(" ") || fallback;
}

async function refreshAccessToken(): Promise<string> {
  // Share refresh requests: token rotation makes concurrent refreshes unsafe.
  if (!refreshing) {
    const version = sessionVersion;
    const work = async () => {
      const refresh = localStorage.getItem("ledger_refresh");
      if (!refresh) {
        if (sessionVersion === version) {
          clearAccessToken();
          window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
        }
        throw new Error("Please sign in again.");
      }
      const response = await fetch(`${API_URL}/auth/token/refresh/`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.access) {
        if (response.status === 400 || response.status === 401) {
          if (sessionVersion === version) {
            clearAccessToken();
            window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
          }
        }
        throw new Error(errorMessage(body, "Session refresh failed. Please retry."));
      }
      // A slow refresh must not restore an account after the user signed out.
      if (sessionVersion !== version) throw new Error("Session ended.");
      saveTokens({ access: body.access, refresh: body.refresh ?? refresh });
      return body.access as string;
    };
    refreshing = work().finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function currentAccessToken(): Promise<string | null> {
  const token = getAccessToken();
  if (!token) return null;
  try {
    const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const { exp } = JSON.parse(atob(encoded)) as { exp?: number };
    if (exp && exp * 1000 > Date.now() + 30_000) return token;
  } catch {
    // The server, not the browser's JWT decoder, validates authenticity.
  }
  return refreshAccessToken();
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const token = await currentAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (response.status === 401 && retry && localStorage.getItem("ledger_refresh")) {
    await refreshAccessToken();
    return request<T>(path, init, false);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    throw new Error(errorMessage(body, `Request failed with ${response.status}`));
  }
  return body as T;
}

function queryString(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return query.toString();
}

export async function login(username: string, password: string): Promise<Tokens> {
  const response = await fetch(`${API_URL}/auth/token/`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.access || !body.refresh) throw new Error(errorMessage(body, "Login failed"));
  sessionVersion += 1;
  saveTokens(body);
  return body as Tokens;
}

export function getMe() {
  return request<{ data: CurrentUser }>("/auth/me/");
}

export function getSummary(runId?: string) {
  return request<{ data: Summary }>(`/summary/?${queryString({ run_id: runId })}`);
}

export function getBatches() {
  return request<{ data: Batch[] }>("/batches/");
}

export function getBatchStatus(id: string) {
  return request<{ data: BatchProgress }>(`/batches/${id}/status/`);
}

export function getRuns() {
  return request<{ data: ReconciliationRun[] }>("/reconciliation/runs/");
}

export function getTransactions(params: { page?: number; page_size?: number; status?: string; search?: string; run_id?: string }) {
  return request<PagedResponse<Transaction>>(`/transactions/?${queryString(params)}`);
}

export function getDiscrepancies(params: { status?: string; page?: number; run_id?: string } = {}) {
  return request<PagedResponse<Discrepancy>>(`/discrepancies/?${queryString(params)}`);
}

export async function uploadBatch(file: File, sourceType: SourceType, sourceAccount: string, onProgress?: (value: number) => void) {
  type UploadResult = { data: { id: string; status: string; task_id: string | null } };
  const send = async (retry: boolean): Promise<UploadResult> => {
    const token = await currentAccessToken();
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);
      form.append("source_type", sourceType);
      form.append("source_account", sourceAccount);
      xhr.open("POST", `${API_URL}/batches/upload/`);
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onerror = () => reject(new Error("Network error while uploading the file."));
      xhr.onload = () => {
        if (xhr.status === 401 && retry && localStorage.getItem("ledger_refresh")) {
          refreshAccessToken().then(() => send(false)).then(resolve, reject);
          return;
        }
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300 && body.data) resolve(body as UploadResult);
          else reject(new Error(errorMessage(body, "Upload failed.")));
        } catch {
          reject(new Error("The server returned an invalid upload response."));
        }
      };
      xhr.send(form);
    });
  };
  return send(true);
}

export function startReconciliation(ledgerBatchId: string, externalBatchId: string) {
  return request<{ data: { id: string; status: string; task_id: string | null } }>("/reconciliation/runs/", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ledger_batch_id: ledgerBatchId, external_batch_id: externalBatchId }),
  });
}

export function resolveDiscrepancy(id: string, resolution: string, note: string) {
  return request<{ data: Discrepancy }>(`/discrepancies/${id}/resolve/`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resolution, note }),
  });
}
