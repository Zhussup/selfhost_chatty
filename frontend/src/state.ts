// Zustand store: sessions, active turn streaming state, settings.

import { create } from "zustand";
import { api, streamChat, type ChatRequestBody } from "./api";
import type {
  ChatTurn,
  MessageRow,
  ModelInfo,
  SessionInfo,
  StreamEvent,
  ToolCall,
} from "./types";

type Think = "low" | "medium" | "high" | null;

interface StoreState {
  booted: boolean;
  loggedIn: boolean;
  activeTab: "chat" | "stats";
  sessions: SessionInfo[];
  activeSessionId: string | null;
  history: MessageRow[];      // persisted rows of the active session (excluding streaming turn)
  turn: ChatTurn | null;      // in-flight streaming turn
  models: ModelInfo[];
  model: string;
  think: Think;
  useTools: boolean;
  busy: boolean;
  error: string | null;

  boot: () => Promise<void>;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  loadSessions: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  newSession: () => void;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  loadModels: () => Promise<void>;
  send: (content: string) => Promise<void>;
  stop: () => void;
  setModel: (name: string) => void;
  cycleThink: () => void;
  toggleTools: () => void;
}

const THINK_CYCLE: Think[] = [null, "low", "medium", "high"];
const abortStore = { controller: null as AbortController | null };

export const useStore = create<StoreState>((set, get) => ({
  booted: false,
  loggedIn: false,
  activeTab: "chat",
  sessions: [],
  activeSessionId: null,
  history: [],
  turn: null,
  models: [],
  model: "",
  think: null,
  useTools: true,
  busy: false,
  error: null,

  boot: async () => {
    try {
      await api.me();
      set({ loggedIn: true, booted: true });
      get().loadSessions().then(() => get().loadModels());
    } catch {
      set({ loggedIn: false, booted: true });
    }
  },

  login: async (password: string) => {
    await api.login(password);
    set({ loggedIn: true });
    get().loadSessions().then(() => get().loadModels());
  },

  logout: async () => {
    await api.logout();
    set({ loggedIn: false, sessions: [], history: [], turn: null });
  },

  loadSessions: async () => {
    const sessions = await api.sessions();
    set({ sessions });
  },

  openSession: async (id: string) => {
    set({ activeSessionId: id, history: [], turn: null });
    const full = await api.session(id);
    set({ history: full.messages, model: full.session.model || get().model });
  },

  newSession: () => set({ activeSessionId: null, history: [], turn: null, error: null }),

  deleteSession: async (id: string) => {
    await api.deleteSession(id);
    const sessions = get().sessions.filter((s) => s.id !== id);
    set({ sessions });
    if (get().activeSessionId === id) set({ activeSessionId: null, history: [] });
  },

  renameSession: async (id: string, title: string) => {
    await api.renameSession(id, title);
    set({ sessions: get().sessions.map((s) => (s.id === id ? { ...s, title } : s)) });
  },

  loadModels: async () => {
    try {
      const { models } = await api.models();
      set({ models });
      if (!get().model) {
        const preferred = models.find((m) => m.name === localStorage.getItem("default_model"))?.name
          ?? models[0]?.name
          ?? "";
        set({ model: preferred });
      }
    } catch {
      /* models stay empty; picker shows the error on open */
    }
  },

  send: async (content: string) => {
    const state = get();
    if (state.turn && !state.turn.done) return; // already streaming
    const body: ChatRequestBody = {
      session_id: state.activeSessionId,
      model: state.model,
      content,
      think: state.think,
      use_tools: state.useTools,
      regenerate: false,
    };
    const ctrl = new AbortController();
    abortStore.controller = ctrl;
    set({
      turn: {
        message_id: "",
        session_id: "",
        think_text: "",
        text: "",
        tools: [],
        done: false,
      },
      busy: true,
      error: null,
    });

    const apply = (ev: StreamEvent) => {
      switch (ev.t) {
        case "meta":
          set((st) => ({ turn: st.turn && { ...st.turn, message_id: ev.message_id, session_id: ev.session_id } }));
          break;
        case "delta":
          set((st) => ({ turn: st.turn && { ...st.turn, text: st.turn.text + ev.v } }));
          break;
        case "thinking":
          set((st) => ({ turn: st.turn && { ...st.turn, think_text: st.turn.think_text + ev.v } }));
          break;
        case "assistant_tool_calls":
          set((st) => ({
            turn:
              st.turn && {
                ...st.turn,
                tools: [
                  ...st.turn.tools,
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
          set((st) => ({
            turn:
              st.turn && {
                ...st.turn,
                tools: st.turn.tools.map((t) =>
                  t.id === ev.id
                    ? { ...t, ok: ev.ok, ms: ev.ms, result: ev.result }
                    : t
                ),
              },
          }));
          break;
        case "usage":
          set((st) => ({ turn: st.turn && { ...st.turn, usage: { prompt: ev.prompt, completion: ev.completion } } }));
          break;
        case "done":
          set((st) => ({
            turn: st.turn && { ...st.turn, done: true, reason: ev.reason, ms: ev.ms, usage: { prompt: ev.prompt, completion: ev.completion } },
          }));
          break;
        case "error":
          set((st) => ({
            turn: st.turn && { ...st.turn, done: true, error: `${ev.code}: ${ev.message}` },
          }));
          break;
        default:
          break; // ping & unknown — ignored
      }
    };

    try {
      await streamChat(body, apply, ctrl.signal);
    } catch (err) {
      const message = err instanceof Error ? err.message : "stream failed";
      set((st) => ({ turn: st.turn && !st.turn.done ? { ...st.turn, done: true, error: message } : st.turn }));
    } finally {
      abortStore.controller = null;
      // finalize: refresh from server to get canonical rows
      const sessionId = get().turn?.session_id || get().activeSessionId;
      if (sessionId) {
        try {
          const full = await api.session(sessionId);
          const sessions = get().sessions;
          const exists = sessions.some((s) => s.id === sessionId);
          set({
            history: full.messages,
            activeSessionId: sessionId,
            sessions: exists
              ? [full.session, ...sessions.filter((s) => s.id !== sessionId)]
              : [full.session, ...sessions],
          });
        } catch {
          /* keep optimistic state */
        }
      }
      set({ turn: null, busy: false });
    }
  },

  stop: () => {
    abortStore.controller?.abort();
  },

  setModel: (name: string) => {
    set({ model: name });
    try {
      localStorage.setItem("default_model", name);
    } catch {
      /* storage may be unavailable */
    }
  },

  cycleThink: () => {
    const cur = get().think;
    const next = THINK_CYCLE[(THINK_CYCLE.indexOf(cur) + 1) % THINK_CYCLE.length];
    set({ think: next });
  },

  toggleTools: () => set({ useTools: !get().useTools }),
}));