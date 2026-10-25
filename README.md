# QA Agent Pipeline V2

가상 중앙제어 시스템(에어컨 관제 화면)에 **변경 요청**이 들어오면, AI가 요구사항을 분석하고 시험을 설계하고, 프로그램이 실제 화면에서 시험한 뒤, **사람이 최종 승인**하는 QA 파이프라인입니다.

## 전체 흐름

| 단계 | 하는 일 | 결과물 |
|---|---|---|
| Agent 1 · 요구사항 분석 | 변경 요청과 제품 요구사항(SRS)을 비교해 시험할 범위와 미정 조건을 정리 | 요구사항 분석 |
| Agent 2 · 시험 설계 | 기존 시험(TC)으로 충분한지 비교하고, 부족한 시험만 새로 설계하거나 기존 시험을 고쳐 씀 | 상세 TC |
| Agent 3 · 자동화·실행 | TC를 자동화 코드로 바꿔 실제 화면에서 시험하고 원래 상태로 복원 | 코드와 실행 증거 |
| Agent 4 · 결과 분석 | 통과·제품 불일치·실행 오류·미실행을 구분해 보고 | 최종 보고서, 사람 검토서 |
| 사람 · 최종 판단 | 결과를 보고 TC 등록·교체, SRS 수정 여부를 결정 | 승인·미등록·보류 기록 |

단계마다 자동 검사(Checkpoint)와 별도 AI 근거 검토를 거치며, 통과하지 못하면 다음 단계로 넘어가지 않습니다. Checkpoint 통과는 자동 검사 통과일 뿐 사람의 승인이 아닙니다.

## AI와 프로그램의 역할

- **AI가 하는 일**: Agent 1·2의 분석·설계, 단계별 근거 검토(OpenAI `gpt-6.1-sol`, 추론 `medium`).
- **프로그램이 하는 일**: 단계 간 파일 해시 확인, 필수 시험 목록 계산·대조(예: 온도 범위가 바뀌면 새 하한·상한 적용과 한 칸 밖 차단), 자동화 코드 생성, 실제 화면 시험·복원, 결과 분류(Agent 4는 규칙 기반).
- **사람이 하는 일**: 애매한 요구사항에 대한 답, 최종 등록·교체·SRS 수정 결정.

