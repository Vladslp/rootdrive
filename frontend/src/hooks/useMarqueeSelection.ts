import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

export type SelectionRect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};
function intersects(first: SelectionRect, second: SelectionRect) {
  return (
    first.right > first.left &&
    first.bottom > first.top &&
    first.left < second.right &&
    first.right > second.left &&
    first.top < second.bottom &&
    first.bottom > second.top
  );
}
function selectionPaths(base: string[], hits: string[], additive: boolean) {
  return additive ? [...new Set([...base, ...hits])] : hits;
}
export function useMarqueeSelection({
  enabled,
  scope,
  selection,
  change,
}: {
  enabled: boolean;
  scope: string;
  selection: string[];
  change: (paths: string[]) => void;
}) {
  const container = useRef<HTMLElement>(null);
  const stop = useRef<(() => void) | null>(null);
  const [rectangle, setRectangle] = useState<SelectionRect | null>(null);
  useEffect(() => {
    return () => {
      stop.current?.();
    };
  }, [enabled, scope]);
  function pointerDown(event: ReactPointerEvent<HTMLElement>) {
    const surface = container.current;
    if (
      !enabled ||
      !surface ||
      stop.current ||
      event.pointerType !== "mouse" ||
      event.button !== 0 ||
      !event.isPrimary
    )
      return;
    const target = event.target as Element;
    if (
      target.closest(
        ".file-card, .list-head, button, input, select, textarea, a, label, summary, [contenteditable], [role=dialog], [role=menu]",
      )
    )
      return;
    const collection = surface.querySelector<HTMLElement>(".file-collection");
    if (
      !collection ||
      event.clientY < collection.getBoundingClientRect().top - 8
    )
      return;
    event.preventDefault();
    const identifier = event.pointerId;
    const start = {
      x: event.clientX + window.scrollX,
      y: event.clientY + window.scrollY,
    };
    const previous = [...selection];
    const additive = event.ctrlKey || event.metaKey || event.shiftKey;
    const cards = [
      ...collection.querySelectorAll<HTMLElement>("[data-selection-path]"),
    ].map((element) => ({ element, path: element.dataset.selectionPath! }));
    let pointer = { x: event.clientX, y: event.clientY };
    let last = [...previous];
    let active = false;
    let frame = 0;
    let timestamp = 0;
    const header = surface.querySelector<HTMLElement>(".topbar");
    function update() {
      const bounds = surface!.getBoundingClientRect();
      const top = collection!.getBoundingClientRect().top;
      const documentRect = {
        left: Math.max(
          bounds.left + window.scrollX,
          Math.min(start.x, pointer.x + window.scrollX),
        ),
        right: Math.min(
          bounds.right + window.scrollX,
          Math.max(start.x, pointer.x + window.scrollX),
        ),
        top: Math.max(
          top + window.scrollY,
          Math.min(start.y, pointer.y + window.scrollY),
        ),
        bottom: Math.min(
          bounds.bottom + window.scrollY,
          Math.max(start.y, pointer.y + window.scrollY),
        ),
      };
      const viewportRect = {
        left: documentRect.left - window.scrollX,
        right: documentRect.right - window.scrollX,
        top: documentRect.top - window.scrollY,
        bottom: documentRect.bottom - window.scrollY,
      };
      const visible = {
        left: Math.max(0, viewportRect.left),
        right: Math.min(window.innerWidth, viewportRect.right),
        top: Math.max(
          header?.getBoundingClientRect().bottom || 0,
          viewportRect.top,
        ),
        bottom: Math.min(window.innerHeight, viewportRect.bottom),
      };
      const nextRectangle =
        visible.right > visible.left && visible.bottom > visible.top
          ? visible
          : null;
      setRectangle((current) =>
        current &&
        nextRectangle &&
        current.left === nextRectangle.left &&
        current.right === nextRectangle.right &&
        current.top === nextRectangle.top &&
        current.bottom === nextRectangle.bottom
          ? current
          : nextRectangle,
      );
      const hits = cards
        .filter(({ element }) =>
          intersects(viewportRect, element.getBoundingClientRect()),
        )
        .map(({ path }) => path);
      const next = selectionPaths(previous, hits, additive);
      if (
        next.length !== last.length ||
        next.some((path, index) => path !== last[index])
      ) {
        last = next;
        change(next);
      }
    }
    function tick(now: number) {
      if (!active) return;
      const elapsed = timestamp ? Math.min(2, (now - timestamp) / 16.67) : 1;
      timestamp = now;
      const bounds = surface!.getBoundingClientRect();
      const top = header?.getBoundingClientRect().bottom || 0;
      if (pointer.x >= bounds.left && pointer.x <= bounds.right) {
        const up =
          pointer.y < top + 52 ? -Math.min(1, (top + 52 - pointer.y) / 52) : 0;
        const down =
          pointer.y > window.innerHeight - 52
            ? Math.min(1, (pointer.y - window.innerHeight + 52) / 52)
            : 0;
        const velocity = down && bounds.bottom > window.innerHeight ? down : up;
        if (velocity)
          window.scrollBy({
            top: velocity * 18 * elapsed,
            behavior: "instant",
          });
      }
      update();
      frame = requestAnimationFrame(tick);
    }
    function move(event: PointerEvent) {
      if (event.pointerId !== identifier) return;
      pointer = { x: event.clientX, y: event.clientY };
      if (
        !active &&
        Math.hypot(
          pointer.x + window.scrollX - start.x,
          pointer.y + window.scrollY - start.y,
        ) >= 5
      ) {
        active = true;
        frame = requestAnimationFrame(tick);
      }
      if (active) event.preventDefault();
    }
    function cleanup() {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("blur", cancel);
      window.removeEventListener("resize", cancel);
      window.removeEventListener("keydown", key, true);
      surface!.removeEventListener("lostpointercapture", cancel);
      if (surface!.hasPointerCapture(identifier))
        surface!.releasePointerCapture(identifier);
      setRectangle(null);
      stop.current = null;
    }
    function finish(event: PointerEvent) {
      if (event.pointerId !== identifier) return;
      pointer = { x: event.clientX, y: event.clientY };
      if (active) update();
      else if (!additive) change([]);
      cleanup();
    }
    function cancel() {
      change(previous);
      cleanup();
    }
    function key(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      cancel();
    }
    stop.current = cleanup;
    surface.setPointerCapture(identifier);
    surface.addEventListener("lostpointercapture", cancel);
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancel);
    window.addEventListener("resize", cancel);
    window.addEventListener("keydown", key, true);
  }
  return { container, pointerDown, rectangle };
}
