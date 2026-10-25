import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, FolderUp, Upload } from "lucide-react";

export function UploadButton({ choose }: { choose: (folder?: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const folderButton = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function dismiss(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div
      ref={container}
      className="upload-button-group"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(false);
          toggle.current?.focus();
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setOpen(true);
          requestAnimationFrame(() => folderButton.current?.focus());
        }
      }}
    >
      <button
        className="button primary"
        onClick={() => {
          setOpen(false);
          choose();
        }}
      >
        <Upload size={17} />
        Upload
      </button>
      <button
        ref={toggle}
        className="button primary upload-options-toggle"
        aria-label="Upload options"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen(!open)}
      >
        <ChevronDown size={15} />
      </button>
      {open && (
        <div className="upload-options" id={menuId}>
          <button
            ref={folderButton}
            onClick={() => {
              setOpen(false);
              choose(true);
            }}
          >
            <FolderUp size={17} />
            Upload folder
          </button>
        </div>
      )}
    </div>
  );
}
