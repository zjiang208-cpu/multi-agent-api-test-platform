from __future__ import annotations

import re
from pathlib import Path

from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.evidence import EvidenceFact


SENSITIVE_NAMES = {".git", ".ssh", ".env", "secrets", "credentials", "certs", "keys"}
MAPPING_MARKERS = (
    "@RequestMapping",
    "@GetMapping",
    "@PostMapping",
    "@PutMapping",
    "@PatchMapping",
    "@DeleteMapping",
)


class JavaSpringSourceEvidenceProvider:
    provider_type = "source_code"

    def __init__(self, *, max_files: int = 200, max_facts: int = 20, max_excerpt: int = 2000) -> None:
        self.max_files = max_files
        self.max_facts = max_facts
        self.max_excerpt = max_excerpt

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        root = context.settings.source_workspace
        if not root:
            return "not_configured", "source workspace is not configured"
        path = Path(root).expanduser()
        if not path.is_dir():
            return "error", "source workspace is not a directory"
        return "healthy", "bounded Java/Spring source scanner is available"

    def retrieve(self, context: EvidenceContext, _: EvidenceQuery) -> list[EvidenceFact]:
        root = Path(context.settings.source_workspace or "").expanduser().resolve()
        operation = context.operation
        path_terms = [part for part in operation.path.split("/") if part and not part.startswith("{")]
        method_marker = f"@{operation.method.title()}Mapping"
        results: list[EvidenceFact] = []
        examined = 0
        for source_file in sorted(root.rglob("*.java")):
            if examined >= self.max_files or len(results) >= self.max_facts:
                break
            if self._is_sensitive(source_file, root):
                continue
            examined += 1
            try:
                content = source_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if method_marker not in content and "@RequestMapping" not in content:
                continue
            mapping_values = [match.group(2) for match in re.finditer(
                r"@(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)\s*\(\s*[\"']([^\"']*)",
                content,
            )]
            if path_terms and not any(self._path_term_matches(term, mapping_values) for term in path_terms):
                continue
            matching_lines = [
                line.strip()
                for line in content.splitlines()
                if any(marker in line for marker in MAPPING_MARKERS)
            ]
            if not matching_lines:
                continue
            relative = source_file.relative_to(root).as_posix()
            excerpt = " ".join(matching_lines)[: self.max_excerpt]
            results.append(
                EvidenceFact(
                    source_type=self.provider_type,
                    reference=f"source:{relative}",
                    operation_id=operation.operation_id,
                    fact=f"Spring mapping source for {operation.method} {operation.path} was found in {relative}.",
                    safe_excerpt=excerpt,
                    metadata={"language": "java", "framework": "spring"},
                )
            )
        return results

    @staticmethod
    def _is_sensitive(path: Path, root: Path) -> bool:
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            return True
        return any(part.lower() in SENSITIVE_NAMES for part in relative_parts)

    @staticmethod
    def _path_term_matches(term: str, mapping_values: list[str]) -> bool:
        pattern = re.compile(rf"(?:^|/){re.escape(term)}(?:/|$|\{{)")
        return any(pattern.search(value) for value in mapping_values)
