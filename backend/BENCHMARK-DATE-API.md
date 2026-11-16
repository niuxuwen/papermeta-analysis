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
