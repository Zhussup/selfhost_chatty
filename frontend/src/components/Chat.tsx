import { useEffect, useRef } from "react";
import Message from "./Message";
import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip, { type ChipData } from "./ToolChip";
import Composer from "./Composer";
import ModelPicker from "./ModelPicker";
import Sidebar from "./Sidebar";
import { useStore } from "../state";
import type { ChatTurn } from "../types";

export default function Chat() {
  const sessionId = useStore((st) => st.activeSessionId);
  const turn = useStore((st) => st.turn);

  return (
    <div className="chat">
      <Sidebar />
      <div className="chat-main">
        <div className="chat-top">
          <ModelPicker />
        </div>
        <MessageList sessionId={sessionId} turn={turn} />
        <Composer />
      </div>
    </div>
  );
}

function MessageList({ sessionId, turn }: { sessionId: string | null; turn: ChatTurn | null }) {
  const history = useStore((st) => st.history);
  const bottomRef = useRef<HTMLDivElement>(null);
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
    if (stick.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [history.length, history[history.length - 1]?.content, turn?.text, turn?.think_text, turn?.tools.length, turn?.done]);

  return (
    <div className="msg-list" ref={listRef}>
      {sessionId === null && !turn && <Welcome />}
      {history.map((m) => {
        if (m.role === "assistant" && m.tool_calls && m.tool_calls.length && !m.content && !m.thinking) {
          // assistant rows that exist only to carry tool calls are rendered through the following tool rows
          return null;
        }
        return (
          <div key={m.id}>
            <Message msg={m} />
          </div>
        );
      })}
      {turn && <StreamingTurn turn={turn} />}
      <div ref={bottomRef} />
    </div>
  );
}

function StreamingTurn({ turn }: { turn: ChatTurn }) {
  return (
    <div className="msg assistant streaming">
      <ThinkingBlock text={turn.think_text} active={!turn.done} />
      {turn.tools.map((t) => {
        const chip: ChipData = { id: t.id, name: t.name, arguments: t.arguments, ok: t.ok, ms: t.ms, result: t.result };
        return <ToolChip key={t.id} chip={chip} />;
      })}
      <Markdown text={turn.text} />
      {turn.usage && (
        <div className="stamp">
          {turn.usage.prompt} in + {turn.usage.completion} out tokens{turn.done ? "" : " so far"}
        </div>
      )}
    </div>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <h1>Chat</h1>
      <p>
        Self-hosted chat on Ollama Cloud. Tools available: web search, page reading, exact math,
        python, long-term memory.
      </p>
    </div>
  );
}