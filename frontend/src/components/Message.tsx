import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip from "./ToolChip";
import MsgActions from "./MsgActions";
import Icon from "./Icon";
import type { ChipData } from "./ToolChip";
import type { MessageRow } from "../types";

function timeStr(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function Message({ msg, onRetry }: { msg: MessageRow; onRetry?: () => void }) {
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
      <div className="msg-avatar">
        <Icon name="sparkle" size={15} />
      </div>
      <div className="msg-main">
        <ThinkingBlock text={msg.thinking ?? ""} active={false} />
        {msg.content ? (
          <Markdown text={msg.content} />
        ) : errored ? (
          <div className="md error-note">
            <Icon name="alert" size={15} />
            <span>{msg.error}</span>
          </div>
        ) : (
          <div className="md muted">(empty)</div>
        )}
        {msg.model && <div className="stamp model-stamp">{msg.model}</div>}
        <MsgActions copyText={msg.content} onRetry={onRetry} />
      </div>
    </div>
  );
}
