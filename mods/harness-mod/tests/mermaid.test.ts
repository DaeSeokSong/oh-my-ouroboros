import { expect, test } from 'claude-code/testing'
import { cellWidth } from '../hooks/band/width.js'
import { renderMermaid, replaceMermaidBlocks } from '../hooks/band/mermaid.js'

// 실행: claude plugin test mods/harness-mod (폴더 안에서는 claude plugin test)
const render = (src: string, w = 100): string => {
  const out = renderMermaid(src, w)
  if (out === null) throw new Error('null 이 나왔습니다')
  return out
}
const count = (s: string, ch: string) => s.split(ch).length - 1

test('TD 단순 사슬: 상자 셋과 화살촉 둘이 위에서 아래로 이어진다', () => {
  const out = render('flowchart TD\n  A --> B --> C')
  expect(out).toBe([
    '┌───┐',
    '│ A │',
    '└─┬─┘',
    '  │',
    '  ▼',
    '┌───┐',
    '│ B │',
    '└─┬─┘',
    '  │',
    '  ▼',
    '┌───┐',
    '│ C │',
    '└───┘',
  ].join('\n'))
})

test('LR 단순 사슬: 화살촉은 ► 이고 왼쪽에서 오른쪽으로 놓인다', () => {
  const out = render('graph LR\n  A-->B-->C')
  expect(out).toBe([
    '┌───┐  ┌───┐  ┌───┐',
    '│ A ├─►│ B ├─►│ C │',
    '└───┘  └───┘  └───┘',
  ].join('\n'))
})

test('BT 는 TD 로, RL 은 LR 로 취급한다', () => {
  expect(render('flowchart BT\nA-->B')).toBe(render('flowchart TD\nA-->B'))
  expect(render('flowchart RL\nA-->B')).toBe(render('flowchart LR\nA-->B'))
})

test('분기와 합류: 같은 층 상자가 나란히 놓이고 모선이 갈라졌다 모인다', () => {
  const out = render('flowchart TD\n  A[시작] --> B{조건}\n  B -->|예| C[처리]\n  B -->|아니오| D[종료]\n  C --> E[끝]\n  D --> E')
  const rows = out.split('\n')
  const rowC = rows.find(r => r.includes('처리') && r.includes('종료'))
  expect(rowC !== undefined).toBe(true)
  expect(out).toContain('┴')            // 갈라지는 모선
  expect(out).toContain('┘')            // 합류
  expect(count(out, '▼')).toBe(4)       // 도착 노드마다 화살촉 하나(합류하는 E 는 하나를 같이 쓴다)
  expect(out).toContain('예')
  expect(out).toContain('아니오')
  expect(out).not.toContain('↪')
})

test('간선 라벨: |라벨| 과 -- 라벨 --> 둘 다 선 옆에 붙는다', () => {
  const a = render('flowchart TD\nA -->|네| B')
  const b = render('flowchart TD\nA -- 네 --> B')
  expect(a).toBe(b)
  expect(a).toContain('│ 네')
})

test('긴 라벨은 선 옆에 두지 않고 아래 목록으로 보낸다', () => {
  const out = render('flowchart TD\nA -->|아주아주 긴 라벨 문장입니다| B')
  expect(out).toContain('A → B : 아주아주 긴 라벨 문장입니다')
  expect(out.split('\n').filter(r => r.includes('아주아주')).length).toBe(1)
})

test('순환: 역방향 간선은 선 대신 ↪ 줄로 적는다', () => {
  const out = render('flowchart TD\nA --> B --> C\nC -->|다시| A')
  expect(out).toContain('↪ C → A : 다시')
  expect(count(out, '▼')).toBe(2)
  expect(render('flowchart TD\nA --> A')).toContain('↪ A → A')
})

test('층 건너뛰기 간선도 ↪ 줄로 적는다', () => {
  const out = render('flowchart TD\nA --> B --> C\nA -.-> C')
  expect(out).toContain('↪ A → C')
  expect(count(out, '▼')).toBe(2)
})

test('한글 노드: 상자 세 줄의 폭이 같다(한글 2칸)', () => {
  const out = render('flowchart TD\nA[가나다 라마] --> B[바사]')
  const rows = out.split('\n')
  const top = rows.findIndex(r => r.startsWith('┌'))
  expect(cellWidth(rows[top])).toBe(cellWidth(rows[top + 1]))
  expect(cellWidth(rows[top])).toBe(cellWidth(rows[top + 2]))
  expect(cellWidth(rows[top])).toBeGreaterThanOrEqual(cellWidth('가나다 라마') + 4)
})

