import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize, Minus, Plus } from "lucide-react";

export function PhotoViewport({
  children,
  width,
  height,
  cropping = false,
}: {
  children: ReactNode;
  width: number;
  height: number;
  cropping?: boolean;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [bounds, setBounds] = useState({ width: 600, height: 400 });
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const fit = Math.min((bounds.width - 28) / Math.max(1, width), (bounds.height - 68) / Math.max(1, height), 1);
  const displayWidth = Math.max(1, width * fit);
  const displayHeight = Math.max(1, height * fit);
  function bounded(zoom: number, x: number, y: number) {
    const maxX = Math.max(0, (displayWidth * zoom - bounds.width + 28) / 2);
    const maxY = Math.max(0, (displayHeight * zoom - bounds.height + 68) / 2);
    return { zoom, x: Math.max(-maxX, Math.min(maxX, x)), y: Math.max(-maxY, Math.min(maxY, y)) };
  }
  function zoomTo(next: number) {
    setView((current) => {
      const zoom = Math.max(0.25, Math.min(8, next));
      return bounded(zoom, current.x * zoom / current.zoom, current.y * zoom / current.zoom);
    });
  }
  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const measure = () => {
      setBounds({ width: node.clientWidth, height: node.clientHeight });
      setView({ zoom: 1, x: 0, y: 0 });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setView({ zoom: 1, x: 0, y: 0 });
    drag.current = null;
  }, [width, height, cropping]);
  useEffect(() => {
    const node = viewport.current;
    if (!node || cropping) return;
    function wheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoomTo(view.zoom * Math.exp(-event.deltaY * 0.01));
    }
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, [view.zoom, displayWidth, displayHeight, bounds, cropping]);
  return (
    <div
      ref={viewport}
      className={"photo-viewport " + (view.zoom > 1 && !cropping ? "photo-viewport-pannable" : "")}
      onDragStart={(event) => event.preventDefault()}
      onDoubleClick={(event) => {
        if (!cropping && !(event.target as HTMLElement).closest("button")) {
          zoomTo(view.zoom === 1 ? 2 : 1);
        }
      }}
      onPointerDown={(event) => {
        if (cropping || view.zoom <= 1 || event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, y: event.clientY, left: view.x, top: view.y };
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        setView(bounded(view.zoom, drag.current.left + event.clientX - drag.current.x, drag.current.top + event.clientY - drag.current.y));
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onLostPointerCapture={() => { drag.current = null; }}
    >
      <div
        className="photo-viewport-content"
        style={{ width: displayWidth, height: displayHeight, transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}
      >
        {children}
      </div>
      <div className="photo-zoom-controls" role="group" aria-label="Photo zoom">
        <button className="icon-button" aria-label="Zoom out" disabled={view.zoom <= .25 || cropping} onClick={() => zoomTo(view.zoom / 1.25)}><Minus size={16} /></button>
        <output aria-live="polite">{Math.round(view.zoom * 100)}%</output>
        <button className="icon-button" aria-label="Zoom in" disabled={view.zoom >= 8 || cropping} onClick={() => zoomTo(view.zoom * 1.25)}><Plus size={16} /></button>
        <span />
        <button className="icon-button" aria-label="Fit photo" disabled={cropping} onClick={() => setView({ zoom: 1, x: 0, y: 0 })}><Maximize size={15} /></button>
      </div>
    </div>
  );
}
