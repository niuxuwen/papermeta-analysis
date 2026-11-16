# Benchmark date and newness query API

Web query: `https://cowhors.com/releases/api/v1/judge.html`

This queries existing evidence. It does not investigate new URLs, accept client
"verified" decisions, modify score evidence, or write to production queues.
Unknown is `PENDING` with `is_new_in_report_period: null`, never a false old flag.
Same-name results remain `AMBIGUOUS` until an exact source is selected.

## Direct reviewed-entity JSON

```sh
curl -fsS https://cowhors.com/releases/api/v1/benchmarks/toolturns.json
curl -fsS https://cowhors.com/releases/api/v1/benchmarks/distdebug-bench.json
curl -fsS https://cowhors.com/releases/api/v1/benchmarks/cogsuite.json
```

Direct paths exist for reviewed identities; absence/404 is not a novelty judgment.
For arbitrary existing catalogue names, source IDs, paper IDs, arXiv links or
reviewed official project links, use the query client below.

## Query clients

Python (standard library; no API key):

```sh
python backend/query_release_api.py --query ToolTurns
python backend/query_release_api.py --query https://arxiv.org/abs/2611.14925v1
python backend/query_release_api.py --query HumanEval --paper-id recent-EXACT_PAPER_ID
python backend/query_release_api.py --ledger dist/releases/current.json --query DistDebug-Bench
```

Browser JavaScript:

```js
const {judge} = await import('https://cowhors.com/releases/api/v1/judge-client.mjs');
const result = await judge('ToolTurns',
  new URL('https://cowhors.com/releases/api/v1/current.json'));
console.log(result);
```

The HTTP API is static JSON. The client reads `current.json`, then the
SHA-256-prefix lookup and judgment shards described there. Every shard's length,
SHA-256, snapshot ID, source hash, registry hash and generation are checked.
`api_root` is resolved relative to that manifest URL, preserving project paths.
Exact normalized names are indexed; there is no automatic fuzzy identity merge.
ArXiv URLs normalize to versionless IDs. Name collisions return multiple sources.
For an exact source, query `paper_id::benchmark_id`; detail pages use this key so
a common benchmark ID cannot hide the current source behind a truncated name query.

## Returned date fields

* `benchmark_first_public_date`: reviewed exact Beijing first-public day, or null.
* `benchmark_date_status`: `VERIFIED_FIRST_PUBLIC`, `PUBLIC_BY_BOUND_ONLY`,
  `NOT_A_BENCHMARK`, or `PENDING`.
* `first_public_on_or_before`: an upper bound supported by a public event; it is
  explicitly **not** an exact first-public date.
* `author_date_claims`: author dates and their event type/unknown time zone.
* `code_release_dates`, `data_release_dates`: verified public timestamps converted
  to Beijing dates, separate from first introduction.
* `source_refs[].release_date` and `date_basis`: original source values, retained
  for audit. `PAPER_V1_PROXY` is never silently upgraded to a benchmark date.
* `date_evidence`, `date_review_notes`, `date_pending_reasons`: provenance and
  unresolved evidence requirements. Commit/repository timestamps are preserved
  as leads, not silently converted into public release dates.

`is_new_in_report_period` refers to the accompanying `report_period`; a known
first introduction outside that interval is false. Scope and independent entity
identity must also be reviewed before a new-release judgment can be true.
Metrics, subsets and ablations are not independent benchmarks.

A verified date-only author launch without a time zone cannot support an exact
Beijing day. Its conservative Beijing upper bound is the author calendar date
plus one day (covering offsets UTC-12 through UTC+14). The author date, event
kind, uncertainty and derivation rule remain visible. Future events are not
reported as already released.

## Existing data overlay

Each immutable release generation contains `benchmark-dates.json.gz`, one row per
exact source `(paper_id, benchmark_id)`, including undated/unclassified reused
evaluations. The file hash is in `releases/current.json`. New date fields are
separate from the original scoring source, paper dates and score-clock dates.
The overlay records honest unknowns across the entire current source snapshot;
it is not a claim that every first-public day has been recovered.

Existing benchmark detail pages query the matching date judgment asynchronously
and require the same score snapshot ID and exact source identity. A mismatch,
network failure or ambiguity leaves the first date pending and score browsing
usable. The source proxy date is labeled as a source date rather than a verified
benchmark first publication.

## Automatic evidence review and date updates

`automatic_date_service.py` is a separate, resumable date worker. It reads a
hash-verified copy of the published source under the publisher lock, then checks
captured paper content, parser SHA-256, exact benchmark identities, evidence
quotes, novelty decisions and historical aliases. It prioritizes the previous
seven complete Beijing calendar days. A source scan is distinct from a verified
first-public date; its status counters expose that difference.

