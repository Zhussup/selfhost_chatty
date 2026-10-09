import { useEffect } from "react";
import { createPortal } from "react-dom";
import Markdown from "./Markdown";
import { useStore } from "../state";
import { fmtStamp, type ExportEntry } from "../export";
import Icon from "./Icon";

/**
 * The PDF path: a print-only copy of a conversation, portaled to <body> and
 * hidden on screen (`@media print` hides #root instead). Building it from the
 * same <Markdown> the chat uses means code highlighting, tables and fonts come
 * out exactly as they look in the app — no PDF library, nothing to install.
 *
 * The browser's own dialog then offers "Save as PDF".
 */
export default function PrintDoc() {
  const job = useStore((st) => st.printJob);

  useEffect(() => {
    if (!job) return;
    let cancelled = false;
    const done = () => {
      if (!cancelled) useStore.getState().endPrint();
    };
    window.addEventListener("afterprint", done);

    // Give highlight.js and the webfonts a beat to settle — a print snapshot
    // taken mid-render would drop colours inside code blocks. The timeout keeps
    // a stuck font load from blocking the dialog forever.
    const settled = Promise.race([
      document.fonts ? document.fonts.ready : Promise.resolve(),
      new Promise((r) => setTimeout(r, 1500)),
    ]);
    settled.then(() =>
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (!cancelled) window.print();
        })
      )
    );

    return () => {
      cancelled = true;
      window.removeEventListener("afterprint", done);
    };
  }, [job]);

  if (!job) return null;

  const models = Array.from(new Set(job.entries.map((e) => e.model).filter(Boolean))) as string[];

  return createPortal(
    <article className="print-doc">
      <h1 className="print-title">{job.title}</h1>
      <div className="print-meta">
        {fmtStamp()}
        {models.length ? ` · ${models.join(", ")}` : ""}
      </div>
      {job.entries.map((e, i) => (
        <PrintEntry key={i} entry={e} />
      ))}
    </article>,
    document.body
  );
}

function PrintEntry({ entry }: { entry: ExportEntry }) {
  if (entry.role === "tool") {
    return (
      <section className="print-msg print-tool">
        <div className="print-who">
          <Icon name="wrench" size={12} /> {entry.name ?? "tool"}
          {entry.ok === false ? " · failed" : ""}
        </div>
        <pre>{entry.text}</pre>
      </section>
    );
  }

  if (entry.role === "user") {
    return (
      <section className="print-msg print-user">
        <div className="print-who">You · {fmtStamp(entry.stamp)}</div>
        {entry.quote ? <div className="print-quote">{entry.quote}</div> : null}
        {entry.images?.length ? (
          <div className="print-images">
            {entry.images.map((im, i) => (
              <img key={i} src={im.src} alt={im.name} />
            ))}
          </div>
        ) : null}
        <div className="print-body">{entry.text}</div>
      </section>
    );
  }

  return (
    <section className="print-msg print-assistant">
      <div className="print-who">
        Assistant · {fmtStamp(entry.stamp)}
        {entry.model ? ` · ${entry.model}` : ""}
      </div>
      {entry.thinking ? (
        <details className="print-thinking" open>
          <summary>thinking</summary>
          <Markdown text={entry.thinking} />
        </details>
      ) : null}
      {entry.text ? <Markdown text={entry.text} /> : null}
    </section>
  );
}
