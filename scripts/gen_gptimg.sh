#!/usr/bin/env bash
# gpt-image-2 생성 래퍼 — OpenAI Codex CLI(codex exec) 경유.
#
# 핵심: 구독 인증(~/.codex/auth.json)을 재사용하므로 별도 OPENAI_API_KEY·API 과금이 불필요하다.
#       (third-party bridge 미사용 — OpenAI 공식 codex exec 경로만 사용)
#
# ⚠️ 비용: 이미지 생성은 Codex 사용 한도를 텍스트 대비 3~5배 빠르게 소모한다.
#         → 반드시 사용자 승인 후에만 실행할 것 (AI 자동 실행 금지).
#
# 사용:  bash gen_gptimg.sh "<프롬프트>" <출력경로.png>
# 예시:  bash gen_gptimg.sh "minimalist concept illustration of modular neural network" \
#                            docs/paper/figures/images/concept.png
#
# NOTE: codex exec의 이미지 생성 트리거($imagegen)·저장 동작은 codex 버전/설정에 따라
#       달라질 수 있다. 최초 도입 시 1회 실제 실행으로 동작을 검증하고, 필요하면
#       아래 codex exec 프롬프트 문구를 환경에 맞게 조정한다.
set -euo pipefail

PROMPT="${1:-}"
OUT="${2:-}"

if [[ -z "$PROMPT" || -z "$OUT" ]]; then
  echo "usage: gen_gptimg.sh \"<prompt>\" <output.png>" >&2
  exit 1
fi

# 1) codex CLI 존재 확인
command -v codex >/dev/null 2>&1 || {
  echo "ERROR: codex CLI를 찾을 수 없습니다. (PATH 확인 또는 'npm i -g @openai/codex')" >&2
  exit 2
}

# 2) 구독 인증 확인 (API 키가 아니라 codex login OAuth)
[[ -f "$HOME/.codex/auth.json" ]] || {
  echo "ERROR: ~/.codex/auth.json 없음 — 'codex login'으로 ChatGPT 구독 로그인이 필요합니다." >&2
  exit 3
}

# 3) 출력 디렉토리 준비 + 절대경로화 (codex가 정확한 경로에 저장하도록)
OUT_DIR="$(dirname "$OUT")"
mkdir -p "$OUT_DIR"
OUT_ABS="$(cd "$OUT_DIR" && pwd)/$(basename "$OUT")"

# 4) codex exec(비대화형)로 gpt-image-2 호출.
#    $imagegen 트리거 + 절대경로 저장 지시. 다른 파일 생성 억제.
codex exec "Use \$imagegen to generate one image and save it as a PNG at exactly this absolute path: ${OUT_ABS}. Image description: ${PROMPT}. Do not create or modify any other files."

# 5) 결과 확인
if [[ -f "$OUT_ABS" ]]; then
  echo "OK: $OUT_ABS"
else
  echo "WARN: 출력 파일이 생성되지 않았습니다 — codex 출력과 버전을 확인하세요." >&2
  echo "      ('codex exec' 이미지 인터페이스는 환경에 따라 프롬프트 조정이 필요할 수 있습니다.)" >&2
  exit 4
fi
