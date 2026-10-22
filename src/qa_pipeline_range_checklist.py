"""Code-computed checklist for allowed-range change requests (range_checklist_contract 1.0).

2026-10-17 사용자 결정: 모드 전환 질문(T-5)이 실제 실행 두 번 연속 빠졌고 검토 AI도
잡지 못했다(분석 단계에 해당 항목이 없어 검토 대상이 없음). 범위 표는 Agent 1이 이미
쓰는 확정 조건 문장에서만 읽고, 필수 시험·질문 목록은 사람 확정 규칙(T-1, T-2, T-5)으로
코드가 계산해 Agent 2에 전달하며, 설계 후 같은 목록으로 대조한다.

Only unambiguous sentences are read (one mode name, one range, the words "허용 범위",
a CHANGE_REQUEST source, 변경/유지 role). Anything else yields no checklist, so the
check never blocks a request it cannot read. Operations and typed verifications are
compared; prose is never parsed for expected values.

1.1 (2026-10-17 사람 대조 H-2): 요청서가 '이번에 다루지 않는 것'(제외_범위)에 바뀐 모드로의
전환·범위 밖 처리를 적어 두었으면 T-5 질문은 필수가 아니다. 1.0 Run은 예전 목록 그대로
다시 검증한다.
"""
from __future__ import annotations

import re
from typing import Any

VERSION = "range-checklist-1.1"
LOCATIONS = ("panel", "card", "internal")
MODE_WORDS = {"COOL": ("COOL", "냉방"), "HEAT": ("HEAT", "난방"), "AUTO": ("AUTO", "자동"),
              "DRY": ("DRY", "제습"), "FAN": ("FAN", "송풍")}
SWITCH_WORDS = ("전환", "바꾸", "바꿀", "바뀌", "바뀔", "범위 밖", "범위를 벗어")
# An exclusion item about entering the changed mode from outside its range.
EXCLUSION_WORDS = (*SWITCH_WORDS, "진입")
# In exclusion prose "자동 보정" is not the AUTO mode; require the mode itself.
EXCLUSION_MODE_WORDS = {**MODE_WORDS, "AUTO": ("AUTO", "자동 모드", "자동(")}
_RANGE = re.compile(r"(\d+)\s*(?:°C|도)?\s*~\s*(\d+)\s*(?:°C|도)")


def _modes(text: str) -> list[str]:
    return [mode for mode, words in MODE_WORDS.items() if any(w in text for w in words)]


def range_table(analysis) -> dict[str, list[dict[str, Any]]] | None:
    """Changed/kept mode ranges stated by Agent 1 itself; None when not a range change."""
    changed, kept = {}, {}
    for condition in analysis.confirmed_conditions:
        role = getattr(condition.change_role, "value", condition.change_role)
        source = getattr(condition.source_type, "value", condition.source_type)
        text = condition.statement
        if source != "CHANGE_REQUEST" or role not in {"변경", "유지"} or "허용 범위" not in text:
            continue
        modes, ranges = _modes(text), _RANGE.findall(text)
        if len(modes) != 1 or not ranges:
            continue
        lower, upper = (int(v) for v in ranges[-1])  # "16~30°C에서 20~30°C로": the stated result
        if lower >= upper:
            continue
        bucket = changed if role == "변경" else kept
        if modes[0] in bucket and bucket[modes[0]] != (lower, upper):
            return None  # conflicting statements: do not guess
        bucket[modes[0]] = (lower, upper)
    if not changed or set(changed) & set(kept):
        return None
    as_rows = lambda d: [dict(mode=m, lower=lo, upper=up) for m, (lo, up) in sorted(d.items())]
    return {"changed": as_rows(changed), "kept": as_rows(kept)}


def excluded_switch_modes(analysis) -> set[str]:
    """Modes whose switch behavior the request itself put out of scope (H-2).

    Read from Agent 1's 제외_범위, which CP1 requires to keep every request
    out_of_scope item. One item must name exactly one mode plus a switch/entry word.
    """
    modes = set()
    for item in getattr(analysis, "excluded_scope", None) or []:
        named = [m for m, words in EXCLUSION_MODE_WORDS.items() if any(w in str(item) for w in words)]
        if len(named) == 1 and any(w in str(item) for w in EXCLUSION_WORDS):
            modes.add(named[0])
    return modes


def checklist(table: dict, excluded_modes=()) -> list[dict[str, Any]]:
    rows = []
    for r in table["changed"]:
        mode, lo, up = r["mode"], r["lower"], r["upper"]
        rows += [dict(id=f"T-1:APPLY:{mode}:{lo}", kind="APPLY", mode=mode, attempted=lo, expected=lo,
                      text=f"{mode} {lo}°C 적용 후 패널·카드·내부값이 {lo}°C인지 별도 기대결과로 확인"),
                 dict(id=f"T-1:APPLY:{mode}:{up}", kind="APPLY", mode=mode, attempted=up, expected=up,
                      text=f"{mode} {up}°C 적용 후 패널·카드·내부값이 {up}°C인지 별도 기대결과로 확인"),
                 dict(id=f"T-2:BLOCK:{mode}:{lo - 1}", kind="BLOCK", mode=mode, attempted=lo - 1, expected=lo,
                      text=f"{mode} {lo}°C에서 {lo - 1}°C로 내리려 해도 패널·카드·내부값이 {lo}°C 그대로인지 확인"),
                 dict(id=f"T-2:BLOCK:{mode}:{up + 1}", kind="BLOCK", mode=mode, attempted=up + 1, expected=up,
                      text=f"{mode} {up}°C에서 {up + 1}°C로 올리려 해도 패널·카드·내부값이 {up}°C 그대로인지 확인")]
        outside = [k for k in table["kept"] if k["lower"] < lo or k["upper"] > up]
        if outside and mode not in excluded_modes:
            ranges = ", ".join(f"{k['mode']} {k['lower']}~{k['upper']}°C" for k in outside)
            rows.append(dict(id=f"T-5:QUESTION:{mode}", kind="QUESTION", mode=mode,
                             kept_modes=[k["mode"] for k in outside],
                             text=f"{ranges}에는 {mode} {lo}~{up}°C 밖 온도가 있다. 그 온도에서 {mode}로 바꿀 때의 동작을 "
                                  "요청이 정하지 않았으면 기대값을 만들지 말고 최종_확인_사항에 질문으로 남긴다"))
    return rows


