# Benchmark first-publication statistics

The evaluation catalogue is not a list of new releases. An eligible score can
come from an existing benchmark. Publication of a paper, public introduction of
a benchmark, data/code availability, and an update are distinct events.

`release-evidence.json` is the reviewed identity/event registry. Exact
`paper_id` + `benchmark_id` bindings reconcile aliases without changing score
groups. Metrics, subsets, subtasks and ablations remain in score evidence but
do not count as independent new benchmarks. Short labels are never excluded
globally. New identities without scores can still enter the release registry.

A confirmed new LLM benchmark needs reviewed primary identity and firstness
evidence plus a first-introduction event with a verified date basis. A paper's
date alone (`PAPER_V1_PROXY`) is insufficient. Code/data releases alone are also
insufficient. Date-only events require an established time zone; aware timestamps
are converted to Asia/Shanghai. Future events are pending. Repository creation
and imported commit dates do not by themselves prove first public availability.

`build_release_ledger.py` streams the hash-verified publication using ijson. It
checks the embedded snapshot ID, produces immutable generations with entity
provenance and a resumable review queue, and replaces `current.json` last.
The generation includes evidence and producer hashes. Inputs are read-only;
no queue database, model endpoint or scoring implementation is accessed.

The evaluated-paper feed is not a global release census. Daily totals and the
daily average therefore remain null. Each date shows a confirmed minimum or
`待核`, never a fabricated zero. Unresolved source identities are candidate
records, not verified new benchmarks; cross-paper duplicates may remain in that
pending pool. The report defaults to the preceding 14 complete Beijing dates
as of the source snapshot. Registry corrections restate those dates on replay.

Run locally:

```sh
python -m pip install ijson==3.6.0
python backend/build_release_ledger.py --source feed/source.json.gz \
  --publication feed/publication.json --registry backend/release-evidence.json \
  --output dist/releases --start 2026-11-02 --end 2026-11-16
python -m unittest discover -s backend -p 'test_release*.py'
```

The production Pages workflow runs `build_release_site.py feed` after the score
site and language editions are built. It requires the release and score snapshot
IDs and source hashes to match, validates every generated archive, and links the
report at `/releases/` from both homepages. It does not change the 60-day paper
window, scoring, source requirements, failure queues or paused manual review.
The existing atomic Pages deployment retains the last successful website if
this build fails.

The initial reviewed registry fixes ten false units and retains the investigated
author release events. Only ToolTurns has been promoted to a confirmed first
introduction in this seed. Other sampled announcements/artifact dates remain
pending where earliest public introduction or scope was unresolved; this is
deliberately not an exhaustive two-week count.
