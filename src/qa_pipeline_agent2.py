from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from qa_pipeline_io import *
from qa_pipeline_contracts import *
from qa_pipeline_agent1 import *


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = value.casefold()
    return any(term.casefold() in normalized for term in terms)

# ---------------------------------------------------------------------------
# Agent 2: 제품 기능 테스트케이스 설계
# ---------------------------------------------------------------------------
AGENT2_SYSTEM_INSTRUCTIONS = QA_EXPECTATION_SCOPE_GUIDANCE + QA_DESIGN_REVIEW_GUIDANCE + QA_HUMAN_JUDGMENT_EXAMPLES + """
당신은 CP1을 통과한 변경 분석을 제품 기능 테스트케이스 후보로 바꾸는 Agent 2입니다.

역할 경계:
- 무엇을 어떤 조건에서 검증할지 설계합니다. Playwright 코드, Selector, Python 코드나 자동화 구현은 작성하지 않습니다.
- 입력으로 제공된 기존 TC 카탈로그와 변경 조건을 먼저 대조합니다. 승인 TC 명세가 제공되면 검증 동작 요약뿐 아니라 사전조건·절차·기대결과·판정 시점·복원을 함께 대조합니다. 명세는 재사용 판단 근거이지 이번 실행 성공의 증거가 아니며, 제공되지 않은 절차나 실제 수행 여부를 추정하지 않습니다.
- test_cases에는 이번 변경으로 새로 필요하거나 기대 결과·절차가 달라져 수정이 필요한 변경 검증 후보만 작성합니다. 유지되는 기존 동작은 이번 범위에 맞는 기존 TC가 있으면 재사용하며, 재사용할 수 없다는 이유만으로 요청 밖 회귀 시험을 새로 만들지 않습니다.
- 출력은 사람의 마지막 승인 전 변경 검증용 제품 TC 후보와 영향받는 기존 회귀 선택입니다.

[코드가 확인하는 구조 규칙 — 요약] 아래는 Checkpoint 2가 자동으로 검사하므로 지키면 됩니다. 위반하면 반려되며, 검사를 피하려고 내용을 바꾸지 않습니다.
- 입력에 있는 Requirement·Condition ID만 사용하고, TC의 requirement_ids는 그 TC의 source_condition_ids가 근거를 가져야 하며 각 ER의 source_condition_ids는 TC의 source_condition_ids 안에 있어야 합니다(CP2-003·005). 관련 있어 보이는 번호를 추측해 추가하거나 불일치를 숨기려고 조건을 삭제하지 않습니다.
- 모든 confirmed_condition을 test_cases 또는 관련_기존_TC의 source_condition_ids 중 최소 한 곳에 반영합니다(CP2-004). existing_tc_comparison_completed=true로 기록합니다(CP2-016).
- 모든 실행 TC는 control_path=CENTRAL을 사용합니다. 현재 V2의 제품 조작 기준은 중앙 관제 패널 하나이며 LOCAL·현장 리모컨 TC, REQ-LOCAL-* 근거를 만들지 않습니다(CP2-008).
- 모든 새 TC는 state_effect를 분류합니다: 조회만 하면 READ_ONLY(restore_required=false, 빈 restore_steps), 값을 바꾸면 STATE_CHANGE, 변경 차단을 확인하면 BLOCKED_CHANGE(둘 다 restore_required=true). 차단 TC에는 알림뿐 아니라 요구된 차단 결과를 실제 대상 상태(UI 또는 내부값)로 확인하는 ER이 있어야 합니다(CP2-022).
- 모든 ER에 verify_after_step(실제 steps 문장 하나를 정확히 복사)과 observation_target을 적습니다(CP2-020). double_assert_policy=REQUIRED이면 UI와 INTERNAL_STATE ER을 모두 두고, UI_ONLY·INTERNAL_ONLY는 해당 계층만 둡니다(CP2-006).
- restoration 구조는 아래 [복원] 절을 따릅니다(CP2-023). execution_spec은 아래 실행 정의 절을 따릅니다(CP2-024).
- [코드로 확인한 SRS 개정 범위]의 required_requirement_ids에만 SRS 개정안을 한 건씩 작성합니다(CP2-018). 요청 원문 제외(out_of_scope)에 해당하는 조건을 기대결과 근거로 쓰지 않습니다(CP2-017).
값·의미·범위의 정확성은 코드가 아니라 별도 근거 검토가 원문과 대조합니다. 구조가 맞는다는 것이 의미가 맞다는 증거는 아닙니다.

[근거와 범위]
1. 검증된 변경 요청 원문, Agent 1의 confirmed_conditions와 고정된 SRS만 사실 근거로 사용합니다. 입력의 명시적 분류(제외 범위·절차 메모)는 Agent 1과 같이 따르며, 제품의 범위 밖 입력은 시험 조건이지 시험 제외가 아닙니다. 단어 하나만 보고 승인된 조건을 다시 분류하지 않습니다.
2. requirement_effects가 NO_IMPACT인 Requirement는 테스트 범위에 포함하지 않습니다. scope_evidence.basis 분류명과 Requirement 이름만으로 알림이나 UI/내부 검사를 추가하거나 생략하지 않습니다. 관련 SRS 전체를 새 검사로 확대하지 않고 요청된 조건의 대상·값·판정 의미를 보존하며, 실제 요청이 상태 일치나 알림을 요구하면 해당 검사는 반드시 포함합니다.
3. MODIFIED는 변경 동작 검증 후보, UPDATE_REQUIRED는 변경으로 기대 결과·절차 수정이 필요한 후보입니다. 대상 Requirement의 VERIFY는 기존 기준의 시험 요청이며 SRS를 개정하지 않습니다. 이 경우에도 기존 TC가 요청한 값·전환·관찰을 모두 검증하지 못하면 CHANGE_VALIDATION 후보를 작성합니다. 대상 외 VERIFY는 관련 기존 동작 회귀 선택이며 요청 밖 회귀 TC를 새로 만들지 않습니다.
3-1. 기존 TC 카탈로그의 `검증 동작`이 VERIFY·유지 조건 또는 변경 후 조건을 그대로 검증하고 TC 전체 실행이 이번 범위에 맞으면 관련_기존_TC로 선택합니다. Requirement ID만 같거나 일부 검사가 맞는다는 이유로 재사용하지 않습니다. 기존 TC는 전체 단위로 실행되므로 명시적 제외와 충돌하는 검사가 포함돼 있으면 선택하지 않고 미선택 이유를 coverage_notes에 기록합니다. 일부 검사만 실행했다고 가정하지 않으며 기존 assertion을 삭제하지 않습니다. 재사용할 수 없으면 요청된 변경분 후보가 실제로 확인하는 유지 기준도 함께 연결하되, 관련 없는 유지 조건을 연결하거나 유지 SRS 전체를 검증했다고 주장하지 않습니다. 기존 TC가 변경 후 조건을 전부 검증하면 test_cases를 비워 둘 수 있습니다. 동일 검사의 중복 생성은 금지합니다.
3-2. 변경 조건을 기존 TC만으로 검증할 때는 실제 요청한 대상·조작·기대값·시점과 허용/차단·활성/비활성 동작이 기존 TC의 검증 동작에 포함되는지 확인합니다. 같은 값이 있어도 매핑·순서·기대 동작이 다르면 동일 검증이 아닙니다. 문장에 등장한 과거·부정·제외 값을 추가 시험으로 요구하지 않습니다. 필요한 검사가 다르거나 확인할 수 없으면 부족한 변경분을 후보로 설계합니다.
3-3. 조건 하나를 여러 기존 TC가 나눠 검증하면 실제로 그 부분을 검증하는 모든 선택에 같은 조건 ID를 연결합니다. 다른 조건 때문에 선택한 TC로 커버리지를 추정하지 않습니다. 각 선택이 어떤 유지·영향 조건을 회귀 확인하는지 selection_reason으로 설명합니다.
3-4. 유지 SRS 조건은 제품 기준이며 그 전체가 이번 실행 범위라는 뜻은 아닙니다. 변경 요청의 대상·동작·확인값·명시적 제외를 기준으로 이번에 검증할 부분을 설계하고, 원문 인용의 모든 선택지·지원 값 전체·보조 근거의 전체 SRS를 시험했다고 주장하지 않습니다. 유지 조건이라는 이유로 이번 요청에 필요한 검사를 생략하지도 않으며, 후보와 기존 TC를 합친 실제 검사 범위만 설명합니다. 복합 조건이 이번 범위보다 넓으면 coverage_notes에 실제 확인한 부분과 참고만 한 부분을 구분합니다. 누락된 필수 시험을 보조 근거로 바꾸거나 명시 제외 밖 회귀 TC를 추가해 연결을 맞추지 않습니다. 필수 검사를 후보·기존 TC 어느 쪽에서도 다룰 수 없거나 제외·요청이 충돌하면 누락을 숨기지 말고 사람 확인 사항으로 남깁니다.
4. 기존 TC 전용 실행: test_cases가 비어 있고 관련_기존_TC만 있으면 준비·복원 메모를 넣기 위해 신규 TC를 만들지 않습니다. 실행기는 요청 원문의 시험 절차 메모를 마지막 사람 검토로 전달하며 기존 자동화가 그 메모를 수행했다고 추정하지 않습니다. 기존 절차 변경이 필요하면 수정 후보를 설계합니다.
5. test_cases는 이번에 필요한 새 시험, 관련_기존_TC는 이미 등록된 시험의 선택입니다. purpose는 설명용이며 이름으로 실제 검증 범위를 대신하지 않습니다. confirmed_condition을 여러 TC가 공유할 수 있지만 동일 목적의 TC를 표현만 바꿔 중복 생성하지 않습니다.
6. 신규·수정 후보가 필요하면 현재 단일 장비 MVP가 실행할 수 있도록 target_role=PRIMARY_TEST_DEVICE인 automation_candidate TC를 우선 설계합니다. target_role은 고정 장치 ID를 추측하지 않고 역할로 지정합니다. automation_candidate는 자동화 가능성 표시일 뿐 코드를 만들지 않으며, 안전한 읽기·복원 방법이 지원 범위에 없으면 false와 사유를 작성합니다. 요구된 새 기능이 제품에 아직 없다는 이유로 TC를 삭제하지 않습니다.
7. Agent 1의 excluded_scope와 `제외된_정보_부족`은 TC로 만들지 말고 `제외_범위`와 `제외된_정보_부족`에 원문 그대로 인계합니다. 제외 범위의 상태 유지 여부를 확인하는 기대 결과도 새로 만들지 않습니다.
8. 설명 필드 구분: 기대 동작을 바꾸지 않는 참고 사항(SRS 후속 개정, 정확한 안내 문구 미지정, 미선택 기존 TC 이유)은 coverage_notes에, 이미 확정됐지만 사람이 최종 보고에서 확인하면 좋은 사항은 `최종_확인_사항`(후속 실행을 막지 않음)에, 충돌하는 권한 입력·기대 결과 미정처럼 TC 의미를 확정할 수 없는 항목만 `중단_확인_사항`에 남깁니다. UPDATE_REQUIRED 자체는 정상 결과이므로 그것만으로 확인 사항을 만들지 않습니다. 설명 필드에 내부 분류명·정책 키나 코드 처리 과정을 풀어 쓰지 않고, 이미 작성한 절차·복원 규칙을 반복하지 않습니다. 추가 확인 사항이 없으면 빈 목록으로 둡니다.

[기대 결과]
9. 모든 기대 결과는 source_condition_ids로 제품 판정 근거를 연결하고, 근거에 없는 수치·시간·문구·UI 동작·알림·색상·버튼을 추가하지 않습니다. 각 ER은 자기 근거 조건의 코드·수치와 허용/차단·활성/비활성 정책을 보존합니다. 시험 입력값은 기대 출력의 근거가 아니며, 초기값 유지는 근거 조건이 유지를 요구할 때만 기대값이 됩니다. 요청된 상태를 다른 지원 상태로 바꾸지 않습니다. 근거 개수와 검증 사실 개수는 다릅니다. 근거 ID를 늘려 새 검사나 값을 만들지 않습니다.
10. 장비 선택 성공, 사전조건 준비 완료, 시험 종료 후 복원처럼 실행을 위한 절차는 preconditions·steps·restore_steps에만 두고 expected_results로 만들지 않습니다. Condition 원문에 없는 `선택하고 적용할 수 있다`, `클릭할 수 있다` 같은 실행 행동 성공 문장을 기대 결과로 만들지 않습니다. Condition 자체가 설정 가능·선택 가능 같은 제품 기능을 요구하면 버튼 활성 상태, 선택값 반영 또는 적용 뒤 상태처럼 실제로 판정할 관찰값으로 구체화합니다. TC 수준 Condition에 준비·복원 지시가 있어도 억지로 expected_results에 다시 넣지 않습니다.
11. 각 expected_result는 한 대상·한 판정 시점·한 observation_layer의 독립된 사실 하나만 담습니다. 화면 모드·화면 온도·대기값 반영·버튼 활성 상태처럼 다른 관찰값은 고유한 ER ID로 분리하되 모든 원래 요구를 보존합니다. 내부 장비 객체의 연관된 여러 필드는 하나의 INTERNAL_STATE 결과로 기록할 수 있습니다. ER 분리는 TC 분리를 뜻하지 않으며, 문장 부호로 기계적으로 나누지 않습니다.
12. 상태 변경 또는 차단을 검증하는 TC는 사용자 화면(UI)과 내부 상태(INTERNAL_STATE)를 함께 확인합니다(double_assert_policy=REQUIRED). 이중 검증은 동일 변경을 다른 계층에서 확인하는 원칙이지, 요청에 없는 화면 배지·선택 표시·잠금 표시를 추가하라는 뜻이 아닙니다. 변경된 버튼 disabled 상태가 UI 결과라면 내부 locked 같은 근거 상태와 짝지을 수 있습니다. 변경 요청·SRS에 `locked`, `mode`, `setTemp`처럼 내부 필드 식별자가 명시돼 있으면 INTERNAL_STATE 기대 결과에 그 식별자를 그대로 보존합니다. UI 전용·내부 전용·해당 없음은 UI_ONLY·INTERNAL_ONLY·NOT_APPLICABLE과 double_assert_reason으로 구분합니다.
13. 화면 조작 설명과 내부 데이터 값은 구분합니다. UI 기대결과에 내부 enum을 곧바로 화면 표시 문자열처럼 쓰지 않습니다. 미확인 표시명·색상은 coverage_notes에 구분합니다. 안내 표시 조건을 검증하는 TC는 NOTIFICATION 기대 결과를 포함하되, 정확한 Toast 문구가 입력에 없으면 문구를 만들어 일치 검증하지 않습니다.
14. common_qa_criteria·domain_qa_criteria·feature_requirement_ids는 선택적인 설명용 QA 분류입니다. 적용 기준이 분명할 때 기록하고 없으면 빈 배열을 허용하며, 분류를 채우려고 새 검사·기대값을 추가하지 않습니다. feature_requirement_ids를 기록하면 해당 TC의 Requirement ID만 사용합니다.
15. 근거 검토가 지적한 추가 주장은 제거·수정하되 원문에 있는 요구는 삭제하지 않습니다. 불확실하면 확인 필요로 남깁니다.

[절차 상세화]
16. 처음 보는 QA 담당자가 재현할 수 있는 상세 초안을 작성합니다. 입력 절차 원문은 Agent 1의 해시 검증된 기록에 보존되며, TC에는 그 의미와 순서를 보존하여 준비는 preconditions에, 본 시험은 steps에, 종료 후 복원은 restore_steps에 나눠 씁니다. 원문 한 문장을 통째로 steps에 복사하거나 문장 조각을 이어 붙이는 방식으로 상세 작성을 대신하지 않습니다. 별도 절차 검토가 입력 원문에서 역으로 누락·순서 변경·임의 추가를 확인합니다.
17. 사전조건에는 대상·초기 상태를, steps에는 화면/조작 위치·대상·입력값·행동을 구체적으로 적습니다. 대상 선택 → 값 선택/입력 → 적용처럼 실제로 다른 조작은 별도 배열 항목으로 나눕니다. 선택·입력과 적용을 한 문장에 합치지 않습니다. 조작 문장에 확인 내용을 붙이지 않습니다(H-4, 2026-10-18 사람 확정). 예: '제습을 적용하고 패널·카드·내부 모드를 확인한다'가 아니라 '제습 모드를 대상 장비에 적용한다'로 쓰고, 확인할 위치·값은 expected_results에 두어 verify_after_step이 그 조작 문장을 가리키게 합니다. 모든 클릭을 기계적으로 쪼개거나 모든 TC를 고정된 3단계로 만들지는 않으며, 읽기 전용 시험에는 불필요한 선택·적용을 만들지 않습니다.
18. 중앙 관제의 장비 값을 조작할 때는 대상 장비 선택을 값 선택/입력보다 앞의 별도 steps 항목에 씁니다. 입력에 이미 선택된 상태가 근거로 있으면 preconditions에 명시하고 재선택하지 않습니다. '대상 장비에 MED를 선택한다'는 풍량 선택이지 장비 선택이 아닙니다.
19. 입력창·버튼·클릭 횟수·화면 표시명·내부 필드명이 제공된 근거에 없으면 추정하지 않습니다. 입력창 근거가 없는데 '입력한다'고 단정하지 말고 대상·목표값·행동을 설명하며, 실제 조작 수단은 Agent 3의 화면 관찰로 확인합니다. 근거가 있으면 그 수단과 횟수를 구체적으로 적습니다.
20. 준비·조작 확인은 preconditions·steps에 기록하고 제품 판정인 expected_results와 구분합니다. 준비 확인과 복원 확인을 제품 expected_results로 늘려 검사 오류를 피하지 않습니다. 기존 승인 TC는 새 작성 형식에 맞추려고 덮어쓰거나 불필요하게 재생성하지 않습니다.
21. 각 TC는 이전 TC 결과에 의존하지 않고 단독 실행 가능해야 합니다. independent_execution=true로 선언하되 선언만으로 독립 실행이 입증되지는 않습니다. independence_reason은 선택 설명으로 null을 허용합니다. 필요한 초기 상태는 preconditions와 실행 정의로 직접 준비하고 확인합니다.

[판정 시점]
22. verify_after_step에는 그 결과를 확인해야 하는 steps 문장을 정확히 복사합니다. 확인만 하는 마지막 단계는 직전 조작 직후의 판정이며 별도 클릭을 뜻하지 않습니다. 같은 적용 동작을 반복하면 각 steps에 순번 또는 해당 조건을 넣어 서로 구별합니다. observation_target에는 '대상 장비 카드의 풍량 표시', '대상 장비의 내부 설정값'처럼 어디에서 확인하는지 적고, statement에도 확인 대상과 요구사항에 근거한 기대값·상태를 적습니다.
23. 같은 조작의 UI·내부 상태는 서로 다른 ER로 쓰되 같은 after_action_id에 연결합니다. 관찰 계층이 다르다는 이유만으로 동일 조작을 반복하거나 중간 복원을 넣지 않습니다. 별도의 적용 전 패널 확인은 적용 후 이중 확인과 함께 둘 수 있고, 관찰만 하는 문장이 나뉘어도 사이에 조작이 없다면 같은 after_action_id에 연결합니다. 근거가 있는 중간 판정만 단계에 연결합니다.

[조건 묶음]
24. 전원·운전 모드·풍량·온도·잠금 및 다른 관제점에 같은 원칙을 적용합니다: 요청한 목표 결과만 본 시험으로 확인하고, 그 시험을 위한 시작 상태 준비는 사전조건으로 분리합니다. 준비→목표 전환 하나는 SINGLE_FLOW입니다. 준비·복원을 빼도 본 시험 조건이 여러 개인지 먼저 확인합니다.
25. TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙입니다. 같은 관제점·제어 경로·업무 규칙이고 입력값이나 모드만 달라지면 하나의 TC로 묶어 중복을 줄입니다. 필수 경계 검사는 같은 범위 규칙의 TC 안에서 조건 구간으로 묶을 수 있으며, 범위 변경과 단일 값/전환 시험의 구분은 설계·검토 공통 기준을 따릅니다. 예시의 모드명·온도값을 고정 규칙으로 쓰지 않고 현재 입력의 Requirement와 confirmed_condition으로 판단합니다. 제출 전에 필수 조건별 실제 조작·관찰을 대조하고, 조건 ID 연결만으로 검사 완료로 취급하지 않습니다.
26. condition_execution은 본 시험의 판정 구간 수입니다. 요청이 여러 중간 결과 자체를 순서대로 확인하도록 요구하면 SEQUENTIAL_TRANSITION, 여러 독립 조건을 각각 초기화해 시험하면 INDEPENDENT_VARIANTS입니다. 준비 상태와 목표 상태가 다르다는 이유만으로 SEQUENTIAL_TRANSITION을 선택하지 않습니다. 묶음 TC의 각 조건은 steps와 expected_results에서 구분하고, 조건별 실행 직후 판정 위치를 명시하며, 모든 결과를 마지막 상태에서 한꺼번에 확인하지 않습니다.
27. 독립 조건 사이에 필요한 초기화·재준비는 steps와 execution_spec에 연결합니다. intermediate_reset_steps는 선택 색인이며 작성하면 해당 steps 원문을 참조합니다. grouping_reason도 선택 설명이며, 묶음의 적절성은 실제 조작·중간 확인·초기화가 요청과 맞는지로 판단합니다.
28. 실제 입력값과 조작 순서는 execution_spec에 작성합니다. initial/requested 모드·온도 필드와 requested_modes·requested_temperatures_c는 선택 요약이며, 작성할 경우 해당 관제점 값만 쓰고 다른 관제점 값을 넣거나 실행 정의와 모순되게 쓰지 않습니다. 증가/감소 같은 상대 조작은 버튼과 순서만 명시하고, 결과로 유지돼야 할 값을 requested 값으로 만들지 않습니다(명시적 입력이 없으면 null·빈 배열). 준비·중간 초기화·최종 복원에만 쓰는 값은 requested 값에 섞지 않습니다. 준비·입력·기대값은 서로 구분합니다.

[복원]
29. 새 TC는 restoration을 작성합니다(READ_ONLY는 operation_steps·confirmations가 빈 목록이고 verify_when=AFTER_RESTORE). 중앙 관제 전원·모드·풍량·온도·잠금은 같은 순서를 따릅니다: 준비 전 관련 화면·내부값 기록 → 명시된 사전조건 준비·확인 → 시험 → 준비와 시험으로 바뀐 관제점을 준비 전 관찰 상태로 복원·확인. 준비 도중 실패해도, 차단 시험이어도 준비로 바꾼 값은 되돌립니다. 이 공통 조작은 Agent 3의 RESTORE_OBSERVED_CONTROLLER로 구현하며 새 필드나 기능별 예외를 만들지 않습니다.
30. restoration.operation_steps에는 복원 조작 문장을, confirmations에는 사람이 읽는 확인 문장을 적고, operation_steps 다음 각 confirmation.source_text를 이어 붙인 결과가 restore_steps와 순서·내용 모두 같아야 합니다. NOTIFICATION이 아닌 ER마다 result_id를 confirmations 전체에서 정확히 한 번 연결하고, 각 comparison은 확인 문장 전체를 source_excerpt로 복사하며 basis=OBSERVED_BASELINE입니다. 같은 대상·기준을 확인하는 경우에만 하나의 confirmation에 여러 result_id를 묶습니다. execution_spec(controller-map-1.0)이 있는 TC에서 준비에서 확인한 관제점 중 시험 ER이 없는 것(예: 온도 TC의 준비에서 바꾼 모드 internal.mode)은 precondition_verifications의 번호(0부터)를 precondition_indexes에 넣은 별도 confirmation으로 준비 전 기록값과 비교하는 확인 문장을 씁니다(result_ids·comparisons는 빈 목록). ER이 있는 대상은 precondition_indexes로 중복 연결하지 않습니다.
31. 복원 확인은 기존 ER의 같은 관찰 위치(화면·내부값 각각)를 준비 전 실제 기록값과 비교합니다. 내부 코드와 화면 표시가 같다고 가정하지 않고, 임의 기본값·고정 초기값으로 초기화하거나 initial_mode·initial_temperature_c를 복원 목표로 쓰지 않습니다(그것은 준비 완료 상태입니다). 원문에 명시된 준비값은 사전조건 준비·확인에만 사용하며 복원 목표와 혼동하지 않습니다. 확인 문장은 대상과 비교 방법을 한 구절에 완결하고 '복원한다', '결과를 확인한다'로 끝내지 않습니다. 확인 문장에 추가 조작이나 제품 기대결과를 넣지 않으며, 복원 실패를 제품 기대 결과로 추가하지 않습니다. 다른 기능·다중 장비의 준비와 복원은 추정하지 않습니다.

[SRS 개정안]
32. [코드로 확인한 SRS 개정 범위]의 required_requirement_ids에만 `SRS_개정_제안`을 정확히 한 건씩 기록합니다. 검토된 VERIFY 대상은 기존 기준 시험이므로 개정안을 만들지 않습니다. MODIFIED·UPDATE_REQUIRED의 개정안은 실제 정책 변경에만 필요하며 기존 정책을 시험 시나리오 한 건으로 대체하지 않습니다. already_reflected_requirement_ids는 요청 after_value 전체 문장과 현재 인수 기준이 일치한 대상이므로 개정안 없이 시험 설계를 계속하고, 이미 반영돼 개정이 불필요하다는 사실만 coverage_notes에 적습니다.
33. current_acceptance_criteria는 응답에 작성하지 않습니다(프로그램이 고정 SRS 원문을 붙입니다). proposed_acceptance_criteria는 해당 Requirement의 인수 기준 셀 전체를 대체하는 문구입니다: 요청으로 바뀌지 않은 기존 기준은 보존하고 바뀌는 부분만 확정 Condition·변경 요청에 근거한 수치로 교체하며, 새 한계·요청 밖 내용·표현만 바꾼 개정을 만들지 않습니다. Requirement 문장 자체는 바꾸지 않고, source_condition_ids로 근거를 연결하며, 사람이 승인하기 전 SRS가 변경된 것처럼 표현하지 않습니다.

작성 수준 예시 (아래는 기존 필드의 일부만 발췌한 형식 참고이며 이번 입력의 제품 기준이 아닙니다):
예시 A의 입력이 '오류·잠금 없는 단일 장비, 초기 LOW, MED 적용 직후 카드 중풍·내부 fanSpeed=MED'를 명시한 경우:
preconditions:
- 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.
- 대상 장비의 풍량이 LOW인지 확인한 뒤 시험을 시작합니다.
steps:
1. 중앙 관제 화면에서 시험할 대상 장비 카드를 선택한다.
2. 선택한 장비의 제어 패널에서 풍량을 MED로 선택한다.
3. 제어 패널의 적용 버튼을 눌러 선택한 풍량을 대상 장비에 적용한다.
expected_results:
- ER-001: 대상 장비 카드의 풍량 표시에 중풍이 표시된다. observation_target='대상 장비 카드의 풍량 표시', observation_layer=UI.
- ER-002: 대상 장비의 내부 fanSpeed는 MED이다. observation_target='대상 장비의 내부 fanSpeed', observation_layer=INTERNAL_STATE.
두 결과의 verify_after_step에는 3번 문장을 번호 없이 정확히 복사하고 각 source_condition_ids는 이번 입력의 해당 제품 조건에 연결합니다.
restore_steps(= restoration 조작 + 확인):
- 준비와 시험으로 바뀐 관제점을 준비 전 관찰한 원래 상태로 복원하고 적용한다.
- 대상 장비 카드의 풍량 표시를 준비 전 관찰값과 비교한다. (ER-001, OBSERVED_BASELINE)
- 대상 장비의 내부 fanSpeed를 준비 전 관찰값과 비교한다. (ER-002, OBSERVED_BASELINE)
대상 선택 성공·알림·선택 색상·LOW의 한글 표시를 새 expected_results로 만들지 않습니다. HIGH 유지 조건을 검증하는 승인 TC가 있다면 관련_기존_TC로 재사용합니다.
예시 B: 입력이 '초기 설정 온도 24°C, 30°C 적용 후 카드·내부 설정 온도 30°C'를 요구하면 대상 선택 → 설정 온도를 30°C로 조절 → 적용으로 작성합니다. 입력창이 명시된 경우만 '30°C를 입력한다', 1회당 1°C인 증가 버튼과 현재 24°C가 근거로 제공된 경우만 '증가 버튼을 6회 누른다'고 구체화합니다. 조작 수단이 없는 입력에서 버튼·횟수를 추정하지 않습니다. 적용 직후 카드 설정 온도와 내부 설정 온도를 각각 확인하고, 복원은 예시 A와 같이 준비 전 관찰값과 비교합니다. 준비에서 모드를 바꿨다면 시험 결과 항목이 없는 모드도 복원 확인 문장을 쓰고 precondition_indexes로 그 준비 확인에 연결합니다. 예시 A의 풍량·MED·LOW·문구를 복사하지 않습니다.
예시 C: 입력이 현재 상태를 조회하는 읽기 전용 시험이면 조회 단계와 그 단계의 기대결과만 작성합니다. 대상 선택이 실제로 필요한 경우만 기록하며 값 입력·적용·복원을 억지로 추가하지 않습니다.
세 예시는 상세한 작성 방식만 보여줍니다. 값·화면명·필드명·조건 ID·초기 상태는 반드시 현재 입력에서 가져오며, 예시를 근거로 제품 판정이나 시험 범위를 추가하지 않습니다.
""".strip()


AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_EXECUTION_CONTRACT
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_REVIEW_RESPONSIBILITIES
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_TASK_BOUNDARIES
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_RANGE_CHANGE_RULES
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_CONFIRMED_RULES
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_TC_REVISION_RULE
AGENT2_SYSTEM_INSTRUCTIONS += "\n" + QA_LANGUAGE_RULE


class Agent2Error(RuntimeError):
    """Raised when Agent 2 cannot produce a validated structured response."""


def _existing_reuse_link_context(
    analysis: Agent1Analysis,
    existing_catalog: tuple[ExistingRegressionSpec, ...],
    design: Agent2TestDesign | None = None,
    *, include_value_tokens: bool = True,
) -> list[dict[str, Any]]:
    """Read-only value/link diagnostics, not semantic approval or auto-linking."""
    catalog = {item.tc_id: item for item in existing_catalog}
    rows = []
    for condition in analysis.confirmed_conditions:
        row: dict[str, Any] = {
            "condition_id": condition.condition_id,
            "condition": condition.statement,
        }
        if include_value_tokens:
            values = _explicit_behavior_values(condition.statement)
            row["detected_values"] = sorted(values)
        if design is not None:
            linked = [item.tc_id for item in design.related_existing_tests
                      if condition.condition_id in item.source_condition_ids]
            behaviors = " ".join(
                behavior for tc_id in linked if tc_id in catalog
                for behavior in catalog[tc_id].covered_behaviors
            )
            row.update(
                linked_existing_tc_ids=linked,
                candidate_tc_ids=[tc.tc_id for tc in design.test_cases
                                  if condition.condition_id in tc.source_condition_ids],
            )
            if include_value_tokens:
                row["values_not_covered_by_links"] = sorted(values - _explicit_behavior_values(behaviors))
        rows.append(row)
    return rows


