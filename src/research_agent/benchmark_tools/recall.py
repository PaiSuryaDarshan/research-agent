import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, field_validator

from research_agent.agents.research.models import Candidate, normalize_doi, work_id
from research_agent.agents.research.openalex import OpenAlexClient

TITLE_FIELDS = "id,doi,display_name,publication_year,cited_by_count"


class RunWork(BaseModel):
    openalex_id: str
    doi: str | None = None
    rank: int | None = None
    found_by: list[str] = []
    via: list[str] = []

    _normalize_doi = field_validator("doi")(normalize_doi)


class RecallResult(BaseModel):
    reference_id: str
    n_references: int
    recall_candidates: float | None
    recall_kept: float | None
    leakage: bool
    reference_in_candidates: bool
    reference_in_search: bool | None


@dataclass
class ReferenceRow:
    id: str
    year: int | None
    title: str
    cited_by_count: int
    found_in_candidates: bool
    found_in_kept: bool | None
    rank: int | None


class RunIndex:
    def __init__(self, entries: Sequence[RunWork]) -> None:
        self._ids = {work_id(item.openalex_id): item for item in entries}
        self._dois = {item.doi: item for item in entries if item.doi}

    def find(self, id_: str, doi: str | None) -> RunWork | None:
        return self._ids.get(id_) or self._dois.get(doi)


def _read_works(path: Path) -> list[RunWork]:
    with path.open(encoding="utf-8") as file:
        return [RunWork.model_validate_json(line) for line in file if line.strip()]


def _titles(client: OpenAlexClient, ids: Sequence[str]) -> dict[str, Candidate]:
    titles = {}
    for offset in range(0, len(ids), 50):
        batch = client.lookup(ids[offset:offset + 50], select=TITLE_FIELDS)
        titles.update((work_id(item.openalex_id), item) for item in batch)
    return titles


def _share(count: int, total: int) -> float | None:
    return count / total if total else None


def _write_report(path: Path, rows: Sequence[ReferenceRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "year", "title", "found_in_candidates", "found_in_kept", "rank"])
        for row in rows:
            writer.writerow([row.id, row.year, row.title, row.found_in_candidates, row.found_in_kept, row.rank])


def measure_recall(
    folder: Path, reference: str, client: OpenAlexClient
) -> tuple[RecallResult, list[ReferenceRow]]:
    metadata_path = folder / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidates = _read_works(folder / "candidates.jsonl")
    screened = folder / "screened.jsonl"
    kept = RunIndex(_read_works(screened)) if screened.exists() else None
    indexed = RunIndex(candidates)

    review = client.reference(reference)
    reference_id = work_id(review.openalex_id)
    ids = list(dict.fromkeys(work_id(id_) for id_ in review.referenced_works))
    titles = _titles(client, ids)
    rows = []
    for id_ in ids:
        details = titles.get(id_)
        doi = details.doi if details else None
        candidate = indexed.find(id_, doi)
        kept_work = kept.find(id_, doi) if kept is not None else None
        ranked = candidate or kept_work
        rows.append(ReferenceRow(
            id=id_,
            year=details.year if details else None,
            title=details.title if details else "[Metadata unavailable]",
            cited_by_count=details.cited_by_count if details else 0,
            found_in_candidates=candidate is not None,
            found_in_kept=(kept_work is not None) if kept is not None else None,
            rank=ranked.rank if ranked else None,
        ))

    reference_candidate = indexed.find(reference_id, review.doi)
    # Older runs have only provenance from candidates that survived the ranking cutoff.
    in_search = None
    if "search_work_ids" in metadata:
        in_search = reference_id in metadata["search_work_ids"]
    if (reference_candidate and reference_candidate.found_by) or any(
        tag in candidate.via
        for candidate in candidates
        for tag in (f"ref_of:{reference_id}", f"cites:{reference_id}")
    ):
        in_search = True

    result = RecallResult(
        reference_id=reference_id,
        n_references=len(rows),
        recall_candidates=_share(sum(row.found_in_candidates for row in rows), len(rows)),
        recall_kept=_share(sum(row.found_in_kept is True for row in rows), len(rows)) if kept is not None else None,
        leakage=reference_candidate is not None or in_search is True,
        reference_in_candidates=reference_candidate is not None,
        reference_in_search=in_search,
    )
    _write_report(folder / f"recall_{reference_id}.csv", rows)
    metadata["recall"] = result.model_dump()
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as staged:
        staged_path = Path(staged.name)
        staged.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    try:
        staged_path.replace(metadata_path)
    finally:
        staged_path.unlink(missing_ok=True)
    missed = sorted((row for row in rows if not row.found_in_candidates), key=lambda row: -row.cited_by_count)
    return result, missed[:10]
