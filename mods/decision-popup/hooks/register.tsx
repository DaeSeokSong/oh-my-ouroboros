import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { DecisionExperiment, DecisionItem, DecisionRequest } from '../types'

// 결정 팝업: 모델이 결정 항목을 넘기면 대화창처럼 포커스를 잡는 pane 을 연다.
// 항목마다 한 페이지, 숫자키로 고르면 다음 항목으로 넘어가고, 마지막 요약 페이지에서
// «확인»을 누르면 고른 값이 이 세션에 새 메시지로 들어간다(확인 전에는 아무것도 보내지 않는다).
// 확정하지 않고 닫으면 «확정하지 않고 닫음»만 알린다.
// 항목 페이지 차례(개정 18): 번호 선택지 → «직접 입력» 칸 → 장단점 표 → 실험 정리 표(experiments 있을 때) → 선택지별 예시(항상) → 이동 줄.

const PLUGIN = 'decision-popup'
const PANE = 'decision'
const TOOL = 'ask'

const REQUEST_REF = { plugin: 'decision-popup', key: 'request' } as const
const request = atom(REQUEST_REF, null as DecisionRequest | null)
const answers = atom({ plugin: 'decision-popup', key: 'answers' } as const, {} as Record<string, number>)
// 주관식 칸(개정 17, 2026-10-21 사용자 지시): 항목마다 «직접 입력» 칸 하나. 그 답은 answers 에 FREE(-1)로 표시하고 글은 texts 에 둔다.
// 번호 선택지를 다시 고르면 texts 에서 지운다(답은 항목마다 하나).
const texts = atom({ plugin: 'decision-popup', key: 'texts' } as const, {} as Record<string, string>)
const page = atom({ plugin: 'decision-popup', key: 'page' } as const, 0)
const FREE = -1

const INPUT_SCHEMA = {
  type: 'object',
  required: ['title', 'items'],
  properties: {
    title: { type: 'string', description: '팝업 제목(예: 열린 질문 5건)' },
    items: {
      type: 'array',
      minItems: 1,
      maxItems: 9,
      items: {
        type: 'object',
        required: ['id', 'title', 'options'],
        properties: {
          id: { type: 'string', description: '항목 표지(예: Q1)' },
          title: { type: 'string', description: '항목 제목 한 줄' },
          problem: { type: 'string', description: '무엇이 문제인지 1~2줄' },
          experiments: {
            type: 'array',
            maxItems: 10,
            description: '이 항목의 제목·문제·선택지 어디에든 등장하는 모든 실험·판 이름과 새 판 별칭(예: r17t, P, R3)마다 무엇을·어떻게·왜를 각 한 줄. 출처(의뢰서·결정 기록·발사 기록)에서 옮기고 없으면 «기록 없음»',
            items: {
              type: 'object',
              required: ['name', 'what', 'how', 'why'],
              properties: {
                name: { type: 'string', description: '판 이름 또는 별칭(예: r17t, R3)' },
                what: { type: 'string', description: '무엇을 한 판인지 한 줄' },
                how: { type: 'string', description: '어떻게 한 판인지 한 줄' },
                why: { type: 'string', description: '왜 한 판인지 한 줄' },
              },
            },
          },
          options: {
            type: 'array',
            minItems: 2,
            maxItems: 4,
            items: {
              type: 'object',
              required: ['label', 'example'],
              properties: {
                label: { type: 'string', description: '선택지 이름 한 줄(번호는 화면이 붙이므로 넣지 않는다)' },
                detail: { type: 'string', description: '무엇을·어떻게 한 줄' },
                pros: { type: 'string', description: '장점 한 줄' },
                cons: { type: 'string', description: '단점 한 줄' },
                example: { type: 'string', description: '이 선택지를 고르면 실제로 어떻게 되는지 구체 예시 한 줄(필수, 수치·파일·장면). 기존 실험(판) 하나를 고르는 항목이면 그 실험의 무엇을·어떻게·왜를 두 줄로 요약해 « / » 로 이어 쓴다(판 이름만 금지, 2026-10-23 사용자 지시)' },
              },
            },
          },
        },
      },
    },
  },
} as const

// 판 이름 꼴(판 명명 예): r17t · r72-1t. \b 는 ASCII 기준이라 «r17t를» 처럼 한글 조사가 붙어도 잡힌다.
const RUN_NAME = /\b[a-z]\d{1,3}(?:-\d+)?t\b/g

