# 요청 예시와 과거 실행 증거

이 폴더는 실행 당시 입력·산출물을 보존합니다. 최신 상태는 [현재 인계 문서](../PROJECT_HANDOFF.md)를 먼저 확인하세요. 파일 이름의 `success`는 과거 사례명이지 새 실행의 성공 보장이 아닙니다.

## 요청 예시

| 파일 | 용도·주의점 |
|---|---|
| [기본 요청](change_request.example.json) | 요청 JSON 작성 형식 참고. 현재 SRS·제품과 대조한 뒤 사용 |
| [HIGH 요청](change_request.success-fan-speed.json) | 과거 강풍 표시 변경 입력. 관련 공식 TC-V2-001은 이미 등록됨 |
| [MED 요청](change_request.success-medium-fan.json) | 과거 중풍 변경·기존 강풍 유지 입력. 관련 공식 TC-V2-002는 이미 등록됨 |
| [난방 범위 요청](change_request.heat-range-narrowing.json) | 2026-10-15 추가. 대표 온도 요청·참고 사례 R01~R08과 다른 모드·양쪽 경계 변경. **미실행**, 제품 미변경이라 실행하면 경계 시험은 불일치 후보가 예상됨 |
| [AUTO 풍량 표시 요청](change_request.auto-fan-label.json) | 2026-10-15 추가. HIGH·MED와 다른 값의 표시 라벨 변경. **미실행** |
| [대표 모드 전환 요청](change_request.representative-mode.json) | 2026-10-10 선정 대표 요청 5개 중 2번(냉방 26°C → 제습 → 냉방, 온도 입력 비활성·`---`·내부 26 유지·복귀 후 재활성). 원문 `runs/manual_checks/representative-ai-20261010/requests/02-mode.json`과 해시 동일(2026-10-17 추가) |
| [대표 전원 요청](change_request.representative-power.json) · [대표 풍량 요청](change_request.representative-fan.json) · [대표 잠금 요청](change_request.representative-lock.json) | 2026-10-18 추가. 대표 요청 5개 중 전원 정지·풍량 강풍·잠금 정책 미정(잠금은 질문을 남기고 멈추는 것이 정상). 원문과 내용 동일 |
| [대표 온도 요청](change_request.representative-temperature.json) | 대표 요청 5개 중 온도 범위 변경(냉방 20~30°C). 2026-10-23 H-6으로 난방 시험을 '16°C 적용 1개'로 변경해 그 전 실행과 요청서가 다름 |
| [전원 정지 평가 요청](change_request.power-stop-evaluation.json) | 2026-10-05 평가용 전원 운전→정지 전환 요청. 제품 기준 변경이 아님 |

HIGH·MED 파일의 과거 변경 전 문구를 현재 SRS라고 간주하지 않습니다. 새로운 변경·등록 시연에는 현재 기준과 실제로 달라지는 요청을 별도로 준비합니다. 기존 요청 파일과 승인 자산은 재현 근거로 보존합니다.

## 대표 공개 실행 기록

| 자료 | 보여주는 범위 |
|---|---|
| [중풍](results/agent1-agent2-agent3-agent4-medium-fan/README.md) | 당시 후보 시험·관련 기존 TC 실행·보고 |
| [잠금](results/agent1-agent2-agent3-agent4-lock-disable/README.md) | 당시 기대결과와 제품 관찰의 불일치 |
| [미정 조건](results/agent1-agent2-agent3-agent4-partial-information/README.md) | 확정 범위와 정보 부족의 구분 |

위 기록은 최신 소스 전체의 재검증 결과가 아닙니다. PASS·보고와 사람의 공식 등록 승인도 구분합니다.

## 초기 단계별 AUTO 온도 기록

| 폴더 | 보존 목적 |
|---|---|
| [Agent 1·CP1](results/agent1-cp1-auto-temperature/) | 초기 분석 단계 기록 |
| [Agent 1·2](results/agent1-agent2-auto-temperature/) | 초기 설계 인계 기록. 저장 바이트와 Manifest 해시 불일치가 있어 현재 재인계 성공 증거로 사용하지 않음 |
| [Agent 1·2·3](results/agent1-agent2-agent3-auto-temperature/) | 초기 자동화 단계 기록·실행 추적 자료 |

여러 폴더에 같은 요청·분석 파일이 있어도 각 단계의 증거 묶음을 보존하기 위한 복사본입니다. 원본 파일·Manifest·추적 자료는 삭제하거나 최신 결과로 덮어쓰지 않습니다. 기존 공개 페이지가 참조하므로 경로도 유지합니다.
