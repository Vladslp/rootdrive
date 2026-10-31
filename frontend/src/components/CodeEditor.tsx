import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Search } from "lucide-react";
import { Compartment, EditorState, type Extension } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  rectangularSelection,
} from "@codemirror/view";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language";
import {
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  autocompletion,
} from "@codemirror/autocomplete";
import {
  highlightSelectionMatches,
  openSearchPanel,
  search,
  searchKeymap,
} from "@codemirror/search";
import { tags } from "@lezer/highlight";

export type CodeEditorHandle = { value: () => string };
type Props = {
  text: string;
  format: string;
  wrap: boolean;
  disabled: boolean;
  changed: (dirty: boolean) => void;
  snapshot?: (text: string) => void;
};

const syntax = HighlightStyle.define([
  {
    tag: [tags.keyword, tags.modifier, tags.operatorKeyword],
    color: "var(--code-keyword)",
  },
  {
    tag: [tags.string, tags.regexp, tags.special(tags.string)],
    color: "var(--code-string)",
  },
  {
    tag: [tags.number, tags.bool, tags.null, tags.atom],
    color: "var(--code-number)",
  },
  {
    tag: [tags.comment, tags.meta],
    color: "var(--code-comment)",
    fontStyle: "italic",
  },
  {
    tag: [tags.function(tags.variableName), tags.function(tags.propertyName)],
    color: "var(--code-function)",
  },
  {
    tag: [tags.typeName, tags.className, tags.tagName],
    color: "var(--code-type)",
  },
  {
    tag: [tags.attributeName, tags.propertyName],
    color: "var(--code-property)",
  },
  { tag: tags.heading, color: "var(--code-keyword)", fontWeight: "600" },
  { tag: tags.link, color: "var(--blue-text)", textDecoration: "underline" },
  { tag: tags.invalid, color: "var(--danger)" },
]);

async function language(format: string): Promise<Extension> {
  if (["js", "jsx", "mjs", "cjs", "ts", "tsx"].includes(format)) {
    const { javascript } = await import("@codemirror/lang-javascript");
    return javascript({
      jsx: ["jsx", "tsx"].includes(format),
      typescript: ["ts", "tsx"].includes(format),
    });
  }
  if (["py", "pyw"].includes(format))
    return (await import("@codemirror/lang-python")).python();
  if (format === "json") return (await import("@codemirror/lang-json")).json();
  if (["html", "htm"].includes(format))
    return (await import("@codemirror/lang-html")).html();
  if (format === "css") return (await import("@codemirror/lang-css")).css();
  if (["md", "markdown"].includes(format))
    return (await import("@codemirror/lang-markdown")).markdown();
  if (format === "sql") return (await import("@codemirror/lang-sql")).sql();
  return [];
}

const CodeEditor = forwardRef<CodeEditorHandle, Props>(function CodeEditor(
  { text, format, wrap, disabled, changed, snapshot },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callback = useRef(changed);
  callback.current = changed;
  const snapshotCallback = useRef(snapshot);
  snapshotCallback.current = snapshot;
  const [position, setPosition] = useState({ line: 1, column: 1, lines: 1 });
  const [syntaxError, setSyntaxError] = useState(false);
  const compartments = useRef({
    language: new Compartment(),
    wrap: new Compartment(),
    editing: new Compartment(),
  });
  useImperativeHandle(
    ref,
    () => ({ value: () => view.current?.state.doc.toString() ?? text }),
    [text],
  );
  useEffect(() => {
    if (!host.current) return;
    let active = true;
    let dirty = false;
    let previewTimer: ReturnType<typeof setTimeout> | undefined;
    const slots = compartments.current;
    const initial = EditorState.create({ doc: text }).doc;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: initial,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          history(),
          foldGutter(),
          drawSelection(),
          dropCursor(),
          indentOnInput(),
          bracketMatching(),
          closeBrackets(),
          rectangularSelection(),
          highlightActiveLine(),
          highlightSelectionMatches(),
          search({ top: true }),
          autocompletion(),
          indentUnit.of("  "),
          syntaxHighlighting(syntax),
          keymap.of([
            ...closeBracketsKeymap,
            ...defaultKeymap,
            ...historyKeymap,
            ...searchKeymap,
            ...foldKeymap,
            ...completionKeymap,
            indentWithTab,
          ]),
          EditorView.contentAttributes.of({
            "aria-label": "File contents",
            "aria-description":
              "Code editor. Press Escape then Tab to leave the editor.",
            spellcheck: "false",
            autocapitalize: "off",
            autocorrect: "off",
          }),
          slots.language.of([]),
          slots.wrap.of(wrap ? EditorView.lineWrapping : []),
          slots.editing.of([
            EditorState.readOnly.of(disabled),
            EditorView.editable.of(!disabled),
          ]),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged && !update.selectionSet) return;
            const caret = update.state.selection.main.head;
            const line = update.state.doc.lineAt(caret);
            setPosition({
              line: line.number,
              column: caret - line.from + 1,
              lines: update.state.doc.lines,
            });
            if (update.docChanged) {
              clearTimeout(previewTimer);
              if (snapshotCallback.current)
                previewTimer = setTimeout(() => {
                  if (active)
                    snapshotCallback.current?.(editor.state.doc.toString());
                }, 400);
              const next = !update.state.doc.eq(initial);
              if (next !== dirty) {
                dirty = next;
                callback.current(next);
              }
            }
          }),
        ],
      }),
    });
    view.current = editor;
    setPosition({ line: 1, column: 1, lines: initial.lines });
    setSyntaxError(false);
    language(format)
      .then((extension) => {
        if (active)
          editor.dispatch({ effects: slots.language.reconfigure(extension) });
      })
      .catch(() => {
        if (active) setSyntaxError(true);
      });
    return () => {
      active = false;
      clearTimeout(previewTimer);
      view.current = null;
      editor.destroy();
    };
  }, [text, format]);
  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.wrap.reconfigure(
        wrap ? EditorView.lineWrapping : [],
      ),
    });
  }, [wrap]);
  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.editing.reconfigure([
        EditorState.readOnly.of(disabled),
        EditorView.editable.of(!disabled),
      ]),
    });
  }, [disabled]);
  return (
    <div className="code-workbench">
      <div ref={host} className="code-surface" />
      <div className="code-status">
        <span>
          {format === "txt" ? "Plain text" : format.toUpperCase()}
          <span className="code-encoding">UTF-8</span>
        </span>
        <span>
          Ln {position.line.toLocaleString()}, Col{" "}
          {position.column.toLocaleString()}
          <span className="code-line-count">
            {position.lines.toLocaleString()} lines
          </span>
        </span>
        <button
          type="button"
          className="code-find"
          disabled={disabled}
          onClick={() => {
            if (view.current) openSearchPanel(view.current);
          }}
          aria-label="Find in file"
        >
          <Search size={14} />
          <span>Find</span>
        </button>
      </div>
      {syntaxError && (
        <p className="code-language-error" role="status">
          Syntax highlighting could not load. Editing is still available.
        </p>
      )}
    </div>
  );
});
export default CodeEditor;
