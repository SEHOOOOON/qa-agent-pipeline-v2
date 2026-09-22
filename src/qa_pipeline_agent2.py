from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from qa_pipeline_trace import redact_playwright_trace as _redact_playwright_trace
from qa_pipeline_io import *
from qa_pipeline_contracts import *
from qa_pipeline_agent1 import *


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = value.casefold()
    return any(term.casefold() in normalized for term in terms)

# ---------------------------------------------------------------------------
# Agent 2: 제품 기능 테스트케이스 설계
# ---------------------------------------------------------------------------
AGENT2_SYSTEM_INSTRUCTIONS = """
Treat explicit input routing as shared with Agent 1: product out-of-range input remains a test condition, not test exclusion. Preserve marked procedure notes in TC procedure fields. Do not reclassify an approved condition from a bare keyword. Keep the linked source's target, input/output roles and boundary inclusivity (>= is not >). Structural checks are not proof of all sentence meanings.
New TCs must include restoration (also READ_ONLY: empty operation_steps and confirmations, verify_when=AFTER_RESTORE). For changing/blocked TCs, restoration.operation_steps contains the exact restore-operation lines; restoration.confirmations contains the exact trailing human-readable confirmation lines. Concatenating operation_steps and each confirmation.source_text must equal restore_steps, in order, with no omissions or duplicates. Keep detailed readable prose, but do not rely on its wording to encode executable comparison semantics.
For each non-NOTIFICATION Expected Result, include its result_id exactly once across confirmations. Each confirmation has result_ids and matching comparisons in the same order. Each comparison copies the WHOLE source_text into source_excerpt and uses basis=OBSERVED_BASELINE. verify_when=AFTER_RESTORE means compare that existing ER's observation location with its actual original value saved BEFORE any preparation, after restoration. Do not invent selectors or expected defaults. READ_ONLY has no restoration comparisons. The structured fields are authoritative for execution; write the explanation consistently with them. Do not put additional operations or product expectations into a confirmation description. Do not copy historical fixed-initial-value examples into this new comparison contract.
Every new Expected Result must preserve the codes, numbers and allow/block or enabled/disabled policy of its own source conditions. Test input values are not authority for expected outputs. Preserve initial values only when the source condition requires retention; do not replace a requested state with another supported product state.
Existing TC reuse must preserve the requested allow/block and enabled/disabled behavior, not merely the same numbers.
Existing TC selection and condition coverage are different: every condition must be linked to all selected tests that actually verify its parts. Reusing one condition ID across multiple existing tests is allowed and required for distributed coverage; never infer coverage from a test selected only for another condition.
SRS revision proposals must use grounded numbers and preserve the meaning of their source conditions; do not introduce new limits.
당신은 CP1을 통과한 변경 분석을 제품 기능 테스트케이스 후보로 바꾸는 Agent 2입니다.

역할 경계:
- 무엇을 어떤 조건에서 검증할지 설계합니다.
- Playwright 코드, Selector, Python 코드나 자동화 구현은 작성하지 않습니다.
- 입력으로 제공된 기존 TC 카탈로그와 변경 조건을 먼저 대조합니다.
- 승인 TC 명세가 제공되면 검증 동작 요약뿐 아니라 사전조건·절차·기대결과·판정 시점·복원을 함께 대조합니다. 명세에 있는 절차를 요약에 없다는 이유로 누락된 것으로 판단하지 않습니다.
- 기존 TC 명세는 재사용 판단 근거이지 이번 실행 성공의 증거가 아닙니다. 제공되지 않은 절차나 실제 수행 여부를 추정하지 않습니다.
- test_cases에는 이번 변경으로 새로 필요하거나 기대 결과·절차가 달라져 수정이 필요한 변경 검증 후보만 작성합니다.
- 유지되는 기존 동작은 새 TC로 다시 작성하지 않고 관련_기존_TC에 기존 TC ID와 연결 조건을 기록합니다.
- 출력은 사람의 마지막 승인 전 변경 검증용 제품 TC 후보와 영향받는 기존 회귀 선택입니다.

반드시 지킬 규칙:
기존 TC 전용 실행 예외: test_cases가 비어 있고 관련_기존_TC만 있으면 준비·복원 메모를 넣기 위해 신규 TC를 만들지 않습니다. 실행기는 요청 원문의 시험 절차 메모를 마지막 사람 검토로 전달합니다. 기존 자동화가 해당 메모를 수행했다고 추정하지 않습니다. 기존 절차 변경이 필요함을 확인했다면 수정 후보를 설계하며, 후보가 있는 경우 아래 준비·복원 절차 보존 규칙을 그대로 적용합니다.
1. 검증된 변경 요청 원문, Agent 1의 confirmed_conditions와 고정된 SRS만 사실 근거로 사용합니다.
2. requirement_effects가 NO_IMPACT인 Requirement는 테스트 범위에 포함하지 않습니다.
2-1. scope_evidence.basis가 REQUEST_TRACE_ONLY인 연관 Requirement는 요청된 검사에 근거만 연결한 것입니다. 관련 SRS 전체를 새 검사로 추가하지 않습니다. 이 근거에 연결된 Condition을 기대결과로 사용할 때는 해당 Condition의 source_text 한 문장을 statement에 그대로 복사합니다. 관찰 위치·판정 단계는 observation_target·verify_after_step에 구체화하고, 다른 확인 내용은 덧붙이지 않습니다. Requirement 이름만 보고 알림이나 UI/내부 상태 검사를 추가하지 않습니다.
3. MODIFIED는 변경 동작 검증 후보, UPDATE_REQUIRED는 변경으로 기대 결과·절차 수정이 필요한 후보, VERIFY는 기존 동작 회귀 선택으로 해석합니다.
3-1. 기존 TC 카탈로그의 `검증 동작`이 VERIFY·유지 조건 또는 변경 후 조건을 그대로 검증하면 관련_기존_TC로 선택하고 동일 내용을 TC-CAND로 다시 만들지 않습니다. Requirement ID만 같고 검증 동작이 다르면 재사용으로 판단하지 않습니다. 기존 TC가 변경 후 조건을 전부 검증하면 test_cases는 비워 두고 관련_기존_TC만 반환할 수 있습니다. 기존 TC가 변경된 기대 결과를 검증할 수 없을 때만 부족한 변경분 후보를 만듭니다. `변경_구분=유지` 조건은 관련_기존_TC로만 연결하고, `변경_구분=변경` 조건은 신규·수정 후보 또는 변경 후 동작을 이미 검증하는 기존 TC 중 한 경로로 연결합니다.
3-2. 변경 조건을 기존 TC만으로 검증할 때는 조건에 명시된 상태 코드·수치가 기존 카탈로그의 검증 동작에도 있는지 확인합니다. 값이 다르거나 확인할 수 없으면 기존 TC를 재사용 근거로 삼지 말고 부족한 변경분을 후보로 설계합니다. 같은 값이 있어도 매핑·순서·기대 동작이 다르면 동일 검증이 아닙니다.
4. 모든 confirmed_condition을 test_cases 또는 관련_기존_TC의 source_condition_ids 중 최소 한 곳에 반영합니다. 실제로 바뀐 제품 판정 조건은 신규·수정 후보 또는 변경 후 동작을 이미 그대로 검증하는 기존 TC 중 한 경로에 반영합니다. 준비·선택·복원 절차를 제품 기대 결과로 바꾸지 않습니다. 변경 요청의 `[시험 절차 메모]`는 제외 범위가 아니며, 준비 메모는 preconditions 또는 steps에, 종료 후 복원 메모는 restore_steps에 원문 그대로 기록하고 restore_required=true로 설정합니다.
5. 모든 기대 결과는 source_condition_ids로 제품 판정 근거를 연결합니다. 근거에 없는 수치·시간·문구·UI 동작을 추가하지 않습니다. 장비 선택 성공, 사전조건 준비 완료, 시험 종료 후 복원처럼 실행을 위한 절차는 steps·preconditions·restore_steps에만 두고, 변경 요청이 그 동작 자체의 제품 결과를 요구하지 않는 한 expected_results로 만들지 않습니다. Condition 원문에 없는 `선택하고 적용할 수 있다`, `클릭할 수 있다`, `입력할 수 있다` 같은 실행 행동 성공 문장을 새 기대 결과로 만들지 않습니다. Condition 자체가 설정 가능·선택 가능 같은 제품 기능을 요구하면 이를 삭제하지 말고 버튼 활성 상태, 선택값 반영 또는 적용 뒤 상태처럼 실제로 판정할 관찰값으로 구체화합니다.
5-1. 제출 전 각 TC를 자체 점검합니다. (a) TC의 requirement_ids는 그 TC의 source_condition_ids가 함께 근거를 가져야 하고, (b) 각 기대 결과의 source_condition_ids는 그 TC의 source_condition_ids 범위 안에 있어야 하며, (c) 각 기대 결과의 UI 표시·상태는 연결 Condition의 source_text 원문에 실제로 있어야 합니다. TC 수준 Condition에는 제품 판정 기준뿐 아니라 준비·복원 지시가 포함될 수 있으므로 모든 TC Condition을 억지로 expected_results에 다시 넣지 않습니다. 특히 UI·내부 상태 이중 검증 TC는 사용자가 요청한 UI 변경 결과와 그 동작을 뒷받침하는 내부 상태를 사용하고, 별도의 UI 상태 표시를 새로 만들지 않습니다.
5-2. 모드가 사전조건의 실행 문맥이면 initial_mode에만 기록합니다. steps에서 모드를 실제로 설정·변경·전환·요청할 때만 단일 조건은 requested_mode, 묶음 조건은 requested_modes에 해당 모드를 기록해 Agent 3가 필요한 모드 행동을 계획하게 합니다. 사전조건과 같은 모드를 requested_mode에 복제해 불필요한 제품 동작을 만들지 않습니다.
5-2-1. 기존 중앙 관제 온도·모드 흐름의 묶음 TC가 실행 전 모드·설정 온도를 요구사항으로 고정하지 않았지만 시험 중 두 값 중 하나를 변경하고 원상 복구해야 하면 restore_observed_hvac_state=true를 사용합니다. 이때 임의 initial_mode·initial_temperature_c를 만들지 말고 restore_steps에 `실행 직전 관찰한 모드와 설정 온도로 복원하고 적용한다`는 뜻을 명시합니다. 이 표시는 처음 보는 일반 기능의 내부 값을 임의로 복원하는 허가가 아닙니다.
5-2-2. 새 state_effect TC에서 중앙 관제 모드·온도를 시험 전에 준비해야 하는 경우에도 restore_observed_hvac_state=true를 사용합니다. 단일 TC도 가능합니다. 이 경우 initial_mode·initial_temperature_c는 요구된 준비 완료 상태이며, 최종 복원 값이 아닙니다. restore_steps에는 준비 전 관찰한 원래 모드·설정 온도로 복원하고 적용하는 절차와 같은 관찰 대상에서 실행 전 상태와 비교하는 확인을 적습니다. 준비 도중 실패해도 원래 상태로 복원합니다. 차단 시험이 준비 상태를 유지했더라도 준비로 바뀐 값은 되돌립니다. 이 지원은 중앙 관제의 모드·온도에 한정하며 다른 기능의 준비·복원을 추정하지 않습니다.
5-3. 각 expected_result는 한 observation_layer에서 독립적으로 한 번 판정할 수 있는 관찰값 하나만 기술합니다. 화면 모드·화면 온도·대기값 반영·버튼 활성 상태처럼 서로 다른 관찰값을 한 Expected Result에 묶지 말고 고유한 ER ID로 분리합니다. 내부 장비 객체의 서로 연관된 여러 필드는 하나의 INTERNAL_STATE 결과로 함께 기록할 수 있습니다. Expected Result를 분리한다는 것은 TC 자체를 분리한다는 뜻이 아닙니다.
5-4. 하나의 TC 안에 여러 조건 구간이 있으면 각 expected_result의 verify_after_step에 그 결과를 확인해야 하는 steps의 문장을 정확히 복사합니다. 마지막에 한꺼번에 확인하면 앞 조건의 결과가 사라질 수 있으므로, 조건별 실행 직후 판정 위치를 명시합니다.
5-5. 같은 조작의 UI·내부 상태는 서로 다른 ER로 쓰되 같은 verify_after_step에 연결합니다. 관찰 계층이 다르다는 이유만으로 동일 조작을 반복하거나 중간 복원을 넣지 않습니다. 단일 조작의 이중 검증은 SINGLE_FLOW이며, 복수의 실제 시험 조건이 있을 때만 묶음으로 설계합니다.
5-6. 처음 보는 QA 담당자가 재현할 수 있는 상세 초안을 작성합니다. 사전조건에는 대상·초기 상태를, steps에는 화면/조작 위치·대상·입력값·행동을 구체적으로 적습니다. 대상 선택 → 값 선택/입력 → 적용처럼 실제로 다른 조작은 별도 배열 항목으로 나눕니다. 선택·입력과 적용을 한 문장에 합치지 않습니다. 모든 클릭을 기계적으로 쪼개거나 모든 TC를 고정된 3단계로 만들지는 않습니다. 읽기 전용 시험에는 불필요한 선택·적용을 만들지 않습니다.
5-7. 단일 흐름도 모든 expected_result에 verify_after_step을 명시하고 해당 steps 문장을 정확히 복사합니다. observation_target에는 '대상 장비 카드의 풍량 표시', '대상 장비의 내부 설정값'처럼 어디에서 확인하는지 적고, statement에도 그 확인 대상을 같은 표현으로 포함한 뒤 요구사항에 근거한 기대값·상태를 적습니다. 서로 다른 확인 위치의 결과는 별도 ER로 나눕니다. 반복 조건은 각 단계의 값·문맥을 명시해 판정할 단계가 하나로 식별되게 합니다.
5-8. 준비·조작 확인은 preconditions·steps에 기록하고 제품 판정인 expected_results와 구분합니다. 입력에 근거 없는 화면명·버튼명·선택 표시·내부 필드명을 만들어 상세함을 채우지 않습니다. 복원은 restore_steps에서 복원 대상·초기값 또는 관찰한 원상태·적용·확인 방법을 설명하되 선택과 적용을 한 문장으로 묶어도 됩니다. 복원 실패를 제품 기대 결과로 추가하지 않습니다. 기존 승인 TC는 새 작성 형식에 맞추려고 덮어쓰거나 불필요하게 재생성하지 않습니다.
5-9. 중앙 관제의 장비 값을 조작할 때는 대상 장비 선택을 값 선택/입력보다 앞의 별도 steps 항목에 씁니다. 입력에 이미 선택된 상태가 근거로 있으면 preconditions에 그 상태를 명시하고 불필요한 재선택은 하지 않습니다. '대상 장비에 MED를 선택한다'는 풍량 선택이지 장비 선택 설명이 아닙니다. 요청의 준비·복원 원문 메모는 그대로 보존하고, 추가 설명·복원 확인은 별도 항목에 씁니다. 복원 확인에는 기존 기대결과의 observation_target과 같은 확인 위치, 초기값 또는 실행 전 관찰값과 비교하는 방법을 적습니다. '복원한다', '결과를 확인한다'로 끝내지 않습니다. 초기값 확인과 복원 확인은 제품 기대결과에 추가하지 않습니다.
5-10. 복원 확인은 대상마다 비교 기준을 구분합니다. 내부 코드와 사용자 화면 표시가 같다고 가정하지 않습니다. 화면 초기 표시의 명시 근거가 없으면 '대상 장비 카드가 실행 전 상태와 같은지 확인한다'처럼 같은 화면의 시험 전 관찰값과 비교합니다. 내부 초기값은 해당 내부 관찰 대상과 원문에 명시한 초기값으로 확인합니다. 각 대상과 비교 방법을 한 구절에 완결하고, 여러 구절은 '확인하고', '확인하며' 등으로 연결하거나 별도 문장으로 적을 수 있습니다. 다른 대상의 구절에 있는 초기값/시험 전 상태 표현을 빌려 쓰지 않습니다. 근거 없는 표시명이나 사전조건을 추가하지 않습니다.
6. test_cases의 purpose는 CHANGE_VALIDATION만 사용합니다. 유지되는 기존 동작은 RELATED_REGRESSION 후보를 새로 만들지 말고 관련_기존_TC로 분리합니다.
6-1. 범위 변경은 변경된 경계뿐 아니라 변경 후 범위의 하한과 상한을 각각 검증합니다. 같은 관제점의 같은 범위 규칙이면 하한·상한을 하나의 TC 안에서 조건 구간으로 묶을 수 있습니다.
6-2. 현재 V2의 제품 조작 기준은 중앙 관제 패널 하나입니다. 모든 실행 TC는 control_path=CENTRAL을 사용하며 LOCAL·현장 리모컨 TC를 만들지 않습니다.
7. TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙입니다. 같은 관제점·제어 경로·업무 규칙이고 입력값이나 모드만 달라지는 경우에는 하나의 TC로 묶어 중복을 줄입니다. 예시의 특정 모드명·온도값을 고정 규칙으로 사용하지 말고 현재 입력의 Requirement와 confirmed_condition으로 동일 업무 규칙인지 판단합니다.
7-1. 관련 조건을 묶을 때 condition_execution을 사용합니다. 조건마다 독립 초기화가 필요하면 INDEPENDENT_VARIANTS, 앞 상태에서 다음 상태로의 전환 자체를 검증하면 SEQUENTIAL_TRANSITION, 조건 구간이 하나뿐이면 SINGLE_FLOW입니다.
7-2. INDEPENDENT_VARIANTS는 각 조건이 앞 조건의 결과에 의존하지 않도록 steps 안에 초기화·재준비 절차를 넣고, 그 문장을 intermediate_reset_steps에도 정확히 복사합니다. SEQUENTIAL_TRANSITION은 전환 순서가 Requirement의 검증 목적일 때만 사용하며 임의로 독립 조건을 연결하지 않습니다.
7-3. 묶음 TC는 grouping_reason에 같은 TC로 처리하는 근거가 되는 공통 관제점·업무 규칙을 구체적으로 기록합니다. 서로 다른 Requirement 목적, 서로 다른 제어 경로, 실패 원인이 무관한 기능은 별도 TC로 분리합니다.
7-4. 묶음 TC의 각 조건은 steps와 expected_results에서 구분되어야 합니다. 한 조건의 입력·행동·결과를 작성한 뒤 필요한 초기화 또는 전환을 거쳐 다음 조건을 작성합니다. 모든 결과를 TC 마지막 상태에서 한꺼번에 확인하도록 작성하지 않습니다.
7-5. requested_modes와 requested_temperatures_c에는 묶음 TC가 실제로 요청하는 모든 모드·온도 값을 중복 없이 기록합니다. 단일 조건은 기존 requested_mode와 requested_temperature_c를 사용할 수 있습니다. test_data와 절차에 없는 값을 자동화 단계가 추정하게 하지 않습니다.
7-6. 초기 준비·중간 초기화·최종 복원에만 쓰는 값은 시험 조건의 requested 값에 섞지 않습니다. 해당 절차와 초기값으로 기록합니다. 복원값을 요청 목록에 넣어 생긴 검사 오류는 그 값을 분리해 고치며, 오류를 피하려고 반복 시험 조건을 새로 만들지 않습니다.
8. REQ-CONTROL-001을 검증하면 CENTRAL 경로에서 관제 패널을 통한 적용을 다룹니다. 과거 산출물의 LOCAL 값이나 REQ-LOCAL-*를 현재 SRS 근거로 추정하거나 새 TC로 확장하지 않습니다.
9. target_role은 고정 장치 ID를 추측하지 말고 PRIMARY_TEST_DEVICE처럼 역할로 지정합니다.
10. test_data에는 준비·요청에 필요한 모드와 온도를 구조화합니다. TC 절차 안에만 값을 숨기지 않으며, 여러 조건을 묶었으면 모든 조건 값을 복수형 필드에 기록합니다.
11. 상태 변경 또는 차단을 검증하는 TC는 사용자 화면(UI)과 내부 상태(INTERNAL_STATE)를 함께 확인합니다. 이중 검증은 동일 변경을 서로 다른 계층에서 확인하는 원칙이지, 요청에 없는 화면 배지·선택 표시·잠금 상태 표시를 추가하라는 뜻이 아닙니다. 변경된 버튼 disabled 상태가 UI 결과라면 내부 locked 같은 근거 상태와 짝지을 수 있으며 별도 잠금 표시 UI를 요구하지 않습니다. 변경 요청·SRS에 `locked`, `mode`, `setTemp`처럼 내부 필드 식별자가 명시돼 있으면 INTERNAL_STATE 기대 결과에도 그 식별자를 번역하거나 생략하지 않고 정확히 보존합니다.
11-1. 각 TC는 V1의 3단계 QA 기준을 명시적으로 기록합니다. common_qa_criteria에는 정상·예외·경계·복구·권한·사용자 피드백 중 적용 기준을, domain_qa_criteria에는 장비 식별·다중 제어·비대상 보존·UI/내부 상태 정합성·부분 장애 격리 중 적용 기준을, feature_requirement_ids에는 기능별 기준이 되는 해당 TC의 Requirement ID를 기록합니다.
11-2. 각 TC는 이전 TC 결과에 의존하지 않고 단독 실행 가능해야 합니다. independent_execution=true와 구체적인 independence_reason을 기록하고, 필요한 초기 상태는 preconditions·test_data로, 상태가 바뀌면 restore_steps로 복원합니다.
11-3. UI와 내부 상태를 함께 확인해야 하면 double_assert_policy=REQUIRED를 사용합니다. UI 전용·내부 상태 전용·해당 없음은 각각 UI_ONLY·INTERNAL_ONLY·NOT_APPLICABLE로 구분하고 double_assert_reason에 예외 사유를 기록합니다.
12. 안내 표시 조건을 검증하는 TC는 NOTIFICATION 기대 결과를 포함합니다. 정확한 Toast 문구가 입력에 없으면 문구를 만들어 일치 검증하지 않습니다.
13. 모든 새 TC는 state_effect를 분류합니다. 조회만 하면 READ_ONLY, 값을 바꾸면 STATE_CHANGE, 변경 차단을 확인하면 BLOCKED_CHANGE입니다. READ_ONLY는 restore_required=false와 빈 restore_steps를 사용하고 준비 과정에서도 값을 바꾸지 않습니다. STATE_CHANGE와 BLOCKED_CHANGE는 restore_required=true로 작성합니다. BLOCKED_CHANGE도 제품 오류로 값이 바뀔 수 있으므로 복원 절차가 필요하며, 실행기는 상태가 그대로이면 복원 조작을 생략합니다. 시험 전 실제 상태를 기록하고 변경한 대상만 복원한 뒤 같은 관찰 위치에서 비교합니다. 임의 기본값으로 초기화하지 않습니다. 복원은 제품 expected_results가 아닌 restore_steps에 기록합니다. 차단 TC에는 알림만 아니라 변경 대상 상태가 유지되는지 판정할 근거가 있어야 합니다. 안전한 읽기·복원 방법이 현재 지원 범위에 없으면 automation_candidate=false와 사유를 작성합니다. 복원 실패는 기록하고 같은 실행 환경을 재사용하지 않습니다.
14. TC가 참조하는 Requirement와 Condition은 입력에 존재하는 ID만 사용합니다.
15. confirmed_condition을 여러 TC가 공유할 수 있지만 동일 목적의 TC를 표현만 바꿔 중복 생성하지 않습니다.
16. automation_candidate는 현재 가상 중앙제어 화면과 내부 상태 조회로 자동화 가능한지 판단한 후보 표시일 뿐이며 코드를 만들지 않습니다.
16-1. 신규·수정 후보가 필요한 경우에는 현재 단일 장비 MVP가 실행할 수 있도록 target_role=PRIMARY_TEST_DEVICE인 automation_candidate TC를 우선 설계합니다. 다만 변경 후 조건을 관련 기존 TC가 전부 검증하면 억지로 신규 후보를 만들지 않습니다.
17. SRS 문구의 후속 개정 필요, 정확한 안내 문구 미지정처럼 기대 동작을 바꾸지 않고 현재 TC를 설계할 수 있는 참고 사항은 coverage_notes에 남깁니다.
17-1. Agent 1의 excluded_scope와 `제외된_정보_부족`은 TC로 만들지 말고 Agent 2의 `제외_범위`와 `제외된_정보_부족`에 원문 그대로 인계합니다. 다만 시험 준비·종료 후 복원 문장이 과거 Agent 1 결과의 excluded_scope에 들어 있어도 실제 제외 범위로 인계하지 말고 규칙 4의 TC 절차로 보존합니다. 제외 범위의 상태 유지 여부를 확인하는 기대 결과도 새로 만들지 않습니다. 확정된 긍정적 변경 결과만 test_cases에 포함합니다.
18. 현재 TC의 기대 결과와 실행 범위가 이미 근거로 확정됐지만 사람이 최종 보고에서 확인하면 좋은 사항은 `최종_확인_사항`에 남깁니다. 이 항목은 후속 자동 실행을 중단하지 않습니다.
19. 서로 충돌하는 권한 입력, 기대 결과 미정처럼 TC 의미를 확정할 수 없어 후속 자동 진행을 중단해야 하는 항목만 `중단_확인_사항`에 남깁니다.
20. UPDATE_REQUIRED 자체는 변경관리의 정상 결과이므로 그것만으로 `중단_확인_사항` 또는 `최종_확인_사항`을 만들지 않습니다.
21. existing_tc_comparison_completed=true로 기록합니다. 관련_기존_TC에는 제공된 기존 TC ID만 사용하고 각 선택이 어떤 유지·영향 조건을 회귀 확인하는지 source_condition_ids와 selection_reason으로 설명합니다. 변경 대상 Requirement를 포함하는 기존 TC도 `검증 동작`을 대조하되 변경 후에도 그대로 유효한 경우에만 선택합니다. 재사용할 수 없으면 억지로 선택하지 말고 TC ID와 미선택 이유를 coverage_notes에 기록합니다.
22. [코드로 확인한 SRS 개정 범위]의 required_requirement_ids에만 `SRS_개정_제안`을 정확히 한 건씩 기록합니다. MODIFIED·UPDATE_REQUIRED는 시험 영향 구분이지 SRS 개정 필요의 확정이 아닙니다. already_reflected_requirement_ids는 요청 after_value 전체 문장과 현재 인수 기준이 앞뒤 공백을 제외하고 일치한 대상입니다. 이 대상은 개정안 없이 기존 TC 대조·필요한 시험 설계를 계속하고, 이미 반영돼 SRS 개정이 불필요하다는 사실을 coverage_notes에 설명합니다. 같은 문장을 수정안으로 제출하거나 이를 사람이 새로 승인해야 한다고 쓰지 않습니다. 요청 밖 내용을 추가하거나 표현만 바꿔 개정안을 만들지 않습니다. 해당 목록 밖의 문장 유사성·TC 재사용 여부만으로 개정을 생략하지 않습니다. 실제 개정안의 current_acceptance_criteria는 SRS 원문과 완전히 같아야 하며, proposed_acceptance_criteria는 확정 Condition과 변경 요청에 근거한 새 판정 문구여야 합니다. Requirement 문장 자체는 바꾸지 않습니다. source_condition_ids로 근거를 연결하고, 사람이 승인하기 전 SRS가 변경된 것처럼 표현하지 않습니다.
작성 수준 예시 (아래는 기존 필드의 일부만 발췌한 형식 참고이며 이번 입력의 제품 기준이 아닙니다):
예시 A의 입력이 '오류·잠금 없는 단일 장비, 초기 LOW, MED 적용 직후 카드 중풍·내부 fanSpeed=MED, 종료 후 LOW 복원'을 명시한 경우:
preconditions:
- 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.
- 첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작합니다.
steps:
1. 중앙 관제 화면에서 시험할 대상 장비 카드를 선택한다.
2. 선택한 장비의 제어 패널에서 풍량을 MED로 선택한다.
3. 제어 패널의 적용 버튼을 눌러 선택한 풍량을 대상 장비에 적용한다.
expected_results:
- ER-001: 대상 장비 카드의 풍량 표시에 중풍이 표시된다. observation_target='대상 장비 카드의 풍량 표시', observation_layer=UI.
- ER-002: 대상 장비의 내부 fanSpeed는 MED이다. observation_target='대상 장비의 내부 fanSpeed', observation_layer=INTERNAL_STATE.
두 결과의 verify_after_step에는 3번 문장을 번호 없이 정확히 복사하고 각 source_condition_ids는 이번 입력의 해당 제품 조건에 연결합니다. 사람이 보는 3-1·3-2는 단계별 결과 표기이며 JSON의 ER ID를 바꾸지 않습니다.
restore_steps:
- 시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용합니다.
- 복원 후 대상 장비의 내부 fanSpeed가 초기값 LOW로 돌아왔는지 확인한다.
화면 복원도 확인할 경우에는 '복원 후 대상 장비 카드의 풍량 표시가 실행 전 상태와 같은지 확인한다'를 별도 확인 문장으로 씁니다. 내부 LOW 코드로 화면 표시명을 추정하지 않습니다.
대상 선택 성공·알림·선택 색상·LOW의 한글 표시를 새 expected_results로 만들지 않습니다. HIGH 유지 조건을 검증하는 승인 TC가 있다면 관련_기존_TC로 재사용합니다.

예시 B: 입력이 '초기 설정 온도 24°C, 30°C 적용 후 카드·내부 설정 온도 30°C'를 요구하면 대상 선택 → 설정 온도 30°C 입력 → 적용으로 작성합니다. 적용 직후 카드 설정 온도와 내부 설정 온도를 각각 확인합니다. 복원은 대상 장비에 초기 24°C를 적용한 뒤 같은 내부 설정 온도가 24°C인지 확인합니다. 예시 A의 풍량·MED·LOW·문구를 복사하지 않습니다.
예시 C: 입력이 현재 상태를 조회하는 읽기 전용 시험이면 조회 단계와 그 단계의 기대결과만 작성합니다. 대상 선택이 실제로 필요한 경우만 기록하며 값 입력·적용·복원을 억지로 추가하지 않습니다.
세 예시는 상세한 작성 방식만 보여줍니다. 값·화면명·필드명·조건 ID·초기 상태는 반드시 현재 입력에서 가져오며, 예시를 근거로 제품 판정이나 시험 범위를 추가하지 않습니다.
""".strip()


