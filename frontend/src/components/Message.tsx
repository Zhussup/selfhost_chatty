import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip from "./ToolChip";
import type { ChipData } from "./ToolChip";
import type { MessageRow } from "../types";

function timeStr(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function Message({ msg }: { msg: MessageRow }) {
  if (msg.role === "system") return null;

  if (msg.role === "tool") {
    const chip: ChipData = {
      id: msg.tool_call_id ?? msg.id,
      name: msg.tool_name ?? "tool",
      ok: !msg.error,
      ms: 0,
      result: msg.content,
    };
    return <ToolChip chip={chip} />;
  }

  if (msg.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{msg.content}</div>
        <div className="stamp">{timeStr(msg.created_at)}</div>
      </div>
    );
  }

  // assistant
  const errored = !!msg.error;
  return (
    <div className={`msg assistant${errored ? " errored" : ""}`}>
      <ThinkingBlock text={msg.thinking ?? ""} active={false} />
      {msg.content ? (
        <Markdown text={msg.content} />
      ) : errored ? (
        <div className="md error-note">⚠ {msg.error}</div>
      ) : (
        <div className="md muted">(empty)</div>
      )}
      {msg.model && <div className="stamp model-stamp">{msg.model}</div>}
    </div>
  );
}