def _srs_revision_policy(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    requirements: dict[str, SrsRequirement],
) -> dict[str, Any]:
    """Revision scope from reviewed requirement relations and exact baseline.

    VERIFY does not propose policy changes. For affected policy requirements,
    only the target's complete requested after-value can prove it is already in
    the frozen SRS. No fuzzy matching, case folding, or TC-reuse inference.
    Other affected requirements still need proposals.
    """
    affected = {
        effect.requirement_id
        for effect in analysis.requirement_effects
        if effect.relation in {RequirementRelation.MODIFIED, RequirementRelation.UPDATE_REQUIRED}
    }
    target = requirements.get(request.target_requirement_id)
    reflected: set[str] = set()
    if (
        target is not None
        and request.target_requirement_id in affected
        and request.after_value.strip() == target.acceptance_criteria.strip()
    ):
        reflected.add(request.target_requirement_id)
    return {
        "required_requirement_ids": sorted(affected - reflected),
        "already_reflected_requirement_ids": sorted(reflected),
        "comparison": "TARGET_FULL_AFTER_VALUE_EQUALS_CURRENT_SRS_TRIM_ONLY",
    }


@dataclass(frozen=True)
class Agent2Response:
    design: Agent2TestDesign
    response_id: str | None
    model: str
    usage: dict[str, int | None]
    raw_model_output: dict[str, Any] | None = None
    srs_source_attachments: list[dict[str, str]] | None = None


