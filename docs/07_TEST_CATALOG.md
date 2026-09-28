# 자동 테스트 카탈로그

이 문서는 파이프라인 코드의 회귀검사 목록입니다. **제품 TC 목록이나 실제 AI의 정확도·성공률이 아닙니다.** 현재 실행 수치와 성공/실패 증거는 [인계 문서](../PROJECT_HANDOFF.md)에 기록합니다.

## 1. 역할별 검사 위치

| 역할 | 코드·테스트 연결 | 확인하는 것 |
|---|---|---|
| SRS·Agent 1 | [test_srs_agent1.py](../tests/test_srs_agent1.py) | SRS 파싱·원문 인용·조건/절차/제외 분류·CP1 |
| Agent 2 | [test_agent2.py](../tests/test_agent2.py) | 기존 TC 대조·상세 TC·실행 정의·SRS 제안·CP2 |
| 공통 인계·CLI | [test_integrity_cli.py](../tests/test_integrity_cli.py) | 파일·계약·해시·저장 인계·실행 명령·공개 자산 보존 |
| Agent 3 | [test_agent3.py](../tests/test_agent3.py) | UI 수집·지원 여부·TC 동일성·CP3·코드 생성·실제 로컬 제품 조작/복원 |
| 의미 검토 연결 | [test_grounding.py](../tests/test_grounding.py) | 검토 대상/근거 ID·응답 형식·변조·오류·대역 SDK 호출 |
| 실행 조정 | [test_orchestration_execution.py](../tests/test_orchestration_execution.py) | 후보 선택·제외·오류 중단·기존 회귀·실행 집계 |
| Agent 4 | [test_agent4_reporting.py](../tests/test_agent4_reporting.py) | 결과 분류·증거·CP4·사람 검토서·외부 보고 |
| UI·승인 | [test_pipeline_ui.py](../tests/test_pipeline_ui.py) | 조회/실행 권한·승인·재시험·동시성·SRS 반영·복구 |

공유 데이터와 대역은 [pipeline_test_support.py](../tests/pipeline_test_support.py)에서 관리합니다. 같은 테스트 함수도 입력 조합에 따라 여러 건으로 수집되므로 함수 수와 실행 건수를 혼동하지 않습니다.

## 2. 유지해야 하는 반례

| 검사 묶음 | 정상 허용 | 계속 막아야 할 경우 |
|---|---|---|
| 요청과 조건 | 준비값·목표값·허용 범위·복수 원문 인용 | 없는 근거·확정 조건 누락·미정 기준 추정 |
| TC 설계 | 필요한 상세 단계와 기존 TC의 실제 재사용 | 요청 밖 기대값·검사 누락·중복 SRS 수정안 |
| 직접 실행 인계 | 같은 TC 값·순서·시점의 조립 | 대상/값/ER/시점·복원 연결 변조 |
| UI 수집 | 관찰된 조작·내부값·실제 장비 ID | 숨김·비활성·중복 요소·누락 내부값·다른 장비 |
| 검토 응답 | 정확한 원본 ID·원문·판정 보존 | 부모/결합/없는 ID·누락·변조·잘못된 응답으로 재작성 |
| 제품·복원 | 요청한 판정과 준비 전 상태 복원 구분 | 제품 불일치 은폐·복원 실패 뒤 동일 환경 진행 |
| 보고·승인 | 유효한 실패 보고·별도 사람 승인 | 환경만으로 제품 PASS·과거 PASS로 최신 실패 승인·미동의 SRS 변경 |

특정 시나리오용 예외를 늘리기보다 다른 관제점·값·표현에서도 같은 보호가 적용되는지 확인합니다. 전체 분기 규칙은 [판단 지도](PROJECT_GUIDE.md#logic-map)에서 봅니다.

## 3. 검증 종류와 한계

- 순수 코드/대역 검사: 정해진 출력에서 진행·재작성·중단·보고가 맞는지 확인합니다. 모델이 실제로 같은 출력을 낸다는 증거는 아닙니다.
- 로컬 브라우저 검사: 운영 수집·컴파일·제품 조작·복원을 확인합니다. 새 API 생성/의미 검토를 생략한 경우 전체 AI 흐름이라고 부르지 않습니다.
- 저장 Run 재현: 과거 TC·계획·증거의 유지와 현재 실행 경로를 비교합니다. 원본 실패를 수정해 성공으로 바꾸지 않습니다.
- 실제 API 검사: 별도 사용자 승인으로 새 생성·검토를 수행합니다. 여기의 로컬 수집 건수에 합치지 않습니다.
- 정적 색인: 코드 위치와 문서 검사 번호를 대조합니다. 커버리지·모든 경로 실행의 증명이 아닙니다.

## 4. 실행과 수집

```powershell
python scripts/verify_offline.py
python scripts/verify_offline.py --focus
python -m pytest --collect-only -q
python scripts/audit_logic_inventory.py --self-test
python scripts/audit_logic_inventory.py --check
git diff --check
```

기본 offline 명령은 전체 Pytest, focus는 근거 검토·실행 조정·보고·UI 승인 검사입니다. 서비스 키 제거와 외부 연결 차단은 프로세스 수준 보호이며 OS 격리나 모든 자식 프로세스의 네트워크 차단 보장이 아닙니다.

실패·오류·skip·중복·수집 수를 구분해 기록합니다. 여러 부분 실행의 합을 전체 검증률로 표시하지 않습니다. 오래된 [분기 감사](branch_audit.json)의 미실행 목록을 안 쓰는 코드라는 이유로 삭제하지 않습니다.

## 5. 제품 TC와 공개 자산

V1 기준 제품 테스트는 [test_controller.py](../product_baseline/tests/test_controller.py), 공식 승인 TC는 [registry.json](../approved_assets/registry.json)에서 확인합니다. 환경 점검·제품 TC·고정 분류 시연은 별도 집계하며 자동 테스트 목록과 합산하지 않습니다.

[정리 전 테스트 추가 이력](07_TEST_CATALOG.history-20260928.md)은 과거 변경 근거입니다. 추가 N건을 모두 더해 현재 수량으로 사용하지 않습니다. 테스트 추가/삭제 시 이 문서의 역할·반례 범위와 인계 문서의 수집 상태를 함께 갱신합니다.