def render(rows) -> str:
    return "\n".join(f"- [{r['id']}] {r['text']}" for r in rows)


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace("°C", "").strip())
    except ValueError:
        return None


def _expected_temp(verification: dict):
    location, _, field = str(verification.get("target") or "").partition(".")
    if field != "setTemp" or location not in LOCATIONS:
        return None
    for key in ("expected_number", "expected_value"):
        if _number(verification.get(key)) is not None:
            return location, _number(verification[key])
    for item in verification.get("expected_fields") or []:
        if item.get("field_name") == "setTemp":
            return location, _number(item.get("expected_value"))
    return location, None


def _probes(design: dict) -> list[dict]:
    """TEST-phase temperature attempts per TC, with the setTemp checks bound to them."""
    probes = []
    for tc in design.get("test_cases") or []:
        spec = tc.get("execution_spec") or {}
        mode = temp = None
        current = []
        for op in spec.get("operations") or []:
            target, phase = str(op.get("target") or ""), op.get("phase")
            if phase == "RESTORE" or target == "controller.restore":
                break
            if target.startswith("mode."):
                mode = target.split(".", 1)[1].upper()
                continue
            attempted = None
            if target == "temperature.set":
                attempted = _number(op.get("value"))
            elif target in {"temperature.increase", "temperature.decrease"} and temp is not None:
                attempted = temp + (1 if target.endswith("increase") else -1)
            if attempted is None:
                if phase == "TEST" and current:
                    current[-1]["window"].append(op.get("action_id"))
                continue
            if phase == "TEST":
                current.append(dict(tc_id=tc.get("tc_id"), mode=mode, attempted=attempted,
                                    window=[op.get("action_id")]))
            temp = attempted
        for probe in current:
            probe["expected"] = dict(found for v in spec.get("verifications") or []
                                     if v.get("after_action_id") in probe["window"]
                                     for found in [_expected_temp(v)] if found)
        probes += current
    return probes


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, list):
        return [t for v in value for t in _strings(v)]
    return []


def _asked(design: dict, mode: str, kept_modes) -> bool:
    """One non-blocking final note names the changed mode and a kept mode or the switch."""
    words = MODE_WORDS.get(mode, (mode,))
    other = [w for k in kept_modes for w in MODE_WORDS.get(k, (k,))]
    for entry in design.get("최종_확인_사항") or design.get("final_review_notes") or []:
        text = " ".join(_strings(entry))
        if any(w in text for w in words) and (any(w in text for w in other) or any(w in text for w in SWITCH_WORDS)):
            return True
    return False


def compare(rows, design: dict) -> list[dict[str, str]]:
    """Missing or wrong checklist items; empty means every required item is present."""
    probes, problems = _probes(design), []
    for row in rows:
        if row["kind"] == "QUESTION":
            if not _asked(design, row["mode"], row["kept_modes"]):
                problems.append(dict(id=row["id"], reason="최종_확인_사항에 모드 전환 질문이 없음(중단_확인_사항이 아니라 최종_확인_사항에 남김)"))
            continue
        matches = [p for p in probes if p["mode"] == row["mode"] and p["attempted"] == row["attempted"]]
        if not matches:
            problems.append(dict(id=row["id"], reason="TEST 단계에 이 값을 시도하는 조작이 없음"))
            continue
        best = None
        for p in matches:
            wrong = {loc: v for loc, v in p["expected"].items() if v is not None and v != row["expected"]}
            missing = [loc for loc in LOCATIONS if p["expected"].get(loc) != row["expected"]]
            if wrong:
                best = f"{p['tc_id']}: 기대값 {wrong}, 정답 {row['expected']}"
                break
            if not missing:
                best = None
                break
            best = f"{p['tc_id']}: {', '.join(missing)} 확인 없음"
        if best:
            problems.append(dict(id=row["id"], reason=best))
    return problems


def range_checklist_check(analysis, design):
    """CP2 check; None when the request is not a readable range change."""
    from qa_pipeline_contracts import CheckResult, CheckStatus
    table = range_table(analysis)
    if table is None:
        return None
    rows = checklist(table, excluded_switch_modes(analysis))
    data = design.model_dump(mode="json", by_alias=True) if hasattr(design, "model_dump") else design
    problems = compare(rows, data)
    if problems:
        return CheckResult(rule_id="CP2-RANGE-CHECKLIST", status=CheckStatus.FAIL,
                           message="[치명] 코드가 계산한 필수 확인 목록 누락: " + "; ".join(
                               f"{p['id']} {p['reason']}" for p in problems))
    return CheckResult(rule_id="CP2-RANGE-CHECKLIST", status=CheckStatus.PASS,
                       message=f"코드가 계산한 필수 확인 목록 {len(rows)}개가 설계에 있습니다({VERSION}).")
