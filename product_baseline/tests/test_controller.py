# -*- coding: utf-8 -*-
# =============================================================================
# test_controller.py
# Virtual Central Control System — Python Playwright QA Automation Test Suite
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  【용어 사전 (Domain Glossary)】                                         │
# │  관제점 (Data Point)    : 시스템이 감시·제어하는 최소 단위 속성값          │
# │                           (운전상태, 설정온도, 운전모드, 풍량, Lock 여부)  │
# │  제어 패널 (Control Panel): 우측 슬라이드 영역 (#det-control-section)    │
# │                           실내기 1대 또는 복수 기기 관제점 조작 UI       │
# │  장치 카드 (Device Card) : 중앙 그리드의 실내기 1대 상태 표현 단위        │
# │                           (.ac-device-card, #device-card-{id})          │
# └─────────────────────────────────────────────────────────────────────────┘
#
# 【핵심 검증 항목 (4대 시나리오 + 확장 2개)】
#   TC-MODE-001: 해피패스 관제 제어 (HEAT 모드 + 24°C 적용 → 로그·카드 동기화 검증)
#   TC-MODE-002: Rule 2 예외 차단 - FAN 모드 시 설정온도 관제점 비활성화
#   TC-MODE-003: Rule 2 양방향 - DRY 비활성화 → COOL 복귀 재활성화
#   TC-LOCK-001: LOCK 관제점 전수 검사 (16대 루프 + 중앙/현장 제어 차단 + 상태 불변)
#   TC-ERR-001: 결함 주입 후 제어 차단 (CH05 에러 주입 → 차단 로그 타임아웃 방어 검증)
#   TC-INT-002: 복수 선택 일괄 제어 (3대 선택 → HEAT 일괄 적용 → 내부 상태 검증)
#   TC-TEMP-001: 온도 상한 경계값 방어 (30°C 초과 시 Toast + 값 차단 검증)
#
# 【Pipeline Validation — 5가지 분류 증명】
#   TC-PIPE-001: 요구사항 모호성 (알람 UI 기준 부재 → requirement_review)
#   TC-PIPE-002: 시뮬레이터 환경 이슈 (Timeout → environment_issue)
#   TC-PIPE-003: 자동화 코드 오류 (잘못된 셀렉터 사용 → automation_issue)
#   TC-PIPE-004: 조건 부족 미실행 (17번 장치 미존재 → not_executed)
#   TC-TEMP-002: 제품 결함 후보 (AUTO 모드 하한 18°C 위반 → product_defect)
#
# 【실행 방법】
#   pip install pytest pytest-playwright pytest-html
#   playwright install chromium
#
#   pytest test_controller.py -v --browser chromium          # Headless 실행
#   pytest test_controller.py -v --browser chromium --headed  # 브라우저 시각 확인
#   pytest test_controller.py -v -k "tc01"                   # 특정 TC만 실행
#
# 【주의사항】
#   - 로컬 HTML 파일을 file:// 프로토콜로 직접 접근
#   - 각 테스트 전 localStorage 완전 초기화 (상태 오염 방지)
#   - appendQALog의 50ms setTimeout을 고려한 wait_for_function 사용
#   - Python Playwright 1.45+에서 .first 는 프로퍼티 (괄호 없이 사용)
#   - 브라우저에서 let 변수는 window 객체에 붙지 않음 (함수만 window에 노출)
# =============================================================================

import re
import pytest
from pathlib import Path
from playwright.sync_api import Page, expect

# ============================================================
# 【QA Custom Exceptions (Failure Classification)】
# ============================================================
class SimulatorTimeoutError(Exception):
    """시뮬레이터 응답 타임아웃 에러"""
    pass



# ============================================================
# 【설정 상수】
# ============================================================

# 테스트 대상 HTML 파일 절대 경로 → file:// URI 자동 변환
VIRTUAL_CONTROLLER_URL = (Path(__file__).parent.parent / "virtual-controller.html").as_uri()

# appendQALog 내부 50ms setTimeout + DOM 렌더링 레이턴시 + 여유 마진
LOG_RENDER_TIMEOUT = 4000

# 관제 명령 적용 후 장치 카드 리렌더링 대기 타임아웃 (ms)
APPLY_CMD_TIMEOUT = 3000

# 기본 장치 카드 수 (virtual-controller.html mock 데이터 기준: 16대)
TOTAL_DEVICE_COUNT = 16


# ============================================================
# 【헬퍼 함수 (Domain-Specific Utilities)】
# ============================================================

