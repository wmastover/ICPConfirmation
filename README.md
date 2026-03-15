# ICP Confirmation CLI

A Python CLI tool that takes a CSV of domains, crawls each website using [Firecrawl](https://firecrawl.dev), and uses an AI model via [OpenRouter](https://openrouter.ai) to determine whether each company matches your Ideal Customer Profile (ICP). It also supports custom **enrichment columns** — extra AI-powered fields you can add to every row of output.

## How it works

1. Reads a list of domains from a CSV file
2. Scrapes each domain via Firecrawl → returns clean markdown content
3. Sends the markdown + your ICP definition to an AI model via OpenRouter
4. Optionally runs additional AI prompts to enrich each row with custom data
5. Outputs a results CSV with `is_icp`, `confidence`, `reasoning`, enrichment columns, and more per domain

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

```
FIRECRAWL_API_KEY=fc-...       # https://firecrawl.dev/app
OPENROUTER_API_KEY=sk-or-...   # https://openrouter.ai/keys
```

### 3. Define your ICP

Edit `icp.md` with a plain-text description of your Ideal Customer Profile. Write it naturally — no special syntax required. The AI uses this text directly when evaluating companies.

### 4. (Optional) Adjust settings

Edit `config.yaml` to change the AI model, crawl depth, concurrency, or enrichments:

```yaml
openrouter:
  model: "anthropic/claude-3.5-sonnet"

crawl:
  pages_per_domain: 1    # 1 = homepage only (faster), >1 = full site crawl
  max_chars: 15000       # chars of content passed to AI per domain
  concurrency: 3         # domains processed in parallel
  deep_crawl_pages: 10   # pages to crawl on retry for enrichment fallback

enrichments:
  - column: "latest_game"
    prompt: "What is the name of the most recently released mobile game by this studio?"
    icp_only: true          # only run this enrichment for ICP-matching companies
    deep_crawl_fallback: true  # re-crawl with deep_crawl_pages if value not found
```

## Usage

```bash
python run.py domains.csv
```

### Options

| Flag | Description |
|------|-------------|
| `--output <path>` | Path for results CSV (default: `results_YYYYMMDD_HHMMSS.csv`) |
| `--concurrency <n>` | Override parallel workers from config |

### Examples

```bash
# Basic run
python run.py my_leads.csv

# Custom output path
python run.py my_leads.csv --output qualified_leads.csv

# Higher concurrency
python run.py my_leads.csv --concurrency 5
```

## Input CSV format

The input CSV should have one domain per row. The tool accepts any of these column names (case-insensitive):

- `domain`
- `website`
- `url`
- `site`
- `company_url`
- `company website`

If none of those match, the first column is used.

Example:

```csv
domain
stripe.com
notion.so
rippling.com
lattice.com
```

## Output CSV

Results are written to a CSV with these columns:

| Column | Description |
|--------|-------------|
| `domain` | The input domain |
| `is_icp` | `true` or `false` |
| `confidence` | `high`, `medium`, or `low` |
| `reasoning` | AI explanation of the verdict |
| `pages_crawled` | Number of pages Firecrawl fetched |
| `error` | Error message if crawl or AI call failed |
| *(enrichment columns)* | One column per entry in `config.yaml` enrichments |

## Enrichments

Enrichments let you extract arbitrary data points from each company's website using a plain-English prompt. Each enrichment adds a new column to the output CSV.

Configure them in `config.yaml` under the `enrichments` key:

```yaml
enrichments:
  - column: "hq_city"
    prompt: "What city is this company's headquarters located in?"

  - column: "latest_game"
    prompt: "What is the most recently released mobile game title by this studio?"
    icp_only: true             # skip this enrichment for non-ICP companies
    deep_crawl_fallback: true  # re-scrape with more pages if answer not found initially
```

**Options per enrichment:**

| Key | Type | Description |
|-----|------|-------------|
| `column` | string | Output CSV column name |
| `prompt` | string | Question sent to the AI along with the crawled content |
| `icp_only` | bool | If `true`, only run for companies that pass the ICP check |
| `deep_crawl_fallback` | bool | If `true`, re-crawl with `deep_crawl_pages` when the answer is not found on the first pass |

## Files

```
ICPConfirmation/
├── .env                 # Your API keys (gitignored — never commit this)
├── .env.example         # Template showing required keys
├── icp.md               # Your ICP definition — edit this freely
├── config.yaml          # Non-secret settings (model, crawl depth, enrichments, etc.)
├── run.py               # CLI entry point
├── requirements.txt
└── src/
    ├── crawler.py       # Firecrawl integration
    ├── ai_checker.py    # OpenRouter AI integration
    └── csv_handler.py   # CSV read/write
```
