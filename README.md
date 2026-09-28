# QA Agent Pipeline V2

기존 요구사항 명세서(SRS)와 테스트케이스(TC)가 있는 가상 중앙제어 시스템에서, **새 변경 요청을 분석하고 시험한 뒤 사람이 테스트 자산을 승인하는 QA 파이프라인**입니다.

## 전체 흐름

| 단계 | 하는 일 | 결과물 |
|---|---|---|
| Agent 1 · 요구사항 분석 | 변경 요청과 SRS를 비교하고 시험할 범위·미정 조건을 정리 | 요구사항 분석 |
| Agent 2 · 테스트 설계 | 기존 TC로 확인할 수 있는지 비교하고 부족한 시험을 설계 | 사용할 기존 TC와 새 상세 TC |
| Agent 3 · 자동화·실행 | TC를 바탕으로 자동화 코드를 만들고 실제 화면에서 시험·복원 | 코드와 실행 증거 |
| Agent 4 · 결과 분석 | 실행 결과와 미실행 사유를 분류해 보고 | 최종 보고서와 사람 검토 자료 |
| 사람 · 최종 판단 | 결과를 검토하고 SRS 개정·공식 TC 등록 여부를 결정 | 승인 또는 보류 기록 |

관련 기존 TC는 이름이 비슷해서가 아니라 **요청과 실제 검증 범위가 관련될 때** 선택합니다. 기존 TC로 충분하면 새 TC를 중복 생성하지 않습니다. PASS는 실행 결과이며 공식 등록 승인이 아닙니다.

## AI와 프로그램의 역할

- Agent 1·2는 OpenAI API로 요구사항을 분석하고 TC를 작성합니다.
- Agent 3는 새 TC의 시험 내용을 이어받아 코드를 생성·실행합니다. 시험할 값이나 기대결과를 새로 정하지 않습니다.
- 별도 모델 검토와 코드 검사는 원문 근거·필수 확인·단계 간 전달을 점검합니다. 모델의 오판 가능성은 남습니다.
- Agent 4는 생성형 AI가 아닌 규칙 기반 분석기입니다. 사람의 최종 승인도 자동화하지 않습니다.

V1은 고정 산출물로 흐름을 보여준 **Fixture 기반 Workflow Prototype**입니다. V2는 실제 모델 생성과 제품 시험을 연결합니다. 내부 구현과 과거 TC 호환 방식은 [프로젝트 안내](docs/PROJECT_GUIDE.md)에 설명합니다.

## 진행·중단·승인 기준

- 근거가 부족한 AI 초안은 정해진 한도 안에서 재작성합니다. 모든 오류를 자동으로 고치지는 않습니다.
- 필요한 조건이 미정이면 사람 확인으로 남깁니다. 없는 기능의 시험도 설계할 수 있지만, 실행 수단이 없으면 미실행 사유를 기록합니다.
- 내부 오류는 이후 후보의 추가 호출을 중단합니다. 복원 실패 시 같은 환경에서 후속 시험을 계속하지 않습니다. 자동화 지원 부족과 실제 제품의 기대결과 불일치는 구분합니다.
- 값을 변경하는 시험은 준비 전 상태를 기록하고 복원·확인합니다. 조회만 하는 시험에는 불필요한 복원을 요구하지 않습니다.
- SRS 개정과 공식 TC 등록은 사람의 동의를 받아 반영합니다. 보고서를 작성하거나 PASS가 나온 것만으로 기존 자산이 바뀌지는 않습니다.

## 구현 범위와 증거 읽는 법

현재 대상은 가상 중앙제어의 전원·모드·풍량·온도·잠금과 MODIFIED 요청입니다. 실제 장비 통신, 임의 웹사이트, 전체 회귀, ADDED·DELETED 요청 처리를 구현 완료로 소개하지 않습니다.

**구현된 기능, 과거 시연, 최신 실제 실행은 서로 구분합니다.** 개별 정상 실행이 성공해도 기존 TC 재사용·SRS 개정·공식 등록까지 모두 검증한 것은 아닙니다. 로컬 테스트 통과는 실제 모델의 정확도나 반복 안정성을 대신하지 않습니다.

- [현재 상태와 다음 작업](PROJECT_HANDOFF.md): 최신 실행 결과, 검증 범위, 남은 과제
- [프로젝트 안내](docs/PROJECT_GUIDE.md): 단계별 계약, 검사·중단·복원·승인 기준
- [의사결정 기록](DECISION_LOG.md): 보완 이유와 과거 변경 이력
- [제품 SRS](docs/01_PRODUCT_SRS.md) · [자동 테스트 목록](docs/07_TEST_CATALOG.md): 제품 기준과 내부 코드 검증

날짜가 붙은 `*.history-20260928.md` 파일은 정리 전 보존본입니다. 현재 설명을 찾을 때는 위 문서를 먼저 읽고, 과거 판단·실패 경과가 필요할 때만 보존본을 참고하세요.

