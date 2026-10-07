// Pure helpers over the pane split tree — no React, no store.
//
// A layout is a binary tree: leaves are panes, splits carry a direction
// ("row" = side by side, "col" = stacked) and a ratio in (0..1) for the first
// child. Split ratios are addressed by a path of child indices (0 = first,
// 1 = second), derived from the current tree on every render.

import type { ChatTurn, MessageRow } from "./types";

export type Think = "low" | "medium" | "high" | null;

export interface Pane {
  id: string;
  sessionId: string | null;
  history: MessageRow[];
  turn: ChatTurn | null;
  model: string;
  think: Think;
  useTools: boolean;
  /** Persona id from the mode registry (see backend/modes.py). */
  mode: string;
  busy: boolean;
  /** Pending quote for the next message — a fragment picked out of an answer.
   *  null = none. Not persisted: it is composer state, like the typed text. */
  quote: string | null;
}

export interface PaneNodeLeaf {
  kind: "leaf";
  paneId: string;
}

export interface PaneNodeSplit {
  kind: "split";
  dir: SplitDir;
  ratio: number;
  first: PaneNode;
  second: PaneNode;
}

export type PaneNode = PaneNodeLeaf | PaneNodeSplit;
export type SplitDir = "row" | "col";
export type MoveDir = "left" | "right" | "up" | "down";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const MAX_PANES = 6;
/** Persona a fresh pane starts in — mirrors backend/modes.DEFAULT_MODE_ID. */
export const DEFAULT_MODE = "assistant";
/** Capture cap for a picked quote — must stay under the backend's max_length. */
export const MAX_QUOTE_CHARS = 1600;
export const MIN_RATIO = 0.08;
export const MAX_RATIO = 0.92;

export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

let seq = 0;
/** Random suffix keeps ids unique across reloads even though the counter resets. */
export function newPaneId(): string {
  seq += 1;
  return `p${seq}-${Math.random().toString(36).slice(2, 8)}`;
}

export function makePane(id: string, model = ""): Pane {
  return {
    id,
    sessionId: null,
    history: [],
    turn: null,
    model,
    think: null,
    useTools: true,
    mode: DEFAULT_MODE,
    busy: false,
    quote: null,
  };
}

export function leaf(paneId: string): PaneNodeLeaf {
  return { kind: "leaf", paneId };
}

export function leafIds(node: PaneNode): string[] {
  if (node.kind === "leaf") return [node.paneId];
  return [...leafIds(node.first), ...leafIds(node.second)];
}

export function leafCount(node: PaneNode): number {
  return leafIds(node).length;
}

export function firstLeaf(node: PaneNode): string {
  return node.kind === "leaf" ? node.paneId : firstLeaf(node.first);
}

/** Replace the leaf `target` with a split holding the original leaf and `newId`. */
export function insertSplit(node: PaneNode, target: string, newId: string, dir: SplitDir): PaneNode {
  if (node.kind === "leaf") {
    if (node.paneId !== target) return node;
    return { kind: "split", dir, ratio: 0.5, first: node, second: leaf(newId) };
  }
  const first = insertSplit(node.first, target, newId, dir);
  const second = insertSplit(node.second, target, newId, dir);
  if (first === node.first && second === node.second) return node;
  return { ...node, first, second };
}

/** Remove a leaf; collapses a split that loses a child. null when nothing is left. */
export function removeLeaf(node: PaneNode, target: string): PaneNode | null {
  if (node.kind === "leaf") return node.paneId === target ? null : node;
  const first = removeLeaf(node.first, target);
  const second = removeLeaf(node.second, target);
  if (!first) return second;
  if (!second) return first;
  if (first === node.first && second === node.second) return node;
  return { ...node, first, second };
}

/** The first leaf of the sibling subtree of `target` — Tilix's close-focus rule. */
export function siblingFirstLeaf(node: PaneNode, target: string): string | null {
  if (node.kind === "leaf") return null;
  if (node.first.kind === "leaf" && node.first.paneId === target) return firstLeaf(node.second);
  if (node.second.kind === "leaf" && node.second.paneId === target) return firstLeaf(node.first);
  return siblingFirstLeaf(node.first, target) ?? siblingFirstLeaf(node.second, target);
}

