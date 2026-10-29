import assert from "node:assert/strict";
import { test } from "node:test";
import { selectionSize } from "../src/services/selection.ts";

const item = (path, size, type = "file") => ({ path, name: path, size, type, modified: 0 });
test("selection totals add files and include recursive folder size once", () => {
  assert.equal(selectionSize([item("Photo.jpg", 12), item("Notes.txt", 8)]), 20);
  assert.equal(selectionSize([item("Folder", 100, "folder"), item("Folder/Photo.jpg", 12), item("Folder/Nested", 30, "folder"), item("Other.txt", 8)]), 108);
});
test("trash totals count separate deleted copies of the same path", () => {
  assert.equal(selectionSize([item("Folder", 100, "folder"), item("Folder/Photo.jpg", 12)], true), 112);
  assert.equal(selectionSize([item("Photo.jpg", 12), item("Photo.jpg", 20)], true), 32);
});
test("empty selections have zero size", () => assert.equal(selectionSize([]), 0));
