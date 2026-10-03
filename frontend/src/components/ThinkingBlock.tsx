import { memo } from "react";
import Markdown from "./Markdown";
import Icon from "./Icon";

/** Collapsible reasoning block. Open while streaming, collapsed once text starts. */
const ThinkingBlock = memo(function ThinkingBlock({ text, active }: { text: string; active: boolean }) {
  if (!text.trim()) return null;
  // key remount forces the open state to follow streaming: open while active, then user may toggle freely
  return (
    <details className="thinking" open={active} key={active ? "open" : "closed"}>
      <summary>
        <Icon name="bulb" size={14} />
        <span className="thinking-label">
          thinking {active && <span className="dot pulse" />}
        </span>
      </summary>
      <div className="thinking-body">
        <Markdown text={text} />
      </div>
    </details>
  );
});

export default ThinkingBlock;