import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { createElement as h, act, useState } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Element: dom.window.Element,
  IS_REACT_ACT_ENVIRONMENT: true,
});
const { createRoot } = await import("react-dom/client");
const { useMarqueeSelection } = await import(
  "../src/hooks/useMarqueeSelection.ts"
);
let root, host, frames, offset, elapsed, frameId, captures;
const locations = {
  A: [250, 320, 450, 520],
  B: [480, 320, 680, 520],
  C: [250, 550, 450, 750],
  D: [480, 550, 680, 750],
};
function rectangle(left, top, right, bottom) {
  return {
    left,
    top,
    right,
    bottom,
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    toJSON() {},
  };
}
function Harness({ initial = [], enabled = true, scope = "files" }) {
  const [selection, change] = useState(initial);
  const marquee = useMarqueeSelection({ enabled, scope, selection, change });
  return h(
    "main",
    { ref: marquee.container, onPointerDown: marquee.pointerDown },
    h("header", { className: "topbar" }, h("button", null, "Toolbar")),
    h(
      "div",
      { className: "file-collection" },
      Object.keys(locations).map((path) =>
        h(
          "article",
          { key: path, className: "file-card", "data-selection-path": path },
          h("button", null, path),
        ),
      ),
    ),
    h("output", { "data-selection": true }, selection.join(",")),
    marquee.rectangle &&
      h("div", { "data-marquee": true, "data-top": marquee.rectangle.top }),
  );
}
function render(props = {}) {
  act(() => root.render(h(Harness, props)));
}
function pointer(target, type, x, y, options = {}) {
  const event = new window.MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    button: 0,
    ...options,
  });
  Object.defineProperties(event, {
    pointerId: { value: options.pointerId || 1 },
    pointerType: { value: options.pointerType || "mouse" },
    isPrimary: { value: true },
  });
  act(() => target.dispatchEvent(event));
}
function step() {
  const pending = [...frames.values()];
  frames.clear();
  elapsed += 16.67;
  act(() => {
    for (const callback of pending) callback(elapsed);
  });
}
function selected() {
  return host
    .querySelector("[data-selection]")
    .textContent.split(",")
    .filter(Boolean);
}
function main() {
  return host.querySelector("main");
}
function start(options = {}) {
  pointer(main(), "pointerdown", 460, 530, options);
}
function move(x = 245, y = 310) {
  pointer(window, "pointermove", x, y);
  step();
}
function end(x = 245, y = 310) {
  pointer(window, "pointerup", x, y);
}
beforeEach(() => {
  frames = new Map();
  offset = 0;
  elapsed = 0;
  frameId = 0;
  captures = new WeakMap();
  Object.defineProperties(window, {
    innerWidth: { configurable: true, value: 1000 },
    innerHeight: { configurable: true, value: 900 },
    scrollX: { configurable: true, get: () => 0 },
    scrollY: { configurable: true, get: () => offset },
  });
  window.scrollBy = ({ top }) => {
    offset = Math.max(0, Math.min(300, offset + top));
  };
  globalThis.requestAnimationFrame = (callback) => {
    frames.set(++frameId, callback);
    return frameId;
  };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  window.HTMLElement.prototype.setPointerCapture = function (id) {
    captures.set(this, id);
  };
  window.HTMLElement.prototype.hasPointerCapture = function (id) {
    return captures.get(this) === id;
  };
  window.HTMLElement.prototype.releasePointerCapture = function () {
    captures.delete(this);
  };
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    if (this.tagName === "MAIN")
      return rectangle(200, -offset, 1000, 1200 - offset);
    if (this.classList.contains("topbar")) return rectangle(200, 0, 1000, 76);
    if (this.classList.contains("file-collection"))
      return rectangle(240, 300 - offset, 700, 760 - offset);
    const bounds = locations[this.dataset.selectionPath];
    return bounds
      ? rectangle(bounds[0], bounds[1] - offset, bounds[2], bounds[3] - offset)
      : rectangle(0, 0, 0, 0);
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  assert.equal(frames.size, 0);
});

