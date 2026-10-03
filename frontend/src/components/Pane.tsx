import { useEffect, useRef } from "react";
import Message from "./Message";
import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip, { type ChipData } from "./ToolChip";
import Composer from "./Composer";
import ModelPicker from "./ModelPicker";
import MsgActions from "./MsgActions";
import Icon from "./Icon";
import { useTypewriter } from "./useTypewriter";
import { PaneProvider, usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import type { ChatTurn, MessageRow } from "../types";

const EMPTY_HISTORY: MessageRow[] = [];

/** Focus a pane's composer. Called from the keyboard/split paths, never on click. */
export function focusComposer(paneId: string): void {
  requestAnimationFrame(() => {
    document.querySelector<HTMLTextAreaElement>(`[data-pane="${paneId}"] textarea`)?.focus();
  });
}

function friendlyError(raw: string): string {
  if (raw.includes("rate_limited")) {
    return "Too many turns running (max 2) — stop another pane and retry.";
  }
  return raw;
}

export default function Pane({ paneId }: { paneId: string }) {
  const exists = useStore((st) => !!st.panes[paneId]);
  const focused = useStore((st) => st.focusedPaneId === paneId);

  // Focus the composer when this pane becomes focused, but only when nothing
  // else holds focus — so splitting never yanks the caret out of another pane.
  useEffect(() => {
    const active = document.activeElement;
    if (focused && (active === null || active === document.body)) focusComposer(paneId);
  }, [focused, paneId]);

  // a closed pane can still render one frame before its parent drops it
  if (!exists) return null;
  return (
    <PaneProvider paneId={paneId}>
      <section
        className={focused ? "pane focused" : "pane"}
        data-pane={paneId}
        onPointerDownCapture={() => useStore.getState().focusPane(paneId)}
      >
        <PaneHeader paneId={paneId} />
        <PaneBody />
      </section>
    </PaneProvider>
  );
}

/**
 * Module scope on purpose: defining this inside `Pane` would make a new
 * component type every render and remount the subtree (losing composer text).
 *
 * The child order is fixed — MessageList then the composer's wrapper — so the
 * empty→non-empty transition only flips a class on `.pane-body` and never
 * remounts `<Composer>`.
 */
function PaneBody() {
  const sessionId = usePane((p) => p.sessionId, null);
  const turn = usePane((p) => p.turn, null);
  const historyLen = usePane((p) => p.history.length, 0);
  const empty = sessionId === null && !turn && historyLen === 0;

  return (
    <div className={empty ? "pane-body empty" : "pane-body"}>
      <MessageList />
      <div className="composer-wrap">
        <Composer empty={empty} />
      </div>
    </div>
  );
}

function PaneHeader({ paneId }: { paneId: string }) {
  const sessionId = usePane((p) => p.sessionId, null);
  const streaming = usePane((p) => !!p.turn && !p.turn.done, false);
  const sessions = useStore((st) => st.sessions);
  const title = sessions.find((s) => s.id === sessionId)?.title ?? "New chat";

  const split = (dir: "row" | "col") => {
    useStore.getState().splitPane(paneId, dir);
    focusComposer(useStore.getState().focusedPaneId);
  };

  return (
    <div className="pane-head">
      {streaming && <span className="dot pulse" />}
      <span className="pane-title">{title}</span>
      <ModelPicker />
      <button className="icon" title="Split right — Ctrl+Shift+E" onClick={() => split("row")}>
        <Icon name="splitV" />
      </button>
      <button className="icon" title="Split down — Ctrl+Shift+O" onClick={() => split("col")}>
        <Icon name="splitH" />
      </button>
      <button
        className="icon hide-narrow"
        title="Close pane — Ctrl+Shift+W"
        onClick={() => {
          useStore.getState().closePane(paneId);
          focusComposer(useStore.getState().focusedPaneId);
        }}
      >
        <Icon name="close" />
      </button>
    </div>
  );
}

function MessageList() {
  const paneId = usePaneId();
  const sessionId = usePane((p) => p.sessionId, null);
  const turn = usePane((p) => p.turn, null);
  const history = usePane((p) => p.history, EMPTY_HISTORY);
  const busy = usePane((p) => p.busy, false);
  // Smooths the streamed answer; owned here (not in StreamingTurn) so the
  // scroll effect below can track the displayed length as it grows.
  const displayText = useTypewriter(turn?.text ?? "", !!turn && !turn.done);
  const stick = useRef(true);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (stick.current && el) {
      // scrollTop, not scrollIntoView — the latter can scroll the outer pane tree
      el.scrollTop = el.scrollHeight;
    }
  }, [
    history.length,
    history[history.length - 1]?.content,
    displayText,
    turn?.think_text,
    turn?.tools.length,
    turn?.done,
  ]);

  const lastId = history[history.length - 1]?.id;

  return (
    <div className="msg-list" ref={listRef}>
      {sessionId === null && !turn && <Welcome />}
      {history.map((m) => {
        if (m.role === "assistant" && m.tool_calls && m.tool_calls.length && !m.content && !m.thinking) {
          // assistant rows that exist only to carry tool calls render through the tool rows
          return null;
        }
        // Only the newest answer can be regenerated — an older one would rerun
        // the tail exchange instead, which is not what the button promises.
        const canRetry = m.role === "assistant" && m.id === lastId && !busy && !turn;
        return (
          <div key={m.id}>
            <Message
              msg={m}
              onRetry={canRetry ? () => useStore.getState().retry(paneId) : undefined}
            />
          </div>
        );
      })}
      {turn && showUserBubble(turn) && (
        <div className="msg user">
          <div className="bubble">{turn.user_text}</div>
        </div>
      )}
      {turn && <StreamingTurn turn={turn} text={displayText} />}
    </div>
  );
}

