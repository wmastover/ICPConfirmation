#!/usr/bin/env python3
"""
ICP Confirmation CLI

Usage:
    python run.py domains.csv
    python run.py domains.csv --output my_results.csv
    python run.py domains.csv --concurrency 5
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from src.ai_checker import ICPResult, check_icp, run_enrichment
from src.crawler import CrawlResult, scrape_domain
from src.csv_handler import read_domains, write_results

console = Console()

CONFIG_PATH = Path(__file__).parent / "config.yaml"
ICP_PATH = Path(__file__).parent / "icp.md"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Error:[/red] config.yaml not found at {CONFIG_PATH}")
        sys.exit(1)
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def load_icp_definition() -> str:
    if not ICP_PATH.exists():
        console.print(f"[red]Error:[/red] icp.md not found at {ICP_PATH}")
        sys.exit(1)
    return ICP_PATH.read_text(encoding="utf-8").strip()


def check_env_keys() -> None:
    missing = []
    if not os.environ.get("FIRECRAWL_API_KEY"):
        missing.append("FIRECRAWL_API_KEY")
    if not os.environ.get("OPENROUTER_API_KEY"):
        missing.append("OPENROUTER_API_KEY")
    if missing:
        console.print(
            f"[red]Error:[/red] Missing environment variables: {', '.join(missing)}\n"
            "Add them to your .env file or export them in your shell."
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Per-domain processing
# ---------------------------------------------------------------------------

def process_domain(
    domain: str,
    icp_definition: str,
    model: str,
    pages_per_domain: int,
    max_chars: int,
    enrichments: list[dict],
    deep_crawl_pages: int = 10,
) -> tuple[CrawlResult, ICPResult, dict[str, tuple]]:
    crawl = scrape_domain(domain, pages_per_domain=pages_per_domain, max_chars=max_chars)

    empty_enrichments: dict[str, tuple] = {e["column"]: ("", "") for e in enrichments}

    if crawl.error and not crawl.markdown:
        icp_result = ICPResult(
            domain=domain,
            is_icp=None,
            confidence="unknown",
            reasoning="",
            error=f"Crawl failed: {crawl.error}",
        )
        return crawl, icp_result, empty_enrichments

    icp_result = check_icp(
        domain=domain,
        markdown=crawl.markdown,
        icp_definition=icp_definition,
        model=model,
    )

    enrichment_results: dict[str, tuple] = {}
    for e in enrichments:
        if e.get("icp_only") and not icp_result.is_icp:
            enrichment_results[e["column"]] = ("", "")
        else:
            enrichment_results[e["column"]] = run_enrichment(
                domain=domain,
                markdown=crawl.markdown,
                prompt=e["prompt"],
                model=model,
            )

    # Deep-crawl retry: for enrichments that came back empty, re-scrape with more pages
    needs_retry = [
        e for e in enrichments
        if e.get("deep_crawl_fallback")
        and enrichment_results.get(e["column"], ("", ""))[0] == ""
        and not (e.get("icp_only") and not icp_result.is_icp)
    ]
    if needs_retry:
        deep_crawl = scrape_domain(domain, pages_per_domain=deep_crawl_pages, max_chars=max_chars)
        if deep_crawl.markdown:
            for e in needs_retry:
                enrichment_results[e["column"]] = run_enrichment(
                    domain=domain,
                    markdown=deep_crawl.markdown,
                    prompt=e["prompt"],
                    model=model,
                )

    return crawl, icp_result, enrichment_results


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(icp_results: list[ICPResult], pages_map: dict) -> None:
    table = Table(title="ICP Confirmation Results", show_lines=True)
    table.add_column("Domain", style="cyan", no_wrap=True)
    table.add_column("ICP?", justify="center")
    table.add_column("Confidence", justify="center")
    table.add_column("Pages", justify="center")
    table.add_column("Reasoning / Error")

    for r in icp_results:
        if r.error and r.is_icp is None:
            icp_str = "[dim]error[/dim]"
            conf_str = "[dim]—[/dim]"
            detail = f"[red]{r.error}[/red]"
        elif r.is_icp is True:
            icp_str = "[bold green]YES[/bold green]"
            conf_str = _conf_style(r.confidence)
            detail = r.reasoning
        else:
            icp_str = "[bold red]NO[/bold red]"
            conf_str = _conf_style(r.confidence)
            detail = r.reasoning

        table.add_row(
            r.domain,
            icp_str,
            conf_str,
            str(pages_map.get(r.domain, 0)),
            detail,
        )

    console.print()
    console.print(table)

    yes = sum(1 for r in icp_results if r.is_icp is True)
    no = sum(1 for r in icp_results if r.is_icp is False)
    errors = sum(1 for r in icp_results if r.is_icp is None)
    console.print(
        f"\n[bold]Summary:[/bold] {yes} ICP match(es), {no} non-match(es), {errors} error(s) "
        f"out of {len(icp_results)} domains."
    )


def _conf_style(conf: str) -> str:
    mapping = {"high": "[green]high[/green]", "medium": "[yellow]medium[/yellow]", "low": "[red]low[/red]"}
    return mapping.get(conf, conf)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Check whether a list of domains match your Ideal Customer Profile (ICP)."
    )
    parser.add_argument("csv", help="Path to input CSV file containing domains")
    parser.add_argument("--output", "-o", help="Path for output CSV (default: results_<timestamp>.csv)")
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=None,
        help="Number of domains to process in parallel (overrides config.yaml)",
    )
    args = parser.parse_args()

    config = load_config()
    icp_definition = load_icp_definition()
    check_env_keys()

    model = config.get("openrouter", {}).get("model", "anthropic/claude-3.5-sonnet")
    crawl_cfg = config.get("crawl", {})
    pages_per_domain = int(crawl_cfg.get("pages_per_domain", 1))
    max_chars = int(crawl_cfg.get("max_chars", 15000))
    concurrency = args.concurrency or int(crawl_cfg.get("concurrency", 3))
    deep_crawl_pages = int(crawl_cfg.get("deep_crawl_pages", 10))
    enrichments: list[dict] = config.get("enrichments") or []
    enrichment_columns = [e["column"] for e in enrichments]

    output_path = args.output or f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    console.rule("[bold blue]ICP Confirmation[/bold blue]")
    console.print(f"  Input CSV   : [cyan]{args.csv}[/cyan]")
    console.print(f"  Output CSV  : [cyan]{output_path}[/cyan]")
    console.print(f"  Model       : [cyan]{model}[/cyan]")
    console.print(f"  Pages/domain: [cyan]{pages_per_domain}[/cyan]")
    console.print(f"  Concurrency : [cyan]{concurrency}[/cyan]")
    if enrichment_columns:
        console.print(f"  Enrichments : [cyan]{', '.join(enrichment_columns)}[/cyan]")
    console.print()

    try:
        domains = read_domains(args.csv)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    console.print(f"Found [bold]{len(domains)}[/bold] domain(s) to process.\n")

    crawl_results: dict[str, CrawlResult] = {}
    icp_results: list[ICPResult] = []
    enrichment_map: dict[str, dict[str, str]] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Processing domains...", total=len(domains))

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    process_domain,
                    domain,
                    icp_definition,
                    model,
                    pages_per_domain,
                    max_chars,
                    enrichments,
                    deep_crawl_pages,
                ): domain
                for domain in domains
            }

            for future in as_completed(futures):
                domain = futures[future]
                try:
                    crawl, icp, domain_enrichments = future.result()
                    crawl_results[domain] = crawl
                    icp_results.append(icp)
                    enrichment_map[domain] = domain_enrichments
                except Exception as exc:
                    crawl_results[domain] = CrawlResult(
                        domain=domain, markdown="", pages_crawled=0, error=str(exc)
                    )
                    icp_results.append(
                        ICPResult(
                            domain=domain,
                            is_icp=None,
                            confidence="unknown",
                            reasoning="",
                            error=str(exc),
                        )
                    )
                    enrichment_map[domain] = {col: ("", "") for col in enrichment_columns}
                finally:
                    progress.advance(task)

    pages_map = {d: cr.pages_crawled for d, cr in crawl_results.items()}

    # Sort results to match input order
    domain_order = {d: i for i, d in enumerate(domains)}
    icp_results.sort(key=lambda r: domain_order.get(r.domain, 9999))

    write_results(icp_results, pages_map, output_path, enrichment_map, enrichment_columns)
    print_summary(icp_results, pages_map)

    console.print(f"\nResults saved to [bold cyan]{output_path}[/bold cyan]\n")


if __name__ == "__main__":
    main()