test('노드 모양 문법과 정리: 모두 상자, 따옴표·<br>·주석·subgraph·style 처리', () => {
  const out = render([
    'flowchart LR',
    '%% 주석',
    'subgraph S[묶음]',
    'A["둥글(x)"] --> B((원))',
    'B --> C>깃발] --> D[[겹]]',
    'end',
    'E{판단<br/>둘째줄} -.-> F(둥근)',
    'classDef k fill:#fff',
    'style A fill:#000',
    'click A href "x"',
  ].join('\n'))
  for (const t of ['둥글(x)', '원', '깃발', '겹', '판단 둘째줄', '둥근']) expect(out).toContain(t)
  expect(out).not.toContain('<br')
  expect(out).not.toContain('"')
})

test('A & B --> C: 두 출발이 한 도착으로 모인다', () => {
  const out = render('flowchart TD\nA & B --> C')
  expect(count(out, '▼')).toBe(1)
  expect(count(out, '┬')).toBe(2)
  expect(out).toContain('├───────┘')
})

test('maxWidth 를 넘으면 층별 목록 꼴로 대신 그린다', () => {
  const src = 'flowchart LR\nA[가나다라마바사] --> B[아자차카타파하] --> C[첫째 둘째 셋째]'
  const wide = render(src, 100)
  expect(wide).toContain('┌')
  const out = render(src, 30)
  expect(out).not.toContain('┌')
  expect(out.split('\n')[0]).toBe('1층: [가나다라마바사]')
  expect(out).toContain('가나다라마바사 → 아자차카타파하')
})

test('층 안 순서·여러 층: 합류 두 줄 이상이어도 줄이 maxWidth 안에 든다', () => {
  const out = render('flowchart TD\nA-->B\nA-->C\nA-->D\nB-->E\nC-->E\nD-->E', 100)
  for (const r of out.split('\n')) expect(cellWidth(r)).toBeLessThanOrEqual(100)
  expect(count(out, '▼')).toBe(4)
})

test('sequenceDiagram 기본: 참여자 상자, 생명선, 메시지 화살표, 별칭', () => {
  const out = render('sequenceDiagram\n  participant A as Alice\n  actor B as Bob\n  A->>B: 안녕\n  B-->>A: 응답')
  expect(out).toBe([
    '┌───────┐  ┌─────┐',
    '│ Alice │  │ Bob │',
    '└───┬───┘  └──┬──┘',
    '    │         │',
    '    │  안녕   │',
    '    ├────────►│',
    '    │         │',
    '    │  응답   │',
    '    │◄┄┄┄┄┄┄┄┄┤',
    '    │         │',
  ].join('\n'))
})

test('sequenceDiagram: 참여자 선언 없이 메시지에서 생기고, 화살표 종류별 머리', () => {
  const out = render('sequenceDiagram\nA->B: 선\nA-xB: 엑스\nA-)B: 비동기')
  expect(out).toContain('A')
  expect(out).toContain('x│')
  expect(out).toContain(')│')
  expect(out).not.toContain('►')
})

test('sequenceDiagram: Note, autonumber, loop/alt/else/end 한 줄 표시', () => {
  const out = render([
    'sequenceDiagram',
    'autonumber',
    'A->>B: 요청',
    'Note over A,B: 두 쪽 메모',
    'Note right of B: 오른쪽',
    'loop 재시도',
    'B->>B: 처리',
    'alt 성공',
    'B-->>A: 완료',
    'else 실패',
    'B-->>A: 오류',
    'end',
    'end',
  ].join('\n'))
  expect(out).toContain('1. 요청')
  expect(out).toContain('(두 쪽 메모)')
  expect(out).toContain('(오른쪽)')
  for (const t of ['[loop 재시도]', '[alt 성공]', '[else 실패]']) expect(out).toContain(t)
  expect(count(out, '[end]')).toBe(2)
  expect(out).toContain('2. 처리')
})

test('sequenceDiagram: 폭을 넘으면 목록 꼴', () => {
  const out = render('sequenceDiagram\nA->>B: 아주 긴 메시지 글자가 여기 들어갑니다\nB-->>A: 응답', 30)
  expect(out).not.toContain('┌')
  expect(out).toContain('참여자: A, B')
  expect(out).toContain('A → B : 아주 긴 메시지 글자가 여기 들어갑니다')
  expect(out).toContain('B ⇢ A : 응답')
})