def load_clean_simulator(page: Page) -> None:
    """
    시뮬레이터 내장 '기기 설정 전체 초기화 (Reset)' 버튼을 클릭하여
    이전 테스트의 관제점 설정값(모드/온도/Lock 등)을 초기 상태로 되돌린다.

    동작 흐름:
    ① 페이지가 아직 열리지 않은 경우 → goto로 최초 접근
    ② QA 드로어가 닫혀 있으면 열기
    ③ '기기 설정 전체 초기화 (Reset)' 버튼 클릭
    ④ resetSimulatorState()가 호출하는 confirm() 다이얼로그를 자동 수락
       (확인을 누르면 내부에서 localStorage 삭제 + location.reload() 실행)
    ⑤ 페이지 reload 완료 후 첫 번째 장치 카드 렌더링 대기

    ※ 새 탭을 열지 않고 현재 탭 안에서만 작동하므로 브라우저 컨텍스트가 유지됨
    """
    # 최초 진입: 아직 시뮬레이터 URL이 아닌 경우 goto로 이동
    if VIRTUAL_CONTROLLER_URL not in page.url:
        page.goto(VIRTUAL_CONTROLLER_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#device-card-1", timeout=5000)
        return  # 최초 로드는 기본값이 초기 상태이므로 Reset 불필요

    # QA 드로어가 닫혀 있으면 열기 (Reset 버튼이 드로어 안에 있음)
    is_open = page.evaluate(
        "document.getElementById('qa-drawer-panel').classList.contains('open')"
    )
    if not is_open:
        page.click("#tab-test-panel")
        page.wait_for_selector("#qa-drawer-panel.open", timeout=3000)

    # confirm() 다이얼로그 자동 수락 핸들러 등록
    # resetSimulatorState() 내부에서 confirm()이 호출되면 즉시 OK를 누름
    page.once("dialog", lambda dialog: dialog.accept())

    # '기기 설정 전체 초기화 (Reset)' 버튼 클릭
    # → resetSimulatorState() 실행 → localStorage 삭제 → location.reload()
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("button:has-text('기기 설정 전체 초기화')")

    # 장치 카드 그리드 렌더링 완료 대기
    page.wait_for_selector("#device-card-1", timeout=5000)


def open_qa_drawer(page: Page) -> None:
    """
    QA 테스트 컨트롤러 드로어(우측 오버레이)를 열고 로그 컨테이너를 확인한다.

    ※ 주의: QA 드로어가 열린 상태에서는 중앙 대시보드의 제어 패널 버튼들이
           z-index 충돌로 클릭 불가 상태가 된다.
           따라서 반드시 제어 명령 적용(apply)이 모두 끝난 후에 열어야 한다.
    """
    is_open = page.evaluate(
        "document.getElementById('qa-drawer-panel').classList.contains('open')"
    )
    if not is_open:
        page.click("#tab-test-panel")
        page.wait_for_selector("#qa-drawer-panel.open", timeout=3000)

    expect(page.locator("#qa-log-container")).to_be_visible()


def close_qa_drawer(page: Page) -> None:
    """QA 드로어를 닫는다. 제어 패널 버튼 클릭 전에 반드시 호출한다."""
    is_open = page.evaluate(
        "document.getElementById('qa-drawer-panel').classList.contains('open')"
    )
    if is_open:
        page.click(".qa-drawer-close")
        page.wait_for_function(
            "!document.getElementById('qa-drawer-panel').classList.contains('open')",
            timeout=2000,
        )


def select_device_card(page: Page, device_id: int) -> None:
    """
    지정된 ID의 장치 카드를 클릭하여 제어 패널에 해당 기기를 로드한다.

    ※ QA 드로어가 열려 있으면 클릭이 차단되므로 사전에 닫혀 있어야 한다.
    """
    # 장치 카드의 실제 클릭 가능 영역(.card-body-split)을 클릭
    page.click(f"#device-card-{device_id} .card-body-split")

    # 제어 패널 헤더가 "선택된 장치 없음"이 아닌 기기명으로 업데이트될 때까지 대기
    page.wait_for_function(
        """() => {
            const el = document.getElementById('det-unit-name');
            return el && el.textContent.trim() !== '선택된 장치 없음';
        }""",
        timeout=2000,
    )

    # 제어 패널의 pointerEvents가 활성화(opacity:1)될 때까지 대기
    page.wait_for_function(
        """() => {
            const sec = document.getElementById('det-control-section');
            return sec && sec.style.pointerEvents !== 'none';
        }""",
        timeout=2000,
    )


def wait_for_log_containing(page: Page, expected_text: str, timeout: int = LOG_RENDER_TIMEOUT) -> None:
    """
    QA 이벤트 로그 컨테이너에 지정된 텍스트를 포함하는 로그 항목이
    나타날 때까지 폴링 대기한다.

    appendQALog() 함수 내부의 setTimeout(50ms) 지연 + DOM 렌더링 레이턴시를
    wait_for_function 폴링으로 안전하게 처리한다.
    """
    page.wait_for_function(
        """(text) => {
            const container = document.getElementById('qa-log-container');
            if (!container) return false;
            return Array.from(container.querySelectorAll('.qa-log-text'))
                        .some(el => el.textContent.includes(text));
        }""",
        arg=expected_text,
        timeout=timeout,
    )


def get_log_text(page: Page, has_text: str) -> str:
    """
    QA 로그 컨테이너에서 특정 텍스트를 포함하는 첫 번째 로그 항목의
    텍스트를 반환한다.

    ※ Python Playwright 1.45+에서 .first 는 프로퍼티이므로 괄호 없이 사용한다.
       page.locator(...).filter(has_text=...).first  [O]
       page.locator(...).filter(has_text=...).first() [X]
    """
    locator = page.locator(".qa-log-text").filter(has_text=has_text).first
    expect(locator).to_be_visible()
    return locator.text_content() or ""


# ============================================================
# 【TC-ENV-000】사전 환경 검증 (Pre-check)
# ============================================================
def test_tc_env_000_pre_environment_check(page: Page):
    """[TC-ENV-000] 사전 환경 검증 (Pre-check) | 테스트 실행 전 가상 환경 및 레지스터 로드 상태 검증"""
    page.goto(VIRTUAL_CONTROLLER_URL, wait_until="domcontentloaded")

    # 1. UI 렌더링 검증 (첫 번째 장치 카드가 보일 때까지 대기)
    expect(page.locator("#device-card-1")).to_be_visible(timeout=5000)

    # 2. 내부 장치 상태(가상 레지스터) 객체 존재 및 16대 로드 검증
    device_count = page.evaluate("() => window.__vccs ? window.__vccs.devices.length : 0")
    assert device_count == 16, f"환경 에러: 16대 장비 로드 실패 (실제 로드 수: {device_count})"

    # 3. QA 드로어 주입 검증
    expect(page.locator(".qa-drawer")).to_be_attached()

# ============================================================
# 【TC-MODE-001】해피패스 관제 제어 검증
#
# 시나리오:
#   1번 장치 카드 클릭 → 제어 패널에서 '난방(HEAT)' 모드 선택
#   → 초기 설정온도 24°C를 유지한 채 '적용' 버튼 클릭
#   → QA 드로어를 열어 트랜잭션 로그 및 장치 카드 상태 검증
#
# 검증 포인트:
#   ① HEAT 모드 버튼 active 클래스
#   ② 설정온도 표시박스 heat 컬러 테마 바인딩 (Rule 1)
#   ③ 트랜잭션 로그에 "운전모드: COOL -> HEAT" 기록
#   ④ 설정온도는 초기값 24°C를 유지
#   ⑤ 장치 카드 모드 배지 '난방' 텍스트 및 mode-heat 클래스 동기화
#
# ※ 핵심 주의: QA 드로어는 적용 버튼 클릭 후에 열어야 한다.
#              드로어가 열린 상태에서는 제어 패널 버튼이 클릭 불가.
# ============================================================
def test_tc_mode_001_heat_mode_and_temp_apply(page: Page):
    """[TC-MODE-001] 해피패스 | 장치 #1 선택 → HEAT 모드 적용 → QA 로그 및 장치 카드 동기화 단일 검증"""
    load_clean_simulator(page)

    # ── Step 1: 1번 장치 카드 선택 ('IDU-00', 초기: COOL) ──
    select_device_card(page, 1)
    expect(page.locator("#det-unit-name")).to_contain_text("IDU-00")

    # ── Step 2: 제어 패널에서 '난방(HEAT)' 운전 모드 관제점 선택 ──
    # ※ QA 드로어가 닫힌 상태에서만 클릭 가능
    page.click("#det-mode-heat")

    # HEAT 버튼 active 상태 검증
    expect(page.locator("#det-mode-heat")).to_have_class(re.compile(r"active"))

    # Rule 1 검증: HEAT 모드 시 설정온도 표시박스에 'heat' 컬러 클래스 바인딩
    # (--color-heat: #ea580c 주황색 테마 적용)
    expect(page.locator("#det-temp-display")).to_have_class(re.compile(r"heat"))

    # ── Step 3: '적용' 버튼 클릭 → applyPanelCommands() 실행 ──
    # ※ QA 드로어가 닫혀 있는 상태에서 적용해야 함
    page.click(".btn-apply-cmd")

    # ── Step 4: QA 드로어를 열어 트랜잭션 로그 검증 ──
    # 적용 완료 후 드로어를 열어야 제어 패널 클릭 차단 문제가 없음
    open_qa_drawer(page)

    # [검증 4-1] 운전모드 변경 로그 (COOL → HEAT) 기록 확인
    wait_for_log_containing(page, "운전모드: COOL -> HEAT")
    mode_log_text = get_log_text(page, "운전모드: COOL -> HEAT")
    assert "운전모드: COOL -> HEAT" in mode_log_text

    # ── Step 5: 장치 카드 상태 동기화 검증 ──
    page.wait_for_function(
        """() => {
            const card = document.getElementById('device-card-1');
            if (!card) return false;
            const modeText = card.querySelector('.card-mode-text');
            return modeText && modeText.textContent.includes('난방');
        }""",
        timeout=APPLY_CMD_TIMEOUT,
    )

    # 장치 카드 모드 배지 '난방' 텍스트 검증
    expect(page.locator("#device-card-1 .card-mode-text")).to_contain_text("난방")

    # 장치 카드에 mode-heat CSS 클래스 동적 바인딩 검증 (Rule 1 주황색 테마)
    expect(page.locator("#device-card-1")).to_have_class(re.compile(r"mode-heat"))

    # ── Step 6: [화면·내부 상태 동시 검증] ──
    # 내부 장치 상태(가상 레지스터) 업데이트 검증
    device_mode = page.evaluate(
        "() => window.__vccs ? window.__vccs.devices.find(d => d.id === 1).mode : null"
    )
    assert device_mode == "HEAT", f"가상 레지스터 동기화 실패: {device_mode}"
    # UI에 속지 않고 백엔드 상태값이 실제로 변경되었는지 크로스체크 (Double-Assert)
    backend_device = page.evaluate("() => window.__vccs.devices.find(x => x.id === 1)")
    assert backend_device["mode"] == "HEAT"
    assert backend_device["setTemp"] == pytest.approx(24.0)


# ============================================================
# 【TC-MODE-002】Rule 2 예외 차단 - 송풍(FAN) 모드
# ============================================================
def test_tc_mode_002_fan_mode_temp_disabled(page: Page):
    """[TC-MODE-002] Rule 2 예외 | 송풍(FAN) 모드 선택 시 설정온도 관제점 비활성화 검증"""
    load_clean_simulator(page)
    select_device_card(page, 1)

    # 초기 상태: 설정온도 활성화 상태
    expect(page.locator("#det-temp-up-btn")).to_be_enabled()
    expect(page.locator("#det-temp-down-btn")).to_be_enabled()
    expect(page.locator("#det-temp-adjust-card")).not_to_have_class(re.compile(r"disabled"))

    # 송풍(FAN) 모드 선택
    page.click("#det-mode-fan")
    expect(page.locator("#det-mode-fan")).to_have_class(re.compile(r"active"))

    # [화면·상태 동시 검증 A] disabled 클래스 추가 검증
    expect(page.locator("#det-temp-adjust-card")).to_have_class(re.compile(r"disabled"))

    # [화면·상태 동시 검증 B-1] UP 버튼 비활성화
    expect(page.locator("#det-temp-up-btn")).to_be_disabled()

    # [화면·상태 동시 검증 B-2] DOWN 버튼 비활성화
    expect(page.locator("#det-temp-down-btn")).to_be_disabled()

    # 비활성화 표시 텍스트 '---' 확인
    expect(page.locator("#det-temp-display")).to_contain_text("---")


# ============================================================
# 【TC-MODE-003】Rule 2 예외 차단 - 제습(DRY) + 냉방(COOL) 복귀 재활성화
# ============================================================
def test_tc_mode_003_dry_mode_then_cool_reactivation(page: Page):
    """[TC-MODE-003] Rule 2 양방향 | 제습(DRY) 비활성화 → 냉방(COOL) 복귀 시 설정온도 관제점 재활성화"""
    load_clean_simulator(page)
    select_device_card(page, 1)

    # 제습(DRY) 모드 → 전수 비활성화 검증 3종 세트
    page.click("#det-mode-dry")
    expect(page.locator("#det-mode-dry")).to_have_class(re.compile(r"active"))
    expect(page.locator("#det-temp-adjust-card")).to_have_class(re.compile(r"disabled"))
    expect(page.locator("#det-temp-up-btn")).to_be_disabled()
    expect(page.locator("#det-temp-down-btn")).to_be_disabled()
    expect(page.locator("#det-temp-display")).to_contain_text("---")

    # 냉방(COOL) 모드로 전환 → 재활성화 검증 (양방향)
    page.click("#det-mode-cool")
    expect(page.locator("#det-mode-cool")).to_have_class(re.compile(r"active"))
    expect(page.locator("#det-temp-adjust-card")).not_to_have_class(re.compile(r"disabled"))
    expect(page.locator("#det-temp-up-btn")).to_be_enabled()
    expect(page.locator("#det-temp-down-btn")).to_be_enabled()

    temp_text = page.locator("#det-temp-display").text_content() or ""
    assert "---" not in temp_text
    assert "°C" in temp_text


# ============================================================
# 【TC-LOCK-001】LOCK 관제점 전수 검사
# ============================================================
def test_tc_lock_001_all_devices_full_inspection(page: Page):
    """[TC-LOCK-001] LOCK 전수 검사 | 16대 잠금 표시 + 중앙/현장 제어 차단 및 상태 불변 검증"""
    load_clean_simulator(page)

    # 초기: locked 카드 0개
    assert page.locator(".ac-device-card.locked").count() == 0

    # ALL LOCK 일괄 주입
    # ※ const/let 변수는 window에 자동 노출 안 됨
    # ※ window.__vccs QA 네임스페이스를 통해 접근 (HTML에 명시적으로 노출됨)
    page.evaluate("""() => {
        window.__vccs.devices.forEach(device => { device.locked = true; });
        window.__vccs.renderGrid();
        window.__vccs.saveStateToLocalStorage();
    }""")

    # renderGrid() 완료 대기
    page.wait_for_function(
        """() => {
            const card = document.getElementById('device-card-1');
            return card && card.classList.contains('locked');
        }""",
        timeout=2000,
    )

    # 16대 전수 루프 조사
    for device_id in range(1, TOTAL_DEVICE_COUNT + 1):
        card = page.locator(f"#device-card-{device_id}")

        # [검증 A] locked CSS 클래스 존재
        expect(card).to_have_class(re.compile(r"locked"))

        # [검증 B] .card-lock-indicator 요소 가시성
        lock_indicator = card.locator(".card-lock-indicator")
        expect(lock_indicator).to_be_visible()

        # [검증 C] 자물쇠 🔒 이모지 텍스트 포함
        lock_text = lock_indicator.text_content() or ""
        assert "🔒" in lock_text, (
            f"장치 카드 {device_id}: 🔒 이모지 없음. 실제: '{lock_text}'"
        )

    # 최종 locked 총 수 = 16
    assert page.locator(".ac-device-card.locked").count() == TOTAL_DEVICE_COUNT

    # LOCK 상태 장치의 기준 상태 저장
    before = page.evaluate("""() => {
        const device = window.__vccs.devices[0];
        return {
            status: device.status,
            mode: device.mode,
            setTemp: device.setTemp,
            fanSpeed: device.fanSpeed,
            purify: device.purify
        };
    }""")

    # 중앙 관제 패널에서 다른 관제점 변경을 시도해도 실제 장치 상태는 불변
    page.click("#device-card-1 .card-body-split")
    page.click("#det-mode-heat")
    page.click("#det-fan-high")
    page.click(".btn-apply-cmd")

    after = page.evaluate("""() => {
        const device = window.__vccs.devices[0];
        return {
            status: device.status,
            mode: device.mode,
            setTemp: device.setTemp,
            fanSpeed: device.fanSpeed,
            purify: device.purify
        };
    }""")
    assert after == before, f"LOCK 상태에서 중앙 관제점 값이 변경됨: before={before}, after={after}"

    open_qa_drawer(page)
    wait_for_log_containing(page, "LOCK 상태로", timeout=LOG_RENDER_TIMEOUT)
    central_lock_log = page.locator(".qa-log-text").filter(has_text="LOCK 상태로").first
    expect(central_lock_log).to_be_visible()

    # LOCK 상태에서 현장 리모컨도 차단
    open_qa_drawer(page)
    page.click("button:has-text('물리 전원 토글')")
    wait_for_log_containing(page, "ALL LOCK", timeout=LOG_RENDER_TIMEOUT)
    # .filter(has_text=...).first 는 프로퍼티 (괄호 없음)
    lock_block_log = page.locator(".qa-log-text").filter(has_text="ALL LOCK").first
    expect(lock_block_log).to_be_visible()


# ============================================================
# 【TC-ERR-001】결함 주입(CH05) 후 제어 차단 검증
# ============================================================
def test_tc_err_001_ch05_fault_injection_control_block(page: Page):
    """[TC-ERR-001] 결함 주입 | CH05 과열 에러 강제 주입 → 제어 명령 차단 로그 및 Toast 검증"""
    load_clean_simulator(page)

    # 1. QA 드로어가 닫힌 상태에서 장치 선택 (오버레이 충돌 방지)
    select_device_card(page, 4)

    # 2. 에러 주입을 위해 QA 드로어 열기
    open_qa_drawer(page)
    unit_name = page.locator("#det-unit-name").text_content()
    print(f"\n  [대상 기기] {unit_name}")

    # CH05 과열 에러 강제 주입
    page.click("button:has-text('CH05 과열 에러')")

    # 에러 로그 비동기 인입 대기 (50ms setTimeout + DOM 렌더링 방어)
    wait_for_log_containing(page, "알람 발생", timeout=LOG_RENDER_TIMEOUT)

    # 에러 로그에 CH05 코드 포함 검증
    error_log = page.locator(".qa-log-text").filter(has_text="알람 발생").first
    expect(error_log).to_be_visible()
    error_log_text = error_log.text_content() or ""
    assert "CH05" in error_log_text, f"에러 로그에 CH05 없음: {error_log_text}"

    # 장치 카드 state-error 클래스 전이 검증
    page.wait_for_function(
        """() => {
            const card = document.getElementById('device-card-4');
            return card && card.classList.contains('state-error');
        }""",
        timeout=2000,
    )
    expect(page.locator("#device-card-4")).to_have_class(re.compile(r"state-error"))

    # QA 드로어 닫기 → 제어 패널 버튼 활성화
    close_qa_drawer(page)

    # 에러 기기에 OPERATION 명령 시도
    page.click("#det-power-on-btn")
    page.click(".btn-apply-cmd")

    # 적용 직후 Toast 알림 표시 먼저 검증 (DOM 구조상 빠른 확인)
    expect(page.locator("#global-toast")).to_have_class(re.compile(r"show"), timeout=1000)

    # QA 드로어 재오픈 → 제어 차단 로그 확인
    open_qa_drawer(page)
    wait_for_log_containing(page, "제어 차단", timeout=LOG_RENDER_TIMEOUT)
    block_log = page.locator(".qa-log-text").filter(has_text="제어 차단").first
    expect(block_log).to_be_visible()
    block_log_text = block_log.text_content() or ""
    assert "에러" in block_log_text, f"차단 로그에 '에러' 없음: {block_log_text}"

    # 기기 내부 상태 ERROR 유지 검증
    # window.__vccs.devices getter를 통해 실제 devices 배열 접근
    device_status = page.evaluate(
        "() => { const d = window.__vccs.devices.find(x => x.id === 4); return d ? d.status : null; }"
    )
    assert device_status == "ERROR", f"상태가 변경됨 (기대: ERROR, 실제: {device_status})"


# ============================================================
# 【TC-INT-002】복수 선택 모드 일괄 제어 검증
# ============================================================
def test_tc_int_002_multi_select_batch_control(page: Page):
    """[TC-INT-002] 복수 선택 일괄 제어 | 3대 선택 → HEAT 일괄 적용 → 내부 상태(devices[].mode) 검증"""
    load_clean_simulator(page)

    # 복수 선택 모드 활성화
    page.click("#btn-multi-select-trigger")
    expect(page.locator("#btn-multi-select-trigger")).to_have_class(re.compile(r"active"))
    expect(page.locator("#chk-multi-select")).to_be_checked()

    # 초기 선택 목록 정리 (JS 강제 주입 안티패턴 제거, 실제 사용자 방식 적용)
    # 이미 선택된 카드들이 있다면 마우스로 한 번씩 더 클릭하여 선택을 해제합니다.
    selected_cards = page.locator(".ac-device-card.selected")
    count = selected_cards.count()
    for i in range(count):
        # 배열이 동적으로 줄어들 수 있으므로 항상 첫 번째 요소를 클릭하여 해제
        selected_cards.first.locator(".card-body-split").click()
        page.wait_for_timeout(50)

    # 모든 선택이 안전하게 해제되었는지 대기
    expect(page.locator(".ac-device-card.selected")).to_have_count(0, timeout=2000)
    page.click("#device-card-1 .card-body-split")
    page.click("#device-card-2 .card-body-split")
    page.click("#device-card-3 .card-body-split")

    # 복수 제어 모드 헤더 업데이트 대기
    page.wait_for_function(
        """() => {
            const el = document.getElementById('det-unit-name');
            return el && el.textContent.includes('외 2대');
        }""",
        timeout=2000,
    )

    # 헤더에 "외 2대" 표시 검증
    expect(page.locator("#det-unit-name")).to_contain_text("외 2대")

    # 선택된 3개 카드 CSS 하이라이트
    expect(page.locator("#device-card-1")).to_have_class(re.compile(r"selected"))
    expect(page.locator("#device-card-2")).to_have_class(re.compile(r"selected"))
    expect(page.locator("#device-card-3")).to_have_class(re.compile(r"selected"))

    # HEAT 모드 선택 → 일괄 적용
    page.click("#det-mode-heat")
    page.click(".btn-apply-cmd")

    # 일괄 적용 로그 확인
    open_qa_drawer(page)
    wait_for_log_containing(page, "제어 적용", timeout=LOG_RENDER_TIMEOUT)
    batch_log = page.locator(".qa-log-text").filter(has_text="제어 적용").first
    expect(batch_log).to_be_visible()

    # window.__vccs.devices 내부 상태 최종 검증 (1, 2, 3번 기기 mode = HEAT)
    for device_id in [1, 2, 3]:
        device_mode = page.evaluate(
            f"() => {{ const d = window.__vccs.devices.find(x => x.id === {device_id}); return d ? d.mode : null; }}"
        )
        assert device_mode == "HEAT", (
            f"기기 {device_id}번 mode가 HEAT가 아님 (실제: {device_mode})"
        )


# ============================================================
# 【TC-TEMP-001】온도 상한 경계값 방어 검증
# ============================================================
def test_tc_temp_001_upper_limit_boundary(page: Page):
    """[TC-TEMP-001] 온도 경계값 방어 | 설정온도 30°C 상한 초과 시도 → Toast 경고 + 값 차단 검증"""
    load_clean_simulator(page)
    select_device_card(page, 1)

    # 29°C 까지 클릭 (Flaky Test 방어 로직 적용)
    for _ in range(20):
        current_text = page.locator("#det-temp-display").inner_text()
        current_val = float(re.sub(r"[^0-9.]", "", current_text.split("°")[0]))
        if current_val >= 29.0:
            break
        page.click("#det-temp-up-btn")
        page.wait_for_timeout(50)

    expect(page.locator("#det-temp-display")).to_contain_text("29.0")

    # 30°C 달성 (정상 범위 내 마지막 허용값)
    page.click("#det-temp-up-btn")
    expect(page.locator("#det-temp-display")).to_contain_text("30.0")

    # 30°C 초과 시도 → Toast 경고 트리거
    page.click("#det-temp-up-btn")

    # Toast 경고 표시 및 메시지 검증
    toast = page.locator("#global-toast")
    expect(toast).to_have_class(re.compile(r"show"))
    toast_text = toast.text_content() or ""
    assert "16.0°C ~ 30.0°C" in toast_text, f"Toast에 범위 안내 없음: {toast_text}"

    # 온도 표시값 30.0°C 차단 검증
    expect(page.locator("#det-temp-display")).to_contain_text("30.0")


# ============================================================
# 【Pipeline Validation】알람 UI 표시 기준 모호성 — 요구사항 확인 필요 분류
# ============================================================
def test_pipeline_001_alarm_ui_ambiguity_classification(page: Page):
    """[TC-PIPE-001] 요구사항 모호성 | 알람(CH05) 발생 시 카드 색상 변경 기준 부재로 인한 Assert 불가"""
    load_clean_simulator(page)
    # QA Drawer가 덮기 전에 장치를 먼저 선택합니다.
    select_device_card(page, 5)
    open_qa_drawer(page)

    # 에러 주입
    page.click("button:has-text('CH05 과열 에러')")
    wait_for_log_containing(page, "알람 발생")

    # 여기서 기획의 공백(Ambiguity) 발생
    # 기획서에는 "알람 시 에러 상태로 변경된다"라고만 되어 있고,
    # 카드의 배경색이 빨간색이 되어야 하는지, 테두리만 바뀌어야 하는지 스펙이 없음.
    pytest.skip("기획·요구사항 확인 필요: CH05 알람 발생 시 장치 카드 배경/UI 표시 색상 기획이 누락되어 Assert 불가.")


# ============================================================
# 【TC-PIPE-002】시뮬레이터 환경 이슈 분류
# ============================================================
def test_pipeline_002_simulator_timeout_classification(page: Page):
    """[TC-PIPE-002] 시뮬레이터 환경 이슈 분류 | 제어 명령 후 가상 환경 미반응 (Simulator Timeout)"""
    load_clean_simulator(page)
    # QA Drawer가 덮기 전에 장치를 먼저 선택합니다.
    select_device_card(page, 1)
    open_qa_drawer(page)

    # 5초간 기다렸으나 가상 환경에서 상태 갱신이 올라오지 않는 상황을 시뮬레이션
    raise SimulatorTimeoutError(
        "테스트 환경·시뮬레이터 문제: UI에서 전원 켜기 제어를 시도했으나, 5000ms 내에 가상 환경으로부터 응답을 받지 못했습니다."
    )


# ============================================================
# 【TC-PIPE-003】자동화 코드 오류 분류
# 분류 목적: 자동화 스크립트의 잘못된 셀렉터가 Playwright TimeoutError를
#           유발하는 경우를 'automation_issue'로 정확하게 분류하는지 검증
# ============================================================
def test_pipeline_003_automation_code_error_classification(page: Page):
    """[TC-PIPE-003] 파이프라인 분류 검증 | UI 변경 후 자동화 스크립트의 요소 식별 정보 불일치로 인한 Playwright TimeoutError"""
    load_clean_simulator(page)

    # 자동화 코드 오류 시뮬레이션:
    # UI 변경 후 기존 요소 식별 정보가 더 이상 유효하지 않은 상황을 재현합니다.
    # 실무에서는 화면 구조가 변경됐지만 자동화 스크립트가 갱신되지 않았을 때 발생합니다.
    # 이 에러는 SimulatorTimeoutError도 AssertionError도 아니므로 → automation_issue 분류
    page.locator("#qa-result-panel").click(timeout=2000)


# ============================================================
# 【TC-PIPE-004】조건 부족 미실행 분류
# 분류 목적: 기획·요구사항 문제가 아닌, 순수하게 테스트 실행 조건이
#           충족되지 않아 미실행 처리하는 경우를 'not_executed'로 분류하는지 검증
# ============================================================
def test_pipeline_004_not_executed_condition_missing(page: Page):
    """[TC-PIPE-004] 조건 부족 미실행 | 시뮬레이터 지원 범위(16대)를 초과한 17번 장치가 없어 실행 보류"""
    load_clean_simulator(page)

    # 실행 조건 선행 검사: 가상 관제 화면의 장치 목록에 17번 장치가 제공되는지 확인
    device_17_exists = page.evaluate(
        "() => !!document.getElementById('device-card-17')"
    )

    # 17번 장치가 없으면 '조건 부족'으로 미실행 처리
    # ※ 이 skip 메시지에는 '기획' / '요구사항' 키워드가 없으므로 → not_executed 분류
    if not device_17_exists:
        pytest.skip(
            "조건 부족으로 미실행: 시뮬레이터 최대 장치 수(16대) 초과 — "
            "가상 관제 화면의 장치 목록에 17번 장치가 제공되지 않아 테스트 실행 불가."
        )

    # 17번 장치가 존재하는 경우 (현재 시뮬레이터에서는 도달 불가)
    select_device_card(page, 17)


# ============================================================
# 【TC-TEMP-002】제품 결함 후보 분류
# 분류 목적: 실제 제품 동작이 기획 요건과 다를 때 AssertionError가 발생하고
#           이를 'product_defect'으로 정확하게 분류하는지 검증
# ============================================================
def test_tc_temp_002_auto_mode_lower_limit(page: Page):
    """[TC-TEMP-002] 제품 결함 후보 | AUTO 모드 온도 하한(18.0°C) 방어 실패 — 17.0°C 설정 허용 결함"""
    load_clean_simulator(page)
    select_device_card(page, 1)

    # 1. 운전모드를 AUTO로 변경
    page.click("#det-mode-auto")
    expect(page.locator("#det-mode-auto")).to_have_class(re.compile(r"active"))

    # 2. 18.0°C까지 하강 (기존 16.0°C에서 18.0°C로 방어선 상향 기획)
    for _ in range(15):
        current_text = page.locator("#det-temp-display").inner_text()
        if "---" in current_text or "18.0" in current_text:
            break
        page.click("#det-temp-down-btn")
        page.wait_for_timeout(50)

    # 3. 18.0°C 상태에서 한 번 더 하강 시도 (17.0°C로 내려가는지 확인)
    page.click("#det-temp-down-btn")

    # 4. 결과 확인
    # 신규 요구사항: AUTO 모드에서는 18.0°C 미만 설정 불가. Toast 경고 노출 및 온도 18.0°C 유지
    # 실제 상황: 시뮬레이터에 해당 분기처리가 누락되어 17.0°C(기존 16.0°C 제한)까지 그냥 내려감
    toast = page.locator("#global-toast")
    has_toast = toast.evaluate("el => el.classList.contains('show')")
    current_text = page.locator("#det-temp-display").inner_text()

    # 이 Assert는 시뮬레이터에 AUTO 모드 온도 제한 로직이 누락되었기 때문에 반드시 실패하여 제품 결함으로 분류됨
    assert has_toast and "18.0" in current_text, (
        f"제품 결함 후보: AUTO 모드 온도 하한(18.0°C) 방어 로직 누락. "
        f"신규 기획 요건: AUTO 모드 시 설정 온도는 18.0°C ~ 30.0°C. "
        f"실제 결과: Toast 노출({has_toast}), 현재 표시온도({current_text})"
    )
