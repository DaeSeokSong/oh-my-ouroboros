"""correction-detect.sh 입력 거르기 회귀 테스트 (2026-11-12 신설).

대상: 사람이 쓴 말만 교정 후보(T12)로 보는 거르기.
      훅 알림 · 예약 점검 · system-reminder 는 통째로 빼고, 붙여 넣은 출력은 잘라 내고,
      결정 팝업은 «직접 입력)» 뒤만 보고, «잘못» 하나로만 걸린 본인 실수형은 건너뛴다.
      경우는 candidates_judgment.md(2026-11-12 판정안)의 실제 후보 문구를 줄여 썼다.

격리: 임시 HOME 에 .claude/{_evolve,_usage} 를 짓고 scripts/ 는 실제 폴더로 심볼릭 링크한다
      (test_loop_wiring.py 와 같은 방식, 실제 대장 · 프롬프트 로그 불변).

실행: python3 ~/.claude/scripts/tests/test_correction_detect.py → 실패 0 이면 exit 0
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
results = []

NOTICE = ("[하네스 변경 알림 · 회신 불요] 하네스 저장소에 새 커밋이 생겼습니다. - abc123 fix: x "
          "반영만 하고 회신하거나 사용자에게 따로 보고하지 마십시오")
SCHEDULED = "[예약 점검 · 0a1b2c3d] sample-project 대기 목록 안전망: 항상 확인하고 다시는 놓치지 마"
REMINDER = "<system-reminder> Scheduled task 1a2b3c4d 앞으로는 매번 실행 </system-reminder>"
POPUP_OPTIONS = ("[결정 팝업 확인] 계획 확정 의뢰서 교정 - S1 «잘못된 막힘» 신호를 어떻게 셀지: 1) 확정: 항상 센다 "
                 "- C1 앞으로는 어디에 둘지: 2) 확정: 훅에 둔다")
POPUP_DIRECT = ("[결정 팝업 확인] effort 묻는 방식 - E1 effort 를 어떻게 물을지: 직접 입력) 앞으로는 각 모델당 effort 정할 수 있게 해 "
                "- E2 잘못된 막힘 처리: 1) 확정: 항상 막음")
PASTED = ("우선 결과부터 봐   <pasted_content id=\"2db0\"> user@host1:~$ sudo bash x.sh "
          "적용하려면 다시 로그인해야 적용됩니다 </pasted_content>")
PASTED_WITH_CORRECTION = "그렇게 하지 마 <pasted_content id=\"a1\"> 항상 다시 로그인해 </pasted_content>"
SELF_1 = "프롬프트 잘못 입력했어"
SELF_2 = "내가 잘못 말했네 그 경로가 맞아"
REAL_1 = "그거 잘못 만들었어"
REAL_2 = "아직도 확인만 해? 너무 오래하는데 잘못된 거 아닌지 확인해"
REAL_3 = "영어 단어면 영어 그대로 써, 음차하지 마"
SELF_3 = "내가 잘못 이해했네"
REAL_4 = "너 잘못 이해했어"
REAL_5 = "잘못 알려 줬잖아 다시 해"


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_home(tmp):
    home = Path(tmp)
    claude = home / ".claude"
    for d in ("_evolve", "_usage"):
        (claude / d).mkdir(parents=True, exist_ok=True)
    (claude / "scripts").symlink_to(SCRIPTS)
    return home


def detect(prompts):
    """임시 HOME 에 프롬프트 로그를 쓰고 감지기를 돌려 (후보 행 목록, 완료 코드)를 돌려준다."""
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [json.dumps({"ts": ts, "cwd": "/x", "prompt": p}, ensure_ascii=False) for p in prompts]
        (home / ".claude/_evolve/prompts.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        r = subprocess.run(["bash", str(SCRIPTS / "correction-detect.sh")], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home)), cwd=str(SCRIPTS.parent), check=False)
        f = home / ".claude/_evolve/candidates.tsv"
        rows = [ln.split("\t") for ln in f.read_text(encoding="utf-8").splitlines()[1:] if ln] if f.exists() else []
        return rows, r.returncode


def test_machine_prompts_skipped():
    for label, p in (("하네스 변경 알림", NOTICE), ("예약 점검", SCHEDULED), ("system-reminder", REMINDER)):
        rows, rc = detect([p])
        check(f"기계 프롬프트 «{label}» 는 잡지 않음", rows == [] and rc == 0, str(rows))


def test_popup_options_skipped_direct_input_kept():
    rows, _ = detect([POPUP_OPTIONS])
    check("결정 팝업 선택지 문구(«잘못된 막힘» · 항상 · 앞으로는)는 잡지 않음", rows == [], str(rows))
    rows, _ = detect([POPUP_DIRECT])
    check("결정 팝업 직접 입력의 진짜 교정은 잡음(1행)", len(rows) == 1, str(rows))
    if rows:
        check("직접 입력 구간만 요약에 남음(다음 항목 « - E2 » 앞에서 끊김)",
              rows[0][5].startswith("앞으로는 각 모델당 effort") and "잘못된 막힘" not in rows[0][5], rows[0][5])
        check("키워드는 직접 입력 구간에서 뽑힘(kw=앞으로는)", rows[0][6] == "kw=앞으로는", rows[0][6])


def test_pasted_content_cut():
    rows, _ = detect([PASTED])
    check("붙여 넣은 터미널 출력(«다시 로그인해»)은 잡지 않음", rows == [], str(rows))
    rows, _ = detect([PASTED_WITH_CORRECTION])
    check("붙여 넣기 앞의 사용자 교정은 잡음", len(rows) == 1 and rows[0][6] == "kw=하지 마", str(rows))
    if rows:
        check("요약에 붙여 넣은 부분이 없음", "pasted_content" not in rows[0][5] and "로그인" not in rows[0][5], rows[0][5])


def test_self_mistake_skipped():
    for p in (SELF_1, SELF_2, SELF_3):
        rows, _ = detect([p])
        check(f"본인 실수형 «{p[:12]}» 는 잡지 않음", rows == [], str(rows))


def test_real_corrections_kept():
    for p, kw in ((REAL_1, "잘못"), (REAL_2, "잘못"), (REAL_3, "하지 마"), (REAL_4, "잘못"), (REAL_5, "잘못")):
        rows, _ = detect([p])
        check(f"진짜 교정 «{p[:14]}» 는 잡음(kw={kw})", len(rows) == 1 and rows[0][6] == f"kw={kw}", str(rows))


def test_mixed_batch():
    rows, rc = detect([NOTICE, SCHEDULED, POPUP_OPTIONS, PASTED, SELF_1, REAL_1, REAL_3, POPUP_DIRECT])
    check("섞인 8줄에서 진짜 교정 3건만 잡음", len(rows) == 3 and rc == 0, str([r[5] for r in rows]))


for fn in (test_machine_prompts_skipped, test_popup_options_skipped_direct_input_kept, test_pasted_content_cut,
           test_self_mistake_skipped, test_real_corrections_kept, test_mixed_batch):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