class Agent2Error(RuntimeError):
    """Raised when Agent 2 cannot produce a validated structured response."""


def _existing_reuse_link_context(
    analysis: Agent1Analysis,
    existing_catalog: tuple[ExistingRegressionSpec, ...],
    design: Agent2TestDesign | None = None,
) -> list[dict[str, Any]]:
    """Read-only value/link diagnostics, not semantic approval or auto-linking."""
    catalog = {item.tc_id: item for item in existing_catalog}
    rows = []
    for condition in analysis.confirmed_conditions:
        values = _explicit_behavior_values(condition.statement)
        row: dict[str, Any] = {
            "condition_id": condition.condition_id,
            "detected_values": sorted(values),
        }
        if design is not None:
            linked = [item.tc_id for item in design.related_existing_tests
                      if condition.condition_id in item.source_condition_ids]
            behaviors = " ".join(
                behavior for tc_id in linked if tc_id in catalog
                for behavior in catalog[tc_id].covered_behaviors
            )
            row.update(
                linked_existing_tc_ids=linked,
                values_not_covered_by_links=sorted(values - _explicit_behavior_values(behaviors)),
                candidate_tc_ids=[tc.tc_id for tc in design.test_cases
                                  if condition.condition_id in tc.source_condition_ids],
            )
        rows.append(row)
    return rows