function validate(raw: unknown): DecisionRequest | string {
  const r = raw as { title?: unknown; items?: unknown }
  if (typeof r.title !== 'string' || !Array.isArray(r.items) || r.items.length === 0) {
    return 'title(문자열)과 items(1개 이상)가 필요합니다'
  }
  const items: DecisionItem[] = []
  for (const it of r.items as DecisionItem[]) {
    if (!it || typeof it.id !== 'string' || typeof it.title !== 'string' || !Array.isArray(it.options)) {
      return '각 항목에 id·title·options 가 필요합니다'
    }
    if (it.options.length < 2 || it.options.length > 4) {
      return `${it.id}: 선택지는 2~4개여야 합니다`
    }
    // 장단점 표 아래 «선택지별 예시» 는 항상 그린다(개정 17 보충, 2026-10-21 사용자 «항상»): 예시가 빈 선택지는 받지 않는다.
    const noExample = it.options.findIndex(o => !o || typeof o.label !== 'string' || typeof o.example !== 'string' || !o.example.trim())
    if (noExample >= 0) {
      return `${it.id}: ${noExample + 1}번 선택지에 label 과 example(구체 예시 한 줄)이 필요합니다`
    }
    // 화면이 «1) » 번호를 붙이므로, 모델이 label 앞에 붙여 보낸 번호(«1) », «2. », «(3) »)는 뗀다(2026-10-21 «1) 1)» 겹침).
    // «.» 는 뒤에 공백이 있을 때만 번호로 본다: «2.5배 방식»·«1.0 버전» 같은 이름을 지키기 위해서다(qa 2026-10-21).
    const options = it.options.map(o => {
      const label = clean(o.label)

      return {
        label: label.replace(/^\s*\(?\d+(?:\)\s*|\.\s+)/, '') || label,
        detail: optClean(o.detail), pros: optClean(o.pros), cons: optClean(o.cons), example: clean(o.example),
      }
    })
    // 실험 정리 표(2026-10-23 사용자 지시): 0e39c90ba 문구 규칙 뒤 같은 날 재발 → 도구 거부로 구조화.
    // 판 이름 꼴(r17t·r72-1t)이 글에 나오면 experiments 에 같은 이름이 있어야 하고, 칸이 비어도 거부한다. 별칭(P·R3)은 기계가 못 찾는다.
    const rawExp: unknown = (it as { experiments?: unknown }).experiments
    if (rawExp !== undefined && (!Array.isArray(rawExp) || rawExp.length > 10)) {
      return `${it.id}: experiments 는 최대 10개의 배열이어야 합니다`
    }
    const experiments: DecisionExperiment[] = []
    for (const [i, x] of ((rawExp ?? []) as Partial<Record<keyof DecisionExperiment, unknown>>[]).entries()) {
      const cell = (v: unknown) => (typeof v === 'string' ? clean(v).trim() : '')
      const row = { name: cell(x?.name), what: cell(x?.what), how: cell(x?.how), why: cell(x?.why) }
      if (!row.name || !row.what || !row.how || !row.why) {
        return `${it.id}: 실험 정리 표(experiments) ${i + 1}번 행의 name·what·how·why 는 모두 비어 있지 않은 글이어야 합니다`
      }
      experiments.push(row)
    }
    const known = new Set(experiments.flatMap(x => [x.name.toLowerCase(), ...(x.name.toLowerCase().match(RUN_NAME) ?? [])]))
    const shown = [clean(it.title), optClean(it.problem) ?? '', ...options.flatMap(o => [o.label, o.detail ?? '', o.pros ?? '', o.cons ?? '', o.example])].join('\n')
    const lost = [...new Set(shown.match(RUN_NAME) ?? [])].filter(n => !known.has(n))
    if (lost.length > 0) {
      return `${it.id}: 실험 정리 표(experiments)에 없는 판: ${lost.join(', ')} — 항목에 나오는 판·별칭마다 무엇을·어떻게·왜 한 줄씩 넣으십시오`
    }
    items.push({ id: clean(it.id), title: clean(it.title), problem: optClean(it.problem), options, ...(experiments.length > 0 ? { experiments } : {}) })
  }

  return { title: clean(r.title), items }
}

