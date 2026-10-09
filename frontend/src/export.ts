// Client-side export of a conversation.
//
// One neutral shape (`ExportEntry`) feeds both outputs: `.md` goes straight to
// the browser as a download, PDF goes through a print-only document (see
// PrintDoc.tsx) so the paper copy reuses the chat's own markdown rendering.
// The markdown here deliberately mirrors backend/routes/sessions.py:export_md,
// so a file exported from the UI reads the same as the sidebar's export.

import { imageUrl } from "./api";
import type { ChatTurn, MessageRow } from "./types";

/** A photo attached to a prompt, already reduced to something an <img> can take. */
export interface ExportImage {
  /** `/api/images/{id}` once the row is persisted; a `data:` URL for a turn that
   *  is still in flight and has no id to fetch the bytes back by. */
  src: string;
  name: string;
}

export interface ExportEntry {
  role: "user" | "assistant" | "tool";
  text: string;
  /** assistant reasoning, when the model produced any */
  thinking?: string;
  /** fragment of an earlier answer this prompt replies to */
  quote?: string;
  /** photos attached to this prompt */
  images?: ExportImage[];
  /** tool name (role === "tool") */
  name?: string;
  /** tool success flag (role === "tool") — false renders as a failed call */
  ok?: boolean;
  /** unix seconds */
  stamp?: number;
  model?: string | null;
}

const p2 = (n: number) => String(n).padStart(2, "0");

/** "2026-10-05 14:30" — local time, same shape the backend writes into .md */
export function fmtStamp(ts?: number): string {
  const d = ts ? new Date(ts * 1000) : new Date();
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/** "2026-10-05-1430" — a filename-safe stamp */
export function fileStamp(): string {
  return fmtStamp().replace(" ", "-").replace(":", "");
}

/** Lowercase, hyphenated, letters of any script kept (Cyrillic titles survive). */
export function slugify(s: string, fallback = "chat"): string {
  const out = s
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
  return out || fallback;
}

/** Rows worth exporting. Assistant rows that only carry tool calls are dropped:
 *  the tool rows themselves already show up in the list. */
export function entriesFromHistory(messages: MessageRow[]): ExportEntry[] {
  const out: ExportEntry[] = [];
  for (const m of messages) {
    if (m.role === "system") continue;
    if (m.role === "assistant" && !m.content && !m.thinking) continue;
    out.push({
      role: m.role,
      text: m.content,
      thinking: m.thinking || undefined,
      quote: m.quote || undefined,
      images: m.images?.length
        ? m.images.map((im) => ({ src: imageUrl(im.id), name: im.name || "image" }))
        : undefined,
      name: m.tool_name ?? undefined,
      ok: m.role === "tool" ? !m.error : undefined,
      stamp: m.created_at,
      model: m.model,
    });
  }
  return out;
}

/** The in-flight exchange, so the dialog export works mid-stream too. */
export function entriesFromTurn(turn: ChatTurn): ExportEntry[] {
  const out: ExportEntry[] = [];
  if (turn.user_text || turn.images.length > 0) {
    out.push({
      role: "user",
      text: turn.user_text,
      quote: turn.quote || undefined,
      // Not persisted yet, so these carry their data: URLs — the only case where
      // an export inlines image bytes. Exporting after the turn finishes links
      // to /api/images instead.
      images: turn.images.length
        ? turn.images.map((im) => ({ src: im.dataUrl, name: im.name || "image" }))
        : undefined,
    });
  }
  for (const t of turn.tools) {
    out.push({ role: "tool", name: t.name, text: t.result, ok: t.ok ?? undefined });
  }
  if (turn.text || turn.think_text) {
    out.push({ role: "assistant", text: turn.text, thinking: turn.think_text || undefined });
  }
  return out;
}

export function entriesToMarkdown(title: string, entries: ExportEntry[]): string {
  const parts: string[] = [`# ${title}`, ""];
  for (const e of entries) {
    const stamp = fmtStamp(e.stamp);
    if (e.role === "user") {
      parts.push(`## You · ${stamp}`, "");
      const quoted = (e.quote ?? "").trim();
      if (quoted) parts.push("> " + quoted.split("\n").join("\n> "), "");
      // Same shape backend/routes/sessions.py:export_md writes: a reference, never
      // inlined bytes, so a photo-heavy chat stays a small text file.
      for (const im of e.images ?? []) parts.push(`![${im.name}](${im.src})`, "");
      parts.push(e.text, "");
    } else if (e.role === "assistant") {
      parts.push(`## Assistant · ${stamp}`, "");
      if (e.thinking) {
        parts.push(`<details><summary>thinking</summary>\n\n${e.thinking}\n\n</details>`, "");
      }
      if (e.text) parts.push(e.text, "");
    } else {
      parts.push(`### tool result — ${e.name ?? "?"}${e.ok === false ? " (failed)" : ""}`, "");
      parts.push("```\n" + e.text + "\n```", "");
    }
  }
  return parts.join("\n");
}

/** Hand the browser a file to save. */
export function downloadMarkdown(filename: string, markdown: string): void {
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Safari needs the object URL alive while the download starts
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