def _srs_revision_policy(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    requirements: dict[str, SrsRequirement],
) -> dict[str, Any]:
    """Conservative document comparison, independent of model/proposal claims.

    Only the target's complete requested after-value can prove it is already in
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


class OpenAIAgent2:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent2Error(
                    "OPENAI_API_KEY 환경변수가 없습니다. 키를 코드에 넣지 말고 "
                    "PowerShell 환경변수로 설정하세요."
                )
            client = OpenAI()
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
    ) -> Agent2Response:
        procedure_notes = list(analysis.procedure_notes)
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
            f"{json.dumps(_existing_reuse_link_context(analysis, existing_catalog, previous_design), ensure_ascii=False)}\n"
            "복합 조건을 여러 기존 TC가 나누어 검증하면 실제 담당 TC 모두의 source_condition_ids에 "
            "그 조건 ID를 넣으세요. TC 선택 목록에 있다는 이유만으로 그 조건을 검증한 것으로 계산하지 않습니다. "
            "형식 예시: 조건 C가 동작 A와 B를 요구하고 TC-X가 A, TC-Y가 B를 검증하면 "
            "TC-X와 TC-Y 모두 C에 연결합니다. 별도 B 전용 조건에 TC-Y를 연결한 것만으로 C가 충족되지는 않습니다. "
            "C·A·B·TC-X·TC-Y는 형식 설명이며 출력에 복사하지 마세요. "
            "위 목록은 코드·수치의 제한된 추출과 기존 연결 진단이며 권장 TC 목록이나 합격 판정이 아닙니다. "
            "빈 detected_values도 검증 불필요를 뜻하지 않습니다. 값만 같고 대상·조작·판정·복원이 다르면 재사용하지 마세요. "
            "신규 후보가 담당하는 조건은 후보의 실제 근거도 함께 대조하세요. "
            "제출 전 복합 조건과 개별 조건을 각각 역으로 따라가 담당 TC 및 검증 범위가 빠짐없이 연결되는지 확인하세요. "
            "연결을 맞추려고 원문 조건·값을 삭제하거나 무관한 TC를 추가하지 마세요. "
            "기존 TC로 실제 검증하지 못하는 동작은 근거 있는 후보 설계 또는 확인 필요 사항으로 남깁니다."
            "새 실행은 설명의 동의어·문체를 실패로 판정하지 않습니다. 상세 작성 예시는 유지하되 "
            "출처 ID, 확인 대상, 판정 단계, 기대값과 복원 연결을 보존하세요. "
            "procedure_notes의 각 원문은 사전조건·조작·복원 중 실제 해당 위치에 보존합니다. "
            "기존 TC만 재사용할 때는 해당 절차의 실제 수행 여부를 최종 검토로 남깁니다."
        )
        user_input += (
            "\n\n[공통 확인 대상·시점·복원 연결 규칙]\n"
            f"{json.dumps(TC_OBSERVATION_BINDING_RULES, ensure_ascii=False)}\n"
        )
        if previous_design is not None:
            user_input += "\n[검사기에서 계산한 TC별 연결 오류]\n" + json.dumps([
                {"tc_id": tc.tc_id,
                 "errors": [*_tc_observation_binding_errors(tc, legacy_wording_checks=False),
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
                prompt_cache_key="qa-v2-agent2-2-35",
                input=[
                    {"role": "system", "content": AGENT2_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent2TestDesign,
            )
        except Exception as exc:
            raise Agent2Error(f"Agent 2 모델 호출에 실패했습니다: {exc}") from exc

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent2Error("모델이 구조화된 Agent 2 결과를 반환하지 않았습니다.")
        return Agent2Response(
            design=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
        )


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

_PROCEDURAL_SELECTION_RESULT = re.compile(
    r"선택(?:된다|되었|되어|상태)", re.IGNORECASE
)
_PROCEDURAL_ACTION_SUCCESS_RESULT = re.compile(
    r"(?:선택|적용|클릭|입력|설정|변경|전환|요청|조작|복원)"
    r"[^.!?\n]{0,40}(?:할\s*수\s*있|가능(?:하|해|했|됨|되))",
    re.IGNORECASE,
)
_UI_DISPLAY_RESULT = re.compile(
    r"(?:(?:화면|\bUI\b)[^.!?]{0,80}(?:표시|보이|나타)|"
    r"(?:표시)[^.!?]{0,40}(?:된다|상태))",
    re.IGNORECASE,
)
_UI_DISPLAY_AUTHORITY = re.compile(
    r"(?:화면|\bUI\b|표시|보이|나타)", re.IGNORECASE
)


def _is_unchanged_condition(condition: ConfirmedCondition) -> bool:
    return condition.change_role == ConditionChangeRole.UNCHANGED


def _is_unchanged_condition_for_request(
    condition: ConfirmedCondition,
    request: ChangeRequest,
) -> bool:
    del request  # The role is structured by Agent 1; word-set similarity is unsafe.
    return _is_unchanged_condition(condition)


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


def _existing_test_procedure_review_notes(
    request: ChangeRequest, design: Agent2TestDesign, *, legacy: bool = False
) -> list[str]:
    """기존 TC 코드를 변경하거나 절차 수행을 추정하지 않고 원문을 인계합니다."""
    if design.test_cases or not design.related_existing_tests:
        return []
    selected = ", ".join(dict.fromkeys(item.tc_id for item in design.related_existing_tests))
    return list(dict.fromkeys(
        f"기존 TC 시험 절차 확인 ({selected}): {note} "
        "[기존 자동화의 해당 절차 수행 여부는 자동 확정하지 않았습니다. 증거를 확인해 주세요.]"
        for note in request.acceptance_notes if _is_test_procedure_note(note, legacy=legacy)
    ))


def _tc_observation_binding_errors(tc: ProductTestCaseCandidate, *, legacy_wording_checks: bool = True) -> list[str]:
    """One binding check for CP2 and repair diagnostics; no fuzzy target aliases."""
    vague = {"화면", "ui", "내부", "값", "상태", "결과", "요청결과", "내부값", "대상", "확인대상"}
    errors = []
    for result in tc.expected_results:
        label = f"{tc.tc_id}/{result.result_id}"
        if not result.verify_after_step or sum(
            _normalize(step) == _normalize(result.verify_after_step) for step in tc.steps
        ) != 1:
            errors.append(f"{label}: 실제 절차 한 곳에 판정 시점을 연결")
        if (not result.observation_target or not result.observation_target.strip()
                or (legacy_wording_checks and (_normalize(result.observation_target) in vague
                or not _contains_fact(result.statement, result.observation_target)))):
            if not legacy_wording_checks:
                errors.append(f"{label}: 확인 대상 observation_target 누락")
                continue
            errors.append(f"{label}: 기대결과에 동일한 표현의 구체적인 확인 대상 명시. "
                          f"현재 대상={result.observation_target!r}; 원문={result.statement!r}. "
                          "원문 안의 실제 확인 대상 구절을 연결하고 원문·값을 변경하지 마세요.")
    return errors


def _tc_procedure_detail_errors(tc: ProductTestCaseCandidate) -> list[str]:
    """Limited authoring checks over existing text fields, not a semantic parser.

    They do not create product expectations or prove browser state. CP3 and the
    trial still have to connect and observe the actual preparation/restoration.
    """
    errors: list[str] = []
    target_object = r"(?:대상\s*)?(?:장비|기기|실내기)(?:\s*카드)?(?:을|를)\s*"
    target_select = re.compile(
        target_object + r"(?:선택|클릭)|\b(?:select|click)\s+(?:the\s+)?(?:target\s+)?device(?:\s+card)?\b", re.I
    )
    selected_state = re.compile(
        r"(?:장비|기기|실내기)(?:\s*카드)?(?:가|는|를|을)?\s*(?:이미\s*)?"
        r"(?:선택된|선택되어|선택돼|선택한\s*상태)"
        r"|\b(?:target\s+)?device\s+(?:is\s+)?(?:already\s+)?selected\b", re.I
    )
    selection_negation = re.compile(
        r"(?:선택|클릭)(?:하지|되지|할\s*필요|할\s*수\s*없)"
        r"|선택(?:된|한)\s*상태(?:가|는)?\s*아니|미선택|\b(?:not|without)\b", re.I
    )
    operation = re.compile(
        r"(?:선택|입력|설정|변경|적용|요청)(?:한다|합니다|하기|한\s*뒤|하고)"
        r"|(?:입력|적용|선택)\s*버튼|\b(?:select|enter|fill|set|apply|submit|toggle|uncheck)\b"
        r"|\bcheck\s+(?:the\s+)?checkbox\b", re.I
    )
    selections, operations = [], []
    for index, step in enumerate(tc.steps):
        match = target_select.search(step)
        # Removing the target-selection phrase leaves any second operation
        # visible, so selecting the device and its value on one line is not
        # accepted as two distinct steps.
        remainder = target_select.sub("", step)
        if match and not selection_negation.search(step) and not operation.search(remainder):
            selections.append(index)
        elif operation.search(step):
            operations.append(index)
    prepared = any(selected_state.search(line) and not selection_negation.search(line) for line in tc.preconditions)
    device_context = bool(re.search(
        r"장비|기기|실내기|\bdevice\b",
        " ".join([tc.title, *tc.preconditions, *tc.steps,
                  *(result.observation_target or "" for result in tc.expected_results)]), re.I
    )) or any(value is not None for value in (tc.test_data.requested_mode, tc.test_data.requested_temperature_c)) or bool(
        tc.test_data.requested_modes or tc.test_data.requested_temperatures_c
    )
    if tc.control_path == ControlPath.CENTRAL and device_context and operations and not prepared:
        if not any(index < operations[0] for index in selections):
            errors.append(f"{tc.tc_id}: 값 조작 전에 대상 장비 선택을 별도 단계로 명시하거나 근거 있는 선택 완료 상태를 사전조건에 명시")

    if tc.restore_required and tc.restoration is None:
        check_word = re.compile(r"확인|비교|검증|\b(?:verify|compare|confirm|check)\b", re.I)
        check_negation = re.compile(r"확인하지|비교하지|검증하지|확인할\s*수\s*없|미확인|생략|\b(?:not|without|skip)\b", re.I)
        original_basis = re.compile(RESTORE_BASELINE_PATTERN + r"|초기값|원래|처음|\b(?:initial|original)\b", re.I)
        observed_basis = re.compile(
            rf"(?:{RESTORE_BASELINE_PATTERN})[^.\n]*(?:관찰|기록|저장)"
            r"|(?:관찰|기록|저장)[^.\n]*(?:원상태|초기값)"
            r"|\b(?:observed|recorded|saved)\s+(?:initial\s+)?(?:state|value|baseline)\b", re.I
        )
        target = re.compile(r"장비|기기|실내기|대상|\b(?:device|target)\b", re.I)
        observation = re.compile(r"내부|화면|카드|패널|표시|설정값|\b(?:state|value|panel|card|display)\b", re.I)
        # Identifiers already in a TC's observation location also qualify; no
        # feature/TC-ID/value whitelist is used (fanSpeed is not special).
        identifiers = {
            word for result in tc.expected_results
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", result.observation_target or "")
            if word.casefold() not in {"ui", "target", "device", "the"}
        }
        initial_values = _explicit_behavior_values(" ".join(tc.preconditions))
        for value in (tc.test_data.initial_mode, tc.test_data.initial_temperature_c):
            if value is not None:
                initial_values.update(_explicit_behavior_values(str(value)))
        restore_values = _explicit_behavior_values(" ".join(tc.restore_steps))
        # This is a drafting completeness check. Actual value grounding and
        # baseline equality must also be checked by CP3, never inferred here.
        has_basis = bool(restore_values or original_basis.search(" ".join(tc.restore_steps)))
        has_target = any(target.search(line) for line in tc.restore_steps) or any(
            result.observation_target and _contains_fact(line, result.observation_target)
            for line in tc.restore_steps for result in tc.expected_results
        )
        detailed_check = False
        for line in tc.restore_steps:
            if not check_word.search(line) or check_negation.search(line):
                continue
            values = _explicit_behavior_values(line)
            location = observation.search(line) or any(re.search(rf"\b{re.escape(word)}\b", line, re.I) for word in identifiers) or any(
                result.observation_target and _contains_fact(line, result.observation_target)
                for result in tc.expected_results
            )
            basis = bool(values) or observed_basis.search(line) or (
                original_basis.search(line) and bool(initial_values)
            )
            if location and basis and not (initial_values and values - initial_values):
                detailed_check = True
        if not (has_target and has_basis and detailed_check):
            errors.append(f"{tc.tc_id}: restore_steps에 복원 대상·초기값/실행 전 상태와 구체적인 관찰 위치의 복귀 확인을 명시 (원문 복원 메모는 유지)")
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
    require_srs_revision_proposals: bool = False,
    allow_already_reflected_srs: bool = False,
    require_existing_behavior_values: bool = False,
    allow_existing_procedure_review: bool = True,
    require_double_assert_timing: bool = True,
    require_meaning_guard: bool = True,
    require_candidate_expectation_guard: bool = True,
    require_tc_detail: bool = True,
    require_procedure_detail: bool = True,
    require_restore_target_basis: bool = False,
    require_state_restoration_policy: bool = False,
    require_structured_restoration: bool = False,
    require_input_contract: bool = True,
    legacy_wording_checks: bool = True,
) -> Checkpoint2Result:
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if design.request_id == analysis.request_id == request.request_id:
        add("CP2-001", CheckStatus.PASS, "변경 요청·Agent 1·Agent 2의 요청 ID가 일치합니다.")
    else:
        add("CP2-001", CheckStatus.FAIL, "Agent 2의 변경 요청 ID가 앞 단계 입력과 다릅니다.")

    tc_ids = [tc.tc_id for tc in design.test_cases]
    result_ids = [result.result_id for tc in design.test_cases for result in tc.expected_results]
    duplicate_tc_ids = sorted({item for item in tc_ids if tc_ids.count(item) > 1})
    duplicate_result_ids = sorted({item for item in result_ids if result_ids.count(item) > 1})
    normalized_titles = [re.sub(r"\s+", "", tc.title).casefold() for tc in design.test_cases]
    duplicate_titles = sorted(
        {
            design.test_cases[index].title
            for index, item in enumerate(normalized_titles)
            if normalized_titles.count(item) > 1
        }
    )
    if duplicate_tc_ids or duplicate_result_ids or duplicate_titles:
        add("CP2-002", CheckStatus.FAIL, "TC·기대 결과 ID 또는 제목이 중복됩니다.")
    else:
        add("CP2-002", CheckStatus.PASS, "TC·기대 결과 ID와 제목이 고유합니다.")

    known_conditions = {item.condition_id: item for item in analysis.confirmed_conditions}
    requirement_relations = {
        item.requirement_id: item.relation for item in analysis.requirement_effects
    }
    trace_only_requirements = {
        item.requirement_id for item in analysis.requirement_effects
        if item.scope_evidence is not None
        and item.scope_evidence.basis == ScopeBasis.REQUEST_TRACE_ONLY
    }
    trace_only_conditions = {
        item.condition_id for item in analysis.confirmed_conditions
        if trace_only_requirements.intersection(item.requirement_ids)
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
    changed_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.change_role == ConditionChangeRole.CHANGED
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

    state_errors: list[str] = []
    notify_errors: list[str] = []
    compound_ui_errors: list[str] = []
    ui_observation_groups = {
        "mode": re.compile(
            r"(?:(?:화면|UI|관제\s*패널)[^.!?]{0,60}(?:표시[^.!?]{0,30})?(?:모드|\bmode\b)\s*(?:는|가|값|상태|[:=])|(?:모드|\bmode\b)\s*(?:표시|값|상태))",
            re.IGNORECASE,
        ),
        "temperature": re.compile(r"(?:설정\s*온도|\bsetTemp\b)", re.IGNORECASE),
        "pending": re.compile(r"(?:대기값|대기\s*상태|\bpending\b)", re.IGNORECASE),
        "control_state": re.compile(r"(?:버튼|컨트롤|활성|비활성|\bdisabled\b|\benabled\b)", re.IGNORECASE),
    }
    for tc in design.test_cases:
        source_requirements = {
            req_id
            for condition_id in tc.source_condition_ids
            if condition_id in known_conditions
            for req_id in known_conditions[condition_id].requirement_ids
        }
        layers = {result.observation_layer for result in tc.expected_results}
        requires_double_assert = (
            "REQ-STATE-001" in (source_requirements - trace_only_requirements)
            or tc.test_type == TcType.STATE_CONSISTENCY
        )
        if requires_double_assert and not {
            ObservationLayer.UI,
            ObservationLayer.INTERNAL_STATE,
        }.issubset(layers):
            state_errors.append(tc.tc_id)
        if "REQ-NOTIFY-001" in (source_requirements - trace_only_requirements) and ObservationLayer.NOTIFICATION not in layers:
            notify_errors.append(tc.tc_id)
        for result in tc.expected_results:
            if result.observation_layer != ObservationLayer.UI:
                continue
            matched_groups = [
                name
                for name, pattern in ui_observation_groups.items()
                if pattern.search(result.statement)
            ]
            if legacy_wording_checks and len(matched_groups) > 1:
                compound_ui_errors.append(
                    f"{tc.tc_id}/{result.result_id}:" + ",".join(matched_groups)
                )
    policy_errors: list[str] = []
    for tc in design.test_cases:
        layers = {result.observation_layer for result in tc.expected_results}
        if require_double_assert_timing and tc.double_assert_policy == DoubleAssertPolicy.REQUIRED:
            # None means the existing single-flow end-of-test assertion point.
            timing = {
                layer: {result.verify_after_step for result in tc.expected_results
                        if result.observation_layer == layer}
                for layer in (ObservationLayer.UI, ObservationLayer.INTERNAL_STATE)
            }
            if timing[ObservationLayer.UI] != timing[ObservationLayer.INTERNAL_STATE]:
                policy_errors.append(f"{tc.tc_id}:UI·내부 상태 이중 검증의 판정 단계 불일치; 같은 조작 직후 함께 확인 필요")
        requires_double_assert = (
            "REQ-STATE-001" in tc.requirement_ids
            or tc.test_type == TcType.STATE_CONSISTENCY
        )
        if requires_double_assert and tc.double_assert_policy != DoubleAssertPolicy.REQUIRED:
            policy_errors.append(f"{tc.tc_id}:필수 이중 검증 정책 누락")
        elif tc.double_assert_policy == DoubleAssertPolicy.REQUIRED and not {
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
        if (
            tc.double_assert_policy != DoubleAssertPolicy.REQUIRED
            and not tc.double_assert_reason
        ):
            policy_errors.append(f"{tc.tc_id}:이중 검증 예외 사유 누락")
    if state_errors or policy_errors or compound_ui_errors:
        details = [*state_errors, *policy_errors]
        details.extend(
            f"{item}:UI 기대 결과를 관찰값별로 분리 필요"
            for item in compound_ui_errors
        )
        add(
            "CP2-006",
            CheckStatus.FAIL,
            "조건부 이중 검증 또는 원자적 기대 결과 계약이 맞지 않습니다: " + ", ".join(details),
        )
    else:
        add(
            "CP2-006",
            CheckStatus.PASS,
            "상태 관련 TC의 이중 검증·예외 정책과 원자적 UI 기대 결과가 일치합니다.",
        )
    if notify_errors:
        add("CP2-007", CheckStatus.FAIL, "알림 기대 결과가 누락된 TC: " + ", ".join(notify_errors))
    else:
        add("CP2-007", CheckStatus.PASS, "알림 조건이 NOTIFICATION 결과로 연결됩니다.")

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
            set(selection.source_condition_ids).intersection(changed_condition_ids)
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
        and bool(set(selection.source_condition_ids).intersection(changed_condition_ids))
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
            tc.purpose == TcPurpose.CHANGE_VALIDATION
            and tc.control_path == control_path
            and request.target_requirement_id in tc.requirement_ids
            and requirement_id in tc.requirement_ids
            for tc in design.test_cases
        )
        existing_has_path = any(
            request.target_requirement_id in spec.requirement_ids
            and requirement_id in spec.requirement_ids
            and bool(
                set(selection.source_condition_ids).intersection(
                    changed_condition_ids
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
        and tc.purpose == TcPurpose.CHANGE_VALIDATION
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
    if tier_errors:
        add(
            "CP2-012",
            CheckStatus.FAIL,
            "3단계 QA 기준 적용 근거가 누락되거나 TC 추적 범위와 다릅니다: "
            + ", ".join(tier_errors),
        )
    else:
        add("CP2-012", CheckStatus.PASS, "모든 TC에 공통·도메인·기능별 QA 기준이 추적됩니다.")

    dependency_pattern = re.compile(
        r"(?:이전|앞선|선행)\s*(?:TC|테스트)|TC-CAND-\d{3}",
        re.IGNORECASE,
    )
    non_dependency_pattern = re.compile(
        r"(?:의존|필요|전제|이어받)[^.!?\n]{0,16}(?:않|없)|없이|무관|독립",
        re.IGNORECASE,
    )
    independence_errors: list[str] = []
    for tc in design.test_cases:
        dependency_texts = [
            *tc.preconditions,
            *tc.steps,
            *tc.restore_steps,
            tc.independence_reason or "",
        ]
        has_cross_tc_dependency = any(
            dependency_pattern.search(text)
            and not non_dependency_pattern.search(text)
            for text in dependency_texts
        )
        if (
            not tc.independent_execution
            or not tc.independence_reason
            or has_cross_tc_dependency
        ):
            independence_errors.append(tc.tc_id)
    if independence_errors:
        add(
            "CP2-013",
            CheckStatus.FAIL,
            "단독 실행 근거가 없거나 다른 TC에 의존합니다: "
            + ", ".join(independence_errors),
        )
    else:
        add("CP2-013", CheckStatus.PASS, "모든 TC가 초기 조건과 복원 기준을 가진 독립 실행 단위입니다.")

    procedure_notes = [
        note for note in request.acceptance_notes
        if (_is_test_procedure_note(note, legacy=not require_input_contract) if legacy_wording_checks
            else re.match(r"\s*\[(?:준비|복원|시험 절차 메모)\]", note))
    ]
    if not legacy_wording_checks:
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
    setup_lines = {
        _normalize(item)
        for tc in design.test_cases
        for item in [*tc.preconditions, *tc.steps]
    }
    restore_lines = {
        _normalize(item)
        for tc in design.test_cases
        for item in tc.restore_steps
        if tc.restore_required
    }
    missing_setup_notes = [
        note
        for note in procedure_notes
        if (_is_test_setup_note(note, legacy=not require_input_contract) if legacy_wording_checks
            else re.match(r"\s*\[준비\]", note)) and _normalize(note) not in setup_lines
    ]
    missing_restore_notes = [
        note
        for note in procedure_notes
        if (_is_test_restore_note(note, legacy=not require_input_contract) if legacy_wording_checks
            else re.match(r"\s*\[복원\]", note)) and _normalize(note) not in restore_lines
    ]
    if not legacy_wording_checks:
        # Preserve every declared procedure, without classifying its verbs.
        # Actual ordering, permitted actions and restoration are checked by CP3.
        missing_setup_notes = [note for note in procedure_notes
                               if _normalize(note) not in setup_lines | restore_lines]
        missing_restore_notes = []
    procedure_review = (
        _existing_test_procedure_review_notes(request, design, legacy=not require_input_contract)
        if allow_existing_procedure_review else []
    )
    if not legacy_wording_checks and allow_existing_procedure_review and not design.test_cases and design.related_existing_tests:
        procedure_review = list(procedure_notes)
    if procedure_review:
        # 기존 코드에는 신규 TC의 절차 필드가 없습니다. 원문은 execute가 최종 검토로 인계합니다.
        missing_setup_notes = []
        missing_restore_notes = []
    if (
        not excluded_scope_matches
        or not excluded_gaps_match
        or excluded_procedure_notes
        or missing_setup_notes
        or missing_restore_notes
    ):
        details: list[str] = []
        if not excluded_scope_matches or not excluded_gaps_match:
            details.append("실제 제외 범위 또는 정보 부족 인계 불일치")
        if excluded_procedure_notes:
            details.append("시험 절차를 제외 범위로 분류")
        if missing_setup_notes:
            details.append("사전 준비 절차 누락=" + " | ".join(missing_setup_notes))
        if missing_restore_notes:
            details.append("종료 후 복원 절차 누락=" + " | ".join(missing_restore_notes))
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
            + (" 기존 TC의 시험 절차 메모는 수행 완료로 간주하지 않고 최종 사람 검토로 전달합니다." if procedure_review else ""),
        )

    grouping_errors: list[str] = []
    for tc in design.test_cases:
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
            if not (
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
    regenerated_regressions = [
        tc.tc_id
        for tc in design.test_cases
        if tc.purpose != TcPurpose.CHANGE_VALIDATION
    ]
    if regenerated_regressions:
        existing_selection_errors.append(
            "기존 회귀를 신규 후보로 재작성=" + ",".join(regenerated_regressions)
        )
    verify_only_candidates = [
        tc.tc_id
        for tc in design.test_cases
        if tc.requirement_ids
        and all(
            requirement_relations.get(requirement_id)
            == RequirementRelation.VERIFY
            for requirement_id in tc.requirement_ids
        )
    ]
    if verify_only_candidates:
        existing_selection_errors.append(
            "VERIFY 유지 동작을 신규 후보로 중복 생성="
            + ",".join(verify_only_candidates)
        )
    unchanged_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if _is_unchanged_condition_for_request(condition, request)
    }
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
    duplicated_unchanged_results = [
        f"{tc.tc_id}/{result.result_id}"
        for tc in design.test_cases
        for result in tc.expected_results
        if result.source_condition_ids
        and set(result.source_condition_ids).issubset(unchanged_condition_ids)
        and set(result.source_condition_ids).intersection(existing_conditions)
    ]
    if duplicated_unchanged_results:
        existing_selection_errors.append(
            "관련 기존 TC로 선택한 유지 동작을 신규 기대 결과로 중복="
            + ",".join(duplicated_unchanged_results)
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
            "변경된 조건만 신규·수정 후보로 만들고 유지 조건은 기존 TC 선택으로 분리했습니다.",
        )

    if require_existing_behavior_values:
        reuse_errors: list[str] = []
        for condition_id in sorted(direct_change_condition_ids - candidate_conditions):
            condition = known_conditions[condition_id]
            behaviors = " ".join(
                behavior
                for selection in design.related_existing_tests
                if condition_id in selection.source_condition_ids
                for behavior in (
                    existing_by_id[selection.tc_id].covered_behaviors
                    if selection.tc_id in existing_by_id else ()
                )
            )
            missing_values = _explicit_behavior_values(condition.statement) - _explicit_behavior_values(behaviors)
            if legacy_wording_checks and require_meaning_guard and _meaning_conflicts(condition.statement, behaviors, compare_relations=require_input_contract):
                reuse_errors.append(f"{condition_id}:기존 TC 검증 동작의 의미가 반대입니다")
            if missing_values:
                reuse_errors.append(f"{condition_id}:기존 TC가 검사하지 않는 명시 값=" + ",".join(sorted(missing_values)))
        add(
            "CP2-019", CheckStatus.FAIL if reuse_errors else CheckStatus.PASS,
            "기존 TC 재사용 근거 불일치: " + "; ".join(reuse_errors)
            if reuse_errors else "기존 TC만 담당하는 변경 조건의 명시 코드·수치가 카탈로그 검증 동작에 있습니다.",
        )

    minimality_errors: list[str] = []
    scope_limit_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.source_type == ConditionSource.CHANGE_REQUEST
        and legacy_wording_checks and _is_scope_exclusion_text(
            f"{condition.statement} {condition.source_text}", legacy=not require_input_contract
        )
    }
    if require_input_contract:
        explicit_exclusions = {_normalize(note) for note in request.out_of_scope}
        scope_limit_condition_ids |= {
            c.condition_id for c in analysis.confirmed_conditions
            if c.source_type == ConditionSource.CHANGE_REQUEST and _normalize(c.source_text) in explicit_exclusions
        }
    for tc in design.test_cases:
        for result in tc.expected_results:
            result_condition_ids = set(result.source_condition_ids)
            if result_condition_ids & trace_only_conditions and (
                len(result_condition_ids) != 1
                or (legacy_wording_checks and result.statement != known_conditions[next(iter(result_condition_ids))].source_text)
            ):
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:근거 연결 조건은 요청 원문 한 문장을 그대로 검증해야 합니다. "
                    "새 검사·기대값을 덧붙이지 마세요."
                )
            excluded_sources = sorted(
                result_condition_ids & scope_limit_condition_ids
            )
            if excluded_sources:
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:제외 조건을 기대 결과로 사용="
                    + ",".join(excluded_sources)
                )
            if (
                legacy_wording_checks and request.target_requirement_id != "REQ-SELECT-001"
                and result.observation_layer == ObservationLayer.UI
                and _PROCEDURAL_SELECTION_RESULT.search(result.statement)
            ):
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:준비용 장비 선택을 제품 기대 결과로 확장"
                )
            source_authority = " ".join(
                known_conditions[condition_id].source_text
                for condition_id in result.source_condition_ids
                if condition_id in known_conditions
            )
            if require_candidate_expectation_guard:
                # Test inputs are not authority for expected outputs (e.g. an
                # invalid boundary request must not become an allowed value).
                expected_values = _explicit_behavior_values(result.statement)
                authority_values = _explicit_behavior_values(source_authority)
                if re.search(r"유지|변경되지|unchanged|retain", source_authority, re.I):
                    authority_values |= _explicit_behavior_values(" ".join(tc.preconditions))
                unsupported = expected_values - authority_values
                # An ER may name the invalid *input* that is blocked. Only
                # permit that grammatical use, not the same value as an output.
                if _state_polarities(source_authority, *_STATE_WORD_PAIRS[2]) == {False}:
                    input_values = _explicit_behavior_values(tc.test_data.model_dump_json())
                    for value in list(unsupported & input_values):
                        if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
                            continue
                        occurrences = [match for match in re.finditer(r"-?\d+(?:\.\d+)?", result.statement)
                                       if float(match.group()) == float(value)]
                        if occurrences and all(re.match(r"\s*(?:°?C|도)?\s*(?:요청|입력|request|input)", result.statement[match.end():], re.I) for match in occurrences):
                            unsupported.discard(value)
                ranges = re.findall(
                    r"(-?\d+(?:\.\d+)?)\s*(?:°?C|도)?\s*(?:~|∼|～|에서|부터|to)\s*(-?\d+(?:\.\d+)?)",
                    source_authority, re.I,
                )
                unsupported = {
                    value for value in unsupported
                    if not (re.fullmatch(r"-?\d+(?:\.\d+)?", value)
                            and any(float(lo) <= float(value) <= float(hi) for lo, hi in ranges))
                }
                if unsupported:
                    minimality_errors.append(
                        f"{tc.tc_id}/{result.result_id}:연결된 조건에 없는 기대값="
                        + ",".join(sorted(unsupported))
                    )
                if legacy_wording_checks and _meaning_conflicts(source_authority, result.statement, compare_relations=require_input_contract):
                    minimality_errors.append(
                        f"{tc.tc_id}/{result.result_id}:연결된 조건과 기대 동작이 반대"
                    )
            if (
                legacy_wording_checks and _PROCEDURAL_ACTION_SUCCESS_RESULT.search(result.statement)
                and not _contains(source_authority, result.statement)
            ):
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:Condition 원문에 없는 실행 행동 성공을 제품 기대 결과로 확장"
                )
            if (
                legacy_wording_checks and result.observation_layer == ObservationLayer.UI
                and _UI_DISPLAY_RESULT.search(result.statement)
            ):
                if not _UI_DISPLAY_AUTHORITY.search(source_authority):
                    minimality_errors.append(
                        f"{tc.tc_id}/{result.result_id}:Condition 원문에 없는 UI 표시 기대"
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
            ("제품 기대 결과가 긍정적 변경 조건과 원문 UI 근거 범위 안에 있습니다." if legacy_wording_checks
             else "기대결과의 조건 연결·제외 역할·명시 값 근거를 확인했습니다. 문장 의미의 정확성 판정은 아닙니다."),
        )

    if require_srs_revision_proposals:
        revision_errors: list[str] = []
        required_revision_ids = {
            effect.requirement_id
            for effect in analysis.requirement_effects
            if effect.relation
            in {RequirementRelation.MODIFIED, RequirementRelation.UPDATE_REQUIRED}
        }
        already_reflected_ids: set[str] = set()
        if allow_already_reflected_srs:
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
            if require_meaning_guard:
                sources = [known_conditions[c].source_text for c in proposal.source_condition_ids if c in known_conditions]
                authority = " ".join([requirement.acceptance_criteria, *sources])
                if proposal.requirement_id == request.target_requirement_id:
                    authority += " " + request.after_value + " " + request.description
                if _explicit_behavior_values(proposal.proposed_acceptance_criteria) - _explicit_behavior_values(authority):
                    revision_errors.append(f"{proposal.proposal_id}:근거에 없는 개정 코드·수치")
                if legacy_wording_checks and any(_meaning_conflicts(source, proposal.proposed_acceptance_criteria, compare_relations=require_input_contract) for source in sources):
                    revision_errors.append(f"{proposal.proposal_id}:변경 조건과 개정 문구의 의미가 반대입니다")
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
                 "MODIFIED·UPDATE_REQUIRED Requirement의 SRS 개정 전·후 문구와 근거가 구조화됐습니다."),
            )

    if require_tc_detail:
        detail_errors: list[str] = []
        # Limited checks for visibly compressed procedures, not a general Korean
        # parser. Restore may remain a concise select-and-apply instruction.
        compressed_action = re.compile(
            r"(?:선택|입력|설정)(?:하고|한\s*(?:뒤|후)|\s*(?:→|>|후|및))[^.\n]*적용"
            r"|\b(?:select|enter|fill|set)\b[^.\n]*\b(?:and|then)\s+(?:click\s+)?(?:apply|submit)\b",
            re.I,
        )
        vague_steps = {"테스트실행", "시험실행", "결과확인", "테스트를실행한다", "결과를확인한다"}
        for tc in design.test_cases:
            for index, step in enumerate(tc.steps, 1):
                if legacy_wording_checks and compressed_action.search(step):
                    detail_errors.append(f"{tc.tc_id} 단계 {index}: 값 선택/입력과 적용을 별도 단계로 구분")
                if legacy_wording_checks and _normalize(step).rstrip(".") in vague_steps:
                    detail_errors.append(f"{tc.tc_id} 단계 {index}: 조작 위치·대상·행동을 구체화")
            detail_errors.extend(_tc_observation_binding_errors(tc, legacy_wording_checks=legacy_wording_checks))
        add("CP2-020", CheckStatus.FAIL if detail_errors else CheckStatus.PASS,
            "TC 상세화 필요: " + "; ".join(detail_errors) if detail_errors
            else ("조작 구분·기대결과 확인 대상·판정 단계의 상세화 항목을 확인했습니다." if legacy_wording_checks
                  else "기대결과 확인 대상·판정 단계 연결을 확인했습니다. 상세 문체는 작성 지침으로 유지합니다."))

        if require_procedure_detail and legacy_wording_checks:
            procedure_errors = [error for tc in design.test_cases for error in _tc_procedure_detail_errors(tc)]
            if require_restore_target_basis:
                procedure_errors.extend(error for tc in design.test_cases for error in _tc_restore_basis_errors(tc))
            add("CP2-021", CheckStatus.FAIL if procedure_errors else CheckStatus.PASS,
                "TC 절차 보완 필요: " + "; ".join(procedure_errors) if procedure_errors
                else "대상 선택 순서와 복원 확인 설명의 명시 항목을 확인했습니다.")

    if require_state_restoration_policy:
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
                policy_errors.append(f"{tc.tc_id}: 차단 안내뿐 아니라 변경 대상 상태의 유지 확인 필요")
        add("CP2-022", CheckStatus.FAIL if policy_errors else CheckStatus.PASS,
            "; ".join(policy_errors) if policy_errors else "조회·변경·차단 유형별 복원 정책을 확인했습니다.")

    if require_structured_restoration or any(tc.restoration is not None for tc in design.test_cases):
        errors = [f"{tc.tc_id}: {error}" for tc in design.test_cases
                  for error in _structured_restoration_errors(tc)]
        add("CP2-023", CheckStatus.FAIL if errors else CheckStatus.PASS,
            "; ".join(errors) if errors else "복원 조작·대상 ER·관찰 기준·확인 시점의 구조화 연결을 확인했습니다.")

    statuses = {item.status for item in checks}
    if CheckStatus.ERROR in statuses:
        status = CheckStatus.ERROR
    elif CheckStatus.FAIL in statuses:
        status = CheckStatus.FAIL
    elif CheckStatus.REVIEW in statuses:
        status = CheckStatus.REVIEW
    else:
        status = CheckStatus.PASS
    return Checkpoint2Result(status=status, checks=checks)

__all__ = [name for name in globals() if not name.startswith("__")]