The SQLite checkpoint records each exact `(paper_id, benchmark_id)`, input
signature, result, reason and research attempts. Repeated cycles retain results;
changed source evidence requeues only affected date tasks. Existing manual
decisions are protected. Historical audited receipts establish conservative
public-by bounds only; variants cannot inherit a parent benchmark's date.

For official GitHub sources, the worker inspects release records and tagged
README content. Edited release bodies only establish an updated public-by bound.
Repository creation, code release and paper submission dates alone cannot set a
first-public day. An exact automatic first date additionally requires a pinned
v1 source, an explicit author statement of first public introduction, matching
identity, chronology and no captured prior-history conflict. Unknowns retain
the missing-evidence reason. HTTP failures are cached, rate limits pause the
host, and transient primary-fetch retries are bounded to three per input.

Recurring deployment example (Linux; run through the installed project venv):

```sh
PYTHONPATH=/project/deployment/publication/deps /project/.venv/bin/python \
  /version/backend/automatic_date_service.py --project /project \
  --state /project/deployment/automatic-dates/state \
  --manual /version/backend/release-evidence.json --workers 8 --publish
```

The worker lock prevents overlap. Its date publisher uses the shared publisher
lock and a Git lease, verifies that score/source blob hashes remain unchanged,
and adds only `feed/release-evidence.json.gz` plus the current Pages workflow.
Normal score publications retain that feed file. The website validates each
automatic source binding against the current source signature before applying
it. Date decisions therefore reach detail labels, query JSON and daily release
reports automatically, without changing scoring or the 60-day paper window.
Each immutable generation includes `automatic-review-progress.json`; source
checking, precise dates, bounds and remaining evidence gaps are shown separately.

This process does not resume the paused manual 1,400-paper review automation.

`automatic_date_publish.py` provides a separate bounded publication retry job.
It may run every minute, uses its own overlap lock, and throttles successful
publications to at least five minutes apart. Each invocation tries the shared
publisher lock at most five times, ten seconds apart. A long review cycle or a
busy score publisher therefore does not discard a completed date checkpoint.
The publisher acquires the shared lock before loading the large evidence file.
Internal freeze, collection, generation and planned dates are retained as
nonpublic source claims, rather than credited as public release evidence.

The paper-introduction stage checks actual dated primary-category arXiv
announcement listings, pinned v1 author benchmark claims and prior-name search
results. It does not use the submission timestamp as a public announcement.
An arXiv-only search is insufficient to establish global first introduction:
earlier project sites, repositories and formal publications must be reconciled
independently. Curated `firstness_clearance` receipts may authorize automatic
date completion only when pinned to the same source hash and accompanied by
reviewed primary evidence. Without that clearance, the actual paper publication
day remains a public-by bound. Existing primary evidence earlier than a claimed
first day invalidates that first-day judgment.

Source capture may proceed while the score publisher is busy only if a private
copy matches the unchanged publication manifest and its exact source hash.
Concurrent or incomplete writes fail closed. This prevents the shared publisher
lock from indefinitely starving date review without changing score data.


## Benchmark date register (paper fallback)

The primary operational view is `/releases/date-table.html`; its complete durable
register is `/releases/date-table.json.gz`, with summary at
`/releases/date-table-summary.json`. Entries retain date basis, fallback flag,
source paper IDs/URLs, aliases, exclusions and revision history. The date service
refreshes this table before optional network research and saves it outside the
rolling paper window. Each date-only publication carries the saved table.

On a table hit, reuse its date and exclusion. A stronger public date replaces a
paper proxy; an earlier date of equal strength replaces the current one. Missing
dates fall back to the earliest associated paper's first-publication field in
Beijing time, explicitly labeled `PAPER_PUBLICATION_FALLBACK`. Missing or future
paper dates stay missing rather than using ingestion time. A primary public-by
date can be used operationally without claiming independently verified firstness.

Each existing query returns `registered_date` (date, basis, fallback, exclusion,
identity grouping and source-newness). Independently reviewed first-publication
fields remain separate. Table grouping uses normalized exact names and reviewed
aliases; known homonyms and distinct version suffixes are not collapsed.

Daily register statistics count source-reported new benchmarks by registered
date, with fallback counts alongside them. Reused/unknown assets are not all
relabeled new merely because their dates have been filled. These are counts of
the collected catalogue under the paper-fallback rule, not an exhaustive web census.
Score inputs, model results and the 60-day paper selection are not changed.
