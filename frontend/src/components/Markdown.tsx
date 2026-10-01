import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-btn"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          },
          () => undefined
        );
      }}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          pre: ({ children }) => (
            <div className="codeblock">
              <CopyButton text={extractCode(children)} />
              <pre>{children}</pre>
            </div>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});

/** Pull plain text out of react-markdown children (code fences). */
function extractCode(children: React.ReactNode): string {
  let out = "";
  const walk = (node: React.ReactNode) => {
    if (typeof node === "string") {
      out += node;
    } else if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (node && typeof node === "object" && "props" in node) {
      const props = (node as { props?: { children?: React.ReactNode } }).props;
      if (props?.children) walk(props.children);
    }
  };
  walk(children);
  return out;
}

export default Markdown;