// Zustand store: sessions, models, and the pane split layout.
//
// Every per-dialog field (session, history, in-flight turn, model, think,
// tools, busy) lives on a Pane. The layout is a binary tree of panes; tree
// edits are pure helpers from panes.ts. Streaming events patch a single pane,
// so untouched panes keep their object identity and do not re-render.

import { create } from "zustand";
import { api, streamChat, type ChatRequestBody } from "./api";
import type { MessageRow, ModelInfo, SessionInfo, StreamEvent, ToolCall } from "./types";
import { clearLayout, loadLayout } from "./persist";
import type { ExportEntry } from "./export";
import {
  clamp,
  findNeighbor,
  firstLeaf,
  insertSplit,
  leaf,
  leafCount,
  makePane,
  newPaneId,
  removeLeaf,
  siblingFirstLeaf,
  withRatio,
  MAX_PANES,
  type MoveDir,
  type Pane,
  type PaneNode,
  type SplitDir,
  type Think,
} from "./panes";

interface StoreState {
  booted: boolean;
  loggedIn: boolean;
  activeTab: "chat" | "stats";
  sessions: SessionInfo[];
  models: ModelInfo[];

  panes: Record<string, Pane>;
  root: PaneNode;
  focusedPaneId: string;

  /** Non-null while a print-only copy of a conversation is mounted (PrintDoc).
   *  Lives in the store, not in the menu that triggered it: the menu sits in a
   *  hover-revealed footer that may unmount before the print dialog closes. */
  printJob: { title: string; entries: ExportEntry[] } | null;

  boot: () => Promise<void>;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  loadSessions: () => Promise<void>;
  loadModels: () => Promise<void>;
  hydratePanes: () => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;

  openSession: (paneId: string, id: string) => Promise<void>;
  openInFocusedPane: (id: string) => Promise<void>;
  newSession: (paneId: string) => void;
  send: (
    paneId: string,
    content: string,
    opts?: { regenerate?: boolean; quote?: string; edit_message_id?: string }
  ) => Promise<void>;
  editMessage: (paneId: string, messageId: string, text: string) => void;
  retry: (paneId: string) => void;
  setQuote: (paneId: string, text: string) => void;
  clearQuote: (paneId: string) => void;
  stop: (paneId: string) => void;
  setModel: (paneId: string, name: string) => void;
  cycleThink: (paneId: string) => void;
  toggleTools: (paneId: string) => void;

  /** Open a conversation in the print-only document (PDF via the print dialog). */
  printDoc: (title: string, entries: ExportEntry[]) => void;
  /** Called by PrintDoc once the print dialog is done. */
  endPrint: () => void;

  splitPane: (paneId: string, dir: SplitDir) => void;
  closePane: (paneId: string) => void;
  focusPane: (paneId: string) => void;
  focusDir: (dir: MoveDir) => void;
  setRatio: (path: number[], ratio: number) => void;
}

const THINK_CYCLE: Think[] = [null, "low", "medium", "high"];
const abortStore: Record<string, AbortController> = {};

const firstId = newPaneId();

function resetPanesForLogout(): Pick<StoreState, "root" | "panes" | "focusedPaneId"> {
  const id = newPaneId();
  return { root: leaf(id), panes: { [id]: makePane(id) }, focusedPaneId: id };
}

/** History up to and including the last user row — mirrors the backend's
 *  `_truncate_after_last_user` for `regenerate`, so the stale answer is gone
 *  as soon as the retry starts instead of lingering until the server refresh. */
function truncateAfterLastUser(history: MessageRow[]): MessageRow[] {
  for (let i = history.length - 1; i >= 0; i--) {
    if (history[i].role === "user") return history.slice(0, i + 1);
  }
  return history;
}

/** History up to (excluding) the given message — used while an edit streams, since
 *  the edited prompt is re-rendered optimistically from the turn. */
function truncateBeforeId(history: MessageRow[], id: string): MessageRow[] {
  const i = history.findIndex((m) => m.id === id);
  return i === -1 ? history : history.slice(0, i);
}

function abortAll(): void {
  for (const ctrl of Object.values(abortStore)) ctrl.abort();
  for (const id of Object.keys(abortStore)) delete abortStore[id];
}

