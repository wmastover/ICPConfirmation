"""
Crawls a domain using the Firecrawl SDK and returns clean markdown content.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from firecrawl import Firecrawl


@dataclass
class CrawlResult:
    domain: str
    markdown: str
    pages_crawled: int
    error: Optional[str] = None


def _normalise_url(domain: str) -> str:
    """Ensure the domain has a scheme so Firecrawl can fetch it."""
    domain = domain.strip()
    if not domain.startswith(("http://", "https://")):
        return f"https://{domain}"
    return domain


def scrape_domain(
    domain: str,
    pages_per_domain: int = 1,
    max_chars: int = 15000,
    api_key: Optional[str] = None,
) -> CrawlResult:
    """
    Scrape a single domain and return its content as trimmed markdown.

    When pages_per_domain == 1, uses the faster scrape() endpoint (homepage only).
    When pages_per_domain > 1, uses crawl() to follow links up to that page limit.
    """
    key = api_key or os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        raise ValueError("FIRECRAWL_API_KEY is not set")

    fc = Firecrawl(api_key=key)
    url = _normalise_url(domain)

    try:
        if pages_per_domain <= 1:
            result = fc.scrape(url, formats=["markdown"])
            # SDK v4 returns a Document object; fall back to dict access for older versions
            if hasattr(result, "markdown"):
                markdown = (result.markdown or "").strip()
            else:
                markdown = (result.get("markdown") or "").strip()
            pages_crawled = 1 if markdown else 0
        else:
            job = fc.crawl(
                url,
                limit=pages_per_domain,
                scrape_options={"formats": ["markdown"]},
            )
            # SDK v4 returns a CrawlStatusResponse with a .data list of Documents
            pages = job.data if hasattr(job, "data") else (job.get("data") or [])
            parts = []
            for p in pages:
                if hasattr(p, "markdown"):
                    text = (p.markdown or "").strip()
                else:
                    text = (p.get("markdown") or "").strip()
                if text:
                    parts.append(text)
            markdown = "\n\n---\n\n".join(parts)
            pages_crawled = len(parts)

        markdown = markdown[:max_chars]

        if not markdown:
            return CrawlResult(
                domain=domain,
                markdown="",
                pages_crawled=0,
                error="No content extracted from page",
            )

        return CrawlResult(domain=domain, markdown=markdown, pages_crawled=pages_crawled)

    except Exception as exc:
        return CrawlResult(domain=domain, markdown="", pages_crawled=0, error=str(exc))
