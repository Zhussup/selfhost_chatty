// Thin REST client + the NDJSON stream reader for POST /api/chat.

import type {
  DayPoint,
  ModeInfo,
  ModelInfo,
  SessionFull,
  SessionInfo,
  StatsSummary,
  StreamEvent,
  ToolCall,
  ToolStat,
  TopModel,
  SessionStat,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function j<T>(res: Promise<Response> | Response): Promise<T> {
  const r = await res;
  if (r.status === 401) throw new ApiError(401, "unauthorized");
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const data = await r.json();
      detail = String((data as { detail?: unknown }).detail ?? JSON.stringify(data));
    } catch {
      /* non-json error body */
    }
    throw new ApiError(r.status, String(detail));
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => j<{ ok: boolean }>(fetch("/api/auth/me")),
  login: (password: string) =>
    j<{ ok: boolean }>(
      fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      })
    ),
  logout: () => j<{ ok: boolean }>(fetch("/api/auth/logout", { method: "POST" })),

  sessions: () => j<SessionInfo[]>(fetch("/api/sessions")),
  session: (id: string) => j<SessionFull>(fetch(`/api/sessions/${id}`)),
  deleteSession: (id: string) => j<{ ok: boolean }>(fetch(`/api/sessions/${id}`, { method: "DELETE" })),
  renameSession: (id: string, title: string) =>
    j<{ ok: boolean }>(
      fetch(`/api/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      })
    ),
  exportUrl: (id: string) => `/api/sessions/${id}/export.md`,
  setSessionMode: (id: string, mode: string) =>
    j<{ ok: boolean }>(
      fetch(`/api/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      })
    ),

  modes: () => j<{ modes: ModeInfo[]; default: string }>(fetch("/api/modes")),

  models: () => j<{ models: ModelInfo[]; cached: boolean }>(fetch("/api/models")),

  statsSummary: () => j<StatsSummary>(fetch("/api/stats/summary")),
  statsTimeseries: (days: number) => j<DayPoint[]>(fetch(`/api/stats/timeseries?days=${days}`)),
  statsTopModels: () => j<TopModel[]>(fetch("/api/stats/top-models")),
  statsTools: () => j<ToolStat[]>(fetch("/api/stats/tools")),
  statsSessions: () => j<SessionStat[]>(fetch("/api/stats/sessions")),
};

export interface ChatRequestBody {
  session_id: string | null;
  model: string;
  content: string;
  /** Photos for this prompt: raw base64, no data: prefix. */
  images?: { data: string; name?: string; width?: number; height?: number }[];
  quote?: string | null;
  think: "low" | "medium" | "high" | null;
  use_tools: boolean;
  /** Persona for this dialog. Omitted only by callers that have none. */
  mode?: string;
  regenerate: boolean;
  /** Edit-and-resend: rewrite this stored user message and drop what follows it. */
  edit_message_id?: string;
}

/** A stored attachment's bytes. Same-origin, so the auth cookie rides along. */
export const imageUrl = (id: string): string => `/api/images/${id}`;

/** Stream chat turns as NDJSON events. */
export async function streamChat(
  body: ChatRequestBody,
  onEvent: (ev: StreamEvent) => void,
  abort: AbortSignal
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: abort,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = String(((await res.json()) as { detail?: unknown }).detail ?? detail);
    } catch {
      /* body not json */
    }
    if (res.status === 401) throw new ApiError(401, "unauthorized");
    onEvent({ t: "error", code: res.status === 409 ? "rate_limited" : "http", message: String(detail) });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const known = new Set([
    "meta", "delta", "thinking", "assistant_tool_calls", "tool_result",
    "usage", "ping", "done", "error",
  ]);
  const onLine = (line: string) => {
    if (!line.trim()) return;
    let ev: { t?: unknown };
    try {
      ev = JSON.parse(line);
    } catch {
      return; // malformed line
    }
    if (typeof ev.t !== "string" || !known.has(ev.t)) return; // unknown event type — ignore
    onEvent(ev as StreamEvent);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      onLine(buf.slice(0, nl));
      buf = buf.slice(nl + 1);
    }
  }
  if (buf.trim()) onLine(buf.trim());
}

export function toolChipLabel(call: ToolCall): string {
  const a = call.arguments ?? {};
  switch (call.name) {
    case "web_search":
      return `searched: ${(a.query as string) ?? ""}`;
    case "fetch_page":
      return `opened: ${(a.url as string) ?? ""}`;
    case "calc":
      return `calc: ${(a.expr as string) ?? ""}`;
    case "python":
      return "ran python";
    case "memory_write":
      return "remembered note";
    case "memory_list":
      return "checked memory";
    default:
      return call.name;
  }
}