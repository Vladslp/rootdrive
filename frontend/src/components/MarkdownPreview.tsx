import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g).map((part, index) => {
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link && /^(https?:|mailto:)/i.test(link[2])) return <a key={index} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}
export function MarkdownPreview({ text }: { text: string }) {
  const lines = text.slice(0, 200000).split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let ordered = false;
  function flush() { if (paragraph.length) { blocks.push(<p key={blocks.length}>{inline(paragraph.join("\n"))}</p>); paragraph = []; } if (list.length) { const items = list.map((item, index) => <li key={index}>{inline(item)}</li>); blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>); list = []; } }
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (line.startsWith("```")) { flush(); const code: string[] = []; while (++index < lines.length && !lines[index].startsWith("```")) code.push(lines[index]); blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>); continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) { flush(); const content = inline(heading[2]); const key = blocks.length; blocks.push(heading[1].length === 1 ? <h1 key={key}>{content}</h1> : heading[1].length === 2 ? <h2 key={key}>{content}</h2> : <h3 key={key}>{content}</h3>); continue; }
    const item = line.match(/^\s*(?:([-*+])|([0-9]+)\.)\s+(.+)$/);
    if (item) { const next = !!item[2]; if (paragraph.length || (list.length && ordered !== next)) flush(); ordered = next; list.push(item[3]); continue; }
    if (/^>\s?/.test(line)) { flush(); blocks.push(<blockquote key={blocks.length}>{inline(line.replace(/^>\s?/, ""))}</blockquote>); continue; }
    if (/^([-*_])\1{2,}$/.test(line.trim())) { flush(); blocks.push(<hr key={blocks.length} />); continue; }
    if (!line.trim()) { flush(); continue; }
    if (list.length) flush();
    paragraph.push(line);
  }
  flush();
  return <article className="markdown-preview" aria-label="Markdown preview">{text.length > 200000 && <p className="muted">Preview shows the first 200,000 characters.</p>}{blocks}</article>;
}