// 모델이 보낸 글은 받을 때 한 번 정리한다(2026-10-21 security·qa): 줄 구분 문자는 « / » 로(oneLine), 그 밖의 제어 문자(C0·DEL·C1)와
// 방향 제어 문자(U+202A~202E · U+2066~2069)는 지운다. 정리하지 않으면 ① 엔진이 제어 문자 든 글을 그리기 거부하고(«a text child holds a
// control character») ② 확정·닫힘 메시지의 줄 꼴을 꾸며 외부 모델 게이트(scripts/external-model-gate.py popup_answers)를 속일 수 있다.
const DROP = (c: number) => c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0x202a && c <= 0x202e) || (c >= 0x2066 && c <= 0x2069)
function clean(s: string): string {
  let out = ''
  for (const ch of oneLine(s)) if (!DROP(ch.codePointAt(0) ?? 0)) out += ch

  return out
}
const optClean = (s: string | undefined) => (typeof s === 'string' ? clean(s) : undefined)

// 글자색: 보색 짝으로 칸끼리 갈라 본다(2026-10-21 사용자 지시). 제목 파랑 ↔ 항목 번호·이동 주황, 문제 노랑 ↔ 안 고른 선택지 보라,
// 장점 초록 ↔ 단점 분홍, 고른 선택지 초록. 어두운·밝은 테마마다 값을 따로 두고(하네스 띠 팔레트와 같은 계열) Claude Code 테마 이름이
// light 로 시작하면 밝은 팔레트를 쓴다. 읽기 실패는 어두운 팔레트.
// 선택지 설명(detail)은 흐린 글자만으로는 안 보인다는 지적(2026-10-21)에 따라 바탕을 깔고 그 위에 대비되는 글자색(detailFg/detailBg)을 쓴다.
// 장점·단점은 선택지마다 따로 두지 않고 페이지 아래에 «선택지 · 장점 · 단점» 테두리 표 하나로 모은다(2026-10-21 사용자 지시).
type Palette = {
  title: string; id: string; problem: string; label: string; picked: string; unpicked: string; detail: string
  detailFg: string; detailBg: string; border: string; pros: string; cons: string; nav: string; missing: string
}
const PALETTES: Record<'dark' | 'light', Palette> = {
  dark: { title: '#A9D8FF', id: '#FFC4A3', problem: '#F6E3A1', label: '#ECEBF5', picked: '#A8E6C1', unpicked: '#C9B8FF', detail: '#8D8AA6',
    detailFg: '#FFE7B3', detailBg: '#353A5C', border: '#6B6F8E', pros: '#A8E6C1', cons: '#FFA8C5', nav: '#FFC4A3', missing: '#FFA8C5' },
  light: { title: '#2F6FA8', id: '#B5582B', problem: '#94740F', label: '#242132', picked: '#2E8A57', unpicked: '#6A4FC0', detail: '#8A879C',
    detailFg: '#3A2E6E', detailBg: '#E6E1F7', border: '#B7B2CC', pros: '#2E8A57', cons: '#C23B6A', nav: '#B5582B', missing: '#C23B6A' },
}

// 창 높이: 머리 6줄(+문제 2줄) + 선택지마다 2줄(이름 · 설명) + 직접 입력 2줄 + 장단점 표(테두리 2 · 머리 1 · 선택지마다 1)
// + 예시 블록(제목 1 · 선택지마다 1). 40줄을 넘으면 창이 스크롤한다.
function wantedRows(req: DecisionRequest): number {
  const per = req.items.map(it => 6 + (it.problem ? 2 : 0) + it.options.length * 4 + 3 + 2 + 1 + (it.experiments ? it.experiments.length + 3 : 0))

  return Math.min(40, Math.max(14, ...per, req.items.length + 7))
}

// 답 메시지는 항목당 한 줄이다. 외부 모델 게이트(scripts/external-model-gate.py popup_answers)가 «- » 줄의 마지막 «: » 뒤를
// 사용자 답으로 읽으므로, 모델이 쓴 제목·표지·이름에 줄바꿈이 있으면 가짜 «- » 줄을 만들 수 있다. 줄바꿈은 « / » 로 바꾼다(2026-10-21).
// 줄 구분 문자: LF·VT·FF·CR·FS·GS·RS·US·NEL·LS·PS. Python splitlines() 가 나누는 문자를 모두 덮는다(qa 2026-10-21).
const LINE_BREAK = (c: number) => (c >= 0x0a && c <= 0x0d) || (c >= 0x1c && c <= 0x1e) || c === 0x1f || c === 0x85 || c === 0x2028 || c === 0x2029
const oneLine = (s: string) => {
  let out = ''
  for (const ch of String(s)) out += LINE_BREAK(ch.codePointAt(0) ?? 0) ? ' / ' : ch

  return out.replace(/ \/ (?:\s*\/ )+/g, ' / ')
}

