import { useState } from "react";
import Icon from "./Icon";
import ExportMenu from "./ExportMenu";
import type { ExportEntry } from "../export";

/** Actions revealed on hover under an assistant answer — Ant Design X's
 *  `Actions` footer: copy the full text, download it, or regenerate. */
export default function MsgActions({
  copyText,
  onRetry,
  exportData,
}: {
  copyText?: string;
  onRetry?: () => void;
  /** When set, shows the download button (Markdown / PDF) for this answer. */
  exportData?: { title: string; entries: ExportEntry[] };
}) {
  const [copied, setCopied] = useState(false);

  if (!copyText && !onRetry && !exportData) return null;

  const copy = () => {
    if (!copyText) return;
    navigator.clipboard?.writeText(copyText).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => undefined
    );
  };

  return (
    <div className="msg-actions">
      {copyText && (
        <button type="button" className="icon" title="Copy" onClick={copy}>
          <Icon name={copied ? "check" : "copy"} size={15} />
        </button>
      )}
      {onRetry && (
        <button type="button" className="icon" title="Regenerate" onClick={onRetry}>
          <Icon name="refresh" size={15} />
        </button>
      )}
      {exportData && <ExportMenu title={exportData.title} entries={exportData.entries} />}
    </div>
  );
}