export const useStore = create<StoreState>((set, get) => {
  /** Merge a partial change into one pane; a no-op if the pane is gone. */
  const patch = (paneId: string, fn: (p: Pane) => Partial<Pane>) =>
    set((s) => {
      const p = s.panes[paneId];
      return p ? { panes: { ...s.panes, [paneId]: { ...p, ...fn(p) } } } : {};
    });

  const restoreLayout = () => {
    const saved = loadLayout();
    if (saved) set({ root: saved.root, panes: saved.panes, focusedPaneId: saved.focusedPaneId });
  };

  const afterLogin = async () => {
    restoreLayout();
    // a transient failure here must not log the user back out
    try {
      await get().loadSessions();
    } catch {
      /* sidebar stays empty; retried on the next session action */
    }
    await get().loadModels(); // swallows its own errors
    await get().hydratePanes(); // swallows per-pane errors
  };

  return {
    booted: false,
    loggedIn: false,
    activeTab: "chat",
    sessions: [],
    models: [],

    panes: { [firstId]: makePane(firstId) },
    root: leaf(firstId),
    focusedPaneId: firstId,

    printJob: null,

    boot: async () => {
      try {
        await api.me();
      } catch {
        set({ loggedIn: false, booted: true });
        return;
      }
      set({ loggedIn: true, booted: true });
      await afterLogin();
    },

    login: async (password: string) => {
      await api.login(password);
      set({ loggedIn: true });
      await afterLogin();
    },

    logout: async () => {
      abortAll();
      clearLayout();
      await api.logout();
      set({ loggedIn: false, sessions: [], ...resetPanesForLogout() });
    },

    loadSessions: async () => {
      const sessions = await api.sessions();
      set({ sessions });
    },

    loadModels: async () => {
      try {
        const { models } = await api.models();
        set({ models });
        let stored: string | null = null;
        try {
          stored = localStorage.getItem("default_model");
        } catch {
          /* storage may be unavailable */
        }
        const pick = (cur: string) =>
          cur || models.find((m) => m.name === stored)?.name || models[0]?.name || "";
        set((s) => {
          const panes: Record<string, Pane> = {};
          for (const [id, p] of Object.entries(s.panes)) panes[id] = { ...p, model: pick(p.model) };
          return { panes };
        });
      } catch {
        /* models stay empty; picker shows the error on open */
      }
    },

    hydratePanes: async () => {
      const ids = Object.values(get().panes)
        .filter((p) => p.sessionId)
        .map((p) => p.id);
      await Promise.all(
        ids.map(async (pid) => {
          const sid = get().panes[pid]?.sessionId;
          if (!sid) return;
          try {
            const full = await api.session(sid);
            set((s) => {
              const p = s.panes[pid];
              if (!p || p.sessionId !== sid) return {};
              return {
                panes: {
                  ...s.panes,
                  [pid]: { ...p, history: full.messages, model: p.model || full.session.model },
                },
              };
            });
          } catch {
            // session deleted server-side: leave an empty pane, don't break boot
            set((s) => {
              const p = s.panes[pid];
              if (!p) return {};
              return { panes: { ...s.panes, [pid]: { ...p, sessionId: null, history: [] } } };
            });
          }
        })
      );
    },

    deleteSession: async (id: string) => {
      await api.deleteSession(id);
      for (const [pid, p] of Object.entries(get().panes)) {
        if (p.sessionId === id) {
          abortStore[pid]?.abort();
          delete abortStore[pid];
        }
      }
      set((s) => {
        const panes: Record<string, Pane> = {};
        for (const [pid, p] of Object.entries(s.panes)) {
          panes[pid] =
            p.sessionId === id
              ? { ...p, sessionId: null, history: [], turn: null, busy: false, quote: null }
              : p;
        }
        return { sessions: s.sessions.filter((x) => x.id !== id), panes };
      });
    },

    renameSession: async (id: string, title: string) => {
      await api.renameSession(id, title);
      set({ sessions: get().sessions.map((s) => (s.id === id ? { ...s, title } : s)) });
    },

    openSession: async (paneId, id) => {
      abortStore[paneId]?.abort();
      patch(paneId, () => ({ sessionId: id, history: [], turn: null, busy: false, quote: null }));
      const full = await api.session(id);
      set((s) => {
        const p = s.panes[paneId];
        // a newer open/send may have replaced this pane's session meanwhile
        if (!p || p.sessionId !== id) return {};
        return {
          panes: {
            ...s.panes,
            [paneId]: { ...p, history: full.messages, model: p.model || full.session.model },
          },
        };
      });
    },

    openInFocusedPane: async (id: string) => {
      await get().openSession(get().focusedPaneId, id);
    },

    newSession: (paneId) => {
      abortStore[paneId]?.abort();
      delete abortStore[paneId];
      patch(paneId, () => ({ sessionId: null, history: [], turn: null, busy: false, quote: null }));
    },

    send: async (paneId, content, opts) => {
      const st = get();
      const pane = st.panes[paneId];
      if (!pane) return;
      if (pane.turn && !pane.turn.done) return; // already streaming
      const model = pane.model || st.models[0]?.name || "";
      if (!model) return;

      const regenerate = opts?.regenerate === true;
      const editId = opts?.edit_message_id;
      // Regenerate never carries a quote: the stored user row already owns one
      // (and the backend ignores the field on that path anyway).
      const quote = regenerate ? "" : opts?.quote !== undefined ? opts.quote : (pane.quote ?? "");
      const ctrl = new AbortController();
      abortStore[paneId] = ctrl;
      patch(paneId, () => ({
        turn: {
          message_id: "",
          session_id: "",
          // On regenerate the user row is already in history, so an optimistic
          // bubble would echo it twice.
          user_text: regenerate ? "" : content,
          quote,
          think_text: "",
          text: "",
          tools: [],
          done: false,
        },
        history: regenerate
          ? truncateAfterLastUser(pane.history)
          : editId
            ? truncateBeforeId(pane.history, editId)
            : pane.history,
        busy: true,
        quote: null,
      }));

      const apply = (ev: StreamEvent) => {
        switch (ev.t) {
          case "meta":
            patch(paneId, (p) => ({
              sessionId: ev.session_id,
              turn: p.turn && { ...p.turn, message_id: ev.message_id, session_id: ev.session_id },
            }));
            break;
          case "delta":
            patch(paneId, (p) => ({ turn: p.turn && { ...p.turn, text: p.turn.text + ev.v } }));
            break;
          case "thinking":
            patch(paneId, (p) => ({
              turn: p.turn && { ...p.turn, think_text: p.turn.think_text + ev.v },
            }));
            break;
          case "assistant_tool_calls":
            patch(paneId, (p) => ({
              turn:
                p.turn && {
                  ...p.turn,
                  tools: [
                    ...p.turn.tools,
                    ...ev.calls.map((c: ToolCall) => ({
                      id: c.id,
                      name: c.name,
                      arguments: c.arguments,
                      ok: null as boolean | null,
                      ms: 0,
                      result: "",
                    })),
                  ],
                },
            }));
            break;
          case "tool_result":
            patch(paneId, (p) => ({
              turn:
                p.turn && {
                  ...p.turn,
                  tools: p.turn.tools.map((t) =>
                    t.id === ev.id ? { ...t, ok: ev.ok, ms: ev.ms, result: ev.result } : t
                  ),
                },
            }));
            break;
          case "usage":
            patch(paneId, (p) => ({
              turn: p.turn && { ...p.turn, usage: { prompt: ev.prompt, completion: ev.completion } },
            }));
            break;
          case "done":
            patch(paneId, (p) => ({
              turn:
                p.turn && {
                  ...p.turn,
                  done: true,
                  reason: ev.reason,
                  ms: ev.ms,
                  usage: { prompt: ev.prompt, completion: ev.completion },
                },
            }));
            break;
          case "error":
            patch(paneId, (p) => ({
              turn: p.turn && { ...p.turn, done: true, error: `${ev.code}: ${ev.message}` },
            }));
            break;
          default:
            break; // ping & unknown — ignored
        }
      };

      const body: ChatRequestBody = {
        session_id: pane.sessionId,
        model,
        content,
        ...(quote ? { quote } : {}),
        think: pane.think,
        use_tools: pane.useTools,
        regenerate,
        ...(editId ? { edit_message_id: editId } : {}),
      };

      try {
        await streamChat(body, apply, ctrl.signal);
      } catch (err) {
        if (ctrl.signal.aborted) {
          // user pressed Stop — not an error
          patch(paneId, (p) => ({ turn: p.turn && { ...p.turn, done: true }, busy: false }));
        } else {
          const message = err instanceof Error ? err.message : "stream failed";
          patch(paneId, (p) => ({
            turn: p.turn && !p.turn.done ? { ...p.turn, done: true, error: message } : p.turn,
            busy: false,
          }));
        }
      } finally {
        if (abortStore[paneId] === ctrl) delete abortStore[paneId];
        const cur = get().panes[paneId];
        const sid = cur?.turn?.session_id || cur?.sessionId || null;
        // A failure before anything streamed (e.g. 409 rate_limited) persists
        // no history row, so keep the turn around — otherwise the message would
        // be wiped here and the user would never see why nothing happened.
        const endedTurn = cur?.turn ?? null;
        const keepTurn = !!endedTurn?.error && !endedTurn.text && endedTurn.tools.length === 0;
        const finish = (p: Pane): Pane =>
          keepTurn ? { ...p, busy: false } : { ...p, turn: null, busy: false };
        if (sid) {
          try {
            const full = await api.session(sid);
            set((s) => {
              const panes: Record<string, Pane> = {};
              for (const [pid, p] of Object.entries(s.panes)) {
                // broadcast to every pane showing the same session
                panes[pid] = pid === paneId || p.sessionId === sid
                  ? { ...p, sessionId: sid, history: full.messages }
                  : p;
              }
              if (panes[paneId]) panes[paneId] = finish(panes[paneId]);
              // functional upsert — concurrent finalizes must not duplicate rows
              return {
                panes,
                sessions: [full.session, ...s.sessions.filter((x) => x.id !== full.session.id)],
              };
            });
          } catch {
            patch(paneId, finish);
          }
        } else {
          patch(paneId, finish);
        }
      }
    },

    /** Rewrite an already-sent prompt and regenerate the answer from it. */
    editMessage: (paneId, messageId, text) => {
      const pane = get().panes[paneId];
      if (!pane || pane.busy || (pane.turn && !pane.turn.done)) return;
      const trimmed = text.trim();
      if (!trimmed) return;
      void get().send(paneId, trimmed, { edit_message_id: messageId });
    },

    /** Regenerate the last exchange, resuming from wherever the pane left off. */
    retry: (paneId) => {
      const pane = get().panes[paneId];
      if (!pane || pane.busy) return;
      const turn = pane.turn;
      if (turn && !turn.done) return; // still streaming

      if (turn) {
        // A turn kept after a failure. When no `meta` ever arrived the prompt
        // was never persisted (409 / pre-stream error), so it has to be resent
        // as a normal message — regenerating would truncate against an older
        // exchange and the model would answer the wrong prompt.
        if (!turn.user_text) return;
        // The quote travels with the resent prompt — picking up whatever chip is
        // pending in the composer would retry a different message than the one
        // that failed. Regenerate reads the stored row instead, so no quote here.
        if (turn.session_id === "") get().send(paneId, turn.user_text, { quote: turn.quote });
        else get().send(paneId, turn.user_text, { regenerate: true });
        return;
      }

      // History only: the last user row is what the backend truncates after.
      // It rejects empty content, so retry is unavailable without it.
      for (let i = pane.history.length - 1; i >= 0; i--) {
        const m = pane.history[i];
        if (m.role === "user") {
          if (m.content) get().send(paneId, m.content, { regenerate: true });
          return;
        }
      }
    },

    stop: (paneId) => {
      abortStore[paneId]?.abort();
    },

    setQuote: (paneId, text) => {
      patch(paneId, () => ({ quote: text }));
    },

    clearQuote: (paneId) => {
      patch(paneId, () => ({ quote: null }));
    },

    setModel: (paneId, name) => {
      patch(paneId, () => ({ model: name }));
      try {
        localStorage.setItem("default_model", name);
      } catch {
        /* storage may be unavailable */
      }
    },

    cycleThink: (paneId) => {
      patch(paneId, (p) => ({
        think: THINK_CYCLE[(THINK_CYCLE.indexOf(p.think) + 1) % THINK_CYCLE.length],
      }));
    },

    toggleTools: (paneId) => {
      patch(paneId, (p) => ({ useTools: !p.useTools }));
    },

    printDoc: (title, entries) => {
      if (entries.length) set({ printJob: { title, entries } });
    },

    endPrint: () => {
      if (get().printJob) set({ printJob: null });
    },

    splitPane: (paneId, dir) => {
      const { root, panes } = get();
      const src = panes[paneId];
      if (!src || leafCount(root) >= MAX_PANES) return;
      const nid = newPaneId();
      const np: Pane = { ...makePane(nid, src.model), think: src.think, useTools: src.useTools };
      set({ root: insertSplit(root, paneId, nid, dir), panes: { ...panes, [nid]: np }, focusedPaneId: nid });
    },

    closePane: (paneId) => {
      const { root, panes, focusedPaneId, models } = get();
      abortStore[paneId]?.abort();
      delete abortStore[paneId];

      if (root.kind === "leaf") {
        // the only pane is never removed — reset it to a fresh chat instead
        const id = paneId;
        const model = panes[id]?.model || models[0]?.name || "";
        set({ panes: { ...panes, [id]: makePane(id, model) }, focusedPaneId: id });
        return;
      }

      const next = removeLeaf(root, paneId);
      if (!next) return;
      const successor =
        focusedPaneId === paneId ? (siblingFirstLeaf(root, paneId) ?? firstLeaf(next)) : focusedPaneId;
      const panesNext: Record<string, Pane> = { ...panes };
      delete panesNext[paneId];
      set({
        root: next,
        panes: panesNext,
        focusedPaneId: panesNext[successor] ? successor : firstLeaf(next),
      });
    },

    focusPane: (paneId) => {
      if (get().panes[paneId] && get().focusedPaneId !== paneId) set({ focusedPaneId: paneId });
    },

    focusDir: (dir) => {
      const { root, focusedPaneId } = get();
      const next = findNeighbor(root, focusedPaneId, dir);
      if (next) set({ focusedPaneId: next });
    },

    setRatio: (path, ratio) => {
      set((s) => ({ root: withRatio(s.root, path, clamp(ratio, 0.08, 0.92)) }));
    },
  };
});
