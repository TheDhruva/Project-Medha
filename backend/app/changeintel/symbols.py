"""Source symbol + import extraction (Phase 2).

Python: structural extraction via stdlib `ast` (HIGH confidence).
TypeScript/JavaScript: pragmatic, well-scoped regex-based extraction (HEURISTIC
confidence). JSON/YAML: treated as configuration artifacts (CONFIG nodes).
Every unsupported source file type is recorded, never guessed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.changeintel.models import (
    FileSymbols,
    ImportRef,
    Language,
    Symbol,
    SymbolKind,
)

_PY_SUFFIXES = {".py", ".pyi"}
_JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_CONFIG_SUFFIXES = {".json", ".yml", ".yaml"}

_IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", ".pytest_cache"}

_JS_IMPORT_RE = re.compile(r"^\s*import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_JS_IMPORT_BARE_RE = re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_JS_REQUIRE_RE = re.compile(r"(?:require|import)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_JS_DYNAMIC_RE = re.compile(r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")

_FN_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+|\bconst\s+\w+\s*=\s*(?:async\s*)?\(?.*?=>)", re.MULTILINE
)
_NAMED_FN_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE
)
_CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
_EXPORT_CONST_RE = re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def classify_language(path: str) -> Language:
    suffix = Path(path).suffix.lower()
    if suffix in _PY_SUFFIXES:
        return Language.PYTHON
    if suffix in _JS_SUFFIXES:
        if suffix in {".ts", ".tsx"}:
            return Language.TYPESCRIPT
        return Language.JAVASCRIPT
    if suffix in _CONFIG_SUFFIXES:
        if suffix == ".json":
            return Language.JSON
        return Language.YAML
    return Language.UNSUPPORTED


def is_ignored_path(path: str) -> bool:
    parts = Path(path).parts
    return any(part in _IGNORED_DIRS for part in parts)


def source_files(root: Path) -> list[str]:
    """Collect supported source/config files under root (deterministic order)."""
    found: list[str] = []
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(root).as_posix()
        if is_ignored_path(rel):
            continue
        if classify_language(rel) != Language.UNSUPPORTED:
            found.append(rel)
    return found


def extract_file_symbols(path: str, content: str) -> FileSymbols:
    language = classify_language(path)
    if language == Language.PYTHON:
        return _extract_python(path, content, language)
    if language in {Language.JAVASCRIPT, Language.TYPESCRIPT}:
        return _extract_js_ts(path, content, language)
    if language in {Language.JSON, Language.YAML}:
        return FileSymbols(
            path=path,
            language=language,
            symbols=[_module_symbol(path, language)],
            imports=[],
        )
    return FileSymbols(path=path, language=Language.UNSUPPORTED)


def load_file(root: Path, rel_path: str) -> str:
    full = root / rel_path
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _module_symbol(path: str, language: Language) -> Symbol:
    fqn = _fqn_for_path(path)
    return Symbol(
        symbol_id=f"{path}::module",
        name=Path(path).stem,
        fqn=fqn,
        kind=SymbolKind.MODULE,
        path=path,
        line=1,
        end_line=1,
        language=language,
    )


def _fqn_for_path(path: str) -> str:
    no_suffix = path[: path.rfind(".")] if "." in Path(path).name else path
    normalized = no_suffix.replace("\\", "/").replace("/", ".")
    if normalized.endswith(".__init__"):
        normalized = normalized[: -len(".__init__")]
    return normalized


def _extract_python(path: str, content: str, language: Language) -> FileSymbols:
    symbols: list[Symbol] = [_module_symbol(path, language)]
    imports: list[ImportRef] = []
    unresolved: list[ImportRef] = []

    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError as exc:
        return FileSymbols(
            path=path,
            language=language,
            symbols=symbols,
            parse_error=f"syntax error at line {exc.lineno}",
        )
    except ValueError:
        return FileSymbols(path=path, language=language, symbols=symbols, parse_error="invalid source")

    pkg_prefix = _python_pkg(path)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportRef(module=alias.name, names=[], line=node.lineno))
            else:
                level = getattr(node, "level", 0) or 0
                module = f"{'.' * level}{node.module}" if node.module else "." * level
                names = [a.asname or a.name for a in node.names]
                imports.append(ImportRef(module=module, names=names, line=node.lineno))
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cls = _enclosing_class(tree, node)
            if cls is not None:
                # Methods are handled by the parent class walk below.
                continue
            name = node.name
            fqn = f"{pkg_prefix}.{name}"
            symbols.append(
                Symbol(
                    symbol_id=f"{path}::{SymbolKind.FUNCTION.value}:{fqn}",
                    name=name,
                    fqn=fqn,
                    kind=SymbolKind.FUNCTION,
                    path=path,
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    language=language,
                )
            )
        elif isinstance(node, ast.ClassDef):
            fqn = f"{pkg_prefix}.{node.name}"
            symbols.append(
                Symbol(
                    symbol_id=f"{path}::{SymbolKind.CLASS.value}:{fqn}",
                    name=node.name,
                    fqn=fqn,
                    kind=SymbolKind.CLASS,
                    path=path,
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    language=language,
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_fqn = f"{fqn}.{child.name}"
                    symbols.append(
                        Symbol(
                            symbol_id=f"{path}::{SymbolKind.METHOD.value}:{method_fqn}",
                            name=child.name,
                            fqn=method_fqn,
                            kind=SymbolKind.METHOD,
                            path=path,
                            line=child.lineno,
                            end_line=getattr(child, "end_lineno", child.lineno) or child.lineno,
                            language=language,
                        )
                    )

    # Detect importlib dynamic imports and treat them as (possibly unresolved) deps.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and len(node.args[0].value) > 0
        ):
            imports.append(
                ImportRef(module=node.args[0].value, names=[], line=node.lineno, native=True)
            )

    return FileSymbols(
        path=path,
        language=language,
        symbols=symbols,
        imports=imports,
        unresolved_imports=unresolved,
    )


def _enclosing_class(tree: ast.Module, node: ast.AST) -> ast.ClassDef | None:
    for parent in ast.walk(tree):
        if isinstance(parent, ast.ClassDef):
            for child in parent.body:
                if child is node:
                    return parent
    return None


def _python_pkg(path: str) -> str:
    return _fqn_for_path(path)


def _extract_js_ts(path: str, content: str, language: Language) -> FileSymbols:
    symbols: list[Symbol] = [_module_symbol(path, language)]
    imports: list[ImportRef] = []
    seen: set[str] = set()

    for match in _JS_IMPORT_RE.finditer(content):
        if match.group(2) in seen:
            continue
        seen.add(match.group(2))
        imports.append(ImportRef(module=match.group(2), names=[], line=_line_at(content, match.start())))
    for match in _JS_IMPORT_BARE_RE.finditer(content):
        if match.group(1) in seen:
            continue
        seen.add(match.group(1))
        imports.append(ImportRef(module=match.group(1), names=[], line=_line_at(content, match.start())))
    for match in _JS_REQUIRE_RE.finditer(content):
        module = match.group(1)
        if not module or module in seen:
            continue
        seen.add(module)
        imports.append(ImportRef(module=module, names=[], line=_line_at(content, match.start())))
    for match in _JS_DYNAMIC_RE.finditer(content):
        module = match.group(1)
        if not module or module in seen:
            continue
        seen.add(module)
        imports.append(ImportRef(module=module, names=[], line=_line_at(content, match.start())))

    for match in _NAMED_FN_RE.finditer(content):
        symbols.append(
            Symbol(
                symbol_id=f"{path}::function:{match.group(1)}",
                name=match.group(1),
                fqn=f"{_fqn_for_path(path)}.{match.group(1)}",
                kind=SymbolKind.FUNCTION,
                path=path,
                line=_line_at(content, match.start()),
                end_line=_line_at(content, match.end()),
                language=language,
            )
        )
    for match in _CLASS_RE.finditer(content):
        symbols.append(
            Symbol(
                symbol_id=f"{path}::class:{match.group(1)}",
                name=match.group(1),
                fqn=f"{_fqn_for_path(path)}.{match.group(1)}",
                kind=SymbolKind.CLASS,
                path=path,
                line=_line_at(content, match.start()),
                end_line=_line_at(content, match.end()),
                language=language,
            )
        )
    for match in _EXPORT_CONST_RE.finditer(content):
        symbols.append(
            Symbol(
                symbol_id=f"{path}::variable:{match.group(1)}",
                name=match.group(1),
                fqn=f"{_fqn_for_path(path)}.{match.group(1)}",
                kind=SymbolKind.VARIABLE,
                path=path,
                line=_line_at(content, match.start()),
                end_line=_line_at(content, match.end()),
                language=language,
            )
        )

    return FileSymbols(
        path=path,
        language=language,
        symbols=symbols,
        imports=imports,
        unresolved_imports=[],
    )


def _line_at(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


# --- import resolution ---------------------------------------------------


def resolve_import(
    module: str,
    from_path: str,
    py_files: set[str],
    js_files: set[str],
) -> list[str]:
    """Resolve an import/require specifier to repo-relative file candidates."""
    if module.startswith("."):
        return _resolve_relative_python(module, from_path, py_files)
    if module.startswith("./") or module.startswith("../"):
        return _resolve_relative_js(module, from_path, js_files)
    return _resolve_absolute_python(module, py_files)


def _resolve_absolute_python(module: str, py_files: set[str]) -> list[str]:
    candidates = []
    dotted = module.replace("/", ".")
    path_part = dotted.replace(".", "/")
    for candidate in (f"{path_part}.py", f"{path_part}/__init__.py"):
        if candidate in py_files:
            candidates.append(candidate)
    return candidates


def _resolve_relative_python(module: str, from_path: str, py_files: set[str]) -> list[str]:
    count = 0
    stripped = module
    while stripped.startswith("."):
        count += 1
        stripped = stripped[1:]
    base_dir = Path(from_path).parent
    for _ in range(max(0, count - 1)):
        base_dir = base_dir.parent
    # absolute import fallback for rooted packages
    candidates = []
    if stripped:
        rel = base_dir / stripped.replace(".", "/")
        for candidate in (rel.as_posix() + ".py", (rel / "__init__.py").as_posix()):
            if candidate in py_files:
                candidates.append(candidate)
    return candidates


def _resolve_relative_js(module: str, from_path: str, js_files: set[str]) -> list[str]:
    base_dir = Path(from_path).parent
    rel_path = Path(module).resolve() if False else module  # keep raw, no fs resolution
    candidate = (base_dir / rel_path).as_posix()
    suffixes = [".ts", ".tsx", ".js", ".jsx", ".mjs"]
    candidates = []
    if candidate in js_files:
        candidates.append(candidate)
    for suffix in suffixes:
        with_suffix = candidate + suffix
        if with_suffix in js_files:
            candidates.append(with_suffix)
    for suffix in suffixes:
        index = (candidate + "/index" + suffix)
        if index in js_files:
            candidates.append(index)
    # normalize leading @/aliases later if needed
    return candidates


SUPPORTED_SUFFIXES = _PY_SUFFIXES | _JS_SUFFIXES | _CONFIG_SUFFIXES