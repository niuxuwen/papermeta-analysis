"""Resume validated stages only for the same source, policy and exact inputs."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

VERSION = "source-stage-checkpoints-v1"


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class StageCheckpoints:
    def __init__(self, root, identity, *, force=False):
        self.root = Path(root) / "stages"
        self.identity = identity
        self.force = force
        self.reused = []

    def _path(self, stage, inputs):
        if stage == 'binding_failure_budget':
            try:
                ticket = json.loads((self.root.parent / 'user_backlog_retry.json').read_text(encoding='utf-8'))
                if (ticket.get('version') == 1 and ticket.get('policy') == 'user-date-register-paper-fallback-20261117-v1'
                        and ticket.get('paper_id') == self.identity.get('paper', {}).get('paper_id')
                        and isinstance(ticket.get('request_sha256'), str) and len(ticket['request_sha256']) == 64):
                    inputs = {**inputs, 'user_requested_backlog_attempt': ticket['request_sha256']}
            except (OSError, ValueError, TypeError):
                pass
        key = fingerprint({"version": VERSION, "identity": self.identity,
                           "stage": stage, "inputs": inputs})
        return self.root / (key + ".json")

    def load(self, stage, inputs):
        if self.force:
            return None
        path = self._path(stage, inputs)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record["version"] != VERSION or record["stage"] != stage
                    or record.get("input_key") != path.stem
                    or fingerprint(record["value"]) != record["value_sha256"]):
                return None
            value = record["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        self.reused.append(stage)
        return deepcopy(value)

    def save(self, stage, inputs, value):
        # Called only after the production validator and source checks succeed.
        path = self._path(stage, inputs)
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"version": VERSION, "stage": stage, "value": value,
                  "input_key": path.stem,
                  "value_sha256": fingerprint(value)}
        if stage == 'novelty_followup':
            record['inputs'] = deepcopy(inputs)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    def load_covering_followup(self, inputs):
        """Reuse a completed full-source pass when only resolved gaps vanished.

        Source, model, window and policy must still produce the stored key.
        Every remaining gap (including its reason) must have been requested.
        Old records without inputs remain exact-key-only caches.
        """
        if self.force or not isinstance(inputs.get('focus'), list) or not inputs['focus']:
            return None
        wanted = {fingerprint(gap) for gap in inputs['focus']}
        rest = {k: v for k, v in inputs.items() if k != 'focus'}
        for path in sorted(self.root.glob('*.json')):
            try:
                record = json.loads(path.read_text(encoding='utf8'))
                old = record.get('inputs')
                if (record.get('stage') != 'novelty_followup' or not isinstance(old, dict)
                        or {k: v for k, v in old.items() if k != 'focus'} != rest
                        or not isinstance(old.get('focus'), list)
                        or not wanted.issubset({fingerprint(gap) for gap in old['focus']})
                        or self._path('novelty_followup', old) != path):
                    continue
                # load() rechecks version and value hash; no cached abstention
                # is upgraded to an accepted benchmark by this operation.
                value = self.load('novelty_followup', old)
                if value is not None:
                    return value
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None


def qualification_gaps(benchmarks):
    """Describe evidence deficits without upgrading any scientific decision."""
    gaps = []
    for bench in benchmarks:
        if bench.get("eligibility") not in {"REVIEW", "PENDING_HISTORY"}:
            continue
        reason = str(bench.get("reason") or "benchmark资格未确定")
        if "元数据" in reason or "v1" in reason:
            code, stage = "V1_METADATA", "metadata"
        elif "别名" in reason or "身份" in reason or "同名" in reason:
            code, stage = "BENCHMARK_IDENTITY", "history"
        elif "检索" in reason or bench.get("eligibility") == "PENDING_HISTORY":
            code, stage = "EARLIER_RELEASE_SEARCH", "history"
        elif "日期" in reason or "发布" in reason:
            code, stage = "RELEASE_DATE", "novelty"
        else:
            code, stage = "NOVELTY_OR_TEST_TARGET", "novelty"
        gaps.append({"benchmark_id": bench.get("benchmark_id"), "code": code,
                     "stage": stage, "reason": reason})
    if not benchmarks:
        gaps.append({"code": "NO_BENCHMARK_EVIDENCE", "stage": "novelty",
                     "reason": "全文未找到可核验的新benchmark证据"})
    return gaps
