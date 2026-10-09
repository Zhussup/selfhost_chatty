// Shared types mirroring the backend NDJSON protocol and REST payloads.

export interface ModelInfo {
  name: string;
  family: string;
  size: number;
  modified: string;
  /** True when upstream /api/show lists the "vision" capability. Absent from older servers. */
  vision?: boolean;
  capabilities?: string[];
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/** A stored attachment. The bytes are fetched lazily from /api/images/{id}. */
export interface ImageRef {
  id: string;
  mime: string;
  name: string;
  width: number;
  height: number;
}

/** An attachment still in flight: not persisted yet, so it carries its own preview. */
export interface TurnImage {
  /** object URL or data URL, for the optimistic thumbnail */
  dataUrl: string;
  /** raw base64, resent as-is when a failed turn is retried */
  base64: string;
  name: string;
  width: number;
  height: number;
}

export interface MessageRow {
  id: string;
  session_id: string;
  role: "system" | "user" | "assistant" | "tool";
  sort: number;
  content: string;
  /** Photos attached to this message; [] when none. */
  images?: ImageRef[];
  /** Fragment of a previous answer this message replies to ("" when none). */
  quote: string;
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
  /** Mode id this dialog runs under; see ModeInfo. */
  mode: string;
  created_at: number;
  updated_at: number;
}

export interface SessionFull {
  session: SessionInfo;
  messages: MessageRow[];
}

/** One persona from the backend registry (GET /api/modes). */
export interface ModeInfo {
  id: string;
  title: string;
  hint: string;
  /** A single emoji, rendered as text — deliberately not an IconName. */
  icon: string;
  tools: "auto" | "on" | "off";
  /** Applied to the pane on switch; null means "no opinion, leave it alone". */
  think: "low" | "medium" | "high" | null;
  /** Extra slash-command tokens besides the id. */
  aliases: string[];
  /** Confirmation shown before switching into this mode; "" for most. */
  warn: string;
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
  user_text: string; // the prompt just sent — rendered optimistically until the turn is persisted
  /** Thumbnails for the in-flight turn; empty on regenerate (the row is already in history). */
  images: TurnImage[];
  quote: string; // the fragment that prompt replies to ("" when none)
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