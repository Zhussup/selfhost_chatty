import { useState } from "react";
import Icon from "./Icon";

/** Actions revealed on hover under an assistant answer — Ant Design X's
 *  `Actions` footer: copy the full text, or regenerate the exchange. */
export default function MsgActions({
  copyText,
  onRetry,
}: {
  copyText?: string;
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  if (!copyText && !onRetry) return null;

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
    </div>
  );
}
