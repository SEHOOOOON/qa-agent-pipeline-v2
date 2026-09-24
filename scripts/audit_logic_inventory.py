"""Build a static logic index without importing or executing pipeline modules.

This indexes syntax, not reachable paths, semantic correctness or test coverage.
The human-readable rule map lives in docs/PROJECT_GUIDE.md.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "logic_inventory.json"
CONTROL = (ast.If, ast.IfExp, ast.BoolOp, ast.For, ast.AsyncFor, ast.While,
           ast.Try, ast.ExceptHandler, ast.Match, ast.Assert, ast.Raise,
           ast.Return, ast.Break, ast.Continue, ast.With, ast.AsyncWith)
SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

# Parse only: never execute scripts extracted from HTML. Prefer a locally
# installed Acorn, otherwise use the parser bundled in Node. Fail explicitly if
# neither is available; never install a dependency or silently omit JS branches.
JS_INDEXER = r'''
const fs = require('node:fs');
let acorn, parserSource;
try { acorn = require('acorn'); parserSource = 'local-acorn'; }
catch {
  const source = process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'];
  if (!source) throw new Error('Acorn unavailable: use a Node distribution with Acorn or provide local acorn.');
  const module = {exports: {}};
  new Function('exports', 'module', source)(module.exports, module);
  acorn = module.exports; parserSource = 'node-bundled-acorn';
}
const inputs = JSON.parse(fs.readFileSync(0, 'utf8'));
const controls = new Set(['IfStatement','ConditionalExpression','LogicalExpression',
 'ForStatement','ForInStatement','ForOfStatement','WhileStatement','DoWhileStatement',
 'TryStatement','CatchClause','SwitchStatement','SwitchCase','ThrowStatement',
 'ReturnStatement','BreakStatement','ContinueStatement','WithStatement','ChainExpression']);
const functionTypes = new Set(['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression',
 'ClassDeclaration','ClassExpression']);
function index(input) {
 const source = input.source;
 const tree = acorn.parse(source, {ecmaVersion:'latest', locations:true,
   sourceType:input.module ? 'module' : 'script', allowReturnOutsideFunction:!!input.handler});
 const definitions = [], control_nodes = [], declarations = [];
 const loc = n => ({line:input.line+n.loc.start.line-1,
   column:n.loc.start.column, end_line:input.line+n.loc.end.line-1});
 const text = n => n ? source.slice(n.start,n.end) : null;
 function visit(n, scope='<script>', guards=[]) {
   if (!n || typeof n.type !== 'string') return;
   if (functionTypes.has(n.type)) {
     scope += '.' + (n.id?.name || `<anonymous:${loc(n).line}:${n.loc.start.column}>`);
     definitions.push({...loc(n),kind:n.type,name:scope});
   }
   if (controls.has(n.type)) {
     const condition = n.test || n.discriminant || n.argument || n.param ||
       (n.type==='LogicalExpression' || n.type==='ChainExpression' ? n : n.right);
     control_nodes.push({...loc(n),kind:n.type,scope,condition_or_value:text(condition),guards});
   }
   if (n.type==='VariableDeclaration') declarations.push({...loc(n),kind:n.type,scope,
     declaration:text(n).length<600 ? text(n) : 'See source span (long data/template).'});
   for (const [key,value] of Object.entries(n)) {
     if (key==='loc') continue;
     let next = guards;
     if ((n.type==='IfStatement'||n.type==='ConditionalExpression') && ['consequent','alternate'].includes(key))
       next = [...guards,`L${loc(n).line} ${key==='consequent'?'TRUE':'FALSE'}: ${text(n.test)}`];
     for (const child of (Array.isArray(value)?value:[value]))
       if (child && typeof child==='object' && typeof child.type==='string') visit(child,scope,next);
   }
 }
 visit(tree);
 return {line:input.line,handler:!!input.handler,definitions,control_nodes,declarations};
}
process.stdout.write(JSON.stringify({parser_source:parserSource,parser_version:acorn.version,
 node_version:process.version,blocks:inputs.map(index)}));
'''


def index_javascript(blocks):
    result = subprocess.run(["node", "-e", JS_INDEXER], input=json.dumps(blocks),
                            text=True, encoding="utf-8", capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


def expression(node):
    return ast.unparse(node) if node is not None else None


def index_python(source):
    tree = ast.parse(source)
    entries, definitions, checks, data, text_blocks = [], [], [], [], []
    scope_types = {}

    def walk(node, scope="<module>", guards=()):
        line = getattr(node, "lineno", None)
        base = {"line": line, "end_line": getattr(node, "end_lineno", line), "scope": scope}
        if isinstance(node, SCOPE):
            name = getattr(node, "name", f"<lambda:{line}>")
            scope = name if scope == "<module>" else f"{scope}.{name}"
            scope_types[scope] = type(node).__name__
            definitions.append({**base, "name": scope, "kind": type(node).__name__,
                                "decorators": [expression(d) for d in getattr(node, "decorator_list", [])]})
        if isinstance(node, CONTROL):
            detail = None
            if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
                detail = expression(node.test)
            elif isinstance(node, ast.BoolOp):
                detail = expression(node)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                detail = f"{expression(node.target)} in {expression(node.iter)}"
            elif isinstance(node, ast.ExceptHandler):
                detail = expression(node.type) or "bare except"
            elif isinstance(node, ast.Raise):
                detail = expression(node.exc) or "re-raise"
            elif isinstance(node, ast.Return):
                detail = expression(node.value)
            elif isinstance(node, ast.Match):
                detail = expression(node.subject)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                detail = [expression(i.context_expr) for i in node.items]
            entries.append({**base, "kind": type(node).__name__, "condition_or_value": detail,
                            "guards": list(guards),
                            "body_lines": [getattr(i, "lineno", None) for i in getattr(node, "body", [])]
                                if isinstance(getattr(node, "body", None), list) else [],
                            "else_lines": [getattr(i, "lineno", None) for i in getattr(node, "orelse", [])]
                                if isinstance(getattr(node, "orelse", None), list) else []})
        if isinstance(node, ast.comprehension):
            entries.append({"line": node.target.lineno, "end_line": node.iter.end_lineno,
                            "scope": scope, "kind": "comprehension",
                            "condition_or_value": {"target": expression(node.target), "iter": expression(node.iter),
                                                   "filters": [expression(i) for i in node.ifs]}, "guards": list(guards)})
        if isinstance(node, ast.match_case):
            entries.append({"line": node.pattern.lineno, "end_line": node.pattern.end_lineno,
                            "scope": scope, "kind": "match_case", "condition_or_value": expression(node.pattern),
                            "case_guard": expression(node.guard), "guards": list(guards)})
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            # Includes schema fields, enums, lookup tables and policy defaults.
            if scope == "<module>" or scope_types.get(scope) == "ClassDef" or isinstance(value, (ast.Dict, ast.Set, ast.List, ast.Tuple)) or isinstance(node, ast.AnnAssign):
                data.append({**base, "kind": type(node).__name__,
                             "declaration": expression(node) if not isinstance(value, (ast.Constant, ast.JoinedStr))
                                 or len(expression(node)) < 600 else "See source span (long text/template)."})
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and isinstance(getattr(node, "value", None), str):
            if "\n" in node.value:
                text_blocks.append({**base, "kind": "multiline_text_or_embedded_code",
                                    "sha256": hashlib.sha256(node.value.encode()).hexdigest()})
        if isinstance(node, ast.JoinedStr) and node.end_lineno > node.lineno:
            text_blocks.append({**base, "kind": "formatted_text_or_code_template"})
        if isinstance(node, ast.Call):
            rid = next((k.value for k in node.keywords if k.arg == "rule_id"), None)
            if isinstance(node.func, ast.Name) and node.func.id == "add" and node.args:
                rid = node.args[0]
            if isinstance(rid, ast.Constant) and isinstance(rid.value, str) and rid.value.startswith("CP"):
                checks.append({**base, "rule_id": rid.value, "guards": list(guards), "call": expression(node)})
        for field, value in ast.iter_fields(node):
            nested_guards = guards
            if isinstance(node, (ast.If, ast.IfExp)) and field in {"body", "orelse"}:
                nested_guards += (f"L{line} {'TRUE' if field == 'body' else 'FALSE'}: {expression(node.test)}",)
            children = value if isinstance(value, list) else [value]
            for child in children:
                if isinstance(child, ast.AST):
                    walk(child, scope, nested_guards)

    walk(tree)
    expected = sum(isinstance(n, CONTROL + (ast.comprehension, ast.match_case)) for n in ast.walk(tree))
    if expected != len(entries):
        raise ValueError("Static control-node inventory is incomplete")
    return {"definitions": definitions, "control_nodes": entries, "checkpoint_occurrences": checks,
            "declarations": data, "embedded_text_spans": text_blocks,
            "node_counts": dict(sorted(Counter(e["kind"] for e in entries).items()))}


class HtmlSurfaceIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.handlers = [], []
        self.active = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = {"line": self.getpos()[0], "attributes": dict(attrs), "source": ""}
        for key, value in attrs:
            if key.lower().startswith("on"):
                self.handlers.append({"line": self.getpos()[0], "event": key, "code": value})

    def handle_data(self, data):
        if self.active is not None:
            self.active["source"] += data

    def handle_endtag(self, tag):
        if tag == "script" and self.active is not None:
            self.scripts.append({**self.active, "end_line": self.getpos()[0]})
            self.active = None


def build_inventory():
    files = {}
    python_paths = sorted((ROOT / "src").glob("*.py"))
    python_paths += sorted((ROOT / "product_baseline" / "tests").glob("*.py"))
    python_paths += sorted((ROOT / "approved_assets" / "automation").glob("*.py"))
    python_paths += [ROOT / "scripts" / "record_demo.py"]
    for path in python_paths:
        raw = path.read_bytes()
        files[path.relative_to(ROOT).as_posix()] = {"sha256": hashlib.sha256(raw).hexdigest(),
                                                  **index_python(raw.decode("utf-8-sig"))}
    surfaces = {}
    for relative in ("product_baseline/virtual-controller.html", "project.html"):
        raw = (ROOT / relative).read_bytes()
        parser = HtmlSurfaceIndex()
        parser.feed(raw.decode("utf-8-sig"))
        inputs = [{"source": b["source"], "line": b["line"], "module": b["attributes"].get("type") == "module"}
                  for b in parser.scripts if not b["attributes"].get("src")
                  and b["attributes"].get("type", "") in {"", "module", "text/javascript", "application/javascript"}]
        inputs += [{"source": b["code"] or "", "line": b["line"], "handler": True} for b in parser.handlers]
        surfaces[relative] = {"sha256": hashlib.sha256(raw).hexdigest(),
                              "script_spans": [{k: v for k, v in b.items() if k != "source"} for b in parser.scripts],
                              "event_handlers": parser.handlers, "javascript": index_javascript(inputs),
                              "coverage": "Inline JavaScript and event handlers parsed only; external script dependencies not included."}
    return {"format": "static-logic-index-1.0",
            "scope": "All src/*.py; baseline tests; approved automation; recording helper; HTML inline JavaScript/events.",
            "limits": ["Not branch-test coverage, reachability analysis, semantic proof or a full call graph.",
                       "Prompt rules and dynamic generated code remain source spans, not all possible runtime variants.",
                       "Dependencies, ignored local scripts, historical Run files and project 2 are outside this inventory.",
                       "Guards describe lexical if/else nesting, not all execution preconditions.",
                       "Counts include historical compatibility and presentation branches; not a count of business rules."],
            "python_files": files, "html_surfaces": surfaces}


def self_test():
    source = '''
class C:
    mode: str = "new"
def f(xs, flag):
    try:
        for x in xs:
            if flag and x:
                continue
            else:
                break
        while flag:
            flag = False
        with open("x") as h:
            assert h
        values = [x for x in xs if x]
        match flag:
            case True if xs:
                raise ValueError("x")
        return 1 if flag else 0
    except ValueError:
        return None
'''
    result = index_python(source)
    assert set(result["node_counts"]) == {"Try", "For", "If", "BoolOp", "Continue", "Break", "While",
                                          "With", "Assert", "comprehension", "Match", "match_case", "Raise", "Return", "IfExp", "ExceptHandler"}
    assert any("FALSE" in " ".join(n["guards"]) for n in result["control_nodes"] if n["kind"] == "Break")
    assert any(d["name"] == "f" for d in result["definitions"])
    check = index_python('if legacy:\n    add("CP2-021", status, "message")\n')
    assert check["checkpoint_occurrences"][0]["guards"] == ["L1 TRUE: legacy"]
    html = HtmlSurfaceIndex()
    html.feed('<button onclick="go()">Go</button>\n<script>if (x) go();</script>')
    assert len(html.scripts) == len(html.handlers) == 1
    js = index_javascript([{"line": 10, "source": "function f(x) { if(x && x.y) return 1; else throw Error('x'); }"}])
    rows = js["blocks"][0]["control_nodes"]
    assert {r["kind"] for r in rows} == {"IfStatement", "LogicalExpression", "ReturnStatement", "ThrowStatement"}
    assert all(r["line"] == 10 for r in rows)
    assert "FALSE" in next(r for r in rows if r["kind"] == "ThrowStatement")["guards"][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed index differs; never rewrite it.")
    parser.add_argument("--self-test", action="store_true", help="Check extractor fixtures only; no pipeline execution.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Inventory extractor fixtures: PASS")
        return 0
    inventory = build_inventory()
    guide = (ROOT / "docs" / "PROJECT_GUIDE.md").read_text(encoding="utf-8")
    section = guide.split("### 전체 Checkpoint 규칙 목록", 1)[1].split("### 누락과 문서 노후화", 1)[0]
    documented = set(re.findall(r"CP[1-4]-\d{3}[A-Z]?", section))
    implemented = {r["rule_id"] for name, content in inventory["python_files"].items()
                   if name.startswith("src/") for r in content["checkpoint_occurrences"]}
    if documented != implemented:
        print(json.dumps({"missing_in_guide": sorted(implemented - documented),
                          "unknown_in_guide": sorted(documented - implemented)}))
        return 1
    rendered = json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("STALE: regenerate docs/logic_inventory.json")
            return 1
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
    files = inventory["python_files"]
    core = {k: v for k, v in files.items() if k.startswith("src/")}
    print(json.dumps({"status": "CURRENT", "python_files": len(files), "core_files": len(core),
                      "core_control_nodes": sum(len(v["control_nodes"]) for v in core.values()),
                      "core_definitions": sum(len(v["definitions"]) for v in core.values()),
                      "checkpoint_ids": sorted({x["rule_id"] for v in core.values() for x in v["checkpoint_occurrences"]}),
                      "html_surfaces": len(inventory["html_surfaces"]),
                      "javascript_control_nodes": sum(len(b["control_nodes"]) for v in inventory["html_surfaces"].values()
                                                       for b in v["javascript"]["blocks"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