/** Immutably set the ratio of the split node addressed by `path`. */
export function withRatio(node: PaneNode, path: number[], ratio: number): PaneNode {
  if (path.length === 0) {
    return node.kind === "split" ? { ...node, ratio: clamp(ratio, MIN_RATIO, MAX_RATIO) } : node;
  }
  if (node.kind !== "split") return node;
  const [i, ...rest] = path;
  if (i === 0) {
    const first = withRatio(node.first, rest, ratio);
    return first === node.first ? node : { ...node, first };
  }
  const second = withRatio(node.second, rest, ratio);
  return second === node.second ? node : { ...node, second };
}

/** Normalized rectangles of every leaf, for geometric focus navigation. */
export function collectRects(node: PaneNode, r: Rect, out: Map<string, Rect>): void {
  if (node.kind === "leaf") {
    out.set(node.paneId, r);
    return;
  }
  if (node.dir === "row") {
    const w1 = r.w * node.ratio;
    collectRects(node.first, { ...r, w: w1 }, out);
    collectRects(node.second, { ...r, x: r.x + w1, w: r.w - w1 }, out);
  } else {
    const h1 = r.h * node.ratio;
    collectRects(node.first, { ...r, h: h1 }, out);
    collectRects(node.second, { ...r, y: r.y + h1, h: r.h - h1 }, out);
  }
}

const EPS = 1e-6;

/** Nearest pane whose center lies in `dir` from `from`; null at the outer edge. */
export function findNeighbor(root: PaneNode, from: string, dir: MoveDir): string | null {
  const rects = new Map<string, Rect>();
  collectRects(root, { x: 0, y: 0, w: 1, h: 1 }, rects);
  const f = rects.get(from);
  if (!f) return null;
  const fx = f.x + f.w / 2;
  const fy = f.y + f.h / 2;
  let best: string | null = null;
  let bestScore = Infinity;
  for (const [id, r] of rects) {
    if (id === from) continue;
    const dx = r.x + r.w / 2 - fx;
    const dy = r.y + r.h / 2 - fy;
    const ok =
      dir === "left" ? dx < -EPS
      : dir === "right" ? dx > EPS
      : dir === "up" ? dy < -EPS
      : dy > EPS;
    if (!ok) continue;
    const primary = dir === "left" || dir === "right" ? Math.abs(dx) : Math.abs(dy);
    const perp = dir === "left" || dir === "right" ? Math.abs(dy) : Math.abs(dx);
    const score = primary + perp * 2; // overlap wins over raw distance
    if (score < bestScore) {
      bestScore = score;
      best = id;
    }
  }
  return best;
}

/** Drop leaves whose pane record is missing (validation of restored layouts). */
export function pruneMissing(node: PaneNode, validIds: Set<string>): PaneNode | null {
  if (node.kind === "leaf") return validIds.has(node.paneId) ? node : null;
  const first = pruneMissing(node.first, validIds);
  const second = pruneMissing(node.second, validIds);
  if (!first) return second;
  if (!second) return first;
  if (first === node.first && second === node.second) return node;
  return { ...node, first, second };
}

/** Runtime validation of a tree parsed from localStorage (untrusted). */
export function parseNode(raw: unknown): PaneNode | null {
  if (!raw || typeof raw !== "object") return null;
  const n = raw as Record<string, unknown>;
  if (n.kind === "leaf") {
    return typeof n.paneId === "string" ? { kind: "leaf", paneId: n.paneId } : null;
  }
  if (n.kind === "split") {
    if (n.dir !== "row" && n.dir !== "col") return null;
    if (typeof n.ratio !== "number" || !Number.isFinite(n.ratio)) return null;
    const first = parseNode(n.first);
    const second = parseNode(n.second);
    if (!first || !second) return null;
    return { kind: "split", dir: n.dir, ratio: clamp(n.ratio, MIN_RATIO, MAX_RATIO), first, second };
  }
  return null;
}
