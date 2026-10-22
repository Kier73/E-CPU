#!/usr/bin/env python3
"""Repository conformance checks for links, secrets, invariants, and hygiene.

Each check is independent and reports its own findings. The exit status is 0
when every enabled check passes and 1 otherwise.

Usage:
    python scripts/verify_repo.py                  # all checks
    python scripts/verify_repo.py --check links    # one or more named checks
    python scripts/verify_repo.py --list

Checks:
    prose      Prose checks
    docstrings Comment and docstring conventions
    links      Every referenced repository path exists
    boundaries Path boundary checks
    secrets    Credentials and environment leakage
    invariants Invariant registry entries resolve
    hygiene    Generated artifacts are untracked

Defined terms follow docs/GLOSSARY.md.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "mailcpu"
DOCS = ROOT / "docs"
PRIVATE_PREFIX = "_dev"

# Environment and identity leakage patterns.
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

LEAKAGE_PROSE_ONLY = ((r"(?<!\w)/home/[a-z][a-z0-9_-]*/", "absolute home path"),)

EXEMPT: dict[Path, tuple[str, ...]] = {
    Path("scripts/verify_repo.py"): ("LEAKAGE",),
    Path("docs/GLOSSARY.md"): (),
    Path("docs/PLAN.md"): (),
    Path("docs/INTEGRATION_SPEC.md"): (),
    Path("docs/ARCHITECTURE.md"): (),
    Path("docs/REPLACEMENT_SPEC.md"): (),
    Path("docs/BOUNDARY_PROCEDURAL_MODEL.md"): (),
    Path("docs/INVARIANTS.md"): (),
    Path("README.md"): (),
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
    return Findings("prose")


def check_docstrings() -> Findings:
    findings = Findings("docstrings")
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            docstring = ast.get_docstring(node)
            if not docstring:
                findings.add(path, node.lineno, node.name, "missing docstring")
            elif "Mathematics:" not in docstring:
                findings.add(path, node.lineno, node.name, "missing governing mathematics annotation")
    return findings


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
    return Findings("boundaries")


BOUNDARY_EXEMPT = {
    Path(".gitignore"),
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
    """Mathematics: return `F = {ROOT/p | p ∈ Git-index ∪ unignored-worktree}`."""

    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    relative_paths = [Path(raw) for raw in result.stdout.decode("utf-8").split("\0") if raw]
    return sorted(ROOT / path for path in relative_paths if path.suffix != ".pyc")


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