인계 문서의 `runs/` 경로는 로컬 진단 기록이며 GitHub에 모두 포함되지는 않습니다. 공개 증거는 아래 링크를 사용하세요.

## 실행 방법

### 로컬 실행 준비

저장소 루트에서 실행하는 개발 환경을 지원합니다. 아래 `-e`는 소스를 복사하지 않고 이 저장소에 연결하므로 UI가 제품 HTML·SRS·실행 기록을 같은 위치에서 찾습니다. 독립 설치형 배포는 지원하지 않습니다. 저장소를 이동했다면 같은 환경에서 다시 등록하세요.

Python 3.10 이상이 필요합니다. OpenAI API 키는 실행 환경의 `OPENAI_API_KEY`에 설정합니다. 실제 모델 호출에는 비용이 발생합니다. 기본 모델은 `gpt-5.6-terra / medium`입니다.

```powershell
python -m pip install -e ".[agent3,test]"
python -m playwright install chromium

# 저장된 실제 Run 조회
python -m qa_pipeline_ui

# 새 API 실행과 사람 승인 기능 활성화
python -m qa_pipeline_ui --allow-live-run --allow-asset-approval
```

브라우저에서 `http://127.0.0.1:8765/`에 접속합니다. 새로 복제한 저장소에는 로컬 실행 기록이 없어 조회 목록이 비어 있을 수 있습니다. `pytest-playwright`는 agent3 설치 옵션에 포함됩니다. 실제 실행·승인 요청은 같은 로컬 페이지의 JSON 요청만 허용합니다.

HTML을 직접 열거나 공개 웹 주소에 접속하면 MED 풍량 정상 변경의 저장된 데모가 표시됩니다. 데모 승인은 화면 시연이며 파일에 반영되지 않습니다. 실제 시험은 로컬 서버가 별도 브라우저에서 수행하고, 관제 화면에는 실행 상태와 결과가 표시됩니다.

CLI에서는 다음 순서로 실행합니다.

```powershell
python -m qa_pipeline_v2 pipeline --request "examples/change_request.success-medium-fan.json" --target-html "product_baseline/virtual-controller.html"
python -m qa_pipeline_v2 execute --run-id "RUN-..." --target-html "product_baseline/virtual-controller.html"
python -m qa_pipeline_v2 agent4 --run-id "RUN-..."
```

`pipeline`은 Agent 1~3, `execute`는 완료 후보 확인·관련 기존 회귀, `agent4`는 분류·최종 보고를 담당합니다. 후자의 두 명령은 모델을 호출하지 않습니다. Slack·Notion은 기본 미리보기이며 CLI에서 `--send`를 명시할 때 실제 전송합니다. 화면에서 시작한 실행은 외부 보고 미리보기까지 진행합니다.

Notion은 실행 후 TC 제목·결과·분류 요약과 함께, 검증된 설계의 사전조건·단계별 조작과 기대결과·복원을 해당 실행 페이지 본문에 연결합니다. 같은 내용의 재전송은 중복 추가하지 않고 수동 메모는 보존합니다. 과거 TC에 단계 연결 정보가 없으면 임의로 보충하지 않습니다. Agent 2 초안만 별도 게시하는 기능은 없으며, 로컬 미리보기·자동 테스트와 실제 Notion 게시 확인은 구분합니다.

## 로컬 검증

```powershell
python scripts/verify_offline.py
python -m pytest --collect-only -q
git diff --check
```

`verify_offline.py`는 서비스 키를 제거하고 Python의 외부 연결과 테스트 브라우저의 외부 리소스를 차단한 상태에서 회귀검사를 수행합니다. `--focus`는 일부 역할 검사만 선택합니다. OS 수준 네트워크 격리나 실제 모델 평가 도구는 아닙니다.

## 공개 실행 기록과 포트폴리오

- [중풍 성공 사례](examples/results/agent1-agent2-agent3-agent4-medium-fan/README.md)
- [잠금 불일치 사례](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md)
- [미정 조건이 남은 사례](examples/results/agent1-agent2-agent3-agent4-partial-information/README.md)

위 자료는 **실행 당시의 증거**이며 최신 구현 전체를 재검증한 기록이 아닙니다. 이전 AUTO 온도 기록(`agent1-agent2-auto-temperature`)은 저장 바이트와 Manifest 해시 불일치가 있어 현재 검증기에 재인계 가능한 성공 증거로 사용하지 않습니다. 과거 원본을 수정해 성공으로 바꾸지 않습니다.

[공개 포트폴리오](https://sehooooon.github.io/qa-agent-pipeline-v2/project.html)는 기존 공개본을 유지합니다. 최신 코드와 설명이 다를 수 있으므로 현재 상태는 이 README와 인계 문서를 확인하세요. 수정 중인 포폴·백업·새 영상은 사용자 검토 전 공개하지 않습니다.

영상 도구와 촬영 제한은 [영상 미리보기 안내](docs/PROJECT_GUIDE.md#승인-전-영상-미리보기-생성)를 참고하세요. 저장 결과를 보여주는 영상과 새 API 전체 실행 영상은 구분합니다.
