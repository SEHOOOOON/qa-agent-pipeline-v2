"""Record missing arcs without treating coverage absence as dead-code proof.

Reads an immutable Git source revision for the baseline and maps unchanged lines
to the current checkout. Does not import pipeline modules or execute model calls.
Classification is a conservative maintenance triage, not a reachability solver.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def entry_context(file, function):
    if function in {'evaluate_checkpoint1', 'evaluate_checkpoint2', 'evaluate_checkpoint3_plan'}:
        return '최초 생성·제한된 재작성 후 검사 및 저장 결과/승인 전 재검사. 잘못된 모델 출력도 입력이므로 정상 예시와 다른 값·연결·조합을 처리합니다.'
    if function == 'inspect_target_ui':
        return '선택된 TC가 요구하는 UI/하네스만 관찰하거나 범용 요소를 추가 수집합니다. 요청별 선택자·제품 초기 상태·미지원 인터페이스에 따라 갈립니다.'
    if function == 'evaluate_agent3_eligibility':
        return 'TC의 대상·제어 경로·화면/내부/알림 관찰 종류로 전용 지원·범용 탐색·지원 부재를 구분합니다.'
    if function == 'compile_automation_candidate' or function.endswith('_read_expression'):
        return '검사된 계획의 행동·Assertion·복원 종류에 따라 Python 코드를 생성합니다. 코드 생성 분기 실행과 생성 코드의 실제 브라우저 실행은 별도 증거입니다.'
    if function in {'_candidate_execution_records', '_candidate_execution_record', '_current_candidate_execution_record'}:
        return '단일/다중 후보 산출물을 최종 실행으로 인계할 때 현재 TC·파일·증거·제품 해시를 확인하고 동일 후보 재사용/재시험을 구분합니다.'
    if function == '_verified_existing_catalog_for_execution':
        return '관련 기존 TC 실행 전에 과거 기본 카탈로그 또는 사람 승인 자산 Snapshot과 자동화 파일을 대조합니다.'
    if file.endswith('agent1.py') or file.endswith('agent2.py') or file.endswith('agent3.py'):
        return '해당 Agent의 입력 구성·기술 ID 정리·TC/계획 검사 보조 경로. 상위 계약과 옵션을 확인해야 도달 가능 여부를 판단할 수 있습니다.'
    if file.endswith('reporting.py'):
        return 'Agent 4 분류·최종 근거 확인·사람 검토 문서·선택적 외부 보고. 재전송/새로고침/증거 손상 시에도 사용됩니다.'
    if file.endswith('ui.py'):
        return '로컬 UI의 조회·입력·잠금·실행·사람 승인/보류 처리. HTTP 콜백·worker thread 등 직접 호출문으로만 찾을 수 없는 진입점도 있습니다.'
    if file.endswith('execution.py') or file.endswith('orchestrator.py'):
        return 'CLI/오케스트레이터의 단계 실행·재사용·인계·실패 종료. 복수 후보와 환경/복원 오류, 명시적 단일 후보 실행도 포함합니다.'
    return '공통 구조화 계약·파일 로더·무결성 검사 또는 공개 진입점. 직접 함수 사용과 CLI의 상위 검증 경계를 함께 확인합니다.'


def purpose(file, function, line, guards, source):
    if (file.endswith('agent1.py') and line == 971) or (file.endswith('agent2.py') and line == 1681):
        return 'DUPLICATED_AGGREGATION', '현재 CP 생성기는 ERROR를 만들지 않지만 공통 상태 집계는 ERROR 우선순위를 보존해야 합니다.'
    if (file.endswith('agent1.py') and line == 499) or (file.endswith('contracts.py') and line == 1114):
        return 'UPSTREAM_SCHEMA_CONSTRAINED', '현재 정상 역직렬화에서는 앞선 스키마가 제한합니다(ChangeType은 MODIFIED만, expected_results는 최소 1건). 직접 호출·모델 변경·향후 계약 확장을 고려해 방어 검사는 유지합니다.'
    if function in {'_acquire_file', 'release'} and 'os.name' in source:
        return 'PLATFORM', 'Windows가 아닌 운영체제의 fcntl 잠금·해제 경로입니다. Windows 미실행을 삭제 근거로 사용하지 않습니다.'
    if function == '<module>' or (function == 'main' and line in {689, 690}):
        return 'ENTRYPOINT', 'import와 직접 CLI 실행/표준 출력 환경의 차이입니다. 부모 프로세스 커버리지는 자식 CLI 실행을 포함하지 않습니다.'
    if any('legacy_wording_checks' in g for g in [source, *guards]) or function == '_tc_restore_basis_errors':
        return 'LEGACY_COMPATIBILITY', '이전 계약의 저장 Run을 읽거나 과거 검사 옵션을 사용하는 경로입니다. 새 실행에서 사용하지 않아도 보존합니다.'
    if function in {'before_and_after_must_differ', 'restore_contract_must_be_consistent',
                    '_structured_restoration_errors', '_precondition_proof_errors',
                    '_restore_comparison_coverage', '_restore_confirmation_coverage',
                    '_structured_restore_plan_coverage'}:
        return 'CONTRACT_GUARD', '잘못된 구조/연결을 거부하는 검사입니다. 상위 스키마가 막는지와 직접 함수 호출 가능성을 함께 확인해야 합니다.'
    if (function.startswith(('_load_verified', '_safe_', '_verify_', '_verified_', '_agent4_'))
            or function in {'load_approved_regression_catalog', 'load_srs_requirements',
                            '_existing_regression_by_id', '_catalog_from_snapshot',
                            '_candidate_execution_record', '_candidate_execution_records',
                            '_candidate_file_for_result', '_read_json_payload', '_resolve_run_dir',
                            '_restore_files_after_error', '_run_directory', '_safe_text'}):
        return 'INTEGRITY_OR_FAILURE_GUARD', '저장 데이터·경로·해시·실행 상태의 오류 또는 출처 경계입니다. 정상 성공 경로에 드물어도 제거하지 않습니다.'
    if function.startswith(('_notion', '_sync_notion', '_upsert_notion')) or function == 'run_external_reporting':
        return 'EXTERNAL_REPORTING', '외부 게시 설정·응답·페이지 처리 분기입니다. 대역 응답 검사와 실제 외부 서비스 검증을 구분합니다.'
    if function in {'decide_existing_srs', '_existing_srs_approval_check', '_decide_candidate_asset_impl',
                    '_candidate_approval_check', 'revalidate_candidate_asset', 'revalidate_asset',
                    'decide_asset', '_next_official_tc_id', 'apply_srs_revision_proposals'}:
        return 'HUMAN_APPROVAL', '보류·승인·중복 등록·재검증·되돌림 조건입니다. 복사본에서만 재현하고 공식 자산은 수정하지 않습니다.'
    return 'CONDITIONAL_PATH_RETAIN', '다른 입력·시험 유형·실행 상태에 따라 달라지는 후보 경로입니다. 미실행만으로 도달 불가를 증명하지 못하므로 유지합니다.'


def normalize_files(report):
    return {name.replace('\\', '/'): data for name, data in report['files'].items()}


def build(baseline, current, revision):
    old_files, new_files = normalize_files(baseline), normalize_files(current)
    references = {}
    for path in sorted((ROOT / 'tests').glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')):
            for node in ast.walk(fn):
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if name:
                    references.setdefault(name, set()).add(f'{path.relative_to(ROOT).as_posix()}:{fn.lineno}:{fn.name}')
    entries, hashes = [], {}
    for file, data in old_files.items():
        old_text = subprocess.check_output(['git', 'show', f'{revision}:{file}'], cwd=ROOT).decode('utf-8-sig')
        now_text = (ROOT / file).read_text(encoding='utf-8-sig')
        old_lines, now_lines = old_text.splitlines(), now_text.splitlines()
        hashes[file] = {'baseline_normalized_sha256': hashlib.sha256('\n'.join(old_lines).encode()).hexdigest(),
                        'current_normalized_sha256': hashlib.sha256('\n'.join(now_lines).encode()).hexdigest()}
        mapping = {}
        for block in difflib.SequenceMatcher(None, old_lines, now_lines, autojunk=False).get_matching_blocks():
            mapping.update({block.a+i+1: block.b+i+1 for i in range(block.size)})
        tree = ast.parse(old_text)
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        conditions = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
        executed = {tuple(arc) for arc in new_files.get(file, {}).get('executed_branches', [])}
        possible = executed | {tuple(arc) for arc in new_files.get(file, {}).get('missing_branches', [])}
        for start, end in data.get('missing_branches', []):
            enclosing = [n for n in funcs if n.lineno <= start <= n.end_lineno]
            function = min(enclosing, key=lambda n: n.end_lineno-n.lineno).name if enclosing else '<module>'
            guards = [ast.unparse(n.test) for n in conditions if n.lineno < start <= n.end_lineno]
            kind, reason = purpose(file, function, start, guards, old_lines[start-1].strip())
            mapped = (mapping.get(start), mapping.get(abs(end)))
            arc = (mapped[0], (-mapped[1] if end < 0 else mapped[1])) if all(mapped) else None
            state = ('EXECUTED_IN_RECHECK' if arc in executed else 'STILL_NOT_OBSERVED' if arc in possible
                     else 'SOURCE_CHANGED_REQUIRES_REVIEW')
            entries.append({'id': f'{file}:{start}->{end}', 'file': file, 'function': function,
                            'baseline_arc': [start, end], 'condition': old_lines[start-1].strip(),
                            'destination': old_lines[end-1].strip() if end > 0 else '<function exit>',
                            'enclosing_conditions': guards, 'purpose': kind, 'retention_reason': reason,
                            'entry_context': entry_context(file, function),
                            'current_arc': arc, 'verification': state,
                            'related_tests_not_arc_proof': sorted(references.get(function, [])),
                            'delete_authorized_by_coverage': False})
    return {'schema': '1.0', 'baseline_revision': revision,
            'scope': 'Original missing src Python arcs; parent process only; no reachability proof or deletion instruction.',
            'baseline_missing_count': len(entries), 'source_hashes': hashes,
            'purpose_counts': dict(Counter(e['purpose'] for e in entries)),
            'verification_counts': dict(Counter(e['verification'] for e in entries)),
            'current_coverage_totals': current['totals'], 'branches': entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', args.revision+'^{commit}'], cwd=ROOT).decode().strip()
    result = build(json.loads(args.baseline.read_text(encoding='utf-8')), json.loads(args.current.read_text(encoding='utf-8')), revision)
    result['coverage_input_sha256'] = {'baseline': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                                      'recheck': hashlib.sha256(args.current.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('baseline_missing_count', 'purpose_counts', 'verification_counts')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
