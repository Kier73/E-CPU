#!/usr/bin/env python3
"""Repository conformance checks for style, boundaries, links, and invariants.

Each check is independent and reports its own findings. The exit status is 0
when every enabled check passes and 1 otherwise.

Usage:
    python scripts/verify_repo.py                  # all checks
    python scripts/verify_repo.py --check style    # one or more named checks
    python scripts/verify_repo.py --list

Checks:
    prose      Prohibited vocabulary and structural rules in documentation
    docstrings Comment and docstring conventions in the package
    links      Every referenced repository path exists
    boundaries No tracked file references an untracked private path
    secrets    Credentials and environment leakage
    invariants Invariant registry entries resolve
    hygiene    Generated artifacts are untracked

Defined terms follow docs/GLOSSARY.md. Writing conventions follow docs/STYLE.md.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "mailcpu"
DOCS = ROOT / "docs"
PRIVATE_PREFIX = "_dev"

# STYLE.md clause 3.1: development narrative and temporal markers.
NARRATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bwe\b", "first-person plural"),
    (r"\bwe're\b", "first-person plural"),
    (r"\bour\b", "first-person possessive"),
    (r"\bI\b(?=\s+(will|would|am|think|believe|added|found|fixed))", "first-person singular"),
    (r"\bTODO\b", "unfinished-work marker"),
    (r"\bFIXME\b", "unfinished-work marker"),
    (r"\bXXX\b", "unfinished-work marker"),
    (r"\bnote to self\b", "working note"),
    (r"\bfor now\b", "temporal deferral"),
    (r"\btemporar(?:y|ily)\b", "temporal deferral"),
    (r"\bnext steps?\b", "roadmap narrative"),
    (r"\bfuture work\b", "roadmap narrative"),
    (r"\bcoming soon\b", "roadmap narrative"),
    (r"\bonce (?:this|we)\b", "roadmap narrative"),
    (r"\bscaffold\b", "dead vocabulary"),
    (r"\bvertical slice\b", "dead vocabulary"),
    (r"\bsimple run\b", "chatty register"),
    (r"\bphase \d+\b", "dead vocabulary"),
    (r"\bdidn'?t\b", "chatty register"),
    (r"\bfeel free\b", "chatty register"),
    (r"\bshould be fine\b", "chatty register"),
)

# STYLE.md clause 3.2: rhetorical qualifiers.
QUALIFIER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bobviously\b", "rhetorical qualifier"),
    (r"\bclearly\b", "rhetorical qualifier"),
    (r"\bpretty much\b", "rhetorical qualifier"),
    (r"\barguably\b", "rhetorical qualifier"),
    (r"\bof course\b", "rhetorical qualifier"),
    (r"\bjust (?:so|to be)\b", "rhetorical qualifier"),
)

# STYLE.md clause 3.3: aspirational and promotional language.
ASPIRATIONAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bblazing(?:ly)?\b", "promotional"),
    (r"\bseamless(?:ly)?\b", "promotional"),
    (r"\bpowerful\b", "promotional"),
    (r"\bbattle[- ]tested\b", "promotional"),
    (r"\bproduction[- ]ready\b", "promotional"),
    (r"\bcutting[- ]edge\b", "promotional"),
    (r"\bawesome\b", "promotional"),
    (r"\bgame[- ]changer\b", "promotional"),
)

# STYLE.md clause 3.6: environment and identity leakage.
LEAKAGE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"[A-Za-z]:\\+Users\\+", "absolute user path"),
    (r"/Users/[a-z][a-z0-9_-]*/", "absolute home path"),
    (r"\\\\\\\\[a-z0-9.-]+\\\\", "UNC path"),
    (r"\bpassword\s*[:=]\s*\S", "credential"),
    (r"\bapi[_-]?key\s*[:=]\s*\S", "credential"),
    (r"\bsecret\s*[:=]\s*\S", "credential"),
    (r"\btoken\s*[:=]\s*['\"][A-Za-z0-9]{16,}", "credential"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "credential"),
    (r"\bghp_[A-Za-z0-9]{20,}", "credential"),
    (r"\bsk-[A-Za-z0-9]{20,}", "credential"),
)

# A POSIX home path is ambiguous: inside `tests/` it denotes a path in the
# virtual filesystem under test, not a path on the host running the suite. The
# rule therefore applies to documentation only.
LEAKAGE_PROSE_ONLY = ((r"(?<!\w)/home/[a-z][a-z0-9_-]*/", "absolute home path"),)

# Files permitted to contain a pattern, because they define it.
EXEMPT: dict[Path, tuple[str, ...]] = {
    Path("docs/STYLE.md"): ("NARRATIVE", "QUALIFIER", "ASPIRATIONAL"),
    Path("scripts/verify_repo.py"): ("NARRATIVE", "QUALIFIER", "ASPIRATIONAL", "LEAKAGE"),
    Path("docs/GLOSSARY.md"): ("QUALIFIER",),
    Path("docs/PLAN.md"): ("QUALIFIER",),
    Path("docs/INTEGRATION_SPEC.md"): ("NARRATIVE", "QUALIFIER", "ASPIRATIONAL"),
    Path("docs/ARCHITECTURE.md"): ("QUALIFIER",),
    Path("docs/REPLACEMENT_SPEC.md"): ("QUALIFIER", "ASPIRATIONAL"),
    Path("docs/BOUNDARY_JEV.md"): ("QUALIFIER", "ASPIRATIONAL"),
    Path("docs/BOUNDARY_PROCEDURAL_MODEL.md"): ("QUALIFIER",),
    Path("docs/INVARIANTS.md"): ("ASPIRATIONAL",),
    Path("README.md"): ("QUALIFIER", "ASPIRATIONAL"),
    Path("AGENTS.md"): ("NARRATIVE", "QUALIFIER", "ASPIRATIONAL"),
}


@dataclass
class Findings:
    """Mathematics: accumulate findings as the finite list `F`, grouped by the check that produced each."""

    check: str
    items: list[str] = field(default_factory=list)

    def add(self, path: Path, line: int, text: str, rule: str) -> None:
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        self.items.append(f"{relative}:{line}: [{rule}] {text.strip()[:140]}")

    def __bool__(self) -> bool:
        return bool(self.items)


def _markdown_files() -> list[Path]:
    return sorted(DOCS.glob("*.md")) + [ROOT / "README.md"]


def _python_files() -> list[Path]:
    return sorted(PACKAGE.glob("*.py"))


def _exempt(path: Path, category: str) -> bool:
    relative = path.relative_to(ROOT)
    return category in EXEMPT.get(relative, ())


def _code_fenced(text: str) -> str:
    """Mathematics: project a document onto its prose by removing fenced blocks, which carry quoted material rather than authored prose."""

    without_fences = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", without_fences)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_prose() -> Findings:
    findings = Findings("prose")
    categories = (
        ("NARRATIVE", NARRATIVE_PATTERNS),
        ("QUALIFIER", QUALIFIER_PATTERNS),
        ("ASPIRATIONAL", ASPIRATIONAL_PATTERNS),
    )
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        prose = _code_fenced(text)
        for line_number, line in enumerate(prose.splitlines(), start=1):
            if _line_is_exempted(path, line_number):
                continue
            findings.items.extend(_scan(line, line_number, path, categories))
    for path in _python_files():
        for line_number, line in _code_lines(path):
            findings.items.extend(_scan(line, line_number, path, categories))
    return findings


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Mathematics: project a module onto the set of lines carrying authored prose, that is, comments and docstrings."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))

    text = path.read_text(encoding="utf-8")
    result: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or line_number in docstring_lines:
            result.append((line_number, line))
    return result


def _scan(
    line: str,
    line_number: int,
    path: Path,
    categories: tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
) -> list[str]:
    findings = Findings("prose")
    for category, patterns in categories:
        if _exempt(path, category):
            continue
        for pattern, rule in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                findings.add(path, line_number, match.group(0), f"{category}: {rule}")
    return findings.items


def _line_is_exempted(path: Path, line_number: int) -> bool:
    """Mathematics: decide whether line `n` of `path` lies inside a block whose text is quoted rather than authored."""

    text = path.read_text(encoding="utf-8")
    inside = False
    for index, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            inside = not inside
        if index == line_number:
            return inside
    return False


def check_docstrings() -> Findings:
    findings = Findings("docstrings")
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if not ast.get_docstring(ast.parse(text)):
            findings.add(path, 1, "module has no docstring", "STYLE 7: module docstring")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = re.match(r"^\s*#\s*Mathematics:", line)
            if match:
                findings.add(
                    path,
                    line_number,
                    "Mathematics prefix on an inline comment",
                    "STYLE 7.2: prefix is docstring-only",
                )
        tree = ast.parse(text)
        findings.items.extend(_missing_docstrings(path, tree))
    return findings


def _missing_docstrings(path: Path, tree: ast.AST) -> list[str]:
    """Mathematics: project the definition set of `tree` onto the subset lacking a docstring."""

    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("__") and node.name.endswith("__"):
            continue
        if ast.get_docstring(node):
            continue
        missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: `{node.name}` has no docstring [STYLE 7.3]")
    return missing


def check_links() -> Findings:
    findings = Findings("links")
    pattern = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|toml|mca|json|yml))`")
    for path in _markdown_files() + _python_files() + sorted((ROOT / "tests").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if path.name == "verify_repo.py":
                continue
            for target in pattern.findall(line):
                if target.startswith(("http://", "https://")):
                    continue
                resolved = _resolve_reference(path, target)
                if resolved is not None and not resolved.exists():
                    findings.add(path, line_number, target, "link target does not exist")
    return findings


def _resolve_reference(source: Path, target: str) -> Path | None:
    """Mathematics: resolve `target` over the candidate set `{ROOT/target, source.parent/target, DOCS/target}`, returning the first candidate that exists and otherwise the repository-root candidate."""

    candidates = [ROOT / target, source.parent / target, DOCS / target]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def check_boundaries() -> Findings:
    findings = Findings("boundaries")
    for path in _tracked_files():
        if path.relative_to(ROOT) in BOUNDARY_EXEMPT:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            # `_dev` as a standalone path segment, not as the prefix of a Python
            # identifier such as `_device` or `_devices`.
            match = re.search(r"(?<![\w.])_dev\b", line)
            if match:
                findings.add(path, line_number, match.group(0), "tracked file references the private workspace")
    return findings


# Files whose stated purpose is to define the `_dev/` boundary. Naming the
# boundary is their function; depending on its contents would not be.
BOUNDARY_EXEMPT = {
    Path(".gitignore"),
    Path("AGENTS.md"),
    Path("scripts/verify_repo.py"),
    Path(".github/workflows/verify.yml"),
}


def check_secrets() -> Findings:
    findings = Findings("secrets")
    for path in _tracked_files():
        if _exempt(path, "LEAKAGE"):
            continue
        patterns = LEAKAGE_PATTERNS
        if path.suffix == ".md" or path == ROOT / "README.md":
            patterns = patterns + LEAKAGE_PROSE_ONLY
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for pattern, rule in patterns:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    findings.add(path, line_number, match.group(0), rule)
    return findings


def check_invariants() -> Findings:
    findings = Findings("invariants")
    sys.path.insert(0, str(ROOT / "scripts"))
    from verify_invariants import verify as verify_invariants  # noqa: PLC0415

    for problem in verify_invariants():
        findings.add(DOCS / "INVARIANTS.md", problem.line, problem.message, problem.rule)
    return findings


def check_hygiene() -> Findings:
    findings = Findings("hygiene")
    generated = ("*.mcpu.json", "*.mcp.json", "*.mtrj", "*.mtrj.idx")
    ignore = _gitignore_patterns()
    for path in _tracked_files():
        if any(path.match(pattern) for pattern in generated):
            findings.add(path, 1, path.name, "generated artifact is tracked")
        for pattern in ignore:
            if _matches(path, pattern):
                findings.add(path, 1, path.name, "tracked file matches a gitignore pattern")
                break
    return findings


def _gitignore_patterns() -> list[str]:
    path = ROOT / ".gitignore"
    if not path.exists():
        return []
    return [
        line.strip().rstrip("/")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and not line.strip().startswith("!")
    ]


def _matches(path: Path, pattern: str) -> bool:
    parts = Path(pattern).parts
    probe = Path("x", *parts)
    if pattern.endswith("*"):
        return any(path.match(part) for part in parts if "*" in part)
    return str(probe) in {str(p) for p in path.parents} or path.match(pattern) or path.as_posix() == pattern


def _tracked_files() -> list[Path]:
    """Mathematics: project the repository tree onto the files eligible for distribution."""

    excluded = {PRIVATE_PREFIX, ".git", "__pycache__", ".pytest_cache", ".venv", "build", "dist"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if excluded & set(relative.parts):
            continue
        if path.suffix in {".pyc"}:
            continue
        files.append(path)
    return sorted(files)


CHECKS = {
    "prose": check_prose,
    "docstrings": check_docstrings,
    "links": check_links,
    "boundaries": check_boundaries,
    "secrets": check_secrets,
    "invariants": check_invariants,
    "hygiene": check_hygiene,
}


def main(argv: list[str] | None = None) -> int:
    """Mathematics: `main` evaluates the requested checks over `dom(CHECKS)` and returns 0 iff every finding set is empty."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="append", choices=sorted(CHECKS), help="run only the named check")
    parser.add_argument("--list", action="store_true", help="list available checks and exit")
    arguments = parser.parse_args(argv)

    if arguments.list:
        for name in sorted(CHECKS):
            print(name)
        return 0

    selected = arguments.check or sorted(CHECKS)
    total = 0
    for name in selected:
        findings = CHECKS[name]()
        status = "FAIL" if findings else "ok"
        print(f"[{status}] {name} ({len(findings.items)} finding(s))")
        for item in findings.items[:200]:
            print(f"    {item}")
        if len(findings.items) > 200:
            print(f"    ... {len(findings.items) - 200} further finding(s) suppressed")
        total += len(findings.items)

    print(f"\n{total} finding(s) across {len(selected)} check(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
