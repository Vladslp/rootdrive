import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { CornerDownLeft, Loader2, Search, type LucideIcon } from "lucide-react";
import { api, type Entry, type Listing } from "../services/api";
import { Art, kindOf } from "./Art";
import { Dialog } from "./Dialog";

export type Command = {
  id: string;
  label: string;
  detail?: string;
  keywords?: string;
  icon: LucideIcon;
  run: () => void;
};

export function CommandPalette({ commands, close, open }: {
  commands: Command[];
  close: () => void;
  open: (entry: Entry) => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ query: string; items: Entry[]; error?: string } | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const term = query.trim();
  const searchFiles = term.length >= 2;
  const words = term.toLocaleLowerCase().split(/\s+/);
  const matching = commands.filter((command) => words.every((part) =>
    `${command.label} ${command.detail || ""} ${command.keywords || ""}`.toLocaleLowerCase().includes(part))).sort((first, second) =>
      Number(!words.every((word) => first.label.toLocaleLowerCase().includes(word))) -
      Number(!words.every((word) => second.label.toLocaleLowerCase().includes(word))));
  const files = searchFiles && result?.query === term ? result.items : [];
  const error = searchFiles && result?.query === term ? result.error : undefined;
  const loading = searchFiles && result?.query !== term;
  const count = matching.length + files.length;
  const current = Math.min(active, Math.max(0, count - 1));

  useEffect(() => {
    if (!searchFiles) return;
    const controller = new AbortController();
    let valid = true;
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ q: term, recursive: "true", limit: "8", sort: "name" });
      api<Listing>("/search?" + params, "GET", undefined, controller.signal)
        .then((value) => { if (valid) setResult({ query: term, items: value.items }); })
        .catch((error: Error) => { if (valid) setResult({ query: term, items: [], error: error.message }); });
    }, 180);
    return () => { valid = false; clearTimeout(timer); controller.abort(); };
  }, [term, searchFiles, retry]);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-command-index="${current}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [current, result, term]);

  function choose(index: number) {
    const command = matching[index];
    const file = files[index - matching.length];
    if (!command && !file) return;
    close();
    if (command) command.run();
    else open(file);
  }

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (count) setActive((current + (event.key === "ArrowDown" ? 1 : count - 1)) % count);
    }
    if (event.key === "Enter") {
      event.preventDefault();
      choose(current);
    }
  }

  return (
    <Dialog title="Quick commands" close={close} className="command-palette">
      <div className="command-search">
        <Search size={21} aria-hidden="true" />
        <input
          role="combobox" aria-label="Search commands and files" aria-autocomplete="list"
          aria-expanded="true" aria-controls={id} aria-activedescendant={count ? `${id}-${current}` : undefined}
          placeholder="What would you like to do?" autoComplete="off" spellCheck={false}
          value={query} onChange={(event) => { setQuery(event.target.value); setActive(0); }} onKeyDown={keyDown}
        />
        {loading && <Loader2 size={17} className="spin" aria-label="Searching files" />}
      </div>
      <div className="command-results" id={id} role="listbox" aria-label="Commands and files" ref={list}>
        {matching.length > 0 && <div className="command-group" role="presentation">{term ? "Commands" : "Jump to or create"}</div>}
        {matching.map((command, index) => (
          <button type="button" role="option" tabIndex={-1} aria-selected={current === index}
            id={`${id}-${index}`} data-command-index={index} key={command.id}
            className={"command-row" + (current === index ? " is-active" : "")}
            onMouseMove={() => { if (active !== index) setActive(index); }} onClick={() => choose(index)}>
            <span className="command-icon"><command.icon size={19} /></span>
            <span className="command-label"><strong>{command.label}</strong>{command.detail && <small>{command.detail}</small>}</span>
            <CornerDownLeft size={15} className="command-enter" aria-hidden="true" />
          </button>
        ))}
        {files.length > 0 && <div className="command-group" role="presentation">Files · all folders</div>}
        {files.map((entry, index) => {
          const position = matching.length + index;
          return <button type="button" role="option" tabIndex={-1} aria-selected={current === position}
            id={`${id}-${position}`} data-command-index={position} key={entry.path}
            className={"command-row command-file" + (current === position ? " is-active" : "")}
            onMouseMove={() => { if (active !== position) setActive(position); }} onClick={() => choose(position)}>
            <Art kind={kindOf(entry)} emptyFolder={entry.type === "folder" && entry.child_count === 0} />
            <span className="command-label"><strong>{entry.name}</strong><small>/{entry.path}</small></span>
            <CornerDownLeft size={15} className="command-enter" aria-hidden="true" />
          </button>;
        })}
      </div>
      <div className="command-status" role="status">
        {error ? <><span className="error-text">{error}</span><button className="text-button" onClick={() => { setResult(null); setRetry((value) => value + 1); }}>Try again</button></> :
          loading ? "Searching your files…" : !count ? "No matches. Try another name." : !searchFiles ? "Type 2 characters to find files anywhere." : `${files.length} ${files.length === 1 ? "file match" : "file matches"}`}
      </div>
      <footer className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>↵</kbd> Open</span><span><kbd>esc</kbd> Close</span></footer>
    </Dialog>
  );
}