AGENT2_SYSTEM_INSTRUCTIONS += """
새 TC에는 execution_spec을 함께 작성합니다. 이는 별도 시험이 아니라 같은 상세 TC의
기계 판독용 조작·확인 정의입니다. Agent 3는 공통 연결표로 위치를 선택하며 AI로 재해석하지 않습니다.
binding_contract는 controller-map-1.0입니다. target에는 아래의 정확한 논리 항목명을 씁니다.
DOM selector나 Python은 작성하지 않습니다. operations는 준비/시험/복원 순서대로,
source_text는 해당 preconditions/steps/restore_steps 원문을 참조합니다.
조작 ID는 ACT-001 형식입니다. 조작 target과 action_type은 다음 짝을 사용합니다:
device.select=SELECT_DEVICE, temperature.set=SET_TEMPERATURE, command.apply=APPLY_COMMANDS,
controller.restore=RESTORE_OBSERVED_CONTROLLER, mode.auto/cool/heat/fan/dry=SET_MODE.
status.operation/stop, fanSpeed.low/med/high/auto, locked.on/off,
temperature.increase/decrease는 CLICK입니다. SET_MODE/SET_TEMPERATURE만 value를 쓰고 나머지는 null입니다.
한 절차에 선택·입력·적용이 있으면 각각의 조작으로 나누되
순서와 원래 입력값을 유지합니다. 클릭 대상은 해당 TC 원문에 분명히 적습니다.
verifications는 ER마다 정확히 하나이며, 같은 result_id·observation_layer와 실제 기대값을
담습니다. after_action_id는 그 ER을 확인할 시점 이전의 마지막 TEST 조작입니다.
입력값과 기대값은 다를 수 있습니다. 예: 범위를 벗어난 입력을 시도하고 허용된 결과를 확인합니다.
관찰만 하는 steps는 해당 ER로 연결하고 불필요한 클릭을 만들지 않습니다.
precondition_verifications는 명시된 시작 상태만 확인합니다. 값 기록 지시는 실행기의
자동 스냅샷을 사용하며 고정 초기값·새 사전조건으로 바꾸지 않습니다.
사용 가능한 조작/reader는 구조화 응답 스키마의 공통 실행 수단입니다. UI_TEMPERATURE와
INTERNAL_SET_TEMP는 expected_number, UI_TEXT_CONTAINS는 expected_text,
UI_VALUE_EQUALS/UI_CHECKED_EQUALS/UI_ENABLED_EQUALS/INTERNAL_VALUE_EQUALS는 expected_value,
CONTROLLER_UI_FIELDS_EQUALS/INTERNAL_DEVICE_FIELDS_EQUALS는 expected_fields를 사용합니다.
그 외 기대값 필드는 비웁니다. 고정 비교 전략은 기대값을 생략해도 되며,
DISABLED_TEMPERATURE_TEXT의 expected_text에 동일한 "---"를 명시해도 됩니다.
고정 비교값과 다른 값은 허용하지 않습니다. 조작 target, verifications.target과 strategy,
준비 확인 observation_target과 read_kind는 입력의 [실행 연결표의 정확한 항목 목록]에서
해당 조합을 그대로 선택합니다. 항목 이름을 축약·확장·번역하거나 접두사를 추가하지 않습니다.
목록은 실행기 연결표에서 직접 가져오며 제품 기대값이나 필수 시험 범위를 뜻하지 않습니다.
필드 비교는 해당 target의 한 필드만 expected_fields에 넣습니다.
장비 카드와 제어패널을 바꿔 연결하지 않으며 ER.observation_target 설명에도 같은 대상을 명시합니다.
공통 제어값 reader는 status OPERATION/STOP, mode COOL/HEAT/FAN/DRY/AUTO,
fanSpeed LOW/MED/HIGH/AUTO, locked boolean, setTemp number를 사용합니다.
화면 표시명의 의미를 동일 코드로 표현하되 새 기대값은 만들지 않습니다.
준비 확인도 목록에 있는 정확한 observation_target과 read_kind를 사용합니다.
같은 복합 사전조건을 인용하는 확인들도 대상을 각각 명시합니다.
현재 없는 기능도 요청에 근거한 TC는 작성할 수 있습니다. 실행 가능 여부는 다음 단계의
실제 UI 관찰로 판단하며, 비슷한 기존 기능으로 대체하지 않습니다. 연결표에 없는 항목은
unsupported.<요청 항목명>으로 보존하세요. 기존 AUTO 모드 등으로 치환하지 않습니다.
복원은 기존 restoration과 같은 조작만 연결합니다. 공통 관제점 복원은
RESTORE_OBSERVED_CONTROLLER, value=null이며 별도 제품 기대결과를 추가하지 않습니다.
"""


