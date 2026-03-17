"""
Reads a CSV of domains and writes ICP results to an output CSV.
"""

import csv
from pathlib import Path
from typing import Dict, List, Optional

from .ai_checker import ICPResult

# Accepted column names for the domain field (case-insensitive)
_DOMAIN_COLUMN_ALIASES = {"domain", "website", "url", "site", "company_url", "company website"}

OUTPUT_FIELDNAMES = [
    "domain",
    "is_icp",
    "confidence",
    "reasoning",
    "pages_crawled",
    "error",
]


def _build_fieldnames(enrichment_columns: Optional[List[str]] = None) -> List[str]:
    extra: List[str] = []
    for col in (enrichment_columns or []):
        extra.append(col)
        extra.append(f"{col}_comment")
    return OUTPUT_FIELDNAMES + extra


def init_output_csv(
    output_path: str,
    enrichment_columns: Optional[List[str]] = None,
) -> None:
    """Create (or overwrite) the output CSV with headers only."""
    fieldnames = _build_fieldnames(enrichment_columns)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()


def append_result(
    result: ICPResult,
    pages_crawled: int,
    output_path: str,
    domain_enrichments: Optional[Dict] = None,
    enrichment_columns: Optional[List[str]] = None,
) -> None:
    """Append a single result row to an already-initialised output CSV."""
    fieldnames = _build_fieldnames(enrichment_columns)
    row: dict = {
        "domain": result.domain,
        "is_icp": "" if result.is_icp is None else str(result.is_icp).lower(),
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "pages_crawled": pages_crawled,
        "error": result.error or "",
    }
    if enrichment_columns:
        for col in enrichment_columns:
            value, comment = (domain_enrichments or {}).get(col, ("", ""))
            row[col] = value
            row[f"{col}_comment"] = comment

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(row)


def read_domains(csv_path: str) -> List[str]:
    """
    Read a CSV file and return a list of domain strings.

    Accepts any column named: domain, website, url, site, company_url, company website.
    Falls back to the first column if none of those match.
    Skips blank rows.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {csv_path}")

    domains: List[str] = []

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(f"CSV file appears to be empty: {csv_path}")

        # Find the column to use
        col = None
        for name in reader.fieldnames:
            if name.strip().lower() in _DOMAIN_COLUMN_ALIASES:
                col = name
                break

        if col is None:
            col = reader.fieldnames[0]

        for row in reader:
            value = (row.get(col) or "").strip()
            if value:
                domains.append(value)

    if not domains:
        raise ValueError(f"No domains found in {csv_path} (column used: '{col}')")

    return domains


def write_results(
    results: list,
    pages_crawled_map: dict,
    output_path: str,
    enrichment_map: Optional[Dict] = None,
    enrichment_columns: Optional[List[str]] = None,
) -> None:
    """
    Write a list of ICPResult objects to a CSV file.

    results            — list of ICPResult
    pages_crawled_map  — dict mapping domain -> pages_crawled int
    output_path        — destination CSV path
    enrichment_map     — optional dict mapping domain -> {column: (value, comment)}
    enrichment_columns — ordered list of enrichment base column names to append;
                         each expands to two columns: {column} and {column}_comment
    """
    extra_fields: List[str] = []
    for col in (enrichment_columns or []):
        extra_fields.append(col)
        extra_fields.append(f"{col}_comment")

    fieldnames = OUTPUT_FIELDNAMES + extra_fields

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row: dict = {
                "domain": r.domain,
                "is_icp": "" if r.is_icp is None else str(r.is_icp).lower(),
                "confidence": r.confidence,
                "reasoning": r.reasoning,
                "pages_crawled": pages_crawled_map.get(r.domain, 0),
                "error": r.error or "",
            }
            if enrichment_columns:
                domain_enrichments = (enrichment_map or {}).get(r.domain, {})
                for col in enrichment_columns:
                    value, comment = domain_enrichments.get(col, ("", ""))
                    row[col] = value
                    row[f"{col}_comment"] = comment
            writer.writerow(row)