/** The prompt is shown right away — but not when the turn never reached the
 *  server (e.g. 409 rate_limited), where nothing was persisted to show. */
function showUserBubble(turn: ChatTurn): boolean {
  return !!turn.user_text && (turn.session_id !== "" || !turn.error);
}

function StreamingTurn({ turn, text }: { turn: ChatTurn; text: string }) {
  const paneId = usePaneId();
  const busy = usePane((p) => p.busy, false);
  // Uses the *displayed* text, so the placeholder holds until the typewriter
  // has revealed its first characters instead of blinking empty.
  const waiting = !turn.done && !turn.error && !text && !turn.think_text && turn.tools.length === 0;
  return (
    <div className="msg assistant streaming">
      <div className="msg-avatar">
        <Icon name="sparkle" size={15} />
      </div>
      <div className="msg-main">
        {waiting && (
          <div className="waiting">
            <span className="ldot" />
            <span className="ldot" />
            <span className="ldot" />
          </div>
        )}
        <ThinkingBlock text={turn.think_text} active={!turn.done} />
        {turn.tools.map((t) => {
          const chip: ChipData = {
            id: t.id,
            name: t.name,
            arguments: t.arguments,
            ok: t.ok,
            ms: t.ms,
            result: t.result,
          };
          return <ToolChip key={t.id} chip={chip} />;
        })}
        <Markdown text={text} />
        {turn.error && <div className="error-note">{friendlyError(turn.error)}</div>}
        {turn.usage && (
          <div className="stamp">
            {turn.usage.prompt} in + {turn.usage.completion} out tokens{turn.done ? "" : " so far"}
          </div>
        )}
        {turn.done && !busy && (
          <MsgActions copyText={turn.text} onRetry={() => useStore.getState().retry(paneId)} />
        )}
      </div>
    </div>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <div className="welcome-mark">
        <Icon name="sparkle" size={26} />
      </div>
      <h1>How can I help you today?</h1>
      <p>
        Self-hosted chat on Ollama Cloud. Tools available: web search, page reading, exact
        math, python, long-term memory.
      </p>
    </div>
  );
}