AI가 기대값이나 시험 범위를 임의로 바꾸지 못하게 하고, 근거 없는 내용은 검토에서 막습니다. 다만 AI 판단에는 여전히 오판 가능성이 있어서, 사람이 정한 정답과 비교하는 평가를 별도 평가 저장소([agent-evaluation-framework](https://github.com/SEHOOOOON/agent-evaluation-framework))에서 합니다. 채점은 생성과 다른 회사의 모델(Claude)로 합니다.

## 주요 안전장치

- 값을 바꾸는 시험은 시작 전 상태를 기록하고, 끝나면 복원한 뒤 화면·내부값을 다시 비교합니다. 복원에 실패하면 같은 환경에서 다음 시험을 하지 않습니다.
- 결과는 조작 **직후** 확인하고, 화면(패널·장비 카드)과 내부 저장값을 각각 봅니다.
- 요구사항이 애매하면 추측하지 않고 질문을 남긴 채 멈춥니다.
- 검토 AI의 지적은 '치명'만 멈추고, '경고'는 기록하고 진행합니다(사람 검토서에 표시).
- SRS 수정과 공식 TC 등록은 사람이 승인할 때만 반영됩니다.

자세한 단계별 규칙은 [프로젝트 안내](docs/PROJECT_GUIDE.md)에 있습니다.

## 실행 방법

Python 3.10 이상, 환경변수 `OPENAI_API_KEY`가 필요합니다. 실제 모델 호출에는 비용이 발생합니다(기본 모델 `gpt-6.1-sol`, 추론 `medium`).

```powershell
python -m pip install -e ".[agent3,test]"
python -m playwright install chromium

# 저장된 실행 기록 조회 (API 호출 없음)
python src/qa_pipeline_ui.py

# 새 실행과 사람 승인 기능까지 사용
python src/qa_pipeline_ui.py --allow-live-run --allow-asset-approval
```

브라우저에서 `http://127.0.0.1:8765/`에 접속합니다. 명령줄로 실행할 때는 다음 순서입니다.

```powershell
python src/qa_pipeline_v2.py pipeline --request "변경요청.json" --target-html "product_baseline/virtual-controller.html"
python src/qa_pipeline_v2.py execute --run-id "RUN-..." --target-html "product_baseline/virtual-controller.html"
python src/qa_pipeline_v2.py agent4 --run-id "RUN-..."
```

`pipeline`은 Agent 1~3, `execute`는 시험 실행, `agent4`는 보고를 담당합니다. Slack·Notion 보고는 기본이 미리보기이며 `--send`를 붙일 때만 실제로 보냅니다. 전송 설정(`SLACK_WEBHOOK_URL`, `NOTION_API_KEY`, `NOTION_DATA_SOURCE_ID`)은 저장소 루트의 `.env`에서 읽으며, `.env`는 Git에 올리지 않습니다.

대표 요청 5개(온도·모드·전원·풍량·잠금)는 `examples/change_request.representative-*.json`에 있습니다.

## 로컬 검증

```powershell
python scripts/verify_offline.py
python -m pytest -q
```

외부 연결을 막은 상태에서 회귀 시험을 돌립니다. 로컬 시험 통과는 실제 AI의 정확도나 반복 안정성을 뜻하지 않습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [현재 상태와 다음 작업](PROJECT_HANDOFF.md) | 최신 실행 결과, 검증 범위, 남은 과제 |
| [프로젝트 안내](docs/PROJECT_GUIDE.md) | 단계별 규칙, 검사·중단·복원·승인 기준 |
| [제품 SRS](docs/01_PRODUCT_SRS.md) · [시험 목록](docs/07_TEST_CATALOG.md) | 제품 기준, 자동 시험 설명 |
| [의사결정 기록](DECISION_LOG.md) · [보관 자료](archive/README.md) | 과거 결정과 이력 |

## 최근 결과 (2026-10-23~24)

| 확인 | 결과 |
|---|---|
| 대표 요청 5개 전체 실행 1회씩 | 전원·풍량·모드·온도 완주, 잠금은 정책이 정해지지 않아 질문을 남기고 멈춤(의도한 동작) |
| 시험 설계 반복(시나리오별 3회) | 전원·풍량·모드는 3번 모두 같은 정답 구조. 온도는 필수 시험 5개를 8번 모두 채움 |
| 평가에서 찾아 고친 문제 | 준비 단계에서 바꾼 모드의 복원 확인이 TC에서 빠짐(4번 중 4번) → 원인인 복원 계약을 고쳐 3번 중 3번 포함, 실제 실행 복원 정상 |

표본이 작아(시나리오당 1~3회) 반복 안정성을 단정하지 않습니다. 평가 방법과 개선 기록은 평가 저장소의 [개선 이력](https://github.com/SEHOOOOON/agent-evaluation-framework/blob/claude/fixes-20261015/improvements/README.md)에 있습니다.

## 구현 범위

가상 중앙제어의 전원·모드·풍량·온도·잠금, 기존 기능을 바꾸는 요청(MODIFIED)이 대상입니다. 실제 장비 통신, 임의의 웹사이트, 전체 회귀 시험, 기능 추가·삭제 요청은 범위 밖입니다.

## 포트폴리오

- [프로젝트 1 소개 페이지](https://htmlpreview.github.io/?https://github.com/SEHOOOOON/qa-agent-pipeline-v2/blob/claude/fixes-20261015/project.html) (작업 브랜치 미리보기, 공개 사이트 배포 전)
- 9월 실행 기록 예시: [중풍 성공](examples/results/agent1-agent2-agent3-agent4-medium-fan/README.md) · [잠금 불일치](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md) · [미정 조건](examples/results/agent1-agent2-agent3-agent4-partial-information/README.md)

예시 실행 기록은 **실행 당시의 코드** 결과이며, 최신 코드로 다시 검증한 것은 아닙니다.