test('지원 밖은 null: pie·gantt·문법 오류·빈 입력·크기 초과', () => {
  expect(renderMermaid('pie\n "a": 1')).toBe(null)
  expect(renderMermaid('gantt\n title x')).toBe(null)
  expect(renderMermaid('flowchart TD\nA --> ')).toBe(null)
  expect(renderMermaid('flowchart TD\nA[열린 --> B')).toBe(null)
  expect(renderMermaid('flowchart TD\n이건 ??? 문장')).toBe(null)
  expect(renderMermaid('sequenceDiagram\n뭔가 이상한 줄')).toBe(null)
  expect(renderMermaid('flowchart TD')).toBe(null)
  expect(renderMermaid('')).toBe(null)
  expect(renderMermaid(undefined as unknown as string)).toBe(null)
  const many = 'flowchart TD\n' + Array.from({ length: 61 }, (_, i) => `N${i}`).join(' --> ')
  expect(renderMermaid(many)).toBe(null)
  const edges = 'flowchart TD\n' + Array.from({ length: 121 }, (_, i) => `A --> B${i % 59}`).join('\n')
  expect(renderMermaid(edges)).toBe(null)
})

test('앞머리(front matter)와 %%{init}%% 주석은 건너뛴다', () => {
  const out = render('---\ntitle: 제목\n---\n%%{init: {"theme":"dark"}}%%\nflowchart TD\nA-->B')
  expect(count(out, '▼')).toBe(1)
})

const FLOW = 'flowchart TD\n  A --> B'
const BAD = 'pie\n  "a": 1'

test('입력 상한: 20KB 초과 · 한 줄 500자 초과 · 노드 60 · 간선 120 초과는 100ms 안에 null (공백 수천 개 · & 곱 포함)', () => {
  const cases: Record<string, string> = {
    '공백 수천 개 간선 줄': 'flowchart TD\nA --' + ' '.repeat(5000) + 'B --> C',
    '공백 수천 개 -- 라벨': 'flowchart TD\nA -- ' + ' '.repeat(300) + 'x' + ' '.repeat(300) + ' --> B',
    '& 곱 2000×2000': 'flowchart TD\n' + Array.from({ length: 2000 }, (_, i) => 'A' + i).join(' & ') + ' --> ' + Array.from({ length: 2000 }, (_, i) => 'B' + i).join(' & '),
    '& 곱 40×40 (한 줄 500자 이내)': 'flowchart TD\n' + Array.from({ length: 40 }, (_, i) => 'A' + i).join(' & ') + ' --> ' + Array.from({ length: 40 }, (_, i) => 'B' + i).join(' & '),
    '20KB 초과': 'flowchart TD\n' + 'A --> B\n'.repeat(3000),
    '노드 61개': 'flowchart TD\n' + Array.from({ length: 61 }, (_, i) => `N${i} --> N${i + 1}`).join('\n'),
  }
  for (const [name, src] of Object.entries(cases)) {
    const t0 = performance.now()
    const out = renderMermaid(src)
    const ms = performance.now() - t0
    expect(`${name} ${out} ${ms < 100}`).toBe(`${name} null true`)
  }
  expect(renderMermaid('flowchart TD\nA --> B')).not.toBeNull()
})

test('replaceMermaidBlocks: 성공한 블록만 text 펜스로 바꾸고 나머지는 한 글자도 안 바꾼다', () => {
  const md = ['앞 글', '```mermaid', FLOW, '```', '중간 글', '```mermaid', BAD, '```', '```python', 'print(1)', '```', '끝'].join('\n')
  const out = replaceMermaidBlocks(md)
  const lines = out.split('\n')
  expect(lines[0]).toBe('앞 글')
  expect(lines[1]).toBe('```text')
  expect(lines[2]).toBe('mermaid → 도해')
  expect(out).toContain('▼')
  expect(out).toContain('중간 글\n```mermaid\npie\n  "a": 1\n```\n```python\nprint(1)\n```\n끝')
  expect(out).not.toContain('flowchart')
})

test('replaceMermaidBlocks: 바뀐 것이 없으면 같은 문자열을 돌려준다', () => {
  const none = '그냥 글\n```python\nx = 1\n```'
  expect(replaceMermaidBlocks(none)).toBe(none)
  const bad = '```mermaid\n' + BAD + '\n```\n'
  expect(replaceMermaidBlocks(bad)).toBe(bad)
  expect(replaceMermaidBlocks('')).toBe('')
})

test('replaceMermaidBlocks: 닫히지 않은 펜스(스트리밍 중)와 다른 펜스 안의 mermaid 는 그대로', () => {
  const open = '글\n```mermaid\n' + FLOW
  expect(replaceMermaidBlocks(open)).toBe(open)
  const nested = '````markdown\n```mermaid\n' + FLOW + '\n```\n````'
  expect(replaceMermaidBlocks(nested)).toBe(nested)
})

test('replaceMermaidBlocks: 들여쓴 펜스는 들여쓰기를 유지하고 maxWidth 를 넘기지 않는다', () => {
  const md = '- 항목\n  ```mermaid\n  flowchart LR\n  A[가나다라마바사] --> B[아자차카타파하]\n  ```'
  const out = replaceMermaidBlocks(md, 30)
  expect(out).toContain('  ```text\n  mermaid → 도해\n  1층: [가나다라마바사]')
})
