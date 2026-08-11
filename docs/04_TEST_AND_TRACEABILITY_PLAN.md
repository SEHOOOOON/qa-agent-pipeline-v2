# 테스트 및 추적성 계획

## 1. 기존 13개 TC의 정확한 분류

기존 결과 8 Pass·3 Fail·2 Skipped는 제품 회귀 성공률이 아니라 **제품 기능 TC와 분류용 Fixture가 섞인 데모 Dataset**입니다.

| 분류 | 수 | TC |
|---|---:|---|
| 환경 사전 점검 사례 | 1 | TC-ENV-000 |
| 제품 기능 후보 | 7 | TC-MODE-001~003, TC-LOCK-001, TC-ERR-001, TC-INT-002, TC-TEMP-001 |
| 제품 결함 분류 Fixture | 1 | TC-TEMP-002 |
| Pipeline Control Fixture | 4 | TC-PIPE-001~004 |
| 합계 | 13 | 프로젝트 1 자산 |

TC-ENV-000은 현재 일반 첫 테스트이며 실패 시 후속 실행을 자동 차단하지 않습니다. V2에서 Gate로 사용하려면 Orchestrator 로직을 별도로 구현해야 합니다.

## 2. 기존 TC→SRS 추적성

| TC ID | 실제 검증 목적 | Requirement | V2 처리 |
|---|---|---|---|
| TC-ENV-000 | 페이지·장비 16대·QA 패널 확인 | REQ-ENV-001 | 사전 점검 사례 |
| TC-MODE-001 | HEAT·24°C 적용과 화면·내부 상태 | REQ-CONTROL-001, REQ-MODE-001, REQ-STATE-001 | 회귀 후보 |
| TC-MODE-002 | FAN 온도 입력 비활성 | REQ-MODE-002 | 회귀 후보 |
| TC-MODE-003 | DRY 비활성 후 COOL 재활성 | REQ-MODE-001, REQ-MODE-002 | 회귀 후보 |
| TC-LOCK-001 | 16대 잠금·중앙·현장 차단 | REQ-LOCK-001 | 회귀 후보 |
| TC-ERR-001 | CH05 오류와 중앙 제어 차단 | REQ-ERROR-001, REQ-LOG-001 | 회귀 후보 |
| TC-INT-002 | 선택 3대 HEAT 적용 | REQ-BATCH-001 | 비대상 불변 검증 보완 전 회귀 제외 |
| TC-TEMP-001 | 30°C 상한 초과 차단 | REQ-TEMP-001 | 회귀 후보 |
| TC-TEMP-002 | AUTO 18°C 하한 위반 분류 | GAP-AUTO-001 | 제품 회귀 제외 |
| TC-PIPE-001 | 알람 UI 기준 부족 | 해당 없음 | REQUIREMENT_REVIEW Fixture |
| TC-PIPE-002 | 시뮬레이터 미응답 | 해당 없음 | ENVIRONMENT_ISSUE Fixture |
| TC-PIPE-003 | 존재하지 않는 Locator | 해당 없음 | AUTOMATION_EXECUTION_ERROR Fixture |
| TC-PIPE-004 | 지원 밖 17번째 장비 | 해당 없음 | NOT_EXECUTED Fixture |

### 제한 사항

- TC-INT-002는 선택 3대만 확인하고 비대상 13대 불변을 검증하지 않습니다.
- TC-TEMP-002의 AUTO 18°C는 SRS 근거가 없으므로 제품 결함 증거로 사용하지 않습니다.
- TC-PIPE-001~004는 제품 PASS Rate에 포함하지 않습니다.
- 기존 결과의 `evidence_path`가 비어 있어 Screenshot·Trace 완전성을 주장하지 않습니다.

## 3. SRS Coverage

| Coverage | Requirement |
|---|---|
| EXISTING_TC | REQ-ENV-001, REQ-CONTROL-001, REQ-BATCH-001, REQ-MODE-001, REQ-MODE-002, REQ-TEMP-001, REQ-LOCK-001, REQ-ERROR-001, REQ-LOG-001, REQ-STATE-001 |
| PARTIAL | REQ-BATCH-002 |
| IMPLEMENTED_WITHOUT_DEDICATED_TC | REQ-SELECT-001, REQ-OVERVIEW-001, REQ-POWER-001, REQ-AUTH-001, REQ-TEMP-002, REQ-FAN-001, REQ-ERROR-002, REQ-GATEWAY-001, REQ-GATEWAY-002, REQ-LOCAL-001, REQ-LOCAL-002, REQ-REGISTER-001, REQ-PERSIST-001, REQ-RESET-001 |
| KNOWN_GAP | GAP-TEMP-001, GAP-AUTO-001, GAP-BATCH-001, GAP-LOCAL-001, GAP-GATE-001, GAP-EVIDENCE-001 |

이 표는 구현 존재와 테스트 통과를 구분합니다. 전용 TC가 없다고 미구현인 것은 아니며, 코드가 있다고 검증 완료인 것도 아닙니다.

## 4. V2 단계별 검증

### Agent 1·CP1

