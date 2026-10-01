// Shared types mirroring the backend NDJSON protocol and REST payloads.

export interface ModelInfo {
  name: string;
  family: string;
  size: number;
  modified: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface MessageRow {
  id: string;
  session_id: string;
  role: "system" | "user" | "assistant" | "tool";
  sort: number;
  content: string;
  thinking: string;
  tool_calls: ToolCall[] | null;
  tool_call_id: string | null;
  tool_name: string | null;
  error: string | null;
  model: string | null;
  created_at: number;
}

export interface SessionInfo {
  id: string;
  title: string;
  model: string;
  created_at: number;
  updated_at: number;
}

export interface SessionFull {
  session: SessionInfo;
  messages: MessageRow[];
}

// --- stream events (t = type) -----------------------------------------------

export type StreamEvent =
  | { t: "meta"; session_id: string; message_id: string }
  | { t: "delta"; v: string }
  | { t: "thinking"; v: string }
  | { t: "assistant_tool_calls"; iter: number; calls: ToolCall[] }
  | { t: "tool_result"; id: string; name: string; ok: boolean; ms: number; result: string }
  | { t: "usage"; iter: number; prompt: number; cached: number; completion: number }
  | { t: "ping" }
  | { t: "done"; message_id: string; reason: string; prompt: number; completion: number; tool_calls: number; ms: number }
  | { t: "error"; code: string; message: string };
// events with an unknown `t` are dropped in api.ts streamChat — they never reach the store

export interface ChatTurn {
  message_id: string; // "" until meta arrives
  session_id: string;
  think_text: string;
  text: string;
  tools: {
    id: string;
    name: string;
    arguments?: Record<string, unknown>;
    ok: boolean | null;
    ms: number;
    result: string;
  }[];
  done: boolean;
  error?: string;
  usage?: { prompt: number; completion: number };
  reason?: string;
  ms?: number;
}

// --- dashboard -------------------------------------------------------------

export interface StatsSummary {
  requests: number;
  requests_failed: number;
  sessions: number;
  user_messages: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  tool_calls: number;
  days_active: number;
}

export interface DayPoint {
  day: string;
  prompt: number;
  completion: number;
  requests: number;
  cached: number;
}

export interface TopModel {
  model: string;
  requests: number;
  prompt: number;
  completion: number;
  avg_ms: number;
}

export interface ToolStat {
  name: string;
  calls: number;
  ok_rate: number;
  avg_ms: number;
}

export interface SessionStat {
  id: string;
  title: string;
  model: string;
  updated_at: number;
  requests: number;
  prompt: number;
  completion: number;
}