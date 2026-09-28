# 요청 예시와 과거 실행 증거

이 폴더는 실행 당시 입력·산출물을 보존합니다. 최신 상태는 [현재 인계 문서](../PROJECT_HANDOFF.md)를 먼저 확인하세요. 파일 이름의 `success`는 과거 사례명이지 새 실행의 성공 보장이 아닙니다.

## 요청 예시

| 파일 | 용도·주의점 |
|---|---|
| [기본 요청](change_request.example.json) | 요청 JSON 작성 형식 참고. 현재 SRS·제품과 대조한 뒤 사용 |
| [HIGH 요청](change_request.success-fan-speed.json) | 과거 강풍 표시 변경 입력. 관련 공식 TC-V2-001은 이미 등록됨 |
| [MED 요청](change_request.success-medium-fan.json) | 과거 중풍 변경·기존 강풍 유지 입력. 관련 공식 TC-V2-002는 이미 등록됨 |

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
