// scripts/claudenews_view.mjs 시험: 임시 HOME 으로 상태 읽기 · 요약 줄 떼기 · 부모 줄 실행.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readView, stripSummary, parentOnly } from "../claudenews_view.mjs";

function home() {
  const h = mkdtempSync(join(tmpdir(), "cnv-"));
  mkdirSync(join(h, ".claudenews"));
  return h;
}
const put = (h, name, body) => writeFileSync(join(h, ".claudenews", name), body);

test("readView: no file, odd sid, odd value fall back to max", () => {
  const h = home();
  assert.equal(readView("abc", h), "max");
  put(h, "view.abc", "weird\n");
  assert.equal(readView("abc", h), "max");
  put(h, "view.a.b", "off\n");
  assert.equal(readView("a.b", h), "max");
  assert.equal(readView("../x", h), "max");
  assert.equal(readView("", h), "max");
  assert.equal(readView("x".repeat(65), h), "max");
});

test("readView: reads off/min/max from the first line", () => {
  const h = home();
  put(h, "view.s1", "off\n");
  put(h, "view.s2", " min \nignored");
  put(h, "view.s3", "max");
  assert.equal(readView("s1", h), "off");
  assert.equal(readView("s2", h), "min");
  assert.equal(readView("s3", h), "max");
});

test("stripSummary: removes only the two summary line shapes", () => {
  const first = "\x1b[90m       ↳\x1b[0m \x1b[2msummary one\x1b[0m";
  const cont = "         \x1b[2msummary two\x1b[0m";
  const text = ["parent line", "title line", first, cont, cont].join("\n") + "\n";
  assert.equal(stripSummary(text), "parent line\ntitle line\n");
  assert.equal(stripSummary("only parent\ntitle\n"), "only parent\ntitle\n");
  // a 9-space line that is not after a summary first line stays
  assert.equal(stripSummary(cont + "\n"), cont + "\n");
});

test("parentOnly: runs parentStatusLine with stdin, trims end; empty when absent or failing", () => {
  const h = home();
  assert.equal(parentOnly("{}", h), "");
  put(h, "config.json", JSON.stringify({ parentStatusLine: "cat; echo; echo" }));
  assert.equal(parentOnly("hello", h), "hello");
  put(h, "config.json", JSON.stringify({ parentStatusLine: "" }));
  assert.equal(parentOnly("hello", h), "");
  put(h, "config.json", "not json");
  assert.equal(parentOnly("hello", h), "");
});
