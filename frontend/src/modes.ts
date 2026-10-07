// Mode lookups and the composer's slash-command parser. Pure — no store access.

import type { ModeInfo } from "./types";

export function modeById(modes: ModeInfo[], id: string): ModeInfo | null {
  return modes.find((m) => m.id === id) ?? null;
}

/** Resolve a token against ids and aliases, case-insensitively. */
export function findMode(modes: ModeInfo[], token: string): ModeInfo | null {
  const needle = token.trim().toLowerCase();
  if (!needle) return null;
  return modes.find((m) => m.id === needle || m.aliases.includes(needle)) ?? null;
}

export type SlashCommand =
  | { kind: "mode"; mode: ModeInfo; content: string }
  | { kind: "unknown"; token: string };

/**
 * A leading `/token` selects a mode. Returns null when the text is not a
 * command at all, so it is sent exactly as typed.
 *
 * The token has to be followed by whitespace or the end of the input, which is
 * what keeps `/usr/bin` and `/2` from being read as commands.
 */
export function parseSlash(text: string, modes: ModeInfo[]): SlashCommand | null {
  const m = /^\/([A-Za-z][A-Za-z0-9-]*)(?:\s+([\s\S]*))?$/.exec(text.trim());
  if (!m) return null;
  const mode = findMode(modes, m[1]);
  if (!mode) return { kind: "unknown", token: m[1] };
  return { kind: "mode", mode, content: (m[2] ?? "").trim() };
}
