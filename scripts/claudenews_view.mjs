// claudenews 뉴스 줄을 세션마다 크게(max) · 작게(min) · 끔(off) 으로 그리기 위한 판정 모듈.
// 왜: 로컬 래퍼(hud/claudenews-hud.mjs)는 git 무시 파일이라, 논리는 이 추적 파일에 두고 래퍼는 불러 쓰기만 한다.
// 무엇을: 상태 읽기(~/.claudenews/view.<세션 id>), 요약 줄 떼기, 부모 상태 줄만 그리기. 의뢰서: intent/2026-11-02-news-line-per-session.md
// 요약 줄 꼴은 claudenews 플러그인 0.21.0 이 찍는 꼴(첫 줄 "↳", 이어지는 줄 9칸 들여쓰기)에 맞춘다.
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const SID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const FIRST = /^\x1b\[90m {7}↳\x1b\[0m \x1b\[2m/;
const CONT = /^ {9}\x1b\[2m/;

/** Read the per-session view state; anything odd falls back to "max". */
export function readView(sid, home = homedir()) {
  if (!SID_RE.test(String(sid))) return "max";
  try {
    const v = readFileSync(join(home, ".claudenews", `view.${sid}`), "utf-8").split("\n")[0].trim();
    return v === "off" || v === "min" ? v : "max";
  } catch {
    return "max";
  }
}

/** Drop the summary lines (first "↳" line and its continuation lines), keep everything else. */
export function stripSummary(text) {
  const lines = String(text).split("\n");
  const out = [];
  let inSummary = false;
  for (const ln of lines) {
    if (FIRST.test(ln)) { inSummary = true; continue; }
    if (inSummary && CONT.test(ln)) continue;
    inSummary = false;
    out.push(ln);
  }
  return out.join("\n");
}

/** Run only the parent status line command the plugin would run; "" when absent or failing. */
export function parentOnly(stdinData, home = homedir()) {
  try {
    const cfg = JSON.parse(readFileSync(join(home, ".claudenews", "config.json"), "utf-8"));
    const cmd = (cfg.parentStatusLine || "").trim();
    if (!cmd) return "";
    const r = spawnSync(cmd, [], { shell: true, input: stdinData, encoding: "utf-8", timeout: 3000, env: { ...process.env, HOME: home } });
    return (r.stdout || "").trimEnd();
  } catch {
    return "";
  }
}