- 유효한 MODIFIED 요청에서 SRS before와 요청 after를 분리합니다.
- 없는 Requirement, before 불일치, after 누락과 현재 SRS·변경 요청 모두에 근거 없는 기능을 차단합니다.
- 변경 요청에 이미 명시된 정책을 SRS에 없다는 이유로 다시 묻는 결과는 CP1 REVIEW로 전환합니다.
- 알려진 GAP을 정상 정책으로 확정하면 REVIEW 또는 FAIL입니다.
- 서로 다른 요청 2건이 다른 변경 분석을 만들어야 합니다.

### Agent 2·CP2

- CP1 검증 범위만 TC로 설계합니다.
- 조건·Step·Expected Result·Requirement 근거를 검사합니다.
- 상태 변경은 가능한 경우 UI와 내부 상태 관찰을 포함합니다.
- 근거 없는 기대값과 기존 결함의 정상값 사용을 차단합니다.
- 의미상 중복과 간접 영향 충분성은 REVIEW로 표시하고 이 경우에만 사람 검토를 요청합니다.

### Agent 3·CP3

- TC의 핵심 Step과 Expected Result가 코드에 매핑되어야 합니다.
- Assertion 누락·약화, 기대값 변경, `assert True`, 무조건 skip과 예외 전체 무시를 차단합니다.
- 외부 URL·Shell·원본 수정은 BLOCKED입니다.
- 새 브라우저 Context에서 후보를 한 번 시험합니다.
- 문법·Locator·Wait·Fixture 기술 오류만 최대 1회 수정합니다.
- Snapshot/Restore와 결함 주입을 구현된 전제조건으로 사용하지 않습니다.

### Agent 4·CP4

- 현재 Run의 결과 수, 단일 Run ID, 중복 TC와 보고 수치를 검사합니다.
- 제품 기능 TC와 파이프라인 검증용 고정 사례를 분리합니다.
- 환경·자동화 오류를 제품 결함으로 확정하지 않습니다.
- 기존 의미 라벨이 포함된 failure_reason으로 분류 정확도를 주장하지 않습니다.

## 5. MVP End-to-End 시나리오

1. **명확한 변경**: A1→CP1→A2→CP2→A3→CP3→자동 실행→보고→정식 QA 자산 등록 승인
2. **없는 Requirement**: CP1 FAIL, 후속 미실행
3. **근거 없는 기대값**: CP2 FAIL 또는 REVIEW
4. **코드 의도 훼손**: CP3가 Assertion 누락·기대값 변경 탐지
5. **기술 오류**: 자동화 오류로 분류하고 최대 1회 기술 수정
6. **조건부 검토**: REVIEW 발생 시 후속 단계를 멈추고 PROCEED·REVISION_REQUIRED·REJECTED 후 재개 또는 종료
7. **정식 등록 반려**: Run 증거는 보존하되 기존 SRS·TC·Playwright 코드는 변경하지 않음

MVP에서는 위 7개 대표 시나리오면 충분합니다. 대규모 Benchmark와 반복 평가를 이번 프로젝트의 완료 조건으로 두지 않습니다.

## 6. Run 증거

- 원본 변경 요청
- 모델 원문과 정규화 JSON
- Checkpoint Rule별 결과와 Finding
- Agent 간 input_artifact_ids
- TC·코드 줄 매핑
- 시험 exit code·stdout·stderr
- 조건부 검토 결과(발생한 경우)
- 정식 QA 자산 등록 승인 결과
- 현재 Run 실행 결과
- 최종 보고 JSON

Screenshot·Trace는 UI 실패 분석에 필요할 때만 저장합니다. 저장하지 않은 증거가 존재한다고 표시하지 않습니다.

## 7. MVP 종료선

- Product SRS를 최초 실행의 초기 제품 기준 문서로 한 번 확정합니다.
- 다른 입력 2건이 다른 Agent 1·2 결과를 만듭니다.
- Agent 1 Artifact가 Agent 2 실제 입력으로 기록됩니다.
- 제품 기능 TC 1건이 코드 후보 1건으로 이어집니다.
- Agent 3가 실제 화면 근거로 Locator를 확인하고 코드 후보를 만듭니다.
- CP3와 격리 시험이 PASS이면 중간 승인 없이 제품 검증으로 이어집니다.
- REVIEW가 발생한 경우에만 조건부 검토와 중단 단계 재개가 기록됩니다.
- 기존 제품 기능 회귀 후보와 파이프라인 검증용 고정 사례를 분리 실행·집계합니다.
- TC→코드→결과→보고 추적이 유지됩니다.
- 정식 QA 자산 등록 승인 전 프로젝트 1 원본을 변경하지 않습니다.

## 8. MVP 이후 추가 여부를 다시 판단할 항목

1. 같은 요청 3회 반복 평가
2. 코드 후보 반복 안정성
3. 대표 결함 검출성
4. 질문 후 중단 단계 재개
5. ADDED·DELETED 지원
6. 정식 QA 자산 자동 등록·버전 갱신
7. Agent Evaluation Framework 연결

이 항목들은 MVP가 실제로 동작한 뒤 얻은 로그와 문제를 보고 추가합니다.