test("drag selects intersecting cards and finishes without leaving a frame", () => {
  render();
  start();
  move();
  assert.deepEqual(selected(), ["A"]);
  assert.ok(host.querySelector("[data-marquee]"));
  end();
  assert.deepEqual(selected(), ["A"]);
  assert.equal(host.querySelector("[data-marquee]"), null);
});

test("shrinking a rectangle removes cards that leave its bounds", () => {
  render();
  pointer(main(), "pointerdown", 700, 530);
  move(245, 310);
  assert.deepEqual(selected(), ["A", "B"]);
  move(470, 310);
  assert.deepEqual(selected(), ["B"]);
  end(470, 310);
});

for (const modifier of ["ctrlKey", "metaKey", "shiftKey"])
  test(`${modifier} adds the rectangle to existing selection`, () => {
    render({ initial: ["C"] });
    start({ [modifier]: true });
    move();
    end();
    assert.deepEqual(selected(), ["C", "A"]);
  });

test("Escape restores the previous selection and stops the active gesture", () => {
  render({ initial: ["C"] });
  start();
  move();
  let reachedGlobal = false;
  const listener = () => {
    reachedGlobal = true;
  };
  window.addEventListener("keydown", listener);
  act(() =>
    window.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  window.removeEventListener("keydown", listener);
  assert.equal(reachedGlobal, false);
  assert.deepEqual(selected(), ["C"]);
  assert.equal(host.querySelector("[data-marquee]"), null);
  move(500, 300);
  assert.deepEqual(selected(), ["C"]);
});

test("clicking blank space clears selection without opening a rectangle", () => {
  render({ initial: ["B"] });
  start();
  end(460, 530);
  assert.deepEqual(selected(), []);
});

test("modified blank clicks retain selection", () => {
  render({ initial: ["B"] });
  start({ metaKey: true });
  end(460, 530);
  assert.deepEqual(selected(), ["B"]);
});

test("touch, card controls, toolbar and disabled views do not start selection", () => {
  render({ initial: ["C"] });
  start({ pointerType: "touch" });
  move();
  end();
  pointer(host.querySelector("article button"), "pointerdown", 300, 400);
  move();
  end();
  pointer(host.querySelector("header button"), "pointerdown", 300, 30);
  move();
  end();
  render({ initial: ["C"], enabled: false });
  start();
  move();
  end();
  assert.deepEqual(selected(), ["C"]);
  assert.equal(host.querySelector("[data-marquee]"), null);
});

test("pointer cancellation releases capture and restores selection", () => {
  render({ initial: ["D"] });
  start();
  move();
  pointer(window, "pointercancel", 245, 310);
  assert.deepEqual(selected(), ["D"]);
  assert.equal(main().hasPointerCapture(1), false);
});

test("autoscroll updates the selection while keeping the frame below the header", () => {
  render();
  pointer(main(), "pointerdown", 700, 780);
  move(245, 890);
  assert.ok(offset > 0);
  move(245, -10);
  assert.ok(Number(host.querySelector("[data-marquee]").dataset.top) >= 76);
  end(245, -10);
});

test("navigation cancels the gesture and removes global listeners", () => {
  render();
  start();
  move();
  render({ scope: "other-folder" });
  assert.equal(host.querySelector("[data-marquee]"), null);
  assert.equal(main().hasPointerCapture(1), false);
  assert.equal(frames.size, 0);
});

test("a zero-width drag does not select files without a visible rectangle", () => {
  render();
  pointer(main(), "pointerdown", 350, 780);
  move(350, 310);
  end(350, 310);
  assert.deepEqual(selected(), []);
});

for (const type of ["blur", "resize", "lostpointercapture"])
  test(`${type} restores selection and clears the active frame`, () => {
    render({ initial: ["D"] });
    start();
    move();
    act(() =>
      (type === "lostpointercapture" ? main() : window).dispatchEvent(
        new window.Event(type),
      ),
    );
    assert.deepEqual(selected(), ["D"]);
    assert.equal(host.querySelector("[data-marquee]"), null);
    assert.equal(frames.size, 0);
  });