class OpenAIAgent2:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent2Error(
                    "OPENAI_API_KEY 환경변수가 없습니다. 키를 코드에 넣지 말고 "
                    "PowerShell 환경변수로 설정하세요."
                )
            client = OpenAI(max_retries=0)
        self.client = client

    def design(
        self,
        request: ChangeRequest,
        analysis: Agent1Analysis,
        requirements: dict[str, SrsRequirement],
        *,
        existing_catalog: tuple[ExistingRegressionSpec, ...] = EXISTING_REGRESSION_CATALOG,
        previous_design: Agent2TestDesign | None = None,
        checkpoint_feedback: list[str] | None = None,
        required_checklist: str | None = None,
    ) -> Agent2Response:
        procedure_notes = list(analysis.procedure_notes)
        # Import at call time: Agent 3 imports Agent 2 for the existing role boundary.
        # Project exact logical keys/types only; do not send selectors or local paths.
        from qa_pipeline_agent3 import controller_connection_catalog
        catalog = controller_connection_catalog()
        connection_options = {
            "actions": {key: value[0] for key, value in catalog["actions"].items()},
            "readers": {key: list(value) for key, value in catalog["readers"].items()},
            "preconditions": {key: value[0] for key, value in catalog["preconditions"].items()},
            "temperature_interface": "이 제품의 온도 조작은 입력칸이 아니라 증가·감소 버튼과 표시창입니다. "
                "버튼별 활성/비활성은 temperature.increase/decrease의 UI_ENABLED_EQUALS로 확인합니다. "
                "temperature.display는 온도 표시이며 활성 상태를 검사하는 입력칸이 아닙니다. "
                "필요한 버튼 상태와 표시의 기대값·확인 시점은 요청/SRS를 따르며 서로 대신하지 않습니다.",
        }
        rendered_procedure_notes = (
            "\n".join(f"- {note}" for note in procedure_notes) or "없음"
        )
        user_input = (
            "[검증된 변경 요청 원문]\n"
            f"{request.model_dump_json(indent=2)}\n\n"
            "[시험 절차 메모]\n"
            f"{rendered_procedure_notes}\n\n"
            "[CP1 통과 Agent 1 분석]\n"
            f"{analysis.model_dump_json(indent=2, by_alias=True)}\n\n"
            "[고정된 SRS Requirement]\n"
            f"{render_srs_context(requirements)}\n\n"
            "[코드로 확인한 SRS 개정 범위]\n"
            f"{json.dumps(_srs_revision_policy(request, analysis, requirements), ensure_ascii=False)}\n\n"
            "[기존 사람 작성·자동화 TC 카탈로그]\n"
            f"{render_existing_regression_context(existing_catalog)}\n\n"
            "[조건별 기존 TC 연결 점검]\n"
            f"{json.dumps(_existing_reuse_link_context(analysis, existing_catalog, previous_design, include_value_tokens=False), ensure_ascii=False)}\n"
            "복합 조건을 여러 기존 TC가 나누어 검증하면 실제 담당 TC 모두의 source_condition_ids에 "
            "그 조건 ID를 넣으세요. TC 선택 목록에 있다는 이유만으로 그 조건을 검증한 것으로 계산하지 않습니다. "
            "형식 예시: 조건 C가 동작 A와 B를 요구하고 TC-X가 A, TC-Y가 B를 검증하면 "
            "TC-X와 TC-Y 모두 C에 연결합니다. 별도 B 전용 조건에 TC-Y를 연결한 것만으로 C가 충족되지는 않습니다. "
            "C·A·B·TC-X·TC-Y는 형식 설명이며 출력에 복사하지 마세요. "
            "위 목록은 원문 조건과 기존 연결 진단이며 권장 TC 목록이나 합격 판정이 아닙니다. "
            "과거·부정·제외 값의 등장만으로 누락된 검사를 추정하지 마세요. 값만 같고 대상·조작·판정·복원이 다르면 재사용하지 마세요. "
            "신규 후보가 담당하는 조건은 후보의 실제 근거도 함께 대조하세요. "
            "제출 전 복합 조건과 개별 조건을 각각 역으로 따라가 담당 TC 및 검증 범위가 빠짐없이 연결되는지 확인하세요. "
            "연결을 맞추려고 원문 조건·값을 삭제하거나 무관한 TC를 추가하지 마세요. "
            "기존 TC로 실제 검증하지 못하는 동작은 근거 있는 후보 설계 또는 확인 필요 사항으로 남깁니다."
            "새 실행은 설명의 동의어·문체를 실패로 판정하지 않습니다. 상세 작성 예시는 유지하되 "
            "출처 ID, 확인 대상, 판정 단계, 기대값과 복원 연결을 보존하세요. "
            "procedure_notes의 각 원문 의미·순서를 사전조건·조작·복원에 상세하게 반영하며 원문은 분석 기록에서 대조합니다. "
            "기존 TC만 재사용할 때는 해당 절차의 실제 수행 여부를 최종 검토로 남깁니다."
        )
        if required_checklist:
            # range_checklist_contract 1.0 (2026-10-17): computed by code from the CP1 conditions.
            user_input += (
                "\n\n[코드가 계산한 필수 확인 목록 — 모두 포함해야 CP2를 통과합니다]\n"
                f"{required_checklist}\n"
                "각 적용·차단 항목은 TEST 단계 조작과 같은 조작 직후의 패널·카드·내부 setTemp 기대결과로 작성합니다. "
                "질문 항목은 실행을 멈추는 중단_확인_사항이 아니라 최종_확인_사항에 질문 문장으로 남기고, "
                "질문 대상 동작의 기대값은 만들지 않습니다. 나머지 시험은 그대로 설계합니다."
            )
        user_input += (
            "\n\n[실행 연결표의 정확한 항목 목록]\n"
            f"{json.dumps(connection_options, ensure_ascii=False, indent=2)}\n"
            "\n\n[공통 확인 대상·시점·복원 연결 규칙]\n"
            f"{json.dumps(TC_OBSERVATION_BINDING_RULES, ensure_ascii=False)}\n"
            "\n[대상 선택·원래값 기록 순서]\n"
            f"{QA_CONTROLLER_BASELINE_GUIDANCE}\n"
        )
        if previous_design is not None:
            user_input += "\n[검사기에서 계산한 TC별 연결 오류]\n" + json.dumps([
                {"tc_id": tc.tc_id,
                 "errors": [*_tc_observation_binding_errors(tc),
                            *_tc_restore_basis_errors(tc)]}
                for tc in previous_design.test_cases
            ], ensure_ascii=False)
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 TC 후보]\n"
                f"{previous_design.model_dump_json(indent=2, by_alias=True)}\n\n"
                "[Checkpoint 2 전체 판정과 재작업 요청]\n"
                f"{feedback}\n"
                "근거와 검증 목적은 바꾸지 말고 실패한 품질 기준만 수정하세요. "
                "PASS인 규칙과 그 근거를 보존하고 새 FAIL을 만들지 마세요. "
                "수정 대상 TC만 반환하지 말고 이전의 전체 test_cases와 관련_기존_TC를 완전한 결과로 반환하세요. "
                "Checkpoint가 삭제를 요구하지 않은 변경분 후보와 기존 TC 선택은 제거하지 마세요. "
                "Playwright 코드는 작성하지 마세요."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                prompt_cache_key="qa-v2-agent2-2-62-rules-6",
                input=[
                    {"role": "system", "content": AGENT2_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent2TransportDesign,
            )
        except Exception as exc:
            raise Agent2Error(f"Agent 2 모델 호출에 실패했습니다 ({type(exc).__name__}). 외부 오류 본문은 저장하지 않습니다.") from None

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent2Error("모델이 구조화된 Agent 2 결과를 반환하지 않았습니다.")
        raw_output = parsed.model_dump(mode="json", by_alias=True)
        design, attachments = materialize_srs_revision_sources(parsed, requirements)
        return Agent2Response(
            design=design,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
            raw_model_output=raw_output,
            srs_source_attachments=attachments,
        )



def _normalize_restoration_layout(tc: ProductTestCaseCandidate) -> list[dict[str, str]]:
    """Canonicalize confirmation layout, not actions, readers or baseline meaning.

    All confirmations run AFTER_RESTORE. Grouping identical prose and ordering
    comparisons by their explicit IDs preserves every (ER, excerpt, basis) link.
    Malformed inputs are left intact for CP2; never repair missing/duplicate IDs.
    Only the new-generation boundary calls this, not historical run loading.
    """
    contract = tc.restoration
    if (contract is None or not tc.restore_required
            or contract.verify_when != RestoreVerificationTiming.AFTER_RESTORE):
        return []
    sources = [c.source_text for c in contract.confirmations]
    results = {r.result_id: r for r in tc.expected_results}
    required = {r.result_id for r in tc.expected_results
                if r.observation_layer != ObservationLayer.NOTIFICATION}
    if (len(results) != len(tc.expected_results)
            or not contract.operation_steps or not sources
            or len(set(contract.operation_steps)) != len(contract.operation_steps)
            or set(contract.operation_steps) & set(sources)
            or contract.operation_steps + sources != tc.restore_steps):
        return []
    linked = [rid for c in contract.confirmations for rid in c.result_ids]
    if not required or set(linked) != required or len(linked) != len(set(linked)):
        return []
    for c in contract.confirmations:
        ids = [comparison.result_id for comparison in c.comparisons]
        if (len(ids) != len(set(ids)) or set(ids) != set(c.result_ids)
                or any(not results[rid].observation_target for rid in c.result_ids)
                or any(comparison.basis != RestoreComparisonBasis.OBSERVED_BASELINE
                       or comparison.source_excerpt != c.source_text for comparison in c.comparisons)):
            return []
    before = {"restoration": contract.model_dump(mode="json"), "restore_steps": list(tc.restore_steps)}
    grouped = {}
    for c in contract.confirmations:
        item = c.model_copy(deep=True)
        by_id = {comparison.result_id: comparison for comparison in item.comparisons}
        item.comparisons = [by_id[rid] for rid in item.result_ids]
        if item.source_text in grouped:
            grouped[item.source_text].result_ids.extend(item.result_ids)
            grouped[item.source_text].comparisons.extend(item.comparisons)
            grouped[item.source_text].precondition_indexes.extend(item.precondition_indexes)
        else:
            grouped[item.source_text] = item
    contract.confirmations = list(grouped.values())
    tc.restore_steps = contract.operation_steps + [c.source_text for c in contract.confirmations]
    after = {"restoration": contract.model_dump(mode="json"), "restore_steps": list(tc.restore_steps)}
    if before == after:
        return []
    return [{"field": f"{tc.tc_id}.restoration_layout",
             "before": json.dumps(before, ensure_ascii=False),
             "after": json.dumps(after, ensure_ascii=False)}]

def _normalize_agent2_live_design(
    design: Agent2TestDesign,
) -> tuple[Agent2TestDesign, list[dict[str, str]]]:
    """Canonicalize technical references and restoration layout, never meaning.

    Only new generation uses this. The caller records the untouched model
    output and every edit before reviewing the normalized candidate.
    """
    candidate = design.model_copy(deep=True)
    changes: list[dict[str, str]] = []

    def reference(obj, field, sources, path):
        value = getattr(obj, field)
        if value is None or value in sources:
            return
        matches = [source for source in sources
                   if " ".join(source.split()) == " ".join(value.split())]
        if len(matches) == 1:
            setattr(obj, field, matches[0])
            changes.append({"field": path, "before": value, "after": matches[0]})

    for tc in candidate.test_cases:
        for result in tc.expected_results:
            reference(result, "verify_after_step", tc.steps,
                      f"{tc.tc_id}/{result.result_id}.verify_after_step")
        if tc.execution_spec is not None:
            sources = {AutomationPhase.PRECONDITION: tc.preconditions,
                       AutomationPhase.TEST: tc.steps,
                       AutomationPhase.RESTORE: tc.restore_steps}
            for op in tc.execution_spec.operations:
                reference(op, "source_text", sources[op.phase],
                          f"{tc.tc_id}/{op.action_id}.source_text")
            for index, check in enumerate(tc.execution_spec.precondition_verifications):
                reference(check, "source_text", tc.preconditions,
                          f"{tc.tc_id}/precondition[{index}].source_text")
    for tc in candidate.test_cases:
        changes.extend(_normalize_restoration_layout(tc))
    candidate, id_changes = _normalize_agent2_technical_ids(candidate)
    return candidate, changes + id_changes


def _normalize_agent2_technical_ids(
    design: Agent2TestDesign,
) -> tuple[Agent2TestDesign, list[dict[str, str]]]:
    """Fix only duplicate technical IDs; never alter TC meaning or expected values."""

    tc_ids = [test_case.tc_id for test_case in design.test_cases]
    result_ids = [
        result.result_id
        for test_case in design.test_cases
        for result in test_case.expected_results
    ]
    normalize_tc_ids = len(tc_ids) != len(set(tc_ids))
    normalize_result_ids = len(result_ids) != len(set(result_ids))
    if not normalize_tc_ids and not normalize_result_ids:
        return design, []
    if any(tc.execution_spec is not None and (
            len({r.result_id for r in tc.expected_results}) != len(tc.expected_results)
            or any(v.result_id not in {r.result_id for r in tc.expected_results}
                   for v in tc.execution_spec.verifications)) for tc in design.test_cases):
        return design, []
    if any(tc.restoration is not None and len({r.result_id for r in tc.expected_results}) != len(tc.expected_results)
           for tc in design.test_cases):
        # An ambiguous local ER reference cannot be repaired by renumbering.
        return design, []
    if any(tc.restoration is not None and any(
            rid not in {r.result_id for r in tc.expected_results}
            for confirmation in tc.restoration.confirmations
            for rid in [*confirmation.result_ids, *(c.result_id for c in confirmation.comparisons)])
           for tc in design.test_cases):
        # A dangling reference must not accidentally become valid when a new
        # number happens to equal the previously unknown ID.
        return design, []

    changes: list[dict[str, str]] = []
    result_number = 1
    normalized_cases: list[ProductTestCaseCandidate] = []
    for case_number, test_case in enumerate(design.test_cases, start=1):
        case_update: dict[str, Any] = {}
        if normalize_tc_ids:
            normalized_tc_id = f"TC-CAND-{case_number:03d}"
            if test_case.tc_id != normalized_tc_id:
                changes.append(
                    {
                        "field": "tc_id",
                        "before": test_case.tc_id,
                        "after": normalized_tc_id,
                    }
                )
            case_update["tc_id"] = normalized_tc_id
        if normalize_result_ids:
            normalized_results: list[ExpectedResult] = []
            result_mapping = {}
            for result in test_case.expected_results:
                normalized_result_id = f"ER-{result_number:03d}"
                result_number += 1
                if result.result_id != normalized_result_id:
                    changes.append(
                        {
                            "field": "result_id",
                            "before": result.result_id,
                            "after": normalized_result_id,
                        }
                    )
                normalized_results.append(
                    result.model_copy(update={"result_id": normalized_result_id})
                )
                result_mapping[result.result_id] = normalized_result_id
            case_update["expected_results"] = normalized_results
            if test_case.execution_spec is not None:
                spec = test_case.execution_spec.model_copy(deep=True)
                for verification in spec.verifications:
                    verification.result_id = result_mapping[verification.result_id]
                case_update["execution_spec"] = spec
            if test_case.restoration is not None:
                restoration = test_case.restoration.model_copy(deep=True)
                for confirmation in restoration.confirmations:
                    confirmation.result_ids = [result_mapping.get(rid, rid) for rid in confirmation.result_ids]
                    for comparison in confirmation.comparisons:
                        comparison.result_id = result_mapping.get(comparison.result_id, comparison.result_id)
                case_update["restoration"] = restoration
        normalized_cases.append(test_case.model_copy(update=case_update))
    return design.model_copy(update={"test_cases": normalized_cases}), changes


# ---------------------------------------------------------------------------
# Checkpoint 2: 테스트케이스 품질 검증
# ---------------------------------------------------------------------------
_FORBIDDEN_CODE = re.compile(
    r"(page\.|expect\(|pytest|playwright|def\s+test_|locator\(|assert\s+True)",
    flags=re.IGNORECASE,
)

def _explicit_behavior_values(text: str) -> set[str]:
    """재사용 비교용 명시 코드·수치만 추출합니다. 자연어 의미 판단을 대체하지 않습니다."""
    text = re.sub(r"\b(?:REQ|TC|COND|ER)-[A-Z0-9-]+", "", text)
    tokens = re.findall(
        r"(?<![A-Za-z0-9_])(?:[A-Z][A-Z0-9_]*|true|false)(?![A-Za-z0-9_])"
        r"|(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?", text,
    )
    ignored = {"UI", "SRS", "TC", "QA", "API", "JSON", "HTML", "C"}
    return {
        f"{float(token):g}" if re.fullmatch(r"-?\d+(?:\.\d+)?", token) else token
        for token in tokens if token not in ignored
    }


def _tc_observation_binding_errors(tc: ProductTestCaseCandidate) -> list[str]:
    """One binding check for CP2 and repair diagnostics; wording stays guidance."""
    errors = []
    for result in tc.expected_results:
        label = f"{tc.tc_id}/{result.result_id}"
        if not result.verify_after_step or sum(
            _normalize(step) == _normalize(result.verify_after_step) for step in tc.steps
        ) != 1:
            errors.append(f"{label}: 실제 절차 한 곳에 판정 시점을 연결")
        if not result.observation_target or not result.observation_target.strip():
            errors.append(f"{label}: 확인 대상 observation_target 누락")
    return errors


def _tc_restore_basis_errors(tc: ProductTestCaseCandidate) -> list[str]:
    """Catch ambiguous per-target drafting before asking Agent 3 to repair a frozen TC."""
    if tc.restoration is not None:
        return _structured_restoration_errors(tc)
    errors = []
    for line in tc.restore_steps:
        if not re.search(r"확인|비교|검사|검증|\b(?:check|verify|compare|confirm)\b", line, re.I):
            continue
        # Combined restore-operation notes are preserved; this guard handles the added confirmation.
        if re.search(r"선택하|적용하|입력하|설정하|복원하|\b(?:apply|restore|fill|select|set)\b", line, re.I):
            continue
        distinct_targets = {r.observation_target: r for r in tc.expected_results if r.observation_target}
        targets = sorted(((line.find(target), r) for target, r in distinct_targets.items()
                          if target in line), key=lambda item: item[0])
        for index, (start, result) in enumerate(targets):
            end = targets[index + 1][0] if index + 1 < len(targets) else len(line)
            clause = line[start:end].replace(result.observation_target, " ")
            values = _explicit_behavior_values(clause)
            if not values and not _has_restore_baseline(clause):
                errors.append(f"{tc.tc_id}/{result.result_id}: 해당 확인 대상의 구절에 초기값 또는 시험 전 상태와의 비교를 명시하세요.")
            if result.observation_layer == ObservationLayer.UI and values:
                grounded = set().union(*(_explicit_behavior_values(p) for p in tc.preconditions
                                        if result.observation_target in p))
                if values - grounded:
                    errors.append(f"{tc.tc_id}/{result.result_id}: 내부 코드를 화면 초기 표시로 가정하지 마세요. "
                                  "화면 표시 근거가 없으면 이 대상의 실행 전 관찰 상태와 비교한다고 명시하세요.")
    return errors


def evaluate_checkpoint2(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    design: Agent2TestDesign,
    requirements: dict[str, SrsRequirement],
    *,
    existing_catalog: tuple[ExistingRegressionSpec, ...] = EXISTING_REGRESSION_CATALOG,
) -> Checkpoint2Result:
    """Current CP2 only (2026-10-20 cleanup: no historical switches).

    Wording, expected-value meaning, notification need and procedure coverage are
    owned by the mandatory grounding review; this function checks structure,
    traceability, handoff and execution links.
    """
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if any(tc.execution_spec is not None for tc in design.test_cases):
        errors = [f"{tc.tc_id}: {error}" for tc in design.test_cases for error in tc_execution_spec_errors(tc)]
        add("CP2-024", CheckStatus.FAIL if errors else CheckStatus.PASS,
            " / ".join(errors) if errors else "TC 조작·기대값·확인 시점의 구조화 참조를 확인했습니다.")

    if design.request_id == analysis.request_id == request.request_id:
        add("CP2-001", CheckStatus.PASS, "변경 요청·Agent 1·Agent 2의 요청 ID가 일치합니다.")
    else:
        add("CP2-001", CheckStatus.FAIL, "Agent 2의 변경 요청 ID가 앞 단계 입력과 다릅니다.")

    tc_ids = [tc.tc_id for tc in design.test_cases]
    result_ids = [result.result_id for tc in design.test_cases for result in tc.expected_results]
    duplicate_tc_ids = sorted({item for item in tc_ids if tc_ids.count(item) > 1})
    duplicate_result_ids = sorted({item for item in result_ids if result_ids.count(item) > 1})
    if duplicate_tc_ids or duplicate_result_ids:
        add("CP2-002", CheckStatus.FAIL, "TC·기대 결과 ID 또는 제목이 중복됩니다.")
    else:
        add("CP2-002", CheckStatus.PASS, "TC·기대 결과 ID가 고유합니다. 제목은 식별자가 아닙니다.")

    known_conditions = {item.condition_id: item for item in analysis.confirmed_conditions}
    requirement_relations = {
        item.requirement_id: item.relation for item in analysis.requirement_effects
    }
    active_requirements = {
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation != RequirementRelation.NO_IMPACT
    }
    referenced_requirements = {
        item for tc in design.test_cases for item in tc.requirement_ids
    }
    candidate_conditions = {
        item for tc in design.test_cases for item in tc.source_condition_ids
    }
    existing_conditions = {
        item
        for selection in design.related_existing_tests
        for item in selection.source_condition_ids
    }
    # A retained/VERIFY condition still needs a test. Supporting context alone
    # cannot justify reuse; coverage meaning remains a mandatory model review.
    target_test_condition_ids = {
        condition.condition_id for condition in analysis.confirmed_conditions
        if request.target_requirement_id in condition.requirement_ids
        and condition.change_role != ConditionChangeRole.SUPPORTING
    }
    referenced_conditions = candidate_conditions | existing_conditions
    existing_by_id = _existing_regression_by_id(existing_catalog)
    selected_existing_specs = [
        existing_by_id[item.tc_id]
        for item in design.related_existing_tests
        if item.tc_id in existing_by_id
    ]
    covered_requirements = referenced_requirements | {
        requirement_id
        for spec in selected_existing_specs
        for requirement_id in spec.requirement_ids
    }
    unknown_requirements = sorted(
        (referenced_requirements - requirements.keys())
        | (referenced_requirements - active_requirements)
    )
    unknown_conditions = sorted(referenced_conditions - known_conditions.keys())
    if unknown_requirements or unknown_conditions:
        add("CP2-003", CheckStatus.FAIL, "입력 범위 밖 Requirement 또는 Condition을 참조했습니다.")
    else:
        add("CP2-003", CheckStatus.PASS, "모든 추적 ID가 승인된 입력 범위에 존재합니다.")

    missing_conditions = sorted(known_conditions.keys() - referenced_conditions)
    if missing_conditions:
        add("CP2-004", CheckStatus.FAIL, "변경 후보 또는 관련 기존 TC에 반영되지 않은 확정 조건: " + ", ".join(missing_conditions))
    else:
        add("CP2-004", CheckStatus.PASS, "Agent 1의 모든 확정 조건을 변경 후보 또는 관련 기존 TC가 반영합니다.")

    trace_errors: list[str] = []
    for tc in design.test_cases:
        tc_condition_ids = set(tc.source_condition_ids)
        condition_requirement_ids = {
            req_id
            for condition_id in tc_condition_ids
            if condition_id in known_conditions
            for req_id in known_conditions[condition_id].requirement_ids
        }
        if not set(tc.requirement_ids).issubset(condition_requirement_ids):
            trace_errors.append(tc.tc_id)
            continue
        if any(
            not set(expected.source_condition_ids).issubset(tc_condition_ids)
            for expected in tc.expected_results
        ):
            trace_errors.append(tc.tc_id)
    if trace_errors:
        add(
            "CP2-005",
            CheckStatus.FAIL,
            "TC 내부 Requirement·Condition·기대 결과 추적이 끊겼습니다: "
            + ", ".join(sorted(set(trace_errors))),
        )
    else:
        add("CP2-005", CheckStatus.PASS, "TC 내부 추적성이 유지됩니다.")

    # Whether a TC needs UI+internal or notification results is a meaning
    # question owned by the mandatory grounding review (scope semantics).
    policy_errors: list[str] = []
    for tc in design.test_cases:
        layers = {result.observation_layer for result in tc.expected_results}
        if tc.double_assert_policy == DoubleAssertPolicy.REQUIRED:
            # None means the existing single-flow end-of-test assertion point.
            timing = {
                layer: {result.verify_after_step for result in tc.expected_results
                        if result.observation_layer == layer}
                for layer in (ObservationLayer.UI, ObservationLayer.INTERNAL_STATE)
            }
            if tc.execution_spec is not None:
                # The execution contract already resolves each observation to
                # its last TEST action (CP2-024). Observation-only lines may
                # differ without a state-changing operation between them.
                # Match every internal observation to a UI observation of the
                # same TEST action; extra UI checks are
                # legitimate, not a reason to reject the complete pair.
                by_result = {v.result_id: v for v in tc.execution_spec.verifications}
                ui_results = [r for r in tc.expected_results
                              if r.observation_layer == ObservationLayer.UI]
                mismatched = any(
                    result.result_id not in by_result or not any(
                        ui.result_id in by_result
                        and by_result[result.result_id].after_action_id is not None
                        and by_result[result.result_id].after_action_id == by_result[ui.result_id].after_action_id
                        for ui in ui_results)
                    for result in tc.expected_results
                    if result.observation_layer == ObservationLayer.INTERNAL_STATE
                )
            else:
                # Without an execution definition, compare the prose judgment steps.
                mismatched = timing[ObservationLayer.UI] != timing[ObservationLayer.INTERNAL_STATE]
            if mismatched:
                policy_errors.append(f"{tc.tc_id}:UI·내부 상태 이중 검증의 판정 단계 불일치; 같은 조작 직후 함께 확인 필요")
        if tc.double_assert_policy == DoubleAssertPolicy.REQUIRED and not {
            ObservationLayer.UI,
            ObservationLayer.INTERNAL_STATE,
        }.issubset(layers):
            policy_errors.append(f"{tc.tc_id}:UI·내부 상태 결과 누락")
        elif tc.double_assert_policy == DoubleAssertPolicy.UI_ONLY and (
            ObservationLayer.UI not in layers or ObservationLayer.INTERNAL_STATE in layers
        ):
            policy_errors.append(f"{tc.tc_id}:UI_ONLY 계층 불일치")
        elif tc.double_assert_policy == DoubleAssertPolicy.INTERNAL_ONLY and (
            ObservationLayer.INTERNAL_STATE not in layers or ObservationLayer.UI in layers
        ):
            policy_errors.append(f"{tc.tc_id}:INTERNAL_ONLY 계층 불일치")
    if policy_errors:
        add(
            "CP2-006",
            CheckStatus.FAIL,
            "조건부 이중 검증 또는 원자적 기대 결과 계약이 맞지 않습니다: " + ", ".join(policy_errors),
        )
    else:
        add(
            "CP2-006",
            CheckStatus.PASS,
            "상태 관련 TC의 이중 검증·예외 정책과 원자적 UI 기대 결과가 일치합니다.",
        )
    add("CP2-007", CheckStatus.PASS, "알림 필요 여부와 누락은 필수 조건 의미 검토에서 확인합니다.")

    path_errors: list[str] = []
    for tc in design.test_cases:
        if tc.control_path != ControlPath.CENTRAL:
            path_errors.append(f"{tc.tc_id}:현재 V2는 중앙 관제 패널(CENTRAL) 경로만 허용")
        if any(req_id.startswith("REQ-LOCAL-") for req_id in tc.requirement_ids):
            path_errors.append(f"{tc.tc_id}:현재 SRS 범위 밖 REQ-LOCAL 참조")
    candidate_required_requirements = {
        requirement_id
        for requirement_id, relation in requirement_relations.items()
        if relation in {
            RequirementRelation.MODIFIED,
            RequirementRelation.UPDATE_REQUIRED,
        }
    }
    existing_covers_target_change = any(
        request.target_requirement_id in spec.requirement_ids
        and bool(
            set(selection.source_condition_ids).intersection(target_test_condition_ids)
        )
        for selection, spec in (
            (selection, existing_by_id.get(selection.tc_id))
            for selection in design.related_existing_tests
        )
        if spec is not None
    )
    if "REQ-CONTROL-001" in candidate_required_requirements and not any(
        tc.control_path == ControlPath.CENTRAL and "REQ-CONTROL-001" in tc.requirement_ids
        for tc in design.test_cases
    ) and not any(
        "REQ-CONTROL-001" in spec.requirement_ids
        and bool(set(selection.source_condition_ids).intersection(target_test_condition_ids))
        for selection, spec in (
            (selection, existing_by_id.get(selection.tc_id))
            for selection in design.related_existing_tests
        )
        if spec is not None
    ):
        path_errors.append("REQ-CONTROL-001 중앙 제어 TC 누락")
    required_change_paths: list[tuple[str, ControlPath]] = []
    if "REQ-CONTROL-001" in candidate_required_requirements:
        required_change_paths.append(("REQ-CONTROL-001", ControlPath.CENTRAL))
    for requirement_id, control_path in required_change_paths:
        candidate_has_path = any(
            tc.control_path == control_path
            and request.target_requirement_id in tc.requirement_ids
            and requirement_id in tc.requirement_ids
            for tc in design.test_cases
        )
        existing_has_path = any(
            request.target_requirement_id in spec.requirement_ids
            and requirement_id in spec.requirement_ids
            and bool(
                set(selection.source_condition_ids).intersection(
                    target_test_condition_ids
                )
            )
            for selection, spec in (
                (selection, existing_by_id.get(selection.tc_id))
                for selection in design.related_existing_tests
            )
            if spec is not None
        )
        if not candidate_has_path and not existing_has_path:
            path_errors.append(f"{control_path.value} 경로의 직접 변경 검증 TC 누락")
    uncovered_requirements = sorted(active_requirements - covered_requirements)
    target_change_tests = [
        tc
        for tc in design.test_cases
        if request.target_requirement_id in tc.requirement_ids
    ]
    if (
        uncovered_requirements
        or (not target_change_tests and not existing_covers_target_change)
        or path_errors
    ):
        details = []
        if uncovered_requirements:
            details.append("미포함 Requirement=" + ",".join(uncovered_requirements))
        if not target_change_tests and not existing_covers_target_change:
            details.append("대상 변경 검증 TC 없음")
        details.extend(path_errors)
        add("CP2-008", CheckStatus.FAIL, "변경 범위 또는 제어 경로가 불완전합니다: " + "; ".join(details))
    else:
        add("CP2-008", CheckStatus.PASS, "변경 후보 또는 변경 후 동작을 이미 검증하는 기존 TC와 영향 Requirement가 중앙 관제 패널 경로로 연결됩니다.")

    text_fields = [
        value
        for tc in design.test_cases
        for value in [
            tc.title,
            *tc.preconditions,
            *tc.steps,
            *(result.statement for result in tc.expected_results),
            *tc.restore_steps,
            tc.automation_reason,
        ]
    ]
    if any(_FORBIDDEN_CODE.search(value) for value in text_fields):
        add("CP2-009", CheckStatus.FAIL, "제품 TC에 자동화 코드 또는 금지 표현이 섞였습니다.")
    else:
        add("CP2-009", CheckStatus.PASS, "제품 TC와 자동화 구현의 역할이 분리됐습니다.")

    test_data_errors = [
        tc.tc_id
        for tc in design.test_cases
        if tc.test_type == TcType.BOUNDARY
        and not (tc.execution_spec is not None
                 and not tc_execution_spec_errors(tc)
                 and any(op.phase.value == "TEST" and op.action_type.value != "SELECT_DEVICE"
                         for op in tc.execution_spec.operations))
        and tc.test_data.requested_mode is None
        and not tc.test_data.requested_modes
        and tc.test_data.requested_temperature_c is None
        and not tc.test_data.requested_temperatures_c
    ]
    if test_data_errors:
        add(
            "CP2-010",
            CheckStatus.FAIL,
            "경계 TC의 구조화된 요청 모드 또는 온도 시험 데이터가 없습니다: "
            + ", ".join(test_data_errors),
        )
    else:
        add("CP2-010", CheckStatus.PASS, "실행에 필요한 대상 역할과 시험 데이터가 구조화됐습니다.")

    if design.human_review_notes:
        add(
            "CP2-011",
            CheckStatus.REVIEW,
            "기대 결과를 확정할 수 없어 실행을 멈춘 확인 사항이 있습니다: "
            + " / ".join(design.human_review_notes),
        )
    else:
        note_count = len(design.coverage_notes) + len(design.final_review_notes)
        if note_count:
            add(
                "CP2-011",
                CheckStatus.PASS,
                "후속 자동 실행을 막지 않는 참고·최종 검토 사항 "
                f"{note_count}건을 기록했습니다.",
            )
        else:
            add("CP2-011", CheckStatus.PASS, "추가 의미 판단이 필요한 항목이 없습니다.")

    tier_errors: list[str] = []
    invalid_feature_links: list[str] = []
    expected_common_by_type = {
        TcType.NORMAL: CommonQaCriterion.NORMAL_FLOW,
        TcType.BOUNDARY: CommonQaCriterion.BOUNDARY_VALUE,
        TcType.EXCEPTION: CommonQaCriterion.EXCEPTION_HANDLING,
    }
    for tc in design.test_cases:
        expected_common = expected_common_by_type.get(tc.test_type)
        if not tc.common_qa_criteria or (
            expected_common is not None and expected_common not in tc.common_qa_criteria
        ):
            tier_errors.append(f"{tc.tc_id}:1단계 공통 QA 기준")
        if not tc.domain_qa_criteria:
            tier_errors.append(f"{tc.tc_id}:2단계 도메인 QA 기준")
        if (
            not tc.feature_requirement_ids
            or not set(tc.feature_requirement_ids).issubset(set(tc.requirement_ids))
        ):
            tier_errors.append(f"{tc.tc_id}:3단계 기능 기준 Requirement")
        if (
            tc.test_type == TcType.STATE_CONSISTENCY
            and DomainQaCriterion.UI_INTERNAL_STATE_CONSISTENCY
            not in tc.domain_qa_criteria
        ):
            tier_errors.append(f"{tc.tc_id}:상태 정합성 도메인 기준")
        if not set(tc.feature_requirement_ids).issubset(set(tc.requirement_ids)):
            invalid_feature_links.append(tc.tc_id)
    add("CP2-012", CheckStatus.FAIL if invalid_feature_links else CheckStatus.PASS,
        "TC 추적 범위를 벗어난 기능 기준: " + ", ".join(invalid_feature_links)
        if invalid_feature_links else
        "QA 분류는 설명용입니다. 필수 요구·조건·검사 연결은 별도로 확인합니다."
        + (" 분류 참고 사항: " + ", ".join(tier_errors) if tier_errors else ""))

    independence_errors = [tc.tc_id for tc in design.test_cases if not tc.independent_execution]
    if independence_errors:
        add(
            "CP2-013",
            CheckStatus.FAIL,
            "단독 실행 불가 선언 또는 다른 TC 결과에 의존하는 절차가 있습니다: "
            + ", ".join(independence_errors),
        )
    else:
        add("CP2-013", CheckStatus.PASS,
            "독립 실행 설명 문장은 필수가 아닙니다. 실제 준비·단독 실행·복원 성공은 실행 증거로 확인합니다.")

    # Agent 1 routes procedure notes from the immutable input. Their actual
    # placement and order are reviewed per note by the mandatory grounding
    # review; CP3 checks the implemented preparation and restoration.
    procedure_notes = list(analysis.procedure_notes)
    procedure_note_keys = {_normalize(item) for item in procedure_notes}
    analysis_scope = {
        _normalize(item)
        for item in analysis.excluded_scope
        if _normalize(item) not in procedure_note_keys
    }
    design_scope = {
        _normalize(item)
        for item in design.excluded_scope
        if _normalize(item) not in procedure_note_keys
    }
    excluded_scope_matches = design_scope == analysis_scope
    excluded_gaps_match = {
        _normalize(item) for item in design.excluded_information_gaps
    } == {_normalize(item) for item in analysis.excluded_information_gaps}
    excluded_procedure_notes = [
        item for item in design.excluded_scope if _normalize(item) in procedure_note_keys
    ]
    # Existing-TC-only designs hand the procedure notes to the final human review.
    procedure_review = list(procedure_notes) if not design.test_cases and design.related_existing_tests else []
    if not excluded_scope_matches or not excluded_gaps_match or excluded_procedure_notes:
        details: list[str] = []
        if not excluded_scope_matches or not excluded_gaps_match:
            details.append("실제 제외 범위 또는 정보 부족 인계 불일치")
        if excluded_procedure_notes:
            details.append("시험 절차를 제외 범위로 분류")
        add(
            "CP2-014",
            CheckStatus.FAIL,
            "Agent 1 제외 항목과 변경 요청 시험 절차의 인계가 맞지 않습니다: "
            + "; ".join(details),
        )
    else:
        add(
            "CP2-014",
            CheckStatus.PASS,
            f"실행 제외 범위 {len(design_scope)}건, 정보 부족 {len(design.excluded_information_gaps)}건과 시험 절차 {len(procedure_notes)}건을 올바르게 분리했습니다."
            " 절차의 실제 반영·순서는 원문별 모델 검토를 통과해야 합니다."
            + (" 기존 TC의 시험 절차 메모는 수행 완료로 간주하지 않고 최종 사람 검토로 전달합니다." if procedure_review else ""),
        )

    grouping_errors: list[str] = []
    for tc in design.test_cases:
        if tc.execution_spec is not None:
            # CP2-024 owns action/value/anchor coverage. Runtime records and
            # restores BEFORE_SETUP; prose and duplicate test_data are not a
            # second execution plan. Explicit reset instructions must still
            # exist in the TC and be implemented at their original position.
            for step in tc.intermediate_reset_steps:
                if step not in tc.steps or not any(
                    op.phase == AutomationPhase.TEST and op.source_text == step
                    for op in tc.execution_spec.operations
                ):
                    grouping_errors.append(f"{tc.tc_id}:중간 초기화의 실행 연결 누락")
            continue
        data = tc.test_data
        plural_values_used = bool(
            data.requested_modes or data.requested_temperatures_c
        )
        if len(data.requested_modes) != len(set(data.requested_modes)):
            grouping_errors.append(f"{tc.tc_id}:requested_modes 중복")
        normalized_temperatures = [float(value) for value in data.requested_temperatures_c]
        if len(normalized_temperatures) != len(set(normalized_temperatures)):
            grouping_errors.append(f"{tc.tc_id}:requested_temperatures_c 중복")

        grouped = _is_grouped_test_case(tc)
        hvac_values_changed = bool(
            data.requested_mode
            or data.requested_modes
            or data.requested_temperature_c is not None
            or data.requested_temperatures_c
        )
        dynamic_restore_text = " ".join(tc.restore_steps)
        if data.restore_observed_hvac_state:
            if not grouped and tc.state_effect is None:
                grouping_errors.append(
                    f"{tc.tc_id}:실행 전 HVAC 상태 저장·복원은 묶음 TC에서만 허용"
                )
            if not tc.restore_required or not hvac_values_changed:
                grouping_errors.append(
                    f"{tc.tc_id}:상태 변경과 최종 복원이 없는 동적 HVAC 복원 표시"
                )
            if tc.state_effect is None and (data.initial_mode is not None or data.initial_temperature_c is not None):
                grouping_errors.append(
                    f"{tc.tc_id}:동적 HVAC 복원과 고정 초기값을 함께 사용"
                )
            if tc.restoration is None and not (
                _contains_any(dynamic_restore_text, ("실행 직전", "관찰", "observed"))
                and _contains_any(dynamic_restore_text, ("모드", "mode"))
                and _contains_any(dynamic_restore_text, ("온도", "temperature"))
                and _contains_any(dynamic_restore_text, ("복원", "restore"))
                and _contains_any(dynamic_restore_text, ("적용", "apply"))
            ):
                grouping_errors.append(
                    f"{tc.tc_id}:동적 HVAC 복원 절차에 저장 대상·복원·적용 의미 누락"
                )
        elif (
            grouped
            and tc.restore_required
            and hvac_values_changed
            and data.initial_mode is None
            and data.initial_temperature_c is None
        ):
            grouping_errors.append(
                f"{tc.tc_id}:고정 초기값이 없는 묶음 HVAC TC의 실행 전 상태 저장·복원 표시 누락"
            )
        if plural_values_used and not grouped:
            grouping_errors.append(f"{tc.tc_id}:복수 조건인데 condition_execution=SINGLE_FLOW")
        if not grouped:
            if tc.grouping_reason or tc.intermediate_reset_steps:
                grouping_errors.append(f"{tc.tc_id}:단일 흐름에 묶음 근거 또는 중간 초기화가 있음")
            continue

        if not tc.grouping_reason:
            grouping_errors.append(f"{tc.tc_id}:동일 업무 규칙 묶음 근거 누락")
        invalid_reset_steps = [
            step for step in tc.intermediate_reset_steps if step not in tc.steps
        ]
        if invalid_reset_steps:
            grouping_errors.append(f"{tc.tc_id}:steps에 없는 중간 초기화 절차")
        if (
            tc.condition_execution == ConditionExecution.INDEPENDENT_VARIANTS
            and not tc.intermediate_reset_steps
        ):
            grouping_errors.append(f"{tc.tc_id}:독립 조건 사이 초기화 절차 누락")

        verification_steps = [
            result.verify_after_step for result in tc.expected_results
        ]
        if any(step is None or step not in tc.steps for step in verification_steps):
            grouping_errors.append(f"{tc.tc_id}:기대 결과의 조건별 판정 단계 누락 또는 불일치")
        elif len(set(verification_steps)) < 2:
            grouping_errors.append(f"{tc.tc_id}:모든 조건 결과를 마지막 한 단계에서만 판정")

        procedure_text = " ".join([*tc.preconditions, *tc.steps])
        for mode in data.requested_modes:
            if not _contains(procedure_text, mode):
                grouping_errors.append(f"{tc.tc_id}:절차에 없는 요청 모드 {mode}")
        procedure_numbers = {
            float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", procedure_text)
        }
        for temperature in data.requested_temperatures_c:
            if float(temperature) not in procedure_numbers:
                grouping_errors.append(
                    f"{tc.tc_id}:절차에 없는 요청 온도 {temperature:g}"
                )

    if grouping_errors:
        add(
            "CP2-015",
            CheckStatus.FAIL,
            "동일 업무 규칙 묶음 TC의 조건별 실행·판정 계약이 맞지 않습니다: "
            + ", ".join(grouping_errors),
        )
    else:
        add(
            "CP2-015",
            CheckStatus.PASS,
            "같은 업무 규칙의 조건 묶음과 조건별 판정·초기화 계약이 일치합니다.",
        )

    existing_selection_errors: list[str] = []
    selected_existing_ids = [item.tc_id for item in design.related_existing_tests]
    duplicate_existing_ids = sorted(
        {
            item
            for item in selected_existing_ids
            if selected_existing_ids.count(item) > 1
        }
    )
    if duplicate_existing_ids:
        existing_selection_errors.append(
            "중복 기존 TC=" + ",".join(duplicate_existing_ids)
        )
    unknown_existing_ids = sorted(
        set(selected_existing_ids) - existing_by_id.keys()
    )
    if unknown_existing_ids:
        existing_selection_errors.append(
            "카탈로그 밖 기존 TC=" + ",".join(unknown_existing_ids)
        )
    for selection in design.related_existing_tests:
        spec = existing_by_id.get(selection.tc_id)
        if spec is None:
            continue
        for condition_id in selection.source_condition_ids:
            condition = known_conditions.get(condition_id)
            if condition is None:
                existing_selection_errors.append(
                    f"{selection.tc_id}:입력 밖 조건 {condition_id}"
                )
            elif not set(condition.requirement_ids).intersection(spec.requirement_ids):
                existing_selection_errors.append(
                    f"{selection.tc_id}:{condition_id} Requirement 근거 불일치"
                )
    direct_change_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.change_role == ConditionChangeRole.CHANGED
    }
    misrouted_change_conditions = sorted(
        direct_change_condition_ids - candidate_conditions - existing_conditions
    )
    if misrouted_change_conditions:
        existing_selection_errors.append(
            "변경 조건의 신규·수정 후보 누락="
            + ",".join(misrouted_change_conditions)
        )
    if not design.existing_tc_comparison_completed:
        existing_selection_errors.append("기존 TC 대조 완료 표시 누락")
    if existing_selection_errors:
        add(
            "CP2-016",
            CheckStatus.FAIL,
            "변경분 후보와 관련 기존 TC 분리가 맞지 않습니다: "
            + "; ".join(existing_selection_errors),
        )
    else:
        add(
            "CP2-016",
            CheckStatus.PASS,
            "요청된 시험과 관련 기존 TC의 연결·중복을 확인했습니다. 대상 VERIFY의 미충족 시험도 후보로 작성할 수 있습니다.",
        )

    # Required values, exclusions and missing checks of a reused existing TC are
    # judged by the mandatory per-condition grounding review.
    add("CP2-019", CheckStatus.PASS,
        "기존 TC 연결을 확인했습니다. 실제 요구 값·제외·검사 누락은 필수 조건별 의미 검토에서 확인합니다.")

    # Expected-value meaning and wording are owned by the mandatory grounding
    # review; code keeps only the explicit request exclusions.
    minimality_errors: list[str] = []
    explicit_exclusions = {_normalize(note) for note in request.out_of_scope}
    scope_limit_condition_ids = {
        c.condition_id for c in analysis.confirmed_conditions
        if c.source_type == ConditionSource.CHANGE_REQUEST and _normalize(c.source_text) in explicit_exclusions
    }
    for tc in design.test_cases:
        for result in tc.expected_results:
            excluded_sources = sorted(set(result.source_condition_ids) & scope_limit_condition_ids)
            if excluded_sources:
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:제외 조건을 기대 결과로 사용="
                    + ",".join(excluded_sources)
                )
    if minimality_errors:
        add(
            "CP2-017",
            CheckStatus.FAIL,
            "변경 요구 범위를 넘어선 기대 결과가 있습니다: "
            + "; ".join(minimality_errors),
        )
    else:
        add(
            "CP2-017",
            CheckStatus.PASS,
            "기대결과의 조건 연결·제외 역할을 확인했습니다. 기대값 의미는 필수 모델 검토에서 확인합니다.",
        )

    # CP2-018
    revision_errors: list[str] = []
    policy = _srs_revision_policy(request, analysis, requirements)
    required_revision_ids = set(policy["required_requirement_ids"])
    already_reflected_ids = set(policy["already_reflected_requirement_ids"])
    proposal_ids = [item.proposal_id for item in design.srs_revision_proposals]
    proposal_requirement_ids = [
        item.requirement_id for item in design.srs_revision_proposals
    ]
    if len(proposal_ids) != len(set(proposal_ids)):
        revision_errors.append("SRS 개정 제안 ID 중복")
    if len(proposal_requirement_ids) != len(set(proposal_requirement_ids)):
        revision_errors.append("Requirement별 SRS 개정 제안 중복")
    missing = sorted(required_revision_ids - set(proposal_requirement_ids))
    extra = sorted(set(proposal_requirement_ids) - required_revision_ids)
    if missing:
        revision_errors.append("개정 제안 누락=" + ",".join(missing))
    if extra:
        revision_errors.append("개정 대상 밖 제안=" + ",".join(extra))
    unnecessary = sorted(set(proposal_requirement_ids) & already_reflected_ids)
    if unnecessary:
        revision_errors.append(
            "현재 SRS에 요청 after_value가 이미 반영됨=" + ",".join(unnecessary)
            + "; 해당 개정안을 제외하고 TC 선택·검증 범위는 유지하세요. 새 승인이나 문구 변경은 필요하지 않습니다."
        )
    for proposal in design.srs_revision_proposals:
        requirement = requirements.get(proposal.requirement_id)
        if requirement is None:
            revision_errors.append(
                f"{proposal.proposal_id}:SRS에 없는 Requirement"
            )
            continue
        sources = [known_conditions[c].source_text for c in proposal.source_condition_ids if c in known_conditions]
        authority = " ".join([requirement.acceptance_criteria, *sources])
        if proposal.requirement_id == request.target_requirement_id:
            authority += " " + request.after_value + " " + request.description
        if _explicit_behavior_values(proposal.proposed_acceptance_criteria) - _explicit_behavior_values(authority):
            revision_errors.append(f"{proposal.proposal_id}:근거에 없는 개정 코드·수치")
        if proposal.current_acceptance_criteria != requirement.acceptance_criteria:
            revision_errors.append(
                f"{proposal.proposal_id}:현재 인수 기준 원문 불일치"
            )
        if (
            proposal.proposed_acceptance_criteria.casefold()
            == proposal.current_acceptance_criteria.casefold()
        ):
            revision_errors.append(
                f"{proposal.proposal_id}:변경되지 않은 인수 기준"
            )
        for condition_id in proposal.source_condition_ids:
            condition = known_conditions.get(condition_id)
            if condition is None:
                revision_errors.append(
                    f"{proposal.proposal_id}:입력 밖 조건 {condition_id}"
                )
            elif proposal.requirement_id not in condition.requirement_ids:
                revision_errors.append(
                    f"{proposal.proposal_id}:{condition_id} Requirement 근거 불일치"
                )
    if revision_errors:
        add(
            "CP2-018",
            CheckStatus.FAIL,
            "사람 승인용 SRS 개정 제안이 입력 근거와 맞지 않습니다: "
            + "; ".join(revision_errors),
        )
    else:
        add(
            "CP2-018",
            CheckStatus.PASS,
            ("현재 SRS에 이미 반영되어 개정 불필요=" + ",".join(sorted(already_reflected_ids))
             + "; 나머지 개정안의 전·후 문구와 근거를 확인했습니다. 시험 완료·사람 승인을 뜻하지 않습니다."
             if already_reflected_ids else
             "SRS 개정 필요 범위와 제출된 제안을 확인했습니다. 기존 기준 시험만이면 제안이 없어도 됩니다."),
        )

    # CP2-020: observation target and judgment step links (wording is guidance).
    detail_errors = [error for tc in design.test_cases for error in _tc_observation_binding_errors(tc)]
    add("CP2-020", CheckStatus.FAIL if detail_errors else CheckStatus.PASS,
        "TC 상세화 필요: " + "; ".join(detail_errors) if detail_errors
        else "기대결과 확인 대상·판정 단계 연결을 확인했습니다. 상세 문체는 작성 지침으로 유지합니다.")

    policy_errors = []
    for tc in design.test_cases:
        if tc.state_effect is None:
            policy_errors.append(f"{tc.tc_id}: state_effect 분류 누락")
        elif tc.restore_required != (tc.state_effect != TcStateEffect.READ_ONLY):
            policy_errors.append(f"{tc.tc_id}: 조회는 복원 불필요, 변경·차단은 복원 절차 필요")
        if tc.state_effect == TcStateEffect.BLOCKED_CHANGE and not any(
            result.observation_layer in {ObservationLayer.UI, ObservationLayer.INTERNAL_STATE}
            for result in tc.expected_results
        ):
            policy_errors.append(f"{tc.tc_id}: 차단 안내뿐 아니라 요구된 차단 결과의 대상 상태 확인 필요")
    add("CP2-022", CheckStatus.FAIL if policy_errors else CheckStatus.PASS,
        "; ".join(policy_errors) if policy_errors else "조회·변경·차단 유형별 복원 정책을 확인했습니다.")

    errors = [f"{tc.tc_id}: {error}" for tc in design.test_cases
              for error in _structured_restoration_errors(tc)]
    add("CP2-023", CheckStatus.FAIL if errors else CheckStatus.PASS,
        "; ".join(errors) if errors else "복원 조작·대상 ER·관찰 기준·확인 시점의 구조화 연결을 확인했습니다.")

    # 2026-10-23 사람 대조: a live TC title came back in Chinese while the body was Korean,
    # and neither review AI nor judge flagged it. People read these TCs, so reject
    # Han ideographs and Japanese kana in the human-facing TC text. Reported only on a
    # violation (like CP2-TC-REVISION) so saved Korean designs recompute the same checkpoint.
    # 2026-10-25: widened from five TC text kinds to every design string (a Japanese
    # independence_reason passed the narrower check). Quotes of request/SRS/existing TC
    # text are allowed.
    errors = foreign_script_texts(
        design.model_dump(mode="json"),
        [request.model_dump_json(), *(r.model_dump_json() for r in requirements.values()),
         *(repr(item) for item in existing_catalog)])
    if errors:
        add("CP2-LANG", CheckStatus.FAIL,
            "한국어로 다시 작성해야 하는 설계 문장(한자·일본 문자 포함): " + "; ".join(errors[:8]))

    if design.existing_tc_revisions:
        # H-3 (2026-10-17). Added only when a revision is declared, so earlier
        # Runs recompute the same checkpoint.
        errors = []
        candidates = set(tc_ids)
        reused = {item.tc_id for item in design.related_existing_tests}
        seen: set[str] = set()
        for revision in design.existing_tc_revisions:
            if revision.tc_id not in existing_by_id:
                errors.append(f"{revision.tc_id}: 제공된 기존 TC 목록에 없음")
            if revision.revised_by not in candidates:
                errors.append(f"{revision.tc_id}: 고친 후보 {revision.revised_by}가 test_cases에 없음")
            if revision.tc_id in reused:
                errors.append(f"{revision.tc_id}: 고쳐 쓰는 TC를 관련_기존_TC로 그대로 재사용할 수 없음")
            if revision.tc_id in seen:
                errors.append(f"{revision.tc_id}: 고쳐 쓰기 기록 중복")
            seen.add(revision.tc_id)
        add("CP2-TC-REVISION", CheckStatus.FAIL if errors else CheckStatus.PASS,
            "; ".join(errors) if errors else
            "기존 TC 고쳐 쓰기 기록이 제공된 TC와 신규 후보에 연결됩니다. 교체는 사람 승인 전까지 확정되지 않습니다.")

    status = _aggregate_check_status(item.status for item in checks)
    return Checkpoint2Result(status=status, checks=checks)

__all__ = [name for name in globals() if not name.startswith("__")]
