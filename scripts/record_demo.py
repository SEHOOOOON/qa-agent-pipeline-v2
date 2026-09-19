"""Read-only V2 recording: real saved runs, never live APIs or asset approval.

The result is an approval-pending preview, not an official-registration video.
No V1 files, source HTML, run artifacts or official assets are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qa_pipeline_ui import PipelineUiBridge, make_handler, summarize_run
from qa_pipeline_reporting import _verify_final_report_sources

RUNS = ("RUN-20260918-110541-4102E0", "RUN-20260827-114925-507176",
        "RUN-20260912-100402-5F1715")


@dataclass(frozen=True)
class Scene:
    run: int
    stage: str
    focus: str
    seconds: int
    title: str
    caption: str


SCENES = (
    Scene(0, "agent4", "stages", 6, "변경 요청에서 검증과 사람 판단까지", "실제 저장 Run 조회 · 승인 전 미리보기"),
    Scene(0, "agent1", "detail", 8, "01 요구사항 정제", "변경 조건과 유지 조건을 나누고, 근거를 대조합니다."),
    Scene(0, "agent2", "tc", 10, "02 상세 테스트 설계", "대상 선택 → 중풍 선택 → 적용 · 화면과 내부 값 확인 · 복원"),
    Scene(0, "agent3", "detail", 8, "03 자동화 계획과 실행", "저장된 실제 시험 기록 · UI 표시와 내부 값, 복원 결과 확인"),
    Scene(0, "agent4", "results", 7, "04 결과 분석 및 보고", "중풍 후보 + 기존 강풍 + 환경 점검: 3건 통과"),
    Scene(0, "agent4", "approval", 12, "05 사람의 최종 판단 — 아직 미등록", "SRS 개정 문구와 증거를 검토하는 화면입니다. 이 영상은 승인을 수행하지 않습니다."),
    Scene(1, "agent2", "tc", 8, "실패 사례 · 잠금 후 버튼 비활성 기대", "당시 실제 실행 기록 조회 · 현재 계약과의 차이는 승인 경고에 유지"),
    Scene(1, "agent4", "results", 11, "제품 불일치 후보 — 결함 확정 아님", "기대값을 바꿔 통과시키지 않고, 실패와 검토 근거를 남깁니다."),
    Scene(2, "agent1", "detail", 9, "미정 조건 · 알림 색상이 정해지지 않은 요청", "미정 색상을 임의의 기대값으로 만들지 않습니다."),
    Scene(2, "agent4", "detail", 7, "시험 통과와 요청 전체 완료는 다릅니다", "3건 통과 + 정보 부족 1건 · 최종 권고는 사람 검토"),
    Scene(0, "agent4", "approval", 4, "근거 · 실행 증거 · 사람 판단", "승인 전 미리보기 종료 · 원본 SRS와 공식 TC는 변경하지 않았습니다."),
)


def permitted_request(url: str, method: str, origin: str) -> bool:
    parsed, local = urlsplit(url), urlsplit(origin)
    return method == "GET" and parsed.scheme == "http" and parsed.netloc == local.netloc


def snapshot() -> dict[str, str]:
    files = [ROOT / "docs/01_PRODUCT_SRS.md", ROOT / "product_baseline/virtual-controller.html"]
    for folder in [ROOT / "approved_assets", *(ROOT / "runs" / rid for rid in RUNS)]:
        files.extend(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def preflight() -> list[dict]:
    checks = []
    for i, rid in enumerate(RUNS):
        source_warning = None
        try:
            _verify_final_report_sources(ROOT / "runs" / rid, rid)
        except ValueError as exc:
            # Only this independently audited historic incompatibility is allowed.
            if i != 1 or str(exc) != "Stored Checkpoint 2 differs from the current CP2 rules.":
                raise
            source_warning = str(exc)
        summary = summarize_run(ROOT / "runs", rid)
        expected = "PASS" if i == 0 else "HUMAN_REVIEW"
        assert summary["overall_status"] == expected, (rid, summary["overall_status"])
        if i == 0:
            candidate = next(c for c in summary["candidate_assets"] if c["tc_id"] == "TC-CAND-001")
            assert candidate["approval_eligible"], candidate["eligibility_reasons"]
            assert not candidate.get("decision"), "This preview expects the unregistered source run."
        report = json.loads((ROOT / "runs" / rid / "final_report.json").read_text(encoding="utf-8"))
        assert report["status_counts"]["PASSED"] == 3
        assert report["total_results"] == (4 if i == 1 else 3)
        if i == 2:
            assert len(report["제외된_정보_부족"]) == 1
        checks.append({"run_id": rid, "overall_status": expected, "historic_source_warning": source_warning})
    return checks


def run(output: Path, smoke: bool = False) -> Path:
    from playwright.sync_api import sync_playwright, expect
    import imageio_ffmpeg

    output = output.resolve()
    if not output.is_relative_to(ROOT / "runs/manual_checks"):
        raise ValueError("Recording output must be a new directory under runs/manual_checks.")
    checks = preflight()
    before = snapshot()
    output.mkdir(parents=True, exist_ok=False)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    bridge = PipelineUiBridge(runs_root=ROOT / "runs", requests_root=ROOT / "examples",
        target_html=ROOT / "product_baseline/virtual-controller.html",
        allow_live_run=False, allow_asset_approval=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bridge))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    scenes = (Scene(0, "agent2", "tc", 4, "시험 녹화 · 상세 TC", "실제 저장 결과 조회 · 승인 및 API 호출 없음"),) if smoke else SCENES
    clips, recorded = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for index, scene in enumerate(scenes):
                context = browser.new_context(viewport={"width": 1600, "height": 900},
                    record_video_dir=str(output / "raw"), record_video_size={"width": 1600, "height": 900},
                    locale="ko-KR", timezone_id="Asia/Seoul")
                context.route("**/*", lambda route: route.continue_() if permitted_request(
                    route.request.url, route.request.method, origin) else route.abort())
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin, wait_until="domcontentloaded")
                page.add_style_tag(content="html {font-size:20px} .qa-live-body {padding-bottom:120px!important}")
                page.locator("#tab-qa").click()
                page.locator("#agent-4-btn").click()
                expect(page.locator("#qa-live-modal")).to_be_visible()
                page.locator("#qa-live-run-select").select_option(RUNS[scene.run])
                expect(page.locator("#qa-live-run-id")).to_have_text(RUNS[scene.run], timeout=15000)
                page.locator(f"#qa-live-stage-{scene.stage}").click()
                expect(page.locator("#qa-live-mode")).not_to_contain_text("데모")
                if scene.focus == "tc":
                    page.get_by_role("button", name="TC-CAND-001 ▾", exact=True).click()
                    focus = page.locator(".qa-live-result-detail:not([hidden])")
                else:
                    focus = page.locator({"detail": ".qa-live-detail", "results": ".qa-live-results",
                        "approval": ".qa-live-approval", "stages": ".qa-live-stage-grid"}[scene.focus])
                # Editorial caption only: do not replace any application result text.
                page.evaluate("""({title, caption}) => {
                    const banner = document.createElement('aside');
                    banner.id='recording-caption';
                    banner.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:1000000;padding:18px 36px;background:#080e18;color:white;border-top:2px solid #58a6ff;font:18px/1.6 sans-serif;pointer-events:none';
                    const heading=document.createElement('strong'); heading.style.cssText='display:block;color:#58a6ff;font-size:22px';heading.textContent=title;
                    const text=document.createElement('div');text.textContent=caption;
                    banner.append(heading,text); document.body.append(banner);
                }""", {"title": scene.title, "caption": scene.caption})
                focus.scroll_into_view_if_needed()
                page.wait_for_timeout(400)
                page.screenshot(path=str(output / f"scene-{index:02d}.png"))
                page.wait_for_timeout((scene.seconds + 1) * 1000)
                assert not errors, errors
                video = page.video
                context.close()
                raw = Path(video.path())
                clip = output / f"clip-{index:02d}.mp4"
                subprocess.run([ffmpeg, "-v", "error", "-n", "-sseof", str(-scene.seconds), "-i", str(raw),
                    "-t", str(scene.seconds), "-an", "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
                    "-preset", "fast", "-crf", "20", "-movflags", "+faststart", str(clip)], check=True, timeout=90)
                clips.append(clip)
                recorded.append({"run_id": RUNS[scene.run], "stage": scene.stage, "seconds": scene.seconds,
                    "title": scene.title, "caption": scene.caption})
                print(f"RECORDED {index + 1}/{len(scenes)} {scene.stage}", flush=True)
            browser.close()
        listing = output / "clips.txt"
        listing.write_text("\n".join(f"file '{clip.name}'" for clip in clips), encoding="utf-8")
        result = output / "qa-v2-approval-pending-preview.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-n", "-f", "concat", "-safe", "1", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(result)], check=True, timeout=90)
        decoded = subprocess.run([ffmpeg, "-v", "error", "-i", str(result), "-progress", "pipe:1",
            "-f", "null", "-"], check=True, capture_output=True, text=True, timeout=90)
        durations = [int(line.split("=", 1)[1]) / 1_000_000 for line in decoded.stdout.splitlines()
                     if line.startswith("out_time_us=") and line.split("=", 1)[1].isdigit()]
        actual_duration = max(durations)
        assert abs(actual_duration - sum(s.seconds for s in scenes)) < 0.15, actual_duration
        assert snapshot() == before, "Protected originals changed during recording"
        (output / "recording-manifest.json").write_text(json.dumps({"preview_only": True,
            "official_registration_performed": False, "api_calls": 0, "external_posts": 0,
            "protected_files_unchanged": len(before), "expected_duration_seconds": sum(s.seconds for s in scenes),
            "decoded_duration_seconds": actual_duration,
            "runs": checks, "scenes": recorded,
            "video_sha256": hashlib.sha256(result.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Record a four-second TC preview only")
    parser.add_argument("--output", type=Path,
        default=ROOT / "runs/manual_checks" / datetime.now().strftime("video-preview-%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    print(run(args.output, args.smoke))
