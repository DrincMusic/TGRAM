from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore

_WORD = re.compile(r"[a-z][a-z0-9_]{1,}", re.IGNORECASE)
_STOP = {"add", "and", "for", "from", "into", "project", "return", "task", "the", "with"}


def _tokens(value: str) -> set[str]:
    return {
        token for token in _WORD.findall(value.casefold().replace("_", " "))
        if token not in _STOP
    }


@dataclass(frozen=True)
class SymbolRecord:
    path: str
    symbol: str
    kind: str
    signature: str
    start_line: int
    end_line: int
    content_hash: str
    concepts: list[str]
    dependencies: list[str]


class ProjectSymbolMemory(TokenizedMemoryStore):
    """Durable code addresses and relationships; source bodies remain in live files."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.token_index = TokenizedMemoryStore.token_index(self.path)

    def refresh(self, project_root: Path) -> list[SymbolRecord]:
        root = project_root.resolve(strict=True)
        records: list[SymbolRecord] = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            lines = source.splitlines(keepends=True)

            def visit(
                body: list[ast.stmt], parents: list[str], *, source_lines=lines,
                source_path=path,
            ) -> None:
                for node in body:
                    if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    qualified = ".".join([*parents, node.name])
                    segment = "".join(source_lines[node.lineno - 1 : node.end_lineno])
                    dependencies = sorted({
                        child.id for child in ast.walk(node) if isinstance(child, ast.Name)
                    } - {node.name})[:30]
                    signature = source_lines[node.lineno - 1].strip()[:300]
                    concepts = sorted(
                        _tokens(qualified + " " + signature + " " + " ".join(dependencies))
                    )[:30]
                    records.append(SymbolRecord(
                        path=source_path.relative_to(root).as_posix(), symbol=qualified,
                        kind="class" if isinstance(node, ast.ClassDef) else "function",
                        signature=signature, start_line=node.lineno, end_line=node.end_lineno,
                        content_hash=hashlib.sha256(segment.encode()).hexdigest(),
                        concepts=concepts, dependencies=dependencies,
                    ))
                    visit(node.body, [*parents, node.name])

            visit(tree.body, [])
        self.path.write_text(
            json.dumps([asdict(record) for record in records], indent=2), encoding="utf-8"
        )
        for record in records:
            self.token_index.remember(
                self._memory_id(record), self._searchable(record), importance=.7,
            )
        return records

    def records(self) -> list[SymbolRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        return [SymbolRecord(**item) for item in payload if isinstance(item, dict)]

    def retrieve(
        self, query: str, *, project_root: Path, max_symbols: int = 3,
        char_budget: int = 7000,
    ) -> list[dict]:
        query_tokens = _tokens(query)
        ranked: list[tuple[float, SymbolRecord]] = []
        for record in self.records():
            symbol_tokens = self.token_index.terms(
                self._memory_id(record), self._searchable(record),
            )
            overlap = len(query_tokens.intersection(symbol_tokens))
            class_hint = 0.5 if record.kind == "class" and "class" in query_tokens else 0
            score = overlap * 3 + class_hint
            ranked.append((score, record))
        ranked.sort(key=lambda item: (
            -item[0], item[1].kind == "class", item[1].path, item[1].start_line
        ))

        root = project_root.resolve(strict=True)
        selected: list[dict] = []
        used = 2
        for score, record in ranked:
            if selected and score <= 0:
                continue
            source = (root / record.path).read_text(encoding="utf-8")
            lines = source.splitlines(keepends=True)
            snippet = "".join(lines[record.start_line - 1 : record.end_line])
            payload = {
                **asdict(record), "source": snippet, "relevance": score,
            }
            size = len(json.dumps(payload, separators=(",", ":")))
            if used + size > char_budget:
                continue
            selected.append(payload)
            used += size
            if len(selected) >= max_symbols:
                break
        return selected

    @staticmethod
    def _memory_id(record: SymbolRecord) -> str:
        return f"{record.path}:{record.symbol}:{record.content_hash}"

    @staticmethod
    def _searchable(record: SymbolRecord) -> str:
        return " ".join((record.path, record.symbol, record.kind, record.signature,
                         " ".join(record.concepts), " ".join(record.dependencies)))
