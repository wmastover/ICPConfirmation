"""
Sends scraped website markdown to OpenRouter AI and returns an ICP verdict.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI


@dataclass
class ICPResult:
    domain: str
    is_icp: Optional[bool]
    confidence: str        # "high" | "medium" | "low" | "unknown"
    reasoning: str
    error: Optional[str] = None


_ENRICHMENT_SYSTEM_PROMPT = """\
You are a research assistant. You will be given scraped website content from a company.
Answer the user's question based only on the website content provided.

Respond ONLY with a valid JSON object in exactly this format:
{
  "value": "the answer if found, or empty string if not determinable from the content",
  "comment": "brief reason why the value could not be determined, or empty string if value is populated"
}

Rules:
- "value" must contain ONLY the direct answer (e.g. a game name), nothing else.
- If the answer cannot be determined from the content, set "value" to "" and put a short explanation in "comment".
- Do not include any text outside the JSON object.
"""

_SYSTEM_PROMPT = """\
You are an expert B2B sales analyst. You will be given:
1. A definition of an Ideal Customer Profile (ICP)
2. Scraped website content from a company

Your task is to determine whether this company matches the ICP.

Respond ONLY with a valid JSON object in exactly this format:
{
  "is_icp": true or false,
  "confidence": "high" or "medium" or "low",
  "reasoning": "A concise 2-4 sentence explanation of your decision."
}

Do not include any text outside the JSON object.
"""


def _build_user_prompt(icp_definition: str, domain: str, markdown: str) -> str:
    return f"""## ICP Definition

{icp_definition.strip()}

## Company Website: {domain}

{markdown.strip()}

---

Based on the website content above, does this company match the ICP? Respond with JSON only."""


def _parse_response(text: str) -> dict:
    """Extract and parse the JSON object from the model response."""
    text = text.strip()

    # Try to extract a JSON block if the model wrapped it in markdown fences
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)

    # Fallback: find the first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    return json.loads(text)


def check_icp(
    domain: str,
    markdown: str,
    icp_definition: str,
    model: str = "anthropic/claude-3.5-sonnet",
    api_key: Optional[str] = None,
) -> ICPResult:
    """
    Call the OpenRouter API to evaluate whether a company matches the ICP.
    Returns an ICPResult with is_icp, confidence, and reasoning.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    client = OpenAI(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(icp_definition, domain, markdown),
                },
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content or ""
        parsed = _parse_response(raw)

        return ICPResult(
            domain=domain,
            is_icp=bool(parsed.get("is_icp")),
            confidence=str(parsed.get("confidence", "unknown")).lower(),
            reasoning=str(parsed.get("reasoning", "")),
        )

    except json.JSONDecodeError as exc:
        return ICPResult(
            domain=domain,
            is_icp=None,
            confidence="unknown",
            reasoning="",
            error=f"Failed to parse AI response as JSON: {exc}",
        )
    except Exception as exc:
        return ICPResult(
            domain=domain,
            is_icp=None,
            confidence="unknown",
            reasoning="",
            error=str(exc),
        )


def run_enrichment(
    domain: str,
    markdown: str,
    prompt: str,
    model: str = "anthropic/claude-3.5-sonnet",
    api_key: Optional[str] = None,
) -> tuple:
    """
    Run a custom enrichment prompt against scraped website content.
    Returns a (value, comment) tuple.
    - value   : the direct answer if found, otherwise empty string
    - comment : brief reason the value could not be found, or empty string when value is populated
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return ("", "OPENROUTER_API_KEY not set")

    client = OpenAI(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _ENRICHMENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"## Company Website: {domain}\n\n"
                        f"{markdown.strip()}\n\n"
                        f"---\n\n"
                        f"{prompt}"
                    ),
                },
            ],
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_response(raw)
        value = str(parsed.get("value") or "").strip()
        comment = str(parsed.get("comment") or "").strip()
        return (value, comment)
    except json.JSONDecodeError:
        return ("", "AI returned non-JSON response")
    except Exception as exc:
        return ("", str(exc))
