import {Fragment, type ReactNode} from "react";
import {safeLink} from "./contracts";

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g).map((part, index) => {
    if (part.startsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) return safeLink(link[2]) ? <a key={index} href={safeLink(link[2])} target="_blank" rel="noreferrer">{link[1]}</a> : <Fragment key={index}>{link[1]}</Fragment>;
    return part;
  });
}

/** Deliberately no raw HTML, remote image loading, or executable URL schemes. */
export function Markdown({content}: {content: string}) {
  const lines = content.replaceAll("\r\n", "\n").split("\n");
  const blocks: ReactNode[] = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) {i++; continue;}
    if (line.startsWith("```")) {
      const code: string[] = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++; blocks.push(<pre key={i}><code>{code.join("\n")}</code></pre>); continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const Tag = heading[1].length === 1 ? "h2" : heading[1].length === 2 ? "h3" : "h4";
      blocks.push(<Tag key={i}>{inline(heading[2])}</Tag>); i++; continue;
    }
    if (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] ?? "")) {
      const cells = (row: string) => row.replace(/^\s*\||\|\s*$/g, "").split("|").map(cell => cell.trim());
      const head = cells(line); i += 2; const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|")) rows.push(cells(lines[i++]));
      blocks.push(<div className="aw-table" key={i}><table><thead><tr>{head.map((cell, j) => <th key={j}>{inline(cell)}</th>)}</tr></thead><tbody>{rows.map((row, j) => <tr key={j}>{row.map((cell, k) => <td key={k}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>); continue;
    }
    if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const ordered = /^\s*\d/.test(line); const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const Tag = ordered ? "ol" : "ul"; blocks.push(<Tag key={i}>{items.map((item, j) => <li key={j}>{inline(item)}</li>)}</Tag>); continue;
    }
    if (line.startsWith("> ")) {blocks.push(<blockquote key={i}>{inline(line.slice(2))}</blockquote>); i++; continue;}
    const paragraph = [line]; i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|```|> |\s*([-*]|\d+\.)\s)/.test(lines[i])) {
      if (lines[i].includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] ?? "")) break;
      paragraph.push(lines[i++]);
    }
    blocks.push(<p key={i}>{inline(paragraph.join("\n"))}</p>);
  }
  return <div className="aw-markdown">{blocks}</div>;
}
