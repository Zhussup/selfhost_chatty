import { toolChipLabel } from "../api";
import type { ToolCall } from "../types";
import Icon from "./Icon";
import type { IconName } from "./Icon";

export interface ChipData {
  id: string;
  name: string;
  arguments?: Record<string, unknown>;
  ok: boolean | null; // null = running
  ms: number;
  result: string;
}

const ICONS: Record<string, IconName> = {
  web_search: "search",
  fetch_page: "file",
  calc: "hash",
  python: "terminal",
  memory_write: "bulb",
  memory_list: "list",
};

export default function ToolChip({ chip }: { chip: ChipData }) {
  const icon = ICONS[chip.name] ?? "wrench";
  const running = chip.ok === null;
  const call: ToolCall = { id: chip.id, name: chip.name, arguments: chip.arguments ?? {} };
  return (
    <details className={`tool-chip ${running ? "running" : chip.ok ? "ok" : "fail"}`}>
      <summary>
        <span className="chip-icon">
          <Icon name={icon} size={14} />
        </span>
        <span className="chip-label">{running ? `${chip.name} · running…` : toolChipLabel(call)}</span>
        {running ? <span className="dot pulse" /> : <span className={`chip-status ${chip.ok ? "okd" : "err"}`} />}
        <span className="chip-ms">{chip.ms} ms</span>
      </summary>
      {chip.result && <pre className="chip-result">{chip.result}</pre>}
    </details>
  );
}