// 한 항목의 답을 한 줄 글로. 직접 입력도 같은 방식으로 한 줄로 싣는다.
function pickedText(it: DecisionItem, k: number | undefined, free: string | undefined): string | undefined {
  if (k === FREE && free !== undefined) return `직접 입력) ${oneLine(free)}`
  const opt = k === undefined ? undefined : it.options[k]

  return opt ? `${k! + 1}) ${oneLine(opt.label)}` : undefined
}

function answerText(req: DecisionRequest, chosen: Record<string, number>, free: Record<string, string>): string {
  const lines = req.items.map(it => `- ${oneLine(it.id)} ${oneLine(it.title)}: ${pickedText(it, chosen[it.id], free[it.id]) ?? '(미선택)'}`)

  return [`[결정 팝업 확인] ${oneLine(req.title)}`, ...lines].join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: TOOL,
      description:
        '사용자에게 결정 항목(각 2~4개 선택지)을 팝업으로 띄운다. 선택지마다 example(고르면 실제로 어떻게 되는지 ' +
        '구체 예시 한 줄)이 필수이며 장단점 표 아래에 선택지별 예시로 보인다. 항목마다 사용자가 글로 답하는 «직접 입력» 칸이 ' +
        '따로 붙는다(답 메시지에 «직접 입력) 글» 로 들어온다). 사용자가 항목마다 고른 뒤 확인하면 ' +
        '답이 «[결정 팝업 확인]» 메시지로 이 세션에 들어온다. 호출한 뒤에는 턴을 끝내고 그 메시지를 기다린다. ' +
        '선택지 순서는 문서·합의 등장 순으로 두고 추천 표시를 넣지 않는다. 기존 실험(판) 가운데 하나를 고르게 할 때는 ' +
        '선택지마다 example 에 그 실험이 무엇을·어떻게·왜 한 것인지 두 줄 요약을 « / » 로 이어 적는다(판 이름만 적지 않는다). ' +
        '항목에 등장하는 모든 실험·판·별칭은 experiments 칸에 무엇을·어떻게·왜 각 한 줄(장단점 표와 예시 사이에 표로 보인다). ' +
        '판 이름 꼴(r17t)이 나오는데 칸에 없으면 거부된다. 별칭(P·Q·R3)은 자동으로 못 찾으니 빠짐없이 적는다.',
      inputSchema: INPUT_SCHEMA,
      isDeferred: false,
    })
    await $.command.register({
      name: 'decision',
      description: '열려 있던 결정 팝업을 다시 띄운다',
    })

    return next(e)
  })

  on('tool.call', { tool: `mcp__${PLUGIN}__${TOOL}` }, async ($, e) => {
    const req = validate(e)
    if (typeof req === 'string') {
      return { deny: `결정 팝업 입력 오류: ${req}` }
    }
    await update($, request, () => req)
    await update($, answers, () => ({}))
    await update($, texts, () => ({}))
    await update($, page, () => 0)
    const opened = await $.ui.open({
      id: PANE,
      title: `결정: ${req.title}`,
      focus: true,
      closeOnEscape: true,
      holdToasts: true,
      rows: wantedRows(req),
    })
    if (!opened.isPlaced) {
      return {
        result: `팝업을 아직 그리지 못했습니다(${opened.reason}). 터미널을 넓히거나 /decision 으로 다시 열 수 있습니다. ` +
          '확인되면 «[결정 팝업 확인]» 메시지가 들어옵니다.',
      }
    }

    return {
      result: `결정 팝업을 띄웠습니다(${req.items.length}개 항목). 사용자가 모두 고르고 확인하면 «[결정 팝업 확인]» 메시지가 새로 들어옵니다. 지금 턴을 끝내고 기다리십시오.`,
    }
  })

  on('command.run', { command: 'decision' }, async $ => {
    const req = await $.state.get(REQUEST_REF)
    if (!req.value) {
      return { text: '열려 있는 결정 팝업이 없습니다.' }
    }
    await $.ui.open({ id: PANE, title: `결정: ${req.value.title}`, focus: true, closeOnEscape: true, holdToasts: true, rows: wantedRows(req.value) })

    return { text: '결정 팝업을 다시 띄웠습니다.' }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') {
      const req = await $.state.get(REQUEST_REF)
      if (req.value) {
        await update($, request, () => null)
        // 제목은 모델 글이라 한 줄로 만든다(가짜 «[결정 팝업 확인]» · «- » 줄 차단, security 2026-10-21).
        void $.prompt.submit({ text: `[결정 팝업 닫힘] ${oneLine(req.value.title)}: 사용자가 확정하지 않고 닫았습니다. 선택은 반영되지 않았습니다.` })
      }
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const el = $.ui.resolve(e)
    const { Box, Text, Button } = el
    // 모바일 화면 요소 표에는 Input 이 없다. 그 화면에서는 직접 입력 칸 대신 안내 한 줄을 그린다.
    const Input = 'Input' in el ? el.Input : undefined
    const req = await read($, request)
    const chosen = await read($, answers)
    const free = await read($, texts)
    const at = await read($, page)

    if (!req) {
      return <Text dimColor>열려 있는 결정이 없습니다.</Text>
    }

    let c = PALETTES.dark
    try {
      const row = (await $.config.list()).find(r => r.key === 'theme')
      if (row && typeof row.value === 'string' && row.value.startsWith('light')) c = PALETTES.light
    } catch {
      c = PALETTES.dark
    }

    const n = req.items.length
    const goto = (p: number) => update($, page, () => Math.max(0, Math.min(n, p)))

    const it = at < n ? req.items[at] : undefined
    if (it) {
      const pick = chosen[it.id]

      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            <Text color={c.id} bold>{`${at + 1}/${n}  ${it.id}  `}</Text>
            <Text color={c.title} bold>{it.title}</Text>
          </Box>
          {it.problem ? <Text color={c.problem}>{it.problem}</Text> : null}
          <Text> </Text>
          {it.options.map((o, k) => (
            <Box key={`o-${it.id}-${k}`} flexDirection="column">
              <Button
                key={`pick-${it.id}-${k}`}
                plain
                hotkey={String(k + 1)}
                variant={pick === k ? 'primary' : undefined}
                onPress={async () => {
                  await update($, answers, a => ({ ...a, [it.id]: k }))
                  await update($, texts, t => {
                    const { [it.id]: _drop, ...rest } = t

                    return rest
                  })
                  await goto(at + 1)
                }}
              >
                <Text color={pick === k ? c.picked : c.unpicked} bold>{pick === k ? '● ' : '○ '}</Text>
                <Text color={pick === k ? c.picked : c.label} bold={pick === k}>{o.label}</Text>
              </Button>
              {o.detail ? (
                <Box key={`d-${it.id}-${k}`} flexDirection="row">
                  <Text>{'   '}</Text>
                  <Box paddingX={1} backgroundColor={c.detailBg}>
                    <Text color={c.detailFg} backgroundColor={c.detailBg}>{o.detail}</Text>
                  </Box>
                </Box>
              ) : null}
            </Box>
          ))}
          <Box key={`free-row-${it.id}`} flexDirection="row">
            <Text color={pick === FREE ? c.picked : c.unpicked} bold>{pick === FREE ? '● ' : '○ '}</Text>
            {Input ? <Input
              key={`free-${it.id}`}
              label={`${it.options.length + 1}) 직접 입력: `}
              placeholder="글로 답하려면 ↓·Tab 으로 이 칸에 와서 적고 Enter"
              value={free[it.id] ?? ''}
              submitLabel="이 답으로"
              onSubmit={async (value: string) => {
                const text = value.trim()
                if (!text) return
                await update($, texts, t => ({ ...t, [it.id]: text }))
                await update($, answers, a => ({ ...a, [it.id]: FREE }))
                await goto(at + 1)
              }}
            /> : <Text color={c.detail}>{`${it.options.length + 1}) 직접 입력은 터미널·데스크톱 화면에서 쓸 수 있습니다`}</Text>}
          </Box>
          {it.options.some(o => o.pros || o.cons) ? (
            <Box key={`t-${it.id}`} flexDirection="column" borderStyle="single" borderColor={c.border}>
              <Box flexDirection="row">
                <Box width="30%" paddingX={1}><Text color={c.id} bold>선택지</Text></Box>
                <Box width="35%" paddingX={1}><Text color={c.pros} bold>장점</Text></Box>
                <Box width="35%" paddingX={1}><Text color={c.cons} bold>단점</Text></Box>
              </Box>
              {it.options.map((o, k) => (
                <Box key={`tr-${it.id}-${k}`} flexDirection="row">
                  <Box width="30%" paddingX={1}>
                    <Text color={pick === k ? c.picked : c.label} bold={pick === k}>{`${k + 1}) ${o.label}`}</Text>
                  </Box>
                  <Box width="35%" paddingX={1}><Text color={c.label}>{o.pros ?? '-'}</Text></Box>
                  <Box width="35%" paddingX={1}><Text color={c.label}>{o.cons ?? '-'}</Text></Box>
                </Box>
              ))}
            </Box>
          ) : null}
          {it.experiments && it.experiments.length > 0 ? (
            <Box key={`xp-${it.id}`} flexDirection="column">
              <Text color={c.title} bold>실험 정리</Text>
              <Box flexDirection="column" borderStyle="single" borderColor={c.border}>
                <Box flexDirection="row">
                  <Box width="16%" paddingX={1}><Text color={c.id} bold>판</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>무엇을</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>어떻게</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>왜</Text></Box>
                </Box>
                {it.experiments.map((x, k) => (
                  <Box key={`xr-${it.id}-${k}`} flexDirection="row">
                    <Box width="16%" paddingX={1}><Text color={c.picked} bold>{x.name}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.what}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.how}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.why}</Text></Box>
                  </Box>
                ))}
              </Box>
            </Box>
          ) : null}
          <Box key={`ex-${it.id}`} flexDirection="column">
            <Text color={c.title} bold>선택지별 예시</Text>
            {it.options.map((o, k) => {
              // 줄 꼴은 «번호) 예시 글»(2026-10-21 사용자 지시: «1) (예시) 2) (예시) 이렇게»). 이름은 위 선택지·표에 이미 있어 되풀이하지 않는다.
              // 예시가 없는 요청(예시 필수 전 코드로 열린 요청)은 빈칸 대신 «(예시 없음)» 을 경고색으로 보인다.
              const ex = typeof o.example === 'string' ? o.example.trim() : ''

              return (
                <Box key={`ex-${it.id}-${k}`} flexDirection="row">
                  <Text color={pick === k ? c.picked : c.id} bold>{`${k + 1}) `}</Text>
                  <Text color={ex ? c.problem : c.missing}>{ex || '(예시 없음: 이 요청은 예시 없이 만들어졌습니다)'}</Text>
                </Box>
              )
            })}
          </Box>
          <Text> </Text>
          <Box flexDirection="row">
            <Button key="prev" plain hotkey="p" onPress={() => goto(at - 1)}>
              <Text color={c.nav}>← 이전</Text>
            </Button>
            <Text>   </Text>
            <Button key="next" plain hotkey="n" onPress={() => goto(at + 1)}>
              <Text color={c.nav}>다음 →</Text>
            </Button>
            <Text color={c.detail}>{`   (${Object.keys(chosen).length}/${n} 고름 · Esc 닫기)`}</Text>
          </Box>
        </Box>
      )
    }

    const missing = req.items.filter(it => pickedText(it, chosen[it.id], free[it.id]) === undefined)

    return (
      <Box flexDirection="column">
        <Box flexDirection="row">
          <Text color={c.id} bold>{'확인  '}</Text>
          <Text color={c.title} bold>{req.title}</Text>
        </Box>
        <Text> </Text>
        {req.items.map((it, i) => {
          const shown = pickedText(it, chosen[it.id], free[it.id])

          return (
            <Button key={`sum-${it.id}`} plain onPress={() => goto(i)}>
              <Text color={c.id} bold>{`${it.id} `}</Text>
              <Text color={c.label}>{`${it.title}: `}</Text>
              <Text color={shown === undefined ? c.missing : c.picked} bold>{shown ?? '(미선택)'}</Text>
            </Button>
          )
        })}
        <Text> </Text>
        {missing.length > 0 ? (
          <Text color={c.missing}>{`아직 고르지 않은 항목: ${missing.map(it => it.id).join(', ')} (항목을 눌러 이동)`}</Text>
        ) : (
          <Button
            key="confirm"
            plain
            hotkey="y"
            variant="primary"
            onPress={async () => {
              const text = answerText(req, chosen, free)
              await update($, request, () => null)
              await $.prompt.submit({ text })
              await $.ui.close({ id: PANE })
            }}
          >
            <Text color={c.picked} bold>이대로 확정</Text>
          </Button>
        )}
        <Box flexDirection="row">
          <Button key="back" plain hotkey="p" onPress={() => goto(n - 1)}>
            <Text color={c.nav}>← 이전</Text>
          </Button>
          <Text>   </Text>
          <Button key="restart" plain hotkey="r" onPress={() => goto(0)}>
            <Text color={c.nav}>처음부터 다시 보기</Text>
          </Button>
        </Box>
      </Box>
    )
  })
}
