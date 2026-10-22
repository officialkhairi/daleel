import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationChip } from "../citations/CitationChip";
import type { Citation } from "../citations/types";

const CITE = "#cite-";
const MARKER = /\[(\d{1,2})\]/g;

interface MarkdownProps {
  text: string;
  citations?: Citation[];
  onCite?: (citation: Citation) => void;
}

/** Model output as Markdown. Raw HTML is never rendered (react-markdown's default). Citation
 * markers for known sources become chips; any other [n] stays plain text. */
export function Markdown({ text, citations = [], onCite }: MarkdownProps) {
  const byNumber = new Map(citations.map((c) => [c.n, c]));
  const linked = onCite
    ? text.replace(MARKER, (marker, n: string) => (byNumber.has(Number(n)) ? `[${n}](${CITE}${n})` : marker))
    : text;

  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const citation = href?.startsWith(CITE) ? byNumber.get(Number(href.slice(CITE.length))) : undefined;
            if (citation && onCite) return <CitationChip citation={citation} onOpen={onCite} />;
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
        }}
      >
        {linked}
      </ReactMarkdown>
    </div>
  );
}
