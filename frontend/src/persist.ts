// Layout persistence: what panes exist, how they are split, and each pane's
// session/model/think/tools. History and in-flight text are deliberately NOT
// persisted — they are re-fetched on restore, and excluding them keeps the
// store subscription from firing on every stream delta.

import {
  leafIds,
  makePane,
  parseNode,
  pruneMissing,
  type Pane,
  type PaneNode,
  type Think,
} from "./panes";

const KEY = "chat.layout.v1";
const V = 1;

/** The slice of store state the layout depends on. */
export interface LayoutState {
  root: PaneNode;
  focusedPaneId: string;
  panes: Record<string, Pane>;
}

export interface LayoutStore {
  getState: () => LayoutState;
  subscribe: (listener: (state: LayoutState) => void) => () => void;
}

interface PersistedPane {
  sessionId: string | null;
  model: string;
  think: Think;
  useTools: boolean;
}

function persistedPanes(panes: Record<string, Pane>): Record<string, PersistedPane> {
  const out: Record<string, PersistedPane> = {};
  for (const [id, p] of Object.entries(panes)) {
    out[id] = { sessionId: p.sessionId, model: p.model, think: p.think, useTools: p.useTools };
  }
  return out;
}

/** Cheap derived signature — changes only on structural/settings edits, never on streaming. */
export function layoutKey(st: LayoutState): string {
  return JSON.stringify({
    root: st.root,
    focused: st.focusedPaneId,
    panes: persistedPanes(st.panes),
  });
}

export function saveNow(st: LayoutState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ v: V, ...JSON.parse(layoutKey(st)) }));
  } catch {
    /* storage may be unavailable (private mode / quota) — layout just won't persist */
  }
}

export function clearLayout(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function loadLayout(): (LayoutState & { panes: Record<string, Pane> }) | null {
  let raw: unknown;
  try {
    raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  const s = raw as { v?: unknown; root?: unknown; focused?: unknown; panes?: unknown };
  if (s.v !== V || !s.panes || typeof s.panes !== "object") return null;

  const rawPanes = s.panes as Record<string, Partial<PersistedPane>>;
  const known = new Set(Object.keys(rawPanes));
  const root = parseNode(s.root);
  if (!root) return null;

  // drop leaves without a record; records the tree never references are ignored
  const pruned = pruneMissing(root, known);
  if (!pruned) return null;
  const live = new Set(leafIds(pruned));

  const panes: Record<string, Pane> = {};
  for (const id of live) {
    const p = rawPanes[id] ?? {};
    const pane = makePane(id, typeof p.model === "string" ? p.model : "");
    pane.sessionId = typeof p.sessionId === "string" ? p.sessionId : null;
    pane.think = p.think === "low" || p.think === "medium" || p.think === "high" ? p.think : null;
    pane.useTools = p.useTools !== false;
    panes[id] = pane;
  }
  const focused = typeof s.focused === "string" && live.has(s.focused) ? s.focused : live.values().next().value!;
  return { root: pruned, panes, focusedPaneId: focused };
}

/** Subscribe once; write only when the derived key changes, debounced. */
export function installPersistence(store: LayoutStore): () => void {
  let last = layoutKey(store.getState());
  let timer: number | undefined;
  const flush = () => saveNow(store.getState());

  const unsub = store.subscribe((st) => {
    const key = layoutKey(st);
    if (key === last) return; // streaming deltas never reach here
    last = key;
    window.clearTimeout(timer);
    timer = window.setTimeout(flush, 300); // coalesces divider-drag frames
  });
  const onUnload = () => flush();
  window.addEventListener("beforeunload", onUnload);
  return () => {
    unsub();
    window.removeEventListener("beforeunload", onUnload);
    window.clearTimeout(timer);
  };
}
