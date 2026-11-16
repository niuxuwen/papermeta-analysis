"""Server CLI: discovery -> quoted novelty -> pinned PDF -> tables -> fresh index.

No historical database or screening checkpoint is opened. A run has a fixed UTC
window, atomic checkpoints, and a process lock. Successful calls use the existing
exact-input LLM cache; failures are retried once per invocation, with bounded
HTTP retries inside each call.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import tempfile
import time

import paper_workflow as workflow
from benchmark_tables import pipeline
from benchmark_tables.database import BenchmarkDatabase
from benchmark_tables.deepseek_client import DeepSeekClient
from benchmark_tables.xlsx_exporter import _filter_observations_for_export
from llm_guard import LLMServiceStop
from . import VERSION, CODE_VERSION
from .discovery import discover_arxiv_with_report, find_prior_mentions, DiscoveryError, DISCOVERY_QUERY_VERSION
from .novelty import utc, screen_paper, document_text, review_novelty, apply_history, SCREENING_VERSION, RECALL_SCREENING_VERSION, screening_semantic_version
from .scope import select_table, bind_observations
from .scheduling import screening_order, extraction_order
from .evidence_policy import ANALYSIS_POLICY_VERSION
from .window_policy import DEFAULT_WINDOW_DAYS, DEFAULT_BENCHMARK_MONTHS
from .recent_evaluation_scope import SCREENING_VERSION as RECENT_SCREENING_VERSION, POLICY_VERSION as RECENT_SCOPE_VERSION
from .source_issues import blocking_source_issues

LOG = logging.getLogger(__name__)
TERMINAL = {"EXCLUDED", "EXCLUDED_FULLTEXT", "REVIEW", "NO_TABLES", "COMPLETE"}
HISTORY_LOCK = threading.Lock()
HISTORY_POLICY_VERSION = "arxiv-history-input-v3-literal-source-names"


def stop_on_service_failure(exc):
    """Promote exhausted transport errors before optional work makes more calls."""
    from .failures import classify_failure
    diagnosis = classify_failure('ANALYSIS', str(exc))
    if diagnosis['service_failure']:
        stopped = LLMServiceStop(str(exc))
        stopped.failure_details = diagnosis
        raise stopped from exc


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    from .io_atomic import atomic_replace
    atomic_replace(temp, path)


class RunLock:
    def __init__(self, root: Path):
        self.path = root / ".run.lock"
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("此运行目录已有进程使用，请等待完成或使用独立目录")
        return self
    def __exit__(self, *args):
        self.handle.close()


def parse_args(argv=None, *, default_run_dir=None):
    parser = argparse.ArgumentParser(description=f"最近{DEFAULT_WINDOW_DAYS}天论文评测的近期LLM benchmark：服务器检索、表格提取和指数")
    parser.add_argument("command", choices=["run", "discover", "export", "label", "enrich", "postprocess", "backfill-labels", "sync", "profile", "score", "taxonomy"])
    parser.add_argument("--run-dir", type=Path, required=default_run_dir is None, default=default_run_dir,
                        help="独立运行目录；同目录续跑使用原时间窗口")
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    class ExplicitBenchmarkMonths(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            setattr(namespace, self.dest, values)
            namespace.benchmark_months_explicit = True
    parser.set_defaults(benchmark_months_explicit=False)
    parser.add_argument("--benchmark-months", type=int, default=DEFAULT_BENCHMARK_MONTHS, action=ExplicitBenchmarkMonths,
                        help="benchmark首次发布的独立日历月窗口，默认5；不改变论文检索days")
    parser.add_argument("--as-of", help="窗口右边界(不含)，UTC ISO时间；默认当前时刻，续跑默认原时刻")
    parser.add_argument("--qualification-as-of", help="续跑时重新计算日期资格的UTC时刻；不改变原始检索及来源窗口")
    parser.add_argument("--qualification-days", type=int, help="兼容旧benchmark天数窗口；与qualification-as-of配合使用，显式benchmark-months优先")
    parser.add_argument("--max-papers", type=int, default=0, help="0=检索全部匹配项；非0在报告中标注检索截断")
    parser.add_argument("--query", help="覆盖arXiv默认查询；仍强制附加首次提交日期窗口")
    parser.add_argument("--arxiv-gate-db", type=Path,
                        help="项目内共享arXiv限速库；官方入口统一使用 data/service/arxiv-gate.sqlite")
    parser.add_argument("--candidates-jsonl", type=Path, help="复用discover生成的候选快照，不做实时检索")
    parser.add_argument("--cache-dir", type=Path, default=os.getenv("RADAR_CACHE_DIR"),
                        help="跨日资产/模型判断缓存；官方入口默认 project/data/cache，不共享最终日期资格/指数")
    parser.add_argument("--no-shared-cache", action="store_true", help="只使用本次运行目录中的成果")
    parser.add_argument("--no-text-preflight", action="store_true", help="对照实验：所有通过摘要的论文直接交MinerU")
    parser.add_argument('--analysis-source', choices=('auto', 'tables', 'fulltext'), default='auto',
                        help='默认auto：全文提取并自动补救未完成表；tables/fulltext保留单轮模式')
    parser.add_argument("--llm-url", default=os.getenv("RADAR_LLM_URL", ""))
    parser.add_argument("--llm-model", default=os.getenv("RADAR_LLM_MODEL", ""))
    from .model_routing import add_model_arguments, resolve_model_arguments
    add_model_arguments(parser)
    parser.add_argument("--workers", type=int, default=2, help="论文审核/提取并发，整个过程同时最多此数量LLM请求")
    parser.add_argument("--download-workers", type=int, default=2)
    parser.add_argument("--download-timeout", type=float, default=120)
    parser.add_argument("--download-total-timeout", type=float, default=300, help="单篇PDF所有请求、退避和重试的总预算秒数")
    parser.add_argument("--download-retries", type=int, default=2, help="PDF失败后额外重试次数，独立于模型重试")
    parser.add_argument("--download-max-mb", type=float, default=100, help="单篇PDF大小上限MiB")
    parser.add_argument("--download-transport", choices=["auto", "requests", "curl"], default="auto")
    parser.add_argument("--no-html-fallback", action="store_true", help="关闭PDF失败后的同篇arXiv v1 HTML回退；已有HTML来源仍按原来源续跑")
    parser.add_argument("--mineru-workers", type=int, default=1)
    parser.add_argument("--mineru-devices", default=os.getenv("RADAR_MINERU_DEVICES", ""))
    parser.add_argument("--mineru-bin", default="mineru")
    parser.add_argument("--mineru-backend", default="pipeline")
    parser.add_argument("--mineru-timeout", type=float, default=7200)
    parser.add_argument("--mineru-device-wait-timeout", type=float, default=60,
                        help="等待GPU设备的独立预算秒数，0..60；不缩短实际OCR超时")
    parser.add_argument("--mineru-cache-tag", default=os.getenv("RADAR_MINERU_CACHE_TAG", ""),
                        help="确认MinerU权重/配置固定后给其版本标签，启用解析产物跨日复用；更换权重或配置必须换标签")
    parser.add_argument("--llm-transport", choices=["curl", "requests"], default="curl")
    parser.add_argument("--json-mode", choices=["off", "auto", "on"], default="off")
    parser.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high"], default="low")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--request-timeout", type=float, default=300)
    parser.add_argument("--request-total-timeout", type=float, default=600)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument('--failure-policy', choices=('strict', 'balanced'), default='strict',
                        help='strict限制失败请求重发并保留精确请求结案；balanced保留原重试策略')
    parser.add_argument("--min-benchmarks", type=int, default=3)
    parser.add_argument("--retry-review", action="store_true", help="重新处理待核实论文；仍复用相同输入的响应缓存")
    parser.add_argument("--screen-only", action="store_true", help="run仅完成摘要粗筛并保存state.json；不下载、解析、提取或覆盖已有导出")
    parser.add_argument("--pipeline-stage", choices=["DOWNLOAD", "PARSE", "ANALYZE"],
                        help="run仅执行一个持久化流水线阶段；复用已完成的摘要判断，不重新检索或筛选")
    parser.add_argument("--core-only", action="store_true",
                        help="run只发布核心来源成绩；能力标签、资源补证、Excel和历史同步由后台处理")
    parser.add_argument("--live-reservation-id", default=os.getenv('RADAR_LIVE_RESERVATION_ID'), help=argparse.SUPPRESS)
    parser.add_argument('--live-background-generation', help=argparse.SUPPRESS)
    parser.add_argument("--refresh-history", action="store_true", help="重新核验更早同名文献，包括已完成论文")
    parser.add_argument("--refresh-candidates", action="store_true", help="重查原时间窗口，可扩大试跑上限；保留既有候选与进度")
    parser.add_argument("--force-review", action="store_true", help="对标签及资源证据强制调用当前模型重审，保留旧审核记录")
    parser.add_argument("--xlsx", action="store_true", help="另外导出沿用现有版式的tables.xlsx；不影响CSV/HTML指数")
    parser.add_argument("--label-capabilities", action="store_true", help="提取后调用模型审核子任务的领域/任务/能力标签")
    parser.add_argument('--labels-only', action='store_true', help='仅按 benchmark 补能力分类，不进行逐指标审核、成绩导出或资源链接核验')
    parser.add_argument('--apply', action='store_true', help='backfill-labels 执行补标；默认仅输出缺口检查')
    parser.add_argument('--max-runs', type=int, default=100000, help='历史补标最多处理的运行目录数；默认覆盖全部已有目录，可指定较小值试跑')
    parser.add_argument('--backfill-report', type=Path, help='历史标签补齐的检查/执行报告 JSON 文件')
    parser.add_argument('--export-label-diagnostic', action='store_true',
                        help='补标结束时另导出缺口原文诊断包；大量目录时可能较慢')
    parser.add_argument('--labels-offline', action='store_true', help='backfill-labels 仅恢复已保存回答和标签缓存，禁止模型请求，不消耗补跑次数')
    parser.add_argument("--enrich-benchmarks", action="store_true", help="run完成后补benchmark分类与资源证据，无成绩也处理")
    parser.add_argument("--asset-timeout", type=float, default=15, help="单条资源链接核验超时秒数")
    parser.add_argument("--warehouse-dir", type=Path, default=os.getenv("RADAR_WAREHOUSE_DIR"),
                        help="跨日历史目录；每次发布去重同步，保留各自日期窗口；官方入口默认 project/data/catalog")
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--task-description", help="用户的具体任务；调用模型生成可编辑的能力权重及条件")
    profile.add_argument("--task-template", choices=["medical-literature-review", "code-development", "structured-extraction"], help="使用内置可编辑任务模板，无需模型解析需求")
    profile.add_argument("--task-profile", type=Path, help="加载已编辑的任务JSON；不调用模型解析需求")
    parser.add_argument("--reference-model", action="append", default=[], help="兼容旧配置；固定量程评分不使用参考模型，也无需指定")
    parser.add_argument("--candidate-model", action="append", help="限定候选模型的完整名称，可多次指定")
    args = parser.parse_args(argv)
    resolve_model_arguments(args)
    if args.qualification_as_of:
        try:
            utc(args.qualification_as_of)
        except (TypeError, ValueError):
            parser.error("qualification-as-of必须是带时区的ISO时间")
        if args.command != "run":
            parser.error("qualification-as-of只用于run")
    if args.qualification_days is not None and (not args.qualification_as_of or not 1 <= args.qualification_days <= 365):
        parser.error("qualification-days须1..365且配合qualification-as-of使用")
    if args.screen_only and args.command != "run":
        parser.error("--screen-only只用于run")
    if (args.pipeline_stage or args.core_only) and args.command != "run":
        parser.error("--pipeline-stage和--core-only只用于run")
    if args.pipeline_stage and (args.screen_only or args.refresh_candidates):
        parser.error("--pipeline-stage不能与screen-only或refresh-candidates同时使用")
    if not 1 <= args.days <= 365 or args.max_papers < 0 or args.retries < 0:
        parser.error("days必须1..365，max-papers和retries不能为负")
    if not 1 <= args.benchmark_months <= 120:
        parser.error("benchmark-months须1..120个日历月")
    if any(getattr(args, name) <= 0 for name in ("workers", "download_workers", "mineru_workers", "request_timeout", "request_total_timeout", "download_timeout", "mineru_timeout", "max_tokens", "min_benchmarks", "asset_timeout")):
        parser.error("并发、超时、token和最小benchmark数量必须为正")
    import math
    if not math.isfinite(args.mineru_device_wait_timeout) or not 0 <= args.mineru_device_wait_timeout <= 60:
        parser.error("mineru-device-wait-timeout须为0..60秒的有限数")
    if (not 0 <= args.download_retries <= 10 or any(not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0
            for name in ("download_timeout", "download_total_timeout", "download_max_mb"))
            or args.download_max_mb * 1024 * 1024 < 1):
        parser.error("download-retries须0..10，下载超时和大小上限须为有限正数（至少1字节）")
    has_profile = bool(args.task_description or args.task_template or args.task_profile)
    if args.command in {"profile", "score"} and not has_profile:
        parser.error("profile/score需要 --task-description、--task-template 或 --task-profile")
    if args.command == "sync" and not args.warehouse_dir:
        parser.error("sync需要 --warehouse-dir 历史目录")
    if not 0 < args.asset_timeout <= 60:
        parser.error("asset-timeout须大于0且不超过60秒")
    if args.enrich_benchmarks and args.command != "run":
        parser.error("--enrich-benchmarks只用于run；现有目录请用enrich命令")
    if args.refresh_candidates and args.command not in {"run", "discover"}:
        parser.error("--refresh-candidates只用于run/discover")
    if args.refresh_history and args.command != "run":
        parser.error("--refresh-history只用于run")
    if args.force_review and args.command not in {"run", "label", "enrich", "backfill-labels"}:
        parser.error("--force-review只用于run/label/enrich/backfill-labels")
    if args.warehouse_dir and args.warehouse_dir.resolve().is_relative_to(args.run_dir.resolve()):
        parser.error("历史目录应在运行目录之外，不能与单次窗口混用")
    if args.labels_only and args.command not in {'postprocess', 'backfill-labels'}:
        parser.error('--labels-only 仅用于 postprocess/backfill-labels')
    if args.apply and args.command != 'backfill-labels':
        parser.error('--apply 仅用于 backfill-labels')
    if args.labels_offline and (args.command != 'backfill-labels' or args.force_review):
        parser.error('--labels-offline 仅用于 backfill-labels，不能与 --force-review 同用')
    if args.export_label_diagnostic and args.command != 'backfill-labels':
        parser.error('--export-label-diagnostic 仅用于 backfill-labels')
    if args.max_runs < 1:
        parser.error('--max-runs 必须大于零')
    needs_llm = args.command in {"run", "label", "enrich", "postprocess"} or (args.command == 'backfill-labels' and args.apply) or (args.command in {"profile", "score"} and args.task_description)
    if needs_llm:
        if not args.llm_url or not (args.screen_model if args.screen_only else args.llm_model):
            parser.error("请配置 RADAR_LLM_URL 和 RADAR_LLM_MODEL；不使用任何写死的模型/接口")
        if not args.labels_offline and not os.getenv("RADAR_API_KEY"):
            parser.error("当前终端缺少 RADAR_API_KEY，请通过环境变量配置")
    return args


def qualification_window(args, manifest):
    """Independent benchmark dates; immutable paper discovery receipts stay fixed."""
    original_end = utc(manifest["end"])
    current_end = getattr(args, "qualification_as_of", None)
    end = utc(current_end) if current_end else original_end
    if end < original_end:
        raise ValueError("当前资格时刻不能早于原始检索窗口")
    # argparse distinguishes its default from an explicitly selected calendar
    # window, so old --qualification-days commands continue to work as written.
    supplied_months = getattr(args, "benchmark_months", None)
    explicit = getattr(args, "benchmark_months_explicit", supplied_months is not None)
    legacy_days = getattr(args, "qualification_days", None)
    if legacy_days is not None and not explicit:
        return end - timedelta(days=legacy_days), end
    months = supplied_months if explicit else manifest.get("benchmark_months", supplied_months or DEFAULT_BENCHMARK_MONTHS)
    from .window_policy import benchmark_window
    return benchmark_window(end, months=months)


def initialize(args):
    root = args.run_dir.resolve()
    path = root / "run.json"
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("version") != VERSION:
            raise ValueError("该目录不是此新流程的运行目录")
        if args.as_of and utc(args.as_of) != utc(manifest["end"]):
            raise ValueError("续跑不能改变日期窗口；检索新一周请用新目录")
        if args.days != manifest["days"]:
            raise ValueError("续跑days与原目录不符，请使用原设置或新目录")
        changed_limit = args.max_papers != manifest.get("max_papers", 0)
        changed_query = args.query is not None and args.query != manifest.get("query")
        if (changed_limit or changed_query) and not getattr(args, "refresh_candidates", False):
            raise ValueError("续跑检索上限/查询与原目录不同；保留原设置，或加 --refresh-candidates 明确重查原窗口")
    else:
        # Refuse silently reusing any historical data root.
        if any(p.name != ".run.lock" for p in root.iterdir()):
            raise ValueError("新流程须使用空目录，不能指向历史流水线目录")
        end = utc(args.as_of) if args.as_of else datetime.now(timezone.utc)
        manifest = {"version": VERSION, "start": (end - timedelta(days=args.days)).isoformat(),
                    "end": end.isoformat(), "days": args.days, "interval": "[start,end)",
                    "benchmark_months": getattr(args, "benchmark_months", DEFAULT_BENCHMARK_MONTHS),
                    "source": "arxiv", "query": args.query, "max_papers": args.max_papers,
                    "created_at": datetime.now(timezone.utc).isoformat()}
        atomic_json(path, manifest)
    from .warehouse import ensure_run_identity
    ensure_run_identity(root)
    return root, manifest


def validate_paper(paper, start, end):
    if not isinstance(paper, dict):
        raise ValueError("候选论文必须为对象")
    arxiv = re.sub(r"v\d+$", "", str(paper.get("arxiv_id", "")))
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})", arxiv):
        raise ValueError("候选缺少合法arXiv ID")
    if not start <= utc(paper.get("publication_date", "")) < end:
        raise ValueError("候选首次提交日期超出当前窗口")
    if not isinstance(paper.get("title"), str) or not paper["title"].strip():
        raise ValueError("候选缺少标题")
    metadata = paper.get("source_metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("source_metadata必须为对象")
    versions = [metadata.get("version")]
    for field in ("arxiv_id", "url", "pdf_url"):
        match = re.search(r"v(\d+)(?:[/?#]|$)", str(paper.get(field, "")))
        if match:
            versions.append(match.group(1))
    explicit = [str(value) for value in versions if value is not None]
    if any(value != "1" for value in explicit):
        raise ValueError("候选含非v1或冲突版本元数据；请重新取得arXiv v1标题、摘要和首次提交日期，不能只改链接")
    # A canonical v1 URL does not authenticate a supplied abstract. Unknown
    # snapshots may proceed to full-text review, but cannot authorize eligibility.
    verified_metadata = str(metadata.get("version")) == "1"
    # A supplied snapshot is a reusable API record, not an instruction or URL
    # allowlist. Force canonical public v1 routes for downloads/evidence.
    return {**paper, "id": arxiv, "arxiv_id": arxiv, "url": f"https://arxiv.org/abs/{arxiv}v1",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv}v1", "data_source": "arxiv",
            "metadata_verification": "V1_DECLARED" if verified_metadata else "UNVERIFIED",
            "paper_id": "recent-" + hashlib.sha256(arxiv.encode()).hexdigest()[:16]}


def candidates(args, root, manifest):
    path = root / "candidates.jsonl"
    report_path = root / "discovery.json"
    start, end = utc(manifest["start"]), utc(manifest["end"])
    previous = []
    previous_report = None
    quarantined = []
    if path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        snapshot = path.read_bytes()
        for number, line in enumerate(snapshot.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                previous.append(validate_paper(json.loads(line), start, end))
            except (ValueError, TypeError) as exc:
                if not getattr(args, "refresh_candidates", False):
                    raise ValueError(f"旧候选第{number}行版本/格式不合规；使用 --refresh-candidates 重新取得v1元数据：{exc}") from exc
                quarantined.append({"line": number, "raw": line, "reason": str(exc)})
        changed_snapshot = report.get("candidate_snapshot_sha256") not in (None, hashlib.sha256(snapshot).hexdigest())
        old_default_query = (manifest.get("query") is None and report.get("status") != "provided"
                             and report.get("query_version") != DISCOVERY_QUERY_VERSION)
        if getattr(args, "refresh_candidates", False):
            LOG.info("明确重查原窗口：原上限=%s 当前上限=%s；保留既有进度", manifest.get("max_papers", 0), args.max_papers)
        elif report.get("status") == "error":
            LOG.warning("上次检索失败，重新检索；已保存论文结果继续复用")
        elif changed_snapshot:
            if report.get("status") == "provided":
                raise ValueError("外部候选快照与保存的校验值不符，请核对文件")
            LOG.warning("检索快照与报告不一致，重新检索原窗口；已有处理进度保留")
        elif old_default_query:
            LOG.info("检索规则升级：%s -> %s；补查原日期窗口，保留原候选及提取进度",
                     report.get("query_version", "legacy"), DISCOVERY_QUERY_VERSION)
        else:
            return previous
        previous_report = report
    if args.candidates_jsonl:
        data = [json.loads(line) for line in args.candidates_jsonl.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        report = {"status": "provided", "source": str(args.candidates_jsonl.resolve()),
                  "query_version": "provided", "complete": False,
                  "note": "外部快照，当前进程未重新核实检索覆盖率"}
    else:
        try:
            limit = args.max_papers if getattr(args, "refresh_candidates", False) else manifest["max_papers"]
            query = args.query if args.query is not None else manifest["query"]
            discovery_options = {"max_results": limit, "query": query}
            if getattr(args, "arxiv_gate_db", None) is not None:
                discovery_options["gate_path"] = args.arxiv_gate_db
            data, report = discover_arxiv_with_report(start, end, **discovery_options)
            report.setdefault("query_version", "custom" if query is not None else DISCOVERY_QUERY_VERSION)
        except DiscoveryError as exc:
            # A refresh failure must not destroy the last usable snapshot/report.
            atomic_json(root / "discovery-refresh-error.json" if previous_report else report_path, exc.report)
            atomic_json(root / "discovery-partial.json", exc.partial_papers)
            raise
    papers = {}
    for paper in data:
        row = validate_paper(paper, start, end)
        if row["id"] in papers and row != papers[row["id"]]:
            raise ValueError(f"候选ID有冲突数据: {row['id']}")
        papers[row["id"]] = row
    fresh_ids = set(papers)
    if previous_report is not None:
        # Keep the original v1 inputs for known IDs so successful evidence/cache
        # remains tied to precisely the same paper text. Only add unseen IDs.
        for row in previous:
            fresh = papers.get(row["id"], {})
            if not (row.get("metadata_verification") == "UNVERIFIED"
                    and fresh.get("metadata_verification") == "V1_DECLARED"):
                papers[row["id"]] = row
        archive_digest = hashlib.sha256(path.read_bytes() + b"\0" + report_path.read_bytes()).hexdigest()
        archive = root / "discovery-history" / archive_digest[:16]
        archive.mkdir(parents=True, exist_ok=True)
        for source in (path, report_path):
            target = archive / source.name
            if not target.exists():
                target.write_bytes(source.read_bytes())
        report["refresh"] = {"previous_query_version": previous_report.get("query_version", "legacy"),
                             "previous_candidates": len(previous),
                             "added_candidates": len(fresh_ids - {p["id"] for p in previous}),
                             "retained_previous_only": len({p["id"] for p in previous} - fresh_ids),
                             "archive": str(archive.relative_to(root))}
        if quarantined:
            atomic_json(archive / "quarantined-candidates.json", quarantined)
            report["refresh"]["quarantined_candidates"] = len(quarantined)
        LOG.info("补查完成：新增=%d 保留已有=%d 合计=%d", report["refresh"]["added_candidates"], len(previous), len(papers))
    report["snapshot_candidate_count"] = len(papers)
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers.values()), encoding="utf-8")
    report["candidate_snapshot_sha256"] = hashlib.sha256(temp.read_bytes()).hexdigest()
    atomic_json(report_path, report)
    temp.replace(path)
    if getattr(args, "refresh_candidates", False):
        manifest.update(max_papers=args.max_papers, query=args.query if args.query is not None else manifest.get("query"))
        atomic_json(root / "run.json", manifest)
    return list(papers.values())


def make_client(args, root, database, *, purpose='analysis'):
    # Adapt only this project's explicit settings; the vendored CLI reads legacy
    # environment defaults even when its command-line arguments override them.
    from .model_routing import selected_model, request_environment
    request_options = request_environment()
    parsed = argparse.Namespace(
        deepseek_url=args.llm_url, deepseek_model=selected_model(args, purpose),
        llm_transport=args.llm_transport, json_mode=args.json_mode,
        reasoning_effort=args.reasoning_effort, max_tokens=args.max_tokens,
        request_timeout=args.request_timeout, request_total_timeout=args.request_total_timeout,
        retries=args.retries,
    )
    from .shared_cache import CachedLLMDatabase
    cache = shared_cache_dir(args, root)
    try:
        if getattr(args, 'labels_offline', False):
            from benchmark_tables.deepseek_client import DeepSeekClient, DeepSeekSettings
            # Retain endpoint/model/settings for exact-key lookup, without
            # requiring credentials or initializing a network service guard.
            client = DeepSeekClient(DeepSeekSettings(
                base_url=parsed.deepseek_url, model=parsed.deepseek_model, api_key=None,
                max_tokens=args.max_tokens, json_mode=args.json_mode,
                reasoning_effort=args.reasoning_effort, failure_policy='strict', **request_options),
                CachedLLMDatabase(database, cache) if cache else database)
            client.cache_only = True
            client.failure_dir = root / 'response-failures'
            return client
        client = pipeline.build_client(parsed, CachedLLMDatabase(database, cache) if cache else database,
                                       api_key=os.getenv("RADAR_API_KEY"))
        from dataclasses import replace
        client.settings = replace(client.settings, failure_policy=getattr(args, 'failure_policy', 'balanced'),
                                  **request_options)
        client.failure_dir = root / "response-failures"
        return client
    except ValueError as exc:
        raise ValueError(str(exc).replace("DEEPSEEK_API_KEY", "RADAR_API_KEY")) from exc


def shared_cache_dir(args, root):
    if getattr(args, "no_shared_cache", False):
        return None
    return Path(getattr(args, "cache_dir", None) or root.parent / ".recent-cache").resolve()


def parallel_stage(args, state, records, function, name, save):
    """Only main thread writes checkpoints; all completed successes survive a stop."""
    if not records:
        return
    fatal = None
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(function, row): row["paper"]["id"] for row in records}
        for count, future in enumerate(as_completed(futures), 1):
            identifier = futures[future]
            if future.cancelled():
                continue
            try:
                state[identifier] = future.result()
                state[identifier].pop("service_error_kind", None)
                if not state[identifier].get("error"):
                    state[identifier].pop("failure_details", None)
            except Exception as exc:
                row = dict(state[identifier])
                partial = getattr(exc, "partial_evidence", None)
                if (name == "analysis" and isinstance(partial, dict)
                        and partial.get("paper", {}).get("id") == identifier):
                    row = partial
                row.update(status="FAILED_" + name.upper(), error=str(exc)[:2000])
                from .failures import classify_failure, safe_failure_details
                details = safe_failure_details(getattr(exc, "failure_details", None))
                row["failure_details"] = details or classify_failure(name, str(exc))
                if details and details["kind"] in {"ARXIV_TRANSIENT", "ARXIV_GATE_BUSY"}:
                    row["status"] = "FAILED_HISTORY"
                    row["service_retry_at"] = details.get("retry_at")
                if partial is row and row.get("observations"):
                    row["status"] = "COMPLETE"
                from benchmark_tables.deepseek_client import LLMQuotaError
                if isinstance(exc, LLMQuotaError):
                    row["service_error_kind"] = "LLM_QUOTA"
                if name == "download" and isinstance(getattr(exc, "report", None), dict):
                    row["download"] = exc.report
                state[identifier] = row
                LOG.error("%s失败 %s: %s", name, identifier, exc)
                if isinstance(exc, LLMServiceStop):
                    fatal = exc
                    for pending in futures:
                        pending.cancel()
            # Record the policy actually used by this attempt, including failed
            # responses. A code upgrade on disk cannot date an old saved error.
            state[identifier]["last_attempt_code_version"] = CODE_VERSION
            state[identifier]["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
            state[identifier]["last_attempt_stage"] = name.upper()
            if name == "screen":
                state[identifier]["screening_attempt_version"] = RECENT_SCREENING_VERSION
            save()
            LOG.info("%s进度：%d/%d paper=%s status=%s", name, count, len(records), identifier, state[identifier]["status"])
    if fatal:
        raise fatal


def screen_one(args, root, row):
    if row["paper"].get("metadata_verification") == "UNVERIFIED":
        result = {"decision": "REVIEW", "reason": "外部候选摘要版本未核验，需v1元数据及全文确认",
                  "evidence_quote": "", "screening_version": RECENT_SCREENING_VERSION}
    else:
        with BenchmarkDatabase(root / "review_cache.sqlite") as db:
            result = screen_paper(make_client(args, root, db, purpose='screen'), row["paper"], high_recall=True, recent_benchmark_scope=True)
    history = list(row.get("screening_history", []))
    if row.get("screening"):
        history.append({"screening": row["screening"], "status": row["status"],
                        "replaced_at": datetime.now(timezone.utc).isoformat()})
    return {**row, "screening": result, "screening_history": history,
            "status": "EXCLUDED" if result["decision"] == "EXCLUDE" else "CANDIDATE", "error": ""}


def needs_screening(row, root=None):
    """Revisit old exclusions and empty reviews without discarding source results."""
    screening = row.get("screening")
    if not isinstance(screening, dict) or row.get("status") == "FAILED_SCREEN":
        return True
    if screening.get("decision") not in {"CANDIDATE", "REVIEW", "EXCLUDE"}:
        return True
    if screening["decision"] == "EXCLUDE":
        if (screening_semantic_version(screening.get('screening_version'))
                == screening_semantic_version(RECENT_SCREENING_VERSION)):
            return False
        # Existing-only used to be out of scope. Other current, supported
        # exclusions retain their meaning and do not spend another model call.
        if screening.get("exclusion_basis") == "EXISTING_EVALUATION_ONLY":
            return True
        from .screen_exclusion_support import EXCLUSION_SUPPORT_BASES
        if (screening.get('exclusion_basis') in EXCLUSION_SUPPORT_BASES
                and screening.get('screening_version') != RECALL_SCREENING_VERSION):
            return True
        return screening_semantic_version(screening.get("screening_version")) != screening_semantic_version(SCREENING_VERSION)
    from .screen_contract_recovery import affected_saved_screen
    obsolete_empty_review = affected_saved_screen(row) or (screening["decision"] == "REVIEW"
                             and isinstance(screening.get("screening_version"), str)
                             and screening["screening_version"].startswith("new-benchmark-screen-")
                             and screening_semantic_version(screening["screening_version"]) != screening_semantic_version(SCREENING_VERSION)
                             and row.get("status") not in {"COMPLETE", "EXCLUDED", "EXCLUDED_FULLTEXT"}
                             and not row.get("benchmarks") and not row.get("observations"))
    if obsolete_empty_review and root is not None:
        # A process can stop after atomically saving source evidence but before
        # state.json is updated. A manual resume must protect that evidence too.
        identifier = (row.get("paper") or {}).get("paper_id")
        if (not isinstance(identifier, str) or not identifier or identifier in {".", ".."}
                or any(char in identifier for char in ("/", "\\", ":"))):
            return False
        try:
            saved = json.loads((Path(root) / "evidence" / (identifier + ".json")).read_text(encoding="utf-8"))
            if (not isinstance(saved, dict)
                    or any(saved.get(name) is not None and saved.get(name) != []
                           for name in ("benchmarks", "observations"))):
                return False
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            return False  # Unreadable evidence cannot establish an empty result.
    return obsolete_empty_review


def needs_fulltext_recheck(row, args):
    from .text_evidence import RECENT_GATE_VERSION
    from .table_evidence import table_only
    return (row.get("status") == "EXCLUDED_FULLTEXT"
            and (table_only(args) or args.retry_review or args.no_text_preflight
                 or row.get("text_preflight", {}).get("exclusion_basis") == "EXISTING_EVALUATION_ONLY"
                 or row.get("text_preflight", {}).get("gate_version") != RECENT_GATE_VERSION))


def needs_benchmark_evidence_recheck(row):
    """Old empty full-text evidence cannot substantiate a scientific exclusion."""
    return (row.get("status") == "EXCLUDED"
            and (row.get("screening") or {}).get("decision") in {"CANDIDATE", "REVIEW"}
            and "benchmarks" in row and row["benchmarks"] == [])


def needs_benchmark_date_recheck(row, args, manifest):
    """Reopen only preserved, verified dates newly covered by the new window.

    This schedules qualification work; it never publishes scores or invents a
    release date. Unknown dates and unresolved source identities stay closed.
    """
    if row.get("status") != "EXCLUDED":
        return False
    if not isinstance(row.get("benchmarks"), list):
        return False
    publication = (row.get("paper") or {}).get("publication_date")
    candidates = [{**b, "paper_first_published": b.get("paper_first_published")
                   or publication}
                  for b in row.get("benchmarks", []) if isinstance(b, dict)
                  and b.get("eligibility") == "EXCLUDED_DATE"
                  and not (b.get("date_basis") == "PAPER_V1_PROXY"
                           and (b.get("release_date") != publication
                                or b.get("paper_first_published") not in {None, "", publication}))]
    if not candidates:
        return False
    from .novelty import reassess_date_window
    try:
        start, end = qualification_window(args, manifest)
        reviewed = reassess_date_window(candidates, start, end, recent_benchmark_scope=True)
    except (ValueError, TypeError, KeyError):
        return False
    return any(b.get("eligibility") in {"ELIGIBLE", "PENDING_HISTORY"} for b in reviewed)


def download_one(root, args, row):
    from .shared_cache import restore_pdf, store_pdf, _pdf_details, verified_pdf_receipt
    from .pdf_download import download_pdf, DownloadError
    paper = row["paper"]
    # Once a run has selected HTML, keep that source across retries. Switching
    # back to PDF would attach existing cell coordinates to a different source.
    html_report = root / "downloads" / (paper["paper_id"] + "-html.json")
    if row.get("source_kind") == "arxiv_html":
        return download_html_one(root, args, row, row.get("download", {}))
    if not getattr(args, "no_html_fallback", False) and html_report.exists():
        from .html_download import verified_html_receipt
        try:
            proof = json.loads(html_report.read_text(encoding="utf-8"))
            raw = root / "html" / paper["paper_id"] / "source.html"
            if verified_html_receipt(paper, raw, proof):
                return download_html_one(root, args, row, row.get("download", {}))
        except (OSError, ValueError):
            pass
    path = root / "pdf" / (paper["paper_id"] + ".pdf")
    path.parent.mkdir(exist_ok=True)
    cache = shared_cache_dir(args, root)
    report_path = root / "downloads" / (paper["paper_id"] + ".json")
    try:
        receipt = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        receipt = None
    local_valid = verified_pdf_receipt(paper, _pdf_details(path), receipt)
    if not local_valid and cache and restore_pdf(cache, paper, path, require_verified=True, receipt_target=report_path):
        LOG.info("PDF公共缓存命中：paper=%s", paper["id"])
        receipt = json.loads(report_path.read_text(encoding="utf-8"))
        return {**row, "source_kind": "pdf", "pdf_path": str(path), "status": "DOWNLOADED", "error": "", "pdf_cache_hit": True, "download": receipt}
    if not local_valid:
        if path.exists():
            LOG.warning("PDF不完整或缺少可核对的v1下载回执，重新获取：paper=%s", paper["id"])
        control = Path(getattr(args, "cache_dir", None) or root.parent / ".recent-cache") / "download-control"
        try:
            receipt = download_pdf(paper, path, timeout=args.download_timeout,
                total_timeout=args.download_total_timeout, retries=args.download_retries,
                max_bytes=int(args.download_max_mb * 1024 * 1024), transport=args.download_transport, control_dir=control)
        except DownloadError as exc:
            atomic_json(report_path, exc.report)
            if not getattr(args, "no_html_fallback", False) and html_fallback_allowed(exc.report):
                LOG.info("PDF获取失败，尝试同篇v1 HTML：paper=%s reason=%s", paper["id"], exc.report.get("error_code", "DOWNLOAD_FAILED"))
                return download_html_one(root, args, row, exc.report)
            raise
        if not verified_pdf_receipt(paper, _pdf_details(path), receipt):
            raise ValueError("下载后PDF完整性或来源回执校验失败，不进入解析")
        atomic_json(report_path, receipt)
    if cache:
        try:
            store_pdf(cache, paper, path, receipt=receipt)
        except (OSError, ValueError) as exc:
            LOG.warning("PDF未写公共缓存，继续本地解析：paper=%s %s", paper["id"], type(exc).__name__)
    return {**row, "source_kind": "pdf", "pdf_path": str(path), "status": "DOWNLOADED", "error": "", "pdf_cache_hit": False, "download": receipt}


def html_fallback_allowed(report):
    """Use another public representation only after ordinary retrieval failures."""
    # Honor access denials and outstanding server cooldowns instead of probing
    # another route immediately. A later queue attempt can retry normally.
    statuses = {report.get("http_status")}
    for key in ("attempt_log", "attempts"):
        entries = report.get(key, [])
        if isinstance(entries, list):
            statuses.update(item.get("http_status") for item in entries if isinstance(item, dict))
    code = str(report.get("error_code", ""))
    return (not statuses.intersection({401, 403, 429})
            and code not in {"HTTP_401", "HTTP_403", "HTTP_429", "RATE_LIMIT_BUDGET", "INVALID_IDENTITY", "INVALID_URL"}
            and not report.get("retry_after_seconds"))


def download_html_one(root, args, row, pdf_report):
    from .html_download import download_html, verified_html_receipt
    from .html_source import prepare_html_source, load_html_document
    from .pdf_download import DownloadError
    paper = row["paper"]
    folder = root / "html" / paper["paper_id"]
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "source.html"
    report_path = root / "downloads" / (paper["paper_id"] + "-html.json")
    # Prefer the immutable artifact on normal resume, including a moved run.
    if row.get("source_kind") == "arxiv_html":
        try:
            from .source_refs import resolve_source_path
            metadata = row["html_source"]
            document = resolve_source_path(root, row["document_path"], metadata["document_sha256"])
            if document is None:
                raise ValueError("HTML来源不在当前运行目录或哈希不符")
            # Never follow a former machine's absolute paths, even if that
            # checkout is still present locally after copying the run.
            local_metadata = {**metadata, "raw_path": str(document.parent / metadata["raw_filename"]),
                              "manifest_path": str(document.with_name(document.name.removesuffix("_content_list.json") + ".manifest.json"))}
            cached = {**row, "document_path": str(document), "html_source": local_metadata,
                      "markdown_path": str(document.with_name(document.name.removesuffix("_content_list.json") + ".md"))}
            load_html_document(cached)
            if verified_html_receipt(paper, Path(cached["html_source"]["raw_path"]), cached.get("html_download")):
                LOG.info("HTML已验证来源复用：paper=%s", paper["id"])
                return {**cached, "status": "DOWNLOADED", "error": "", "html_cache_hit": True}
        except (OSError, ValueError, KeyError):
            pass
    try:
        proof = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        proof = None
    reused = verified_html_receipt(paper, raw, proof)
    try:
        if not reused:
            control = Path(getattr(args, "cache_dir", None) or root.parent / ".recent-cache") / "download-control"
            proof = download_html(paper, raw, timeout=args.download_timeout,
                total_timeout=args.download_total_timeout, retries=args.download_retries,
                max_bytes=min(int(args.download_max_mb * 1024 * 1024), 20 * 1024 * 1024),
                transport=args.download_transport, control_dir=control)
            atomic_json(report_path, proof)
        if not verified_html_receipt(paper, raw, proof):
            raise ValueError("HTML下载来源或内容校验失败")
        if getattr(args, "pipeline_stage", None) == "DOWNLOAD":
            # Native HTML geometry belongs to the parser lane, just as PDF
            # geometry belongs to MinerU. The downloader publishes only bytes
            # and the pinned v1 transport receipt.
            result = {**row, "source_kind": "arxiv_html", "html_download": proof,
                      "download": pdf_report, "html_cache_hit": reused,
                      "status": "DOWNLOADED", "error": ""}
            for key in ("pdf_path", "document_path", "html_source", "markdown_path"):
                result.pop(key, None)
            return result
        prepared = prepare_html_source(paper, raw, folder, proof)
        result = {**row, **prepared, "html_download": proof, "download": pdf_report,
                  "html_cache_hit": reused, "status": "DOWNLOADED", "error": ""}
        result.pop("pdf_path", None)
        load_html_document(result)
        LOG.info("HTML来源就绪：paper=%s 待复核问题=%d，跳过MinerU", paper["id"], len(result.get("source_issues", [])))
        return result
    except (DownloadError, ValueError, OSError) as exc:
        html_report = getattr(exc, "report", None) or {"status": "FAILED", "error_code": "HTML_SOURCE_INVALID", "error": str(exc)[:1000]}
        atomic_json(report_path, html_report)
        combined = {"status": "FAILED", "error_code": html_report.get("error_code", "HTML_DOWNLOAD_FAILED"),
                    "pdf": pdf_report, "html": html_report}
        if html_report.get("retry_after_seconds"):
            combined["retry_after_seconds"] = html_report["retry_after_seconds"]
        raise DownloadError("PDF不可用，HTML回退也未取得可核验全文：" + str(exc)[:1000], combined) from exc


def text_preflight_one(args, root, row):
    from .table_evidence import table_only
    if table_only(args):
        return row
    from .html_pdf_fallback import needs_html_pdf_fallback
    if needs_html_pdf_fallback(row):
        return row
    if row.get("source_kind") == "arxiv_html":
        # HTML is already native text. The full evidence review below handles
        # it; the PDF-only shortcut cannot prove a converted HTML is complete.
        return row
    from .text_evidence import extract_native_text, review_text, RECENT_GATE_VERSION
    screening = row.get("screening", {})
    if getattr(args, "no_text_preflight", False) or (screening.get("decision") != "REVIEW"
                                                   and not screening.get("requires_evidence_followup")):
        return row
    # Existing partial table data must never be revoked by the cheaper gate.
    previous_path = root / "evidence" / (row["paper"]["paper_id"] + ".json")
    if previous_path.exists():
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        if previous.get("status") != "EXCLUDED_FULLTEXT" or previous.get("observations"):
            return row
    native = extract_native_text(Path(row["pdf_path"]), cache_dir=shared_cache_dir(args, root))
    native_path = root / "text-evidence" / (row["paper"]["paper_id"] + ".json")
    atomic_json(native_path, native)
    detail = {k: v for k, v in native.items() if k not in {"text", "page_texts"}}
    detail["source_path"] = str(native_path)
    detail["gate_version"] = RECENT_GATE_VERSION
    if native.get("status") != "READY":
        return {**row, "text_preflight": {**detail, "decision": "CONTINUE"}}
    try:
        with BenchmarkDatabase(root / "review_cache.sqlite") as db:
            decision = review_text(make_client(args, root, db), row["paper"], native, recent_benchmark_scope=True)
    except LLMServiceStop:
        raise
    except (ValueError, RuntimeError) as exc:
        decision = {"decision": "CONTINUE", "reason": "轻量补证失败，保留MinerU回退", "error": str(exc)[:1000]}
    LOG.info("全文轻量补证：paper=%s decision=%s reason=%s", row["paper"]["id"], decision["decision"], decision["reason"])
    result = {**row, "text_preflight": {**detail, **decision}}
    if decision["decision"] == "EXCLUDE":
        result.update(status="EXCLUDED_FULLTEXT", error="", observations=[], benchmarks=[])
        atomic_json(root / "evidence" / (row["paper"]["paper_id"] + ".json"), result)
    return result


def mineru_args(args, root):
    # The parser helper needs only these settings. Calling the old workflow CLI
    # would also load unrelated endpoint, credential and historical-path defaults.
    return argparse.Namespace(
        work_dir=root / "work", mineru_output=root / "mineru",
        mineru_bin=args.mineru_bin, mineru_backend=args.mineru_backend,
        mineru_workers=args.mineru_workers, mineru_devices=args.mineru_devices,
        mineru_timeout=args.mineru_timeout, mineru_batch_size=1,
        mineru_method=getattr(args, "source_recovery_method", "auto"), mineru_language="en", mineru_attempts=3,
        mineru_heartbeat_seconds=60.0,
    )


def mineru_cache_identity(args):
    if not getattr(args, "mineru_cache_tag", ""):
        return None
    try:
        version = importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        LOG.warning("无法核验当前MinerU安装版本，禁用公共解析缓存")
        return None
    binary = shutil.which(args.mineru_bin)
    if not binary:
        return None
    from benchmark_tables.hashing import sha256_file
    try:
        binary_hash = sha256_file(Path(binary))
    except OSError:
        return None
    return {"mineru_version": version, "backend": args.mineru_backend, "binary_sha256": binary_hash,
             "configuration_and_weights_tag": args.mineru_cache_tag, "adapter_version": "recent-mineru-v1",
             "method": getattr(args, "source_recovery_method", "auto")}


def parse_downloaded(args, root, downloaded):
    from .parser_cache import restore_mineru, store_mineru
    cache = shared_cache_dir(args, root)
    if cache:
        cache = cache / "mineru"
    identity = mineru_cache_identity(args) if cache else None
    successful, pending = set(), []
    for row in downloaded:
        if row.get("source_kind") == "arxiv_html":
            from .html_source import load_html_document
            from .html_pdf_fallback import needs_html_pdf_fallback, recover_html_as_pdf, HtmlPdfFallbackError
            try:
                document = load_html_document(row)
                if needs_html_pdf_fallback(row, document):
                    replacement = recover_html_as_pdf(args, root, row, document)
                    row.clear()
                    row.update(replacement)
                successful.add(row["paper"]["paper_id"].casefold())
            except HtmlPdfFallbackError as exc:
                row.update(source_error=str(exc), source_failure_code=exc.code,
                           failure_details=exc.failure_details)
                LOG.warning("HTML整篇来源未恢复：paper=%s 原因=%s；停止重复模型分析", row["paper"]["id"], exc.code)
            except (OSError, ValueError) as exc:
                if (getattr(exc, 'failure_details', {}) or {}).get('kind') in {
                        'MINERU_DEVICE_BUSY', 'ARXIV_GATE_BUSY', 'ARXIV_TRANSIENT'}:
                    raise
                row["source_error"] = str(exc)[:1000]
                LOG.error("HTML来源校验失败，隔离当前论文：paper=%s %s", row["paper"]["id"], exc)
            continue
        source = Path(row["pdf_path"])
        if cache and identity and restore_mineru(cache, source, root / "mineru", identity):
            LOG.info("MinerU公共缓存命中：paper=%s", row["paper"]["id"])
            successful.add(source.stem.casefold())
        else:
            pending.append(row)
    if pending:
        # Only papers still needing table parsing are visible to directory scans.
        with tempfile.TemporaryDirectory(prefix="mineru-input-", dir=root) as folder:
            for row in pending:
                source = Path(row["pdf_path"])
                shutil.copy2(source, Path(folder) / source.name)
            from .mineru_device_gate import mineru_device_lease
            controls = (Path(args.cache_dir) if getattr(args, 'cache_dir', None)
                        else shared_cache_dir(args, root) or root.parent / ".recent-cache") / "mineru-device-gates"
            # A source-recovery OCR call from the analysis lane shares the same
            # physical GPU lease as the main parser lane. Remote model waits
            # happen outside this lease and cannot idle the device.
            device_wait = getattr(args, 'mineru_device_wait_timeout', 60)
            LOG.info('MinerU设备获取：papers=%s devices=%s 等待上限=%.1f秒 OCR上限=%.1f秒',
                     ','.join(row['paper']['id'] for row in pending), args.mineru_devices or 'cpu',
                     device_wait, args.mineru_timeout)
            with mineru_device_lease(controls, args.mineru_devices, timeout=device_wait):
                LOG.info('MinerU设备已获取：papers=%s devices=%s',
                         ','.join(row['paper']['id'] for row in pending), args.mineru_devices or 'cpu')
                successful.update(workflow.run_mineru(mineru_args(args, root), Path(folder)))
        if cache and identity:
            for row in pending:
                source = Path(row["pdf_path"])
                if source.stem.casefold() in successful:
                    # Require the same reader used for analysis to accept the
                    # artifact before publishing it to another day's run.
                    try:
                        if workflow._stream_find_document(root / "mineru", source) is not None:
                            store_mineru(cache, source, root / "mineru", identity)
                    except (ValueError, OSError) as exc:
                        LOG.warning("未共享该MinerU产物：paper=%s %s", row["paper"]["id"], type(exc).__name__)
    return successful


def history_report(args, root, paper, bench):
    """Only reuse complete, recent results for exactly this history query."""
    # A paper can use the short primary name earlier than its expanded alias.
    # Searching only multiword aliases would silently omit that history.
    names = [bench.get("name", ""), *bench.get("aliases", [])]
    names = [name for name in names if isinstance(name, str) and name.strip()]
    names = sorted({" ".join(name.split()) for name in names}, key=str.casefold)
    cutoff = utc(paper["publication_date"]).isoformat()
    identity = {"policy": HISTORY_POLICY_VERSION, "names": names, "before": cutoff,
                "primary_name": bench.get("name")}
    path = root / "history" / (bench["benchmark_id"] + ".json")
    try:
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        report = None
    now = datetime.now(timezone.utc)
    recent = False
    if isinstance(report, dict):
        try:
            age = (now - utc(report.get("cached_at", ""))).total_seconds()
            recent = 0 <= age < 86400
        except (TypeError, ValueError):
            pass
    reusable = (isinstance(report, dict) and report.get("cache_identity") == identity
                and report.get("status") == "complete" and report.get("complete") is True
                and not report.get("truncated") and isinstance(report.get("papers"), list) and recent)
    if reusable and not getattr(args, "refresh_history", False):
        return report
    try:
        with HISTORY_LOCK:
            try:
                report = find_prior_mentions(names, utc(cutoff),
                                             gate_path=getattr(args, "arxiv_gate_db", None),
                                             primary_name=bench.get("name"))
            finally:
                if not getattr(args, "arxiv_gate_db", None):
                    time.sleep(3.1)
    except DiscoveryError as exc:
        report = exc.report
    report = {**report, "cache_identity": identity, "cached_at": now.isoformat(),
              "query_policy_version": HISTORY_POLICY_VERSION}
    atomic_json(path, report)
    return report


def analyze_one(args, root, manifest, row):
    paper = row["paper"]
    if row.get("source_kind") == "arxiv_html":
        from .html_source import load_html_document
        document = load_html_document(row)
    else:
        document = workflow._stream_find_document(root / "mineru", Path(row["pdf_path"]))
    if document is None:
        return {**row, "status": "FAILED_MINERU", "error": "MinerU未生成可识别的来源文件"}
    from .html_pdf_fallback import needs_html_pdf_fallback, HtmlPdfFallbackError, source_failure_row
    if needs_html_pdf_fallback(row, document):
        return source_failure_row(row, HtmlPdfFallbackError('HTML_REPARSE_REQUIRED'))
    document = workflow._bind_stream_document(document, paper["paper_id"], paper["title"])
    recovered_sources, source_recovery = {}, []
    with BenchmarkDatabase(root / "benchmark_tables.sqlite") as db:
        client = make_client(args, root, db)
        # The downloaded document is pinned v1. Never mix an external/latest
        # abstract into the source used to authorize benchmark novelty.
        from .table_evidence import table_only, evidence_text, abstract_text, verified_abstract, TableEvidenceClient, POLICY_VERSION as TABLE_EVIDENCE_VERSION
        tables_only = table_only(args)
        if tables_only:
            from benchmark_tables.schema_repair_budget import SchemaRepairBudget
            client.schema_repair_budget = SchemaRepairBudget(limit=2)
        context_paper = paper if not tables_only or verified_abstract(paper) else {**paper, 'title': '', 'abstract_text': ''}
        text = evidence_text(paper, document.tables) if tables_only else document_text(document.source_path)
        if tables_only:
            client = TableEvidenceClient(client)
            LOG.info('摘要后直接分析表格：paper=%s 表格=%d；跳过正文判断', paper['id'], len(document.tables))
        if not text.strip():
            return {**row, "status": "FAILED_SOURCE", "error": "来源正文为空，无法核验benchmark资格"}
        from .source_refs import source_reference
        from .novelty import POLICY_VERSION, IDENTITY_POLICY_VERSION, reassess_date_window
        from .scope import model_scope_version, table_scope_version, table_payload
        from .reported_model_policy import POLICY_VERSION as MODEL_ADMISSION_VERSION, BINDING_PROMPT_VERSION, candidate_observations
        from .review_cache import review_configuration
        from .stage_checkpoints import StageCheckpoints, qualification_gaps
        from .benchmark_identity_resolution import reconcile_benchmark_identities, IDENTITY_RESOLUTION_VERSION
        from .observation_values import has_numeric_result
        reference = source_reference(root, document.source_path)
        qualification_start, qualification_end = qualification_window(args, manifest)
        evidence_path = root / 'evidence' / (paper['paper_id'] + '.json')
        previous = json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.exists() else {}
        from .qualification_retention import saved_qualifications, retain_qualifications
        saved_benches = saved_qualifications(root, previous, paper, reference,
            qualification_start, qualification_end, analysis_source='tables' if tables_only else 'fulltext')
        stages = StageCheckpoints(root, {
            "paper": {key: paper.get(key) for key in ("id", "paper_id", "title", "publication_date", "metadata_verification", "source_metadata")},
            "source": reference, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "window": {key: manifest[key] for key in ("start", "end")},
            "analysis_policy": ANALYSIS_POLICY_VERSION,
            "analysis_source": TABLE_EVIDENCE_VERSION if tables_only else 'fulltext',
            "novelty_policy": POLICY_VERSION, "identity_policy": IDENTITY_POLICY_VERSION,
            # Response budgets and JSON transport format cannot invalidate a
            # source-validated success. Failed model calls keep their own exact
            # response keys, so changed budgets still apply to missing work.
            "model_configuration": {key: value for key, value in review_configuration(args).items()
                                    if key not in {"max_tokens", "json_mode"}},
        }, force=getattr(args, "force_review", False))
        identity_failure = None

        def resolve_identity(values):
            nonlocal identity_failure
            identity_input = {"benchmarks": values, "policy": IDENTITY_RESOLUTION_VERSION}
            reconciled = stages.load("benchmark_identity", identity_input)
            if reconciled is None:
                try:
                    from .benchmark_decision_cache import CachedIdentityClient
                    component_failures = []
                    def keep_component_failure(exc, source_ids):
                        stop_on_service_failure(exc)
                        component_failures.append(str(exc)[:1200])
                        LOG.warning("benchmark身份分组补证失败：来源=%s；保留独立分组结果：%s", source_ids, str(exc)[:1200])
                    reconciled = reconcile_benchmark_identities(
                        CachedIdentityClient(client,args,root,text), context_paper, text, values,
                        on_component_error=keep_component_failure)
                    if component_failures:
                        identity_failure = "；".join(component_failures)[:1500]
                    else:
                        stages.save("benchmark_identity", identity_input, reconciled)
                except LLMServiceStop:
                    raise
                except (RuntimeError, ValueError) as exc:
                    stop_on_service_failure(exc)
                    identity_failure = str(exc)[:1500]
                    LOG.warning("benchmark身份补证失败，保留其他已确认资格：%s", identity_failure)
            return reconciled if reconciled is not None else values

        def review_merged_identity(values):
            from .source_claim_aggregation import aggregate_source_claims
            # This is the pinned paper metadata, not the publication time of a
            # different document mentioning the same benchmark. Only a source
            # NEW claim may use it as a first-disclosure proxy below.
            rebound = []
            for bench in values:
                bench = dict(bench)
                publication = paper.get("publication_date")
                if bench.get("date_basis") == "PAPER_V1_PROXY":
                    # A cache's own date field cannot attest its original paper.
                    # Rebind metadata only; preserve the claimed release date so
                    # a foreign proxy remains a visible mismatch, not a repair.
                    foreign = (bench.get("paper_first_published") not in {None, "", publication}
                               or bench.get("release_date") != publication)
                    bench["paper_first_published"] = publication
                    if foreign:
                        bench.update(eligibility="REVIEW", date_source_mismatch=True,
                                     reason="DATE_SOURCE_MISMATCH：论文代理发布日期与当前来源论文不一致")
                elif not bench.get("paper_first_published"):
                    bench["paper_first_published"] = publication
                rebound.append(bench)
            values = rebound
            values = [(aggregate_source_claims(b, paper, text, qualification_start, qualification_end) or b)
                      if b.get("date_source_mismatch") is not True else b
                      for b in values]
            if not any(b.get("eligibility") == "REVIEW" for b in values):
                return values
            from .novelty import review_merged_benchmark_evidence
            joint_input = {"benchmarks": values, "policy": POLICY_VERSION, "strategy": "joint-bounded-v2",
                           "qualification_scope": RECENT_SCOPE_VERSION}
            reviewed = stages.load("merged_joint", joint_input)
            if reviewed is None:
                reviewed = review_merged_benchmark_evidence(client, context_paper, text, values,
                                                            qualification_start, qualification_end,
                                                            recent_benchmark_scope=True)
                stages.save("merged_joint", joint_input, reviewed)
            return reviewed

        novelty_input = {"qualification_scope": RECENT_SCOPE_VERSION}
        benches = stages.load("novelty", novelty_input)
        qualification_reused = (not getattr(args, 'force_review', False)
                                and not getattr(args, 'refresh_history', False) and saved_benches
                                and len(saved_benches) == len(previous.get('benchmarks', [])))
        if qualification_reused:
            benches = saved_benches
            LOG.info('复用已核验benchmark资格：paper=%s 数量=%d；同源同规则，日期窗口重新检查', paper['id'], len(benches))
        if benches is None:
            old_benches = stages.load("novelty", {})
            # A saved positive NEW claim is still relevant. An old empty list
            # or existing-only scan cannot establish coverage of this scope.
            if (isinstance(old_benches, list) and old_benches
                    and all(isinstance(b, dict) and b.get("novelty") == "NEW"
                            and b.get("tests_llms") is True for b in old_benches)):
                benches = old_benches
                stages.save("novelty", novelty_input, benches)
        novelty_reused = benches is not None
        if benches is None:
            benches = review_novelty(client, context_paper, text, qualification_start, qualification_end,
                                     source_claims=True, recent_benchmark_scope=True)
            stages.save("novelty", novelty_input, benches)
        benches = retain_qualifications(benches, saved_benches)
        # Resolve cached aliases before deciding a new novelty pass is needed.
        if not qualification_reused:
            benches = resolve_identity(benches)
            benches = review_merged_identity(benches)
        # Date-register corrections also apply to reused source qualifications.
        benches = reassess_date_window(benches, qualification_start, qualification_end, recent_benchmark_scope=True)
        if not tables_only and benches and any(b.get("eligibility") == "REVIEW" for b in benches):
            # One focused evidence pass uses a different exact-input key. Later
            # attempts reuse it rather than replaying the same full-text calls.
            focus = qualification_gaps(benches)
            focus_input = {"qualification_scope": RECENT_SCOPE_VERSION, "focus": focus}
            refined = stages.load("novelty_followup", focus_input)
            if refined is None:
                refined = stages.load_covering_followup(focus_input)
                if refined is not None:
                    LOG.info('复用已完成全文补证：paper=%s 剩余缺口=%d；同源同规则且已覆盖，不重复调用', paper['id'], len(focus))
            if refined is None:
                refined = review_novelty(client, paper, text, qualification_start,
                                         qualification_end, followup=focus, source_claims=True,
                                         recent_benchmark_scope=True)
                stages.save("novelty_followup", focus_input, refined)
            # A follow-up can add evidence, but cannot silently discard earlier
            # explicit contradictions or confirmed benchmark identities.
            from .novelty import combine_novelty_reviews
            benches = combine_novelty_reviews(benches, refined)
            benches = resolve_identity(benches)
            benches = review_merged_identity(benches)
            benches = reassess_date_window(benches, qualification_start, qualification_end, recent_benchmark_scope=True)
        no_benchmark_verdict = None
        if not benches and not tables_only:
            from .novelty import review_no_benchmark
            no_benchmark_verdict = stages.load("no_benchmark_verdict", novelty_input)
            if no_benchmark_verdict is None:
                try:
                    no_benchmark_verdict = review_no_benchmark(client, paper, text, recent_benchmark_scope=True)
                    stages.save("no_benchmark_verdict", novelty_input, no_benchmark_verdict)
                except LLMServiceStop:
                    raise
                except (RuntimeError, ValueError) as exc:
                    stop_on_service_failure(exc)
                    no_benchmark_verdict = {"decision": "REVIEW", "reason": "全文范围补证失败：" + str(exc)[:1000]}
        history_failures = []
        for i, bench in enumerate(benches):
            if bench["eligibility"] != "PENDING_HISTORY":
                continue
            from .source_release_policy import admit_source_release, cached_history
            local_history = cached_history(root, paper, bench)
            admitted = admit_source_release(bench, paper, text, qualification_start, qualification_end,
                history=local_history, aggregate_claims=True)
            if admitted is not None and not getattr(args, 'refresh_history', False):
                benches[i] = admitted
                LOG.info('benchmark首次发布日期来源核验通过：%s benchmark=%s；历史检索不阻塞成绩提取，核验范围已标注', paper['id'], bench['name'])
                continue
            if isinstance(local_history, dict) and (local_history.get('papers') or
                    local_history.get('identity_status') == 'POTENTIAL_PRIOR_MENTION'):
                # An expired cache does not erase previously discovered counterevidence.
                benches[i] = {**bench, 'history': local_history, 'eligibility': 'REVIEW',
                    'reason': '发现更早同名文献，需区分既有benchmark与名称碰撞'}
                continue
            report = history_report(args, root, paper, bench)
            if report.get("service_failure") is True or report.get("scheduler_deferred") is True:
                # Keep the source novelty/date decision pending. An unavailable
                # API does not prove an older benchmark exists or exhaust the
                # bounded budget for scientific evidence.
                benches[i] = {**bench, "history": report,
                              "reason": ("arXiv请求名额正在使用，历史检索稍后继续" if report.get("scheduler_deferred") is True
                                         else "arXiv历史检索暂不可用，等待共享冷却后重试")}
                history_failures.append(report)
            else:
                benches[i] = apply_history(bench, report)
        if paper.get("metadata_verification") == "UNVERIFIED":
            for bench in benches:
                if bench.get("eligibility") in {"ELIGIBLE", "PENDING_HISTORY"}:
                    bench.update(eligibility="REVIEW", reason="外部候选v1元数据/首次提交日期未核验；使用 --refresh-candidates 获取v1元数据")
        benches = retain_qualifications(benches, saved_benches)
        # Save the eligibility ledger before any model extraction call.
        evidence_path = root / "evidence" / (paper["paper_id"] + ".json")
        previous = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
        if evidence_path.exists():
            content = evidence_path.read_bytes()
            archive = root / "evidence-history" / paper["paper_id"] / (hashlib.sha256(content).hexdigest() + ".json")
            if not archive.exists():
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(content)
            else:
                archive.touch()  # Repeated evidence retains its latest chronology.
        eligible_ids = {b["benchmark_id"] for b in benches if b["eligibility"] == "ELIGIBLE"}
        # Carry existing cells across the v5 name-ID -> v6 alias-ID upgrade only
        # when the complete same-paper identity set has one unambiguous match.
        from .novelty import normalized
        def aliases(bench):
            return frozenset(normalized(x) for x in [bench.get("name", ""), *bench.get("aliases", [])] if x)
        id_map = {}
        for old in previous.get("benchmarks", []):
            names = aliases(old)
            matching = [b for b in benches if (names and names == aliases(b))
                        or (b.get("identity_resolution", {}).get("relation") == "SAME"
                            and old.get("benchmark_id") in b["identity_resolution"].get("source_ids", []))]
            if len(matching) == 1:
                id_map[old["benchmark_id"]] = matching[0]["benchmark_id"]
        retained = [{**o, "benchmark_id": id_map.get(o.get("benchmark_id"), o.get("benchmark_id"))}
                    for o in previous.get("observations", [])
                    if (previous.get("analysis_policy_version") == ANALYSIS_POLICY_VERSION
                        and o.get("model_kind") == "BASE" and o.get("base_model_verified") is True
                        and has_numeric_result(o)
                        and id_map.get(o.get("benchmark_id"), o.get("benchmark_id")) in eligible_ids)]
        if previous.get("source_sha256") and previous["source_sha256"] != reference["source_sha256"]:
            retained = []
        # Audit notes do not change the source decision or invalidate healthy
        # table/binding checkpoints. Preserve them only in the public ledger.
        eligible = [{k: v for k, v in b.items()
                     if k not in {'qualification_retention_policy', 'qualification_recheck'}}
                    for b in benches if b["eligibility"] == "ELIGIBLE"]
        if eligible:
            from .source_recovery import recover_source
            original_table_ids = {t.table_id for t in document.tables}
            document, recovered_sources, source_recovery = recover_source(args, root, row, document)
            superseded_table_ids = original_table_ids - {t.table_id for t in document.tables}
            # A replacement representation cannot be counted alongside the
            # damaged old table. Preserve unrelated healthy source results.
            retained = [o for o in retained if o.get("table_id") not in superseded_table_ids]
        if eligible and document.tables:
            try:
                # Verify source compatibility in the extraction DB before
                # publishing current-policy provenance alongside retained cells.
                pipeline.ingest_document(document, db)
            except (RuntimeError, ValueError) as exc:
                failed = {**row, **reference, "benchmarks": benches, "observations": [],
                          "analysis_policy_version": None, "status": "FAILED_SOURCE", "error": str(exc),
                          "scope_reviews": [{"reason": "来源入库校验失败；旧台账已归档，禁止将旧成绩绑定到新来源"}]}
                atomic_json(evidence_path, failed)
                from .failures import classify_failure
                exc.failure_details = classify_failure('SOURCE', str(exc))
                raise
        # Only current source-coordinate/DB matches can survive an abstention
        # on a repeat. Previously published counts alone are not proof.
        from .live_progress import checked_result
        from .accepted_scores import merge_table_rows
        if retained:
            checked = checked_result(root, {'paper_id': paper['paper_id'],
                'arxiv_id': paper.get('arxiv_id', paper['id'])},
                candidate_ledger={**previous, **reference, 'paper': paper,
                                  'benchmarks': benches, 'observations': retained})
            retained = checked['observations'] if checked else []
        ledger = {**row, "benchmarks": benches, **reference, "status": "REVIEW", "error": "",
                  "analysis_policy_version": ANALYSIS_POLICY_VERSION,
                  "qualification_window": {"start": qualification_start.isoformat(), "end": qualification_end.isoformat()},
                  "identity_policy_version": IDENTITY_POLICY_VERSION, "observations": retained}
        # This is a new analysis verdict; transport errors from earlier stages
        # must not leak into early qualification/no-table returns.
        for stale_key in ('failure_details', 'service_error_kind', 'service_retry_at'):
            ledger.pop(stale_key, None)
        ledger['live_reservation_id'] = getattr(args, 'live_reservation_id', None)
        ledger['analysis_source'] = 'tables' if tables_only else 'fulltext'
        ledger['model_admission_policy_version'] = MODEL_ADMISSION_VERSION
        ledger['table_scope_policy_version'] = table_scope_version(eligible, recent_benchmark_scope=True)
        ledger['completion'] = {'extraction_complete': False,
            'total_tables': len(document.tables), 'processed_tables': 0,
            'pending_table_ids': [t.table_id for t in document.tables],
            'accepted_observations': len(retained)}
        source_reviews = [{"reason": "HTML来源需复核", "source_issue": issue}
                          for issue in blocking_source_issues(row.get("source_issues", []))]
        raw_source_issues = row.get("source_issues", [])
        local_table_indices = {issue["table_index"] for issue in raw_source_issues
                               if isinstance(issue, dict) and not blocking_source_issues([issue])} if isinstance(raw_source_issues, list) else set()
        all_source_reviews = [{"reason": "HTML来源需复核", "source_issue": issue,
                               **({"table_id": "html-source-table-" + str(issue["table_index"])}
                                  if isinstance(issue, dict) and not blocking_source_issues([issue]) else {})}
                              for issue in raw_source_issues] if isinstance(raw_source_issues, list) else list(source_reviews)
        ledger["scope_reviews"] = all_source_reviews
        ledger["qualification_gaps"] = qualification_gaps(benches)
        ledger["qualification_gaps"].extend({"benchmark_id": b.get("benchmark_id"),
            "code": "DATE_SOURCE_MISMATCH", "stage": "novelty",
            "reason": "缓存论文代理日期与当前来源论文不一致；不能采用其他论文时间"}
            for b in benches if b.get("date_source_mismatch") is True)
        if identity_failure:
            ledger["qualification_gaps"].append({"code": "BENCHMARK_IDENTITY_RESPONSE",
                                                  "stage": "identity", "reason": identity_failure})
        ledger["resumed_stages"] = list(stages.reused)
        if no_benchmark_verdict is not None:
            ledger["fulltext_scope_verdict"] = no_benchmark_verdict
        atomic_json(root / "evidence" / (paper["paper_id"] + ".json"), ledger)
        history_interrupted = None
        if history_failures:
            from .failures import ArxivServiceBackoff
            # Reports use normalized UTC timestamps; select the longest pause.
            report = max(history_failures, key=lambda r: r.get("retry_at") or "")
            history_interrupted = ArxivServiceBackoff(report)
            ledger["failure_details"] = history_interrupted.failure_details
            ledger["service_retry_at"] = history_interrupted.failure_details.get("retry_at")
            if not eligible:
                ledger.update(status="FAILED_HISTORY", error=str(history_interrupted))
                atomic_json(evidence_path, ledger)
                history_interrupted.partial_evidence = ledger
                raise history_interrupted
        if not eligible:
            unresolved = [b for b in benches if b["eligibility"] == "REVIEW"]
            # A quarantined table can hide another evaluation contribution.
            # It may not block proved good scores, but prevents a whole-paper
            # negative conclusion from incomplete source coverage.
            explicitly_excluded = (not all_source_reviews and (
                bool(benches) and all(b["eligibility"].startswith("EXCLUDED_") for b in benches)
                or not benches and (no_benchmark_verdict or {}).get("decision") == "EXCLUDE"))
            ledger.update(status="EXCLUDED" if explicitly_excluded else "REVIEW",
                          error="; ".join(b.get("reason", "benchmark资格未确定") for b in unresolved)
                                if unresolved else "" if explicitly_excluded
                                else (no_benchmark_verdict or {}).get("reason")
                                or ("摘要及表格未找到可核验的benchmark证据" if tables_only else "全文未找到可核验的新benchmark证据，不能据此明确排除"))
            atomic_json(evidence_path, ledger)
            return ledger
        if not document.tables:
            ledger.update(status="REVIEW" if row.get("source_kind") == "arxiv_html" else "NO_TABLES", observations=[])
            atomic_json(evidence_path, ledger)
            return ledger
        bindings, scopes, scope_reviews, errors = list(retained), [], list(all_source_reviews), []
        completed_tables = set()
        progress_marker = None
        selection_client = None

        def publish_progress():
            nonlocal progress_marker
            if selection_client is not None:
                ledger['scope_dispatch'] = dict(selection_client.stats)
            ledger.update(observations=bindings, table_scopes=scopes, scope_reviews=scope_reviews,
                          table_errors=errors, source_recovery=source_recovery,
                          completion={'extraction_complete': False,
                              'accepted_observations': len(bindings),
                              'total_tables': len(document.tables) + len(local_table_indices),
                              'processed_tables': len(completed_tables),
                              'selected_tables': sum(s.get('decision') == 'SELECT' for s in scopes),
                              'pending_table_ids': sorted({t.table_id for t in document.tables}
                                  - completed_tables | {s['table_id'] for s in scopes if s.get('decision') == 'REVIEW'}
                                  | {e['table_id'] for e in errors}
                                  | {item['table_id'] for item in scope_reviews
                                     if item.get('table_id') and item.get('resolution') != 'EXCLUDED'}),
                              'unresolved_observations': sum(item.get('resolution') != 'EXCLUDED'
                                  for item in scope_reviews)})
            atomic_json(evidence_path, ledger)
            marker = (len(bindings), len(completed_tables))
            if marker != progress_marker:
                LOG.info('基础模型成绩进度：paper=%s 已核验成绩=%d 已处理表=%d/%d 待处理表=%d',
                         paper['id'], len(bindings), len(completed_tables), len(document.tables),
                         len(document.tables) - len(completed_tables))
                progress_marker = marker

        def finish_ledger(*, interrupted=None):
            if selection_client is not None:
                ledger['scope_dispatch'] = dict(selection_client.stats)
                LOG.info('筛表调度：paper=%s 批量=%d 单表=%d 独立补判=%d 来源缓存=%d；底层响应缓存可能免HTTP',
                         paper['id'], selection_client.stats['batch_requests'], selection_client.stats['single_requests'],
                         selection_client.stats['isolated_fallbacks'], selection_client.stats['decision_cache_hits'])
            outcome = asdict(pipeline.inspect_analysis(db, paper["paper_id"]))
            unresolved = [item for item in scope_reviews if item.get("resolution") != "EXCLUDED"]
            pending = {e["table_id"] for e in errors}
            pending.update(s["table_id"] for s in scopes if s.get("decision") == "REVIEW")
            pending.update(item["table_id"] for item in unresolved if item.get("table_id"))
            from benchmark_tables.analysis_outcomes import RETRYABLE_ISSUES, REVIEW_ISSUES
            open_issues = db.connection.execute(
                "SELECT table_id, issue_type FROM review_issues WHERE paper_id=? AND status='OPEN'",
                (paper["paper_id"],))
            selected_ids = {s["table_id"] for s in scopes if s.get("decision") == "SELECT"}
            for issue in open_issues:
                # Old planner/model issues on an explicitly excluded table do
                # not create an endless repair of an unrelated benchmark.
                if issue["table_id"] in selected_ids and issue["issue_type"] in (RETRYABLE_ISSUES | REVIEW_ISSUES):
                    pending.add(issue["table_id"])
            from .negative_admission import conclusive_negative
            # Complete, source-checked row admission supersedes stale model-only
            # review issues. Technical work and unfinished tables still block.
            pending.difference_update(tid for tid, receipt in admissions.items()
                if conclusive_negative(receipt) and tid in completed_tables
                and tid not in {e['table_id'] for e in errors}
                and tid not in {r.get('table_id') for r in unresolved})
            if interrupted:
                pending.update(t.table_id for t in document.tables if t.table_id not in {s["table_id"] for s in scopes})
                pending.add(active_table_id)
            pending.update(t.table_id for t in document.tables if t.table_id not in completed_tables)
            incomplete = bool(pending or unresolved or interrupted or history_interrupted
                              or all_source_reviews)
            valid = [o for o in bindings if o.get("benchmark_id") in eligible_ids
                     and o.get("model_kind") == "BASE" and o.get("base_model_verified") is True
                     and has_numeric_result(o)]
            from .extraction_settlement import table_settlements, retry_partial
            table_outcomes = table_settlements(
                [t.table_id for t in document.tables] + list(pending | {s['table_id'] for s in scopes}),
                scopes=scopes, observations=valid, errors=errors, reviews=unresolved,
                pending=pending, admissions=admissions)
            from .extraction_resolution import resolve_extraction
            status, diagnosis, gaps = resolve_extraction(valid=valid, errors=errors,
                interrupted=interrupted or history_interrupted,
                source_blocked=bool(source_reviews if valid else all_source_reviews),
                scopes=scopes, total_tables=len(document.tables) + len(local_table_indices),
                pending=pending, reviews=unresolved, outcome=outcome, table_outcomes=table_outcomes)
            error = str(interrupted or history_interrupted)[:1500] if (interrupted or history_interrupted) else "; ".join(e["error"] for e in errors)
            ledger.update(status=status, observations=bindings, table_scopes=scopes, scope_reviews=scope_reviews,
                          analysis=outcome, table_errors=errors, resumed_stages=list(stages.reused),
                          error=error, extraction_gaps=gaps, source_recovery=source_recovery,
                          completion={"extraction_complete": not incomplete and bool(valid),
                                      "accepted_observations": len(valid), "pending_table_ids": sorted(pending),
                                      "unresolved_observations": len(unresolved),
                                      "total_tables": len(document.tables) + len(local_table_indices),
                                      "processed_tables": len(completed_tables),
                                      "selected_tables": sum(s.get("decision") == "SELECT" for s in scopes),
                                      "analysis_status": outcome["status"]})
            if interrupted or history_interrupted:
                from .failures import classify_failure, safe_failure_details
                stopped = interrupted or history_interrupted
                ledger["failure_details"] = (safe_failure_details(getattr(stopped, "failure_details", None))
                                             or classify_failure("analysis", str(stopped)))
            elif diagnosis:
                ledger["failure_details"] = diagnosis
            else:
                ledger.pop("failure_details", None)
            ledger['table_outcomes'] = table_outcomes
            ledger['table_admissions'] = admissions
            ledger['resolution'] = {
                'status': 'FAILED' if status == 'REVIEW' else status,
                'reason_code': (gaps[0]['code'] if gaps else diagnosis['kind'] if diagnosis
                                else 'VERIFIED_BASE_SCORES' if valid else
                                'NO_APPLICABLE_MODEL_SCORES' if any(r.get('reason_code') == 'ALL_MODEL_ROWS_EXCLUDED' for r in table_outcomes)
                                else 'SOURCE_SCOPE_EXCLUDED'),
                'automatic_retry': retry_partial(diagnosis),
                'same_evidence_replay': False}
            atomic_json(evidence_path, ledger)
            return ledger

        from .table_scope_batches import TableScopeBatchClient
        scope_text = abstract_text(paper) if tables_only else text
        selection_client = TableScopeBatchClient(client, document.tables, eligible, scope_text, checkpoints=stages,
                                                recent_benchmark_scope=True)
        admissions = {}
        active_table_id = None

        def process_table(index, table, *, repair=False):
            nonlocal bindings, scope_reviews, active_table_id
            active_table_id = table.table_id
            LOG.info("新benchmark表格进度：paper=%s 表=%d/%d", paper["id"], index, len(document.tables))
            try:
                scope_input = {"table": table_payload(table), "benchmarks": eligible,
                               "policy": table_scope_version(eligible, recent_benchmark_scope=True) + ('|abstract-tables-v1' if tables_only else '') + ('|automatic-repair-v1' if repair else '')}
                scope = stages.load("table_scope", scope_input)
                if scope is None:
                    scope = select_table(repair_client if repair else selection_client, table, eligible, paper_text=scope_text, recent_benchmark_scope=True)
                    if scope.get("decision") in {"SELECT", "EXCLUDE"}:
                        stages.save("table_scope", scope_input, scope)
                scopes.append({"table_id": table.table_id, **scope})
                selected = scope["decision"] == "SELECT"
                prior_rows = [o for o in bindings if o.get('table_id') == table.table_id]
                if scope['decision'] != 'REVIEW' or not prior_rows:
                    db.store_selection(table.table_id, selected=selected, group_id=None, confidence=1.0,
                                       reason=scope["reason"], source=VERSION, prompt_version=VERSION)
                if not selected:
                    if scope['decision'] == 'EXCLUDE':
                        bindings = [o for o in bindings if o["table_id"] != table.table_id]
                        scope_reviews = [r for r in scope_reviews if r.get("table_id") != table.table_id]
                    completed_tables.add(table.table_id)
                    publish_progress()
                    return
                from benchmark_tables.structural_candidates import needs_rebuild
                rebuild_structure = needs_rebuild(db, table)
                observations = None if rebuild_structure else candidate_observations(db, table, persist=True)
                if rebuild_structure or observations is None and not pipeline._has_current_successful_plan(db, table):
                    pipeline._analyze_table(table, db, repair_client if repair else client, defer_model_admission=True)
                if observations is None:
                    observations = candidate_observations(db, table, persist=True)
                coordinates_checked = observations is not None
                if observations is None:
                    kept, _ = _filter_observations_for_export(db.fetch_active_observations(paper["paper_id"]))
                    observations = [dict(o) for o in kept if o["table_id"] == table.table_id]
                if prior_rows:
                    # A rebuilt plan may legitimately change coordinates or
                    # model labels. Retain only cells still matching that DB.
                    checked = checked_result(root, {'paper_id': paper['paper_id'],
                        'arxiv_id': paper.get('arxiv_id', paper['id'])},
                        candidate_ledger={**ledger, 'observations': prior_rows})
                    bindings = [o for o in bindings if o.get('table_id') != table.table_id] + (
                        checked['observations'] if checked else [])
                binding_input = {"table": table_payload(table), "observations": observations,
                                 "benchmarks": eligible,
                                 "policy": model_scope_version(eligible, recent_benchmark_scope=True) + '|' + MODEL_ADMISSION_VERSION + '|' + BINDING_PROMPT_VERSION,
                                 "plan_rule": pipeline.PLAN_RULE_VERSION, "automatic_repair": repair}
                from benchmark_tables.model_aliases import changed_finetuning_label, is_finetuning_delta_observation, FINETUNING_LABEL_POLICY
                if any(changed_finetuning_label(o.get('model_raw', ''), o.get('model_setting', ''))
                       or is_finetuning_delta_observation(o.get('metric', ''), table.caption) for o in observations):
                    binding_input['finetuning_label_policy'] = FINETUNING_LABEL_POLICY
                binding = stages.load("bindings", binding_input)
                if binding is None:
                    earlier_reviews = list(scope_reviews)

                    def save_binding_progress(mapped, unassigned):
                        nonlocal bindings, scope_reviews
                        if table.table_id in recovered_sources:
                            proof = recovered_sources[table.table_id]
                            mapped = [{**o, "table_source_path": proof["source_path"],
                                       "table_source_sha256": proof["source_sha256"]} for o in mapped]
                        bindings = merge_table_rows(bindings, mapped, unassigned, table.table_id)
                        scope_reviews = earlier_reviews + [{**item, "table_id": table.table_id} for item in unassigned]
                        publish_progress()

                    mapped, unassigned = bind_observations(repair_client if repair else client, table, observations, eligible, paper_text=scope_text,
                                                           checkpoints=stages, on_progress=save_binding_progress,
                                                           reported_models=True, recent_benchmark_scope=True)
                    # Unresolved rows are revisited; an entirely checked table
                    # can be skipped on a repair of another table.
                    unassigned = [{**item, "table_id": table.table_id} for item in unassigned]
                    if all(item.get("resolution") == "EXCLUDED" for item in unassigned):
                        stages.save("bindings", binding_input, {"mapped": mapped, "unassigned": unassigned})
                else:
                    mapped, unassigned = binding["mapped"], binding["unassigned"]
                if table.table_id in recovered_sources:
                    proof = recovered_sources[table.table_id]
                    mapped = [{**o, "table_source_path": proof["source_path"],
                               "table_source_sha256": proof["source_sha256"]} for o in mapped]
                bindings = merge_table_rows(bindings, mapped, unassigned, table.table_id)
                scope_reviews = [item for item in scope_reviews if item.get("table_id") != table.table_id] + unassigned
                from .negative_admission import excluded_model_table
                receipt = excluded_model_table(table.table_id, observations, mapped, unassigned,
                                               coordinates_checked=coordinates_checked)
                if receipt:
                    admissions[table.table_id] = receipt
                completed_tables.add(table.table_id)
                publish_progress()
            except LLMServiceStop as exc:
                saved = finish_ledger(interrupted=exc)
                if saved["status"] == "COMPLETE":
                    exc.partial_evidence = saved
                raise
            except (RuntimeError, ValueError) as exc:
                from .failures import classify_failure
                diagnosis = classify_failure('ANALYSIS', str(exc))
                if diagnosis['service_failure']:
                    # Endpoint outages cannot be repaired by requesting every
                    # remaining table. Stop now, preserving independently proved
                    # sibling cells; ordinary table validation errors continue.
                    stopped = LLMServiceStop(str(exc))
                    stopped.failure_details = diagnosis
                    saved = finish_ledger(interrupted=stopped)
                    if saved['status'] == 'COMPLETE':
                        stopped.partial_evidence = saved
                    raise stopped from exc
                errors.append({"table_id": table.table_id, "error": str(exc)[:1500]})
                completed_tables.add(table.table_id)
                publish_progress()
                LOG.error("表格失败但保留其他成功结果：%s %s", table.table_id, exc)
        from .automatic_intake import RepairClient, unresolved_tables, completion_report
        repair_client = RepairClient(client)
        for index, table in enumerate(document.tables, 1):
            process_table(index, table)
        # Full-source mode has already run source recovery and the independent
        # qualification follow-up. Now repair only tables with open outcomes.
        if getattr(args, 'analysis_source', 'auto') == 'auto':
            pending_repair = unresolved_tables(scopes, scope_reviews, errors, bindings)
            from .automatic_intake import repair_tables
            from .negative_admission import conclusive_negative
            pending_repair.difference_update(tid for tid, receipt in admissions.items()
                                            if conclusive_negative(receipt))

            def repair_key(table):
                return {"table": table_payload(table), "benchmarks": eligible,
                        "policy": "automatic-repair-v1", "text": hashlib.sha256(scope_text.encode()).hexdigest()}

            def repair_table(index, table):
                LOG.info('首次处理自动补救：paper=%s table=%s', paper['id'], table.table_id)
                scopes[:] = [s for s in scopes if s['table_id'] != table.table_id]
                errors[:] = [e for e in errors if e['table_id'] != table.table_id]
                # Keep unresolved rows until the validated replacement binding
                # supersedes them, including when a repair fails midway.
                process_table(index, table, repair=True)

            repair_tables(document.tables, pending_repair, stages, repair_key,
                          repair_table, lambda tid: tid in unresolved_tables(
                              scopes, scope_reviews, errors, bindings)
                          and not conclusive_negative(admissions.get(tid)))
        result = finish_ledger()
        result['automatic_intake'] = completion_report(result)
        atomic_json(evidence_path, result)
        return result


PIPELINE_STAGE_VERSION = "radar-pipeline-stage-v1"


def _stage_paper_binding(row):
    paper = row["paper"]
    return {key: paper.get(key) for key in
            ("id", "paper_id", "arxiv_id", "publication_date", "pdf_url", "source_metadata")}


def _verified_download(root, row):
    """Return local immutable bytes, never following a former host's path."""
    root = Path(root).resolve()
    paper = row["paper"]
    identifier = paper["paper_id"]
    if (not isinstance(identifier, str) or not identifier or identifier in {".", ".."}
            or any(c in identifier for c in ("/", "\\", ":"))):
        raise ValueError("流水线paper_id无效")
    from benchmark_tables.hashing import sha256_file
    if row.get("source_kind") == "arxiv_html":
        from .html_download import verified_html_receipt
        path = root / "html" / identifier / "source.html"
        receipt_path = root / "downloads" / (identifier + "-html.json")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not path.resolve().is_relative_to(root) or not verified_html_receipt(paper, path, receipt):
            raise ValueError("HTML下载回执与当前来源不符")
        return {"source_kind": "arxiv_html", "download_sha256": sha256_file(path)}, path, receipt
    from .shared_cache import _pdf_details, verified_pdf_receipt
    path = root / "pdf" / (identifier + ".pdf")
    receipt_path = root / "downloads" / (identifier + ".json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    details = _pdf_details(path)
    if not path.resolve().is_relative_to(root) or not verified_pdf_receipt(paper, details, receipt):
        raise ValueError("PDF下载回执与当前来源不符")
    return {"source_kind": "pdf", "download_sha256": details["sha256"]}, path, receipt


def _local_download_row(root, row):
    binding, path, receipt = _verified_download(root, row)
    if binding["source_kind"] == "pdf":
        return {**row, "source_kind": "pdf", "pdf_path": str(path), "download": receipt}
    result = {**row, "source_kind": "arxiv_html", "html_download": receipt}
    result.pop("pdf_path", None)
    # A copied run may contain old machine paths. Rebind only artifacts whose
    # exact hashes remain covered by the immutable HTML manifest.
    if row.get("document_path") and row.get("html_source"):
        from .source_refs import resolve_source_path
        metadata = row["html_source"]
        document = resolve_source_path(root, row["document_path"], metadata.get("document_sha256"))
        if document is not None:
            result.update(document_path=str(document),
                html_source={**metadata, "raw_path": str(document.parent / metadata["raw_filename"]),
                    "manifest_path": str(document.with_name(document.name.removesuffix("_content_list.json") + ".manifest.json"))},
                markdown_path=str(document.with_name(document.name.removesuffix("_content_list.json") + ".md")))
    return result


def _parsed_document(root, row):
    local = _local_download_row(root, row)
    if local.get("source_kind") == "arxiv_html":
        from .html_source import load_html_document
        document = load_html_document(local)
    else:
        document = workflow._stream_find_document(Path(root) / "mineru", Path(local["pdf_path"]))
    if document is None:
        raise ValueError("解析未生成可识别的当前论文来源")
    return local, document


def _parse_checkpoint_path(root, row):
    return Path(root) / "pipeline-stages" / (row["paper"]["paper_id"] + "-parse.json")


def _save_parse_checkpoint(root, row):
    from .source_refs import source_reference
    binding, _, _ = _verified_download(root, row)
    local, document = _parsed_document(root, row)
    from .html_pdf_fallback import needs_html_pdf_fallback, HtmlPdfFallbackError
    if needs_html_pdf_fallback(local, document):
        raise HtmlPdfFallbackError('HTML_REPARSE_REQUIRED')
    receipt = {"version": PIPELINE_STAGE_VERSION, "paper": _stage_paper_binding(row),
               "download": binding, "source": source_reference(root, document.source_path),
               "completed_at": datetime.now(timezone.utc).isoformat()}
    atomic_json(_parse_checkpoint_path(root, row), receipt)
    return local


def checked_stage_ready(root, row, stage):
    """Check completed artifacts, rather than trusting a queue/stage status."""
    try:
        binding, _, _ = _verified_download(root, row)
        if stage == "DOWNLOAD":
            return True
        if stage != "PARSE":
            return False
        receipt = json.loads(_parse_checkpoint_path(root, row).read_text(encoding="utf-8"))
        if (receipt.get("version") != PIPELINE_STAGE_VERSION
                or receipt.get("paper") != _stage_paper_binding(row)
                or receipt.get("download") != binding):
            return False
        from .source_refs import source_reference
        _, document = _parsed_document(root, row)
        from .html_pdf_fallback import needs_html_pdf_fallback
        if needs_html_pdf_fallback(row, document):
            return False
        return receipt.get("source") == source_reference(root, document.source_path)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def resume_pipeline_stage(root, row, args=None):
    """The earliest unfinished source stage; a legacy file needs one attestation."""
    if checked_stage_ready(root, row, "PARSE"):
        return "ANALYZE"
    if checked_stage_ready(root, row, "DOWNLOAD"):
        return "PARSE"
    return "DOWNLOAD"


def _stage_candidates(args, root, manifest):
    """A downstream lane cannot discover or replace its frozen source snapshot."""
    path = root / "candidates.jsonl"
    report = json.loads((root / "discovery.json").read_text(encoding="utf-8"))
    data = path.read_bytes()
    checksum = report.get("candidate_snapshot_sha256")
    if checksum is not None and checksum != hashlib.sha256(data).hexdigest():
        raise ValueError("流水线候选快照哈希不符；请重新完成摘要阶段")
    papers = [validate_paper(json.loads(line), utc(manifest["start"]), utc(manifest["end"]))
              for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    if not papers or len({paper["id"] for paper in papers}) != len(papers):
        raise ValueError("流水线候选快照为空或论文ID重复")
    return papers


def _analysis_preflight(args, root, row):
    """The optional remote text judgment belongs to analysis, never GPU slots."""
    from .html_pdf_fallback import needs_html_pdf_fallback, HtmlPdfFallbackError, source_failure_row
    if needs_html_pdf_fallback(row):
        return source_failure_row(row, HtmlPdfFallbackError('HTML_REPARSE_REQUIRED'))
    from .text_evidence import RECENT_GATE_VERSION
    download, _, _ = _verified_download(root, row)
    binding = {"gate_version": RECENT_GATE_VERSION, "qualification_scope": RECENT_SCOPE_VERSION,
               "paper": _stage_paper_binding(row), "download": download,
               "screening": row.get("screening"),
               "disabled": bool(getattr(args, "no_text_preflight", False))}
    if row.get("pipeline_text_preflight") == binding:
        if (row.get("text_preflight") or {}).get("decision") == "EXCLUDE":
            return {**row, "status": "EXCLUDED_FULLTEXT", "error": "", "observations": [], "benchmarks": []}
        return row
    reviewed = text_preflight_one(args, root, row)
    # The full table analysis remains authoritative after a preflight fallback.
    # Replaying that same auxiliary request cannot improve its source coverage.
    return {**reviewed, "pipeline_text_preflight": binding}


def _stage_terminal(root, row, args, manifest=None):
    from .html_pdf_fallback import needs_html_pdf_fallback
    if needs_html_pdf_fallback(row) and not (
            row.get('status') == 'EXCLUDED' and (row.get('screening') or {}).get('decision') == 'EXCLUDE'):
        return False
    if row.get("status") in {"EXCLUDED", "EXCLUDED_FULLTEXT", "NO_TABLES"}:
        return (not (row.get("status") == "NO_TABLES" and "benchmarks" not in row)
                and not needs_fulltext_recheck(row, args) and not needs_benchmark_evidence_recheck(row)
                and not (manifest and needs_benchmark_date_recheck(row, args, manifest)))
    if (row.get("status") == "COMPLETE" and row.get("analysis_policy_version") == ANALYSIS_POLICY_VERSION
            and row.get("completion", {}).get("extraction_complete") is not False):
        from .live_progress import checked_result
        paper = row["paper"]
        result = checked_result(root, {"paper_id": paper["paper_id"], "arxiv_id": paper["arxiv_id"]})
        return bool(result and result.get("usable_result"))
    return False


def _write_stage_completion(args, root, records, manifest=None):
    phase = args.pipeline_stage
    next_phase = {"DOWNLOAD": "PARSE", "PARSE": "ANALYZE", "ANALYZE": None}[phase]
    items = []
    for row in records:
        terminal = _stage_terminal(root, row, args, manifest) or phase == "ANALYZE"
        ready = (not terminal and not row.get("metadata_invalid")
                 and not str(row.get("status", "")).startswith("FAILED_")
                 and checked_stage_ready(root, row, phase))
        item = {"arxiv_id": row["paper"]["arxiv_id"], "paper_id": row["paper"]["paper_id"],
                "status": row.get("status"), "ready": ready, "next_phase": next_phase if ready else None,
                "terminal": terminal, "source_kind": row.get("source_kind"), "error": row.get("error", "")}
        items.append(item)
    receipt = {"version": "radar-stage-completion-v1", "phase": phase,
               "reservation_id": getattr(args, "live_reservation_id", None), "code_version": CODE_VERSION,
               "completed_at": datetime.now(timezone.utc).isoformat(), "papers": items,
               "ready": bool(items) and all(item["ready"] for item in items),
               "next_phase": next_phase if items and all(item["ready"] for item in items) else None,
               "terminal": bool(items) and all(item["terminal"] for item in items)}
    if len(items) == 1:
        receipt.update({key: items[0][key] for key in ("arxiv_id", "paper_id", "status")})
    atomic_json(root / "stage_completion.json", receipt)


def _run_pipeline_stage(args, root, manifest, state, papers, save):
    """One lane owns only its phase, preserving successful handoff boundaries."""
    phase = args.pipeline_stage
    records = [state[p["id"]] for p in papers]
    error = None
    (root / "stage_completion.json").unlink(missing_ok=True)
    try:
        work = []
        for row in records:
            if row.get("metadata_invalid") or needs_screening(row, root):
                row.update(status="FAILED_" + phase, error="当前论文缺少成功且适用的摘要判断；请先完成SCREEN阶段")
            elif _stage_terminal(root, row, args, manifest):
                continue
            elif row["screening"]["decision"] == "EXCLUDE":
                row.update(status="EXCLUDED", error="")
            else:
                work.append(row)
        save()
        if phase == "DOWNLOAD":
            from copy import copy
            stage_args = copy(args)
            stage_args.workers = args.download_workers
            def download(row):
                if checked_stage_ready(root, row, "DOWNLOAD"):
                    return {**_local_download_row(root, row), "status": "DOWNLOADED", "error": ""}
                result = download_one(root, args, row)
                _verified_download(root, result)
                return result
            parallel_stage(stage_args, state, work, download, "download", save)
        elif phase == "PARSE":
            ready = []
            for row in work:
                if not checked_stage_ready(root, row, "DOWNLOAD"):
                    row.update(status="FAILED_PARSE", error="当前下载来源或回执无效；请先完成DOWNLOAD阶段")
                elif checked_stage_ready(root, row, "PARSE"):
                    state[row["paper"]["id"]] = {**_local_download_row(root, row), "status": "PARSED", "error": ""}
                else:
                    ready.append({**_local_download_row(root, row), "status": "DOWNLOADED", "error": ""})
            save()
            for row in ready:
                if row.get("source_kind") == "arxiv_html":
                    from .html_source import prepare_html_source
                    _, raw, proof = _verified_download(root, row)
                    row.update(prepare_html_source(row["paper"], raw, raw.parent, proof))
            if ready:
                successful = parse_downloaded(args, root, ready)
                for row in ready:
                    identifier = row["paper"]["id"]
                    if row["paper"]["paper_id"].casefold() not in successful:
                        state[identifier] = {**row, "status": "FAILED_SOURCE" if row.get("source_kind") == "arxiv_html" else "FAILED_MINERU",
                                             "error": row.get("source_error", "解析失败，未发布ANALYZE入口")}
                        continue
                    try:
                        local = _save_parse_checkpoint(root, row)
                        state[identifier] = {**local, "status": "PARSED", "error": ""}
                    except (OSError, ValueError, KeyError) as exc:
                        state[identifier] = {**row, "status": "FAILED_PARSE", "error": str(exc)[:1500]}
                save()
        else:
            ready = []
            for row in work:
                if checked_stage_ready(root, row, "PARSE"):
                    ready.append({**_local_download_row(root, row), "status": "PARSED", "error": ""})
                else:
                    from .html_pdf_fallback import needs_html_pdf_fallback, HtmlPdfFallbackError, source_failure_row
                    if needs_html_pdf_fallback(row):
                        row.update(source_failure_row(row, HtmlPdfFallbackError('HTML_REPARSE_REQUIRED')))
                    else:
                        row.update(status="FAILED_ANALYSIS", error="当前解析checkpoint或来源哈希无效；请先完成PARSE阶段")
            save()
            parallel_stage(args, state, ready, lambda row: _analysis_preflight(args, root, row), "text_preflight", save)
            ready = [state[row["paper"]["id"]] for row in ready
                     if not str(state[row["paper"]["id"]].get("status", "")).startswith("FAILED_")
                     and state[row["paper"]["id"]].get("status") != "EXCLUDED_FULLTEXT"]
            parallel_stage(args, state, ready, lambda row: analyze_one(args, root, manifest, row), "analysis", save)
    except Exception as exc:
        error = exc
        from .failures import classify_failure, safe_failure_details
        for paper in papers:
            row = state[paper["id"]]
            if (not str(row.get("status", "")).startswith("FAILED_")
                    and not _stage_terminal(root, row, args, manifest)
                    and not checked_stage_ready(root, row, phase)):
                row.update(status="FAILED_" + phase, error=str(exc)[:1500],
                           failure_details=safe_failure_details(getattr(exc, "failure_details", None))
                           or classify_failure(phase, str(exc)))
        LOG.error("流水线%s阶段停止，已保存成功检查点：%s", phase, exc)
    finally:
        save()
        _write_stage_completion(args, root, [state[p["id"]] for p in papers], manifest)
        if phase == "ANALYZE":
            from .reporting import export_reports
            export_reports(root, manifest, state, min_benchmarks=args.min_benchmarks,
                           xlsx=args.xlsx and not getattr(args, "core_only", False))
    if error:
        return 1
    return 2 if any(row.get("metadata_invalid") or str(row.get("status", "")).startswith("FAILED_")
                    for row in (state[p["id"]] for p in papers)) else 0


def run(args, root, manifest):
    phase = getattr(args, 'pipeline_stage', None)
    if phase:
        (root / 'stage_failure.json').unlink(missing_ok=True)
    try:
        return _run_impl(args, root, manifest)
    except Exception as exc:
        if phase and getattr(args, 'live_reservation_id', None):
            from .failures import classify_failure, safe_failure_details
            from .stage_closeout import VERSION as FAILURE_VERSION
            try:
                atomic_json(root / 'stage_failure.json', {'version': FAILURE_VERSION,
                    'phase': phase, 'reservation_id': args.live_reservation_id,
                    'failure_details': safe_failure_details(getattr(exc, 'failure_details', None))
                        or classify_failure(phase, str(exc)),
                    'exception_type': type(exc).__name__})
            except OSError:
                LOG.warning('阶段错误记录无法写入；原始异常保留在本篇日志')
        raise


def _run_impl(args, root, manifest):
    phase = getattr(args, "pipeline_stage", None)
    if phase:
        (root / "stage_completion.json").unlink(missing_ok=True)
    papers = _stage_candidates(args, root, manifest) if phase else candidates(args, root, manifest)
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    for paper in papers:
        state.setdefault(paper["id"], {"paper": paper, "status": "PENDING"})
        updated = state[paper["id"]]
        old_paper = updated["paper"]
        changed_metadata = (any(old_paper.get(key) != paper.get(key) for key in ("title", "abstract_text", "publication_date"))
                            or (old_paper.get("source_metadata") or {}).get("version") != (paper.get("source_metadata") or {}).get("version"))
        if changed_metadata:
            updated.setdefault("metadata_history", []).append(old_paper)
            if updated.get("screening"):
                updated.setdefault("screening_history", []).append({"screening": updated["screening"], "status": updated["status"],
                    "replaced_at": datetime.now(timezone.utc).isoformat(), "reason": "v1元数据重新核验"})
            updated.update(paper=paper, status="PENDING", screening=None, analysis_policy_version=None)
        elif old_paper.get("metadata_verification") != paper.get("metadata_verification"):
            updated.update(paper=paper, analysis_policy_version=None)
        updated.pop("metadata_invalid", None)
        # A prior service outage marker must never classify a different failure
        # on this attempt as another quota outage.
        updated.pop("service_error_kind", None)
    # A failed legacy entry not recovered by refresh remains auditable, but
    # cannot re-enter extraction through old state left outside the new snapshot.
    for row in state.values():
        try:
            validate_paper(row["paper"], utc(manifest["start"]), utc(manifest["end"]))
        except (ValueError, TypeError) as exc:
            row.update(metadata_invalid=True, status="REVIEW_METADATA", error=str(exc), analysis_policy_version=None)
            row["paper"] = {**row["paper"], "metadata_verification": "UNVERIFIED"}
    def save():
        atomic_json(state_path, state)
    save()
    if args.command == "discover":
        LOG.info("检索完成：候选=%d；来源/覆盖率见 discovery.json", len(papers))
        return 0
    if phase:
        return _run_pipeline_stage(args, root, manifest, state, papers, save)
    error = None
    try:
        pending = screening_order([r for r in state.values() if not r.get("metadata_invalid") and needs_screening(r, root)])
        old_exclusions = sum(isinstance(r.get("screening"), dict) and r["screening"].get("decision") == "EXCLUDE" for r in pending)
        old_reviews = sum(isinstance(r.get("screening"), dict) and r["screening"].get("decision") == "REVIEW" for r in pending)
        LOG.info("摘要模型判断：待处理=%d 其中旧排除复核=%d 旧空证据REVIEW=%d 规则=%s",
                 len(pending), old_exclusions, old_reviews, RECENT_SCREENING_VERSION)
        parallel_stage(args, state, pending, lambda row: screen_one(args, root, row), "screen", save)
        if getattr(args, "screen_only", False):
            # This durable checkpoint is handed back to the service's extraction
            # lane. Previously completed source evidence and exports stay intact;
            # downstream failures do not turn a successful cached screen into a
            # new screening failure.
            return 2 if any(row.get("metadata_invalid") or row.get("status") == "FAILED_SCREEN"
                            for row in state.values()) else 0
        active = [r for r in state.values() if isinstance(r.get("screening"), dict)
                  and not r.get("metadata_invalid")
                  and r["screening"].get("decision") in {"CANDIDATE", "REVIEW"}
                  and r["status"] != "FAILED_SCREEN"
                  and (r["status"] not in TERMINAL or (args.retry_review and r["status"] == "REVIEW")
                       or (args.retry_review and r["status"] == "COMPLETE"
                           and r.get("completion", {}).get("extraction_complete") is False)
                       or (r.get("benchmarks") and (getattr(args, "refresh_history", False)
                           or r.get("analysis_policy_version") != ANALYSIS_POLICY_VERSION))
                       or needs_fulltext_recheck(r, args)
                       or needs_benchmark_evidence_recheck(r)
                       or needs_benchmark_date_recheck(r, args, manifest)
                       or (r["status"] == "NO_TABLES" and "benchmarks" not in r))]
        if not active:
            return 2 if any(r["status"].startswith("FAILED_") for r in state.values()) else 0
        active = extraction_order(active)
        # A wider release window changes eligibility, not the pinned document.
        # A validated parser handoff can go straight to cached source analysis;
        # it must not spend another download, preflight or GPU pass.
        date_ready = [r for r in active if needs_benchmark_date_recheck(r, args, manifest)
                      and checked_stage_ready(root, r, "PARSE")]
        date_ids = {r["paper"]["id"] for r in date_ready}
        active = [r for r in active if r["paper"]["id"] not in date_ids]
        if date_ready:
            parallel_stage(args, state, date_ready, lambda row: analyze_one(args, root, manifest, row), "analysis", save)
        from copy import copy
        download_args = copy(args)
        download_args.workers = args.download_workers
        parallel_stage(download_args, state, active, lambda row: download_one(root, args, row), "download", save)
        downloaded = [state[r["paper"]["id"]] for r in active if state[r["paper"]["id"]]["status"] == "DOWNLOADED"]
        parallel_stage(args, state, downloaded, lambda row: text_preflight_one(args, root, row), "text_preflight", save)
        excluded = sum(state[r["paper"]["id"]]["status"] == "EXCLUDED_FULLTEXT" for r in downloaded)
        downloaded = [state[r["paper"]["id"]] for r in downloaded if state[r["paper"]["id"]]["status"] == "DOWNLOADED"]
        LOG.info("全文补证汇总：明确不符=%d 继续解析=%d；不确定/文字不足仍解析", excluded, len(downloaded))
        if downloaded:
            successful = parse_downloaded(args, root, downloaded)
            ready = []
            for row in downloaded:
                if row["paper"]["paper_id"].casefold() in successful:
                    ready.append(row)
                else:
                    html = row.get("source_kind") == "arxiv_html"
                    state[row["paper"]["id"]] = {**row, "status": "FAILED_SOURCE" if html else "FAILED_MINERU",
                        "error": row.get("source_error", "HTML来源校验失败") if html else "解析失败，见 work/mineru_failures.csv"}
            save()
            parallel_stage(args, state, ready, lambda row: analyze_one(args, root, manifest, row), "analysis", save)
    except Exception as exc:
        error = exc
        LOG.error("本轮停止，已保存结果可原目录续跑：%s", exc)
    finally:
        # A worker may have completed tables before an auth stop. Its immutable
        # evidence file preserves those results even when the outer future fails.
        if not getattr(args, "screen_only", False):
            from .reporting import export_reports
            export_reports(root, manifest, state, min_benchmarks=args.min_benchmarks,
                           xlsx=args.xlsx and not getattr(args, "core_only", False))
    if error:
        return 1
    return 2 if any(r["status"].startswith("FAILED_") for r in state.values()) else 0


def sync_outputs(args, root):
    if args.warehouse_dir:
        from .warehouse import sync_run
        deferred = getattr(args, '_backfill_defer_export', False)
        result = sync_run(root, args.warehouse_dir, publish=not deferred)
        if deferred and getattr(args, '_backfill_export_dirty', None) is not None:
            args._backfill_export_dirty.set()
        LOG.info("历史目录同步完成：%s；统计=%s", args.warehouse_dir, result)


def postprocess(args, root, manifest, state):
    """Finish display metadata independently of published source-score status."""
    from .reporting import export_reports
    from .catalog_enrichment import enrich_all
    from .tasks import task_outputs
    from copy import copy
    from .table_evidence import source_state
    state = source_state(args, state)
    task_args = copy(args)
    task_args.command = "run"  # Preserve configured task scoring in the background.
    results = []
    marker = root / "service_error.json"
    old_error = marker.read_bytes() if marker.exists() else None
    operations = [
        ("export", lambda: export_reports(root, manifest, state, min_benchmarks=args.min_benchmarks, xlsx=args.xlsx)),
        ("enrich", lambda: enrich_all(args, root, state)),
        ("labels", lambda: task_outputs(task_args, root, manifest, state, label=False)),
        ("sync", lambda: sync_outputs(args, root)),
    ]
    if getattr(args, 'labels_only', False):
        # Catalog classification is one job per benchmark. Score-group audits
        # are deliberately not part of historical/automatic tag repair.
        projection_path = root / 'benchmark_enrichment.json'
        def semantic_labels():
            try:
                projection = json.loads(projection_path.read_text(encoding='utf-8'))
                return [(item.get('paper_id'), item.get('benchmark_id'), item.get('source_scope'),
                         {key: item.get('labels', {}).get(key) for key in ('result', 'error', 'input_fingerprint')})
                        for item in projection.get('items', [])]
            except (OSError, ValueError, TypeError, AttributeError):
                return None
        before_labels = semantic_labels()
        previous_completion = root / 'postprocess_completion.json'
        try:
            previous_stages = json.loads(previous_completion.read_text(encoding='utf-8')).get('stages', [])
        except (OSError, ValueError, TypeError, AttributeError):
            previous_stages = []
        previously_synced = any(s.get('stage') == 'sync' and s.get('exit_code') == 0
                                for s in previous_stages if isinstance(s, dict))
        def sync_changed_labels():
            if previously_synced and before_labels is not None and before_labels == semantic_labels():
                LOG.info('目录标签结果未变化，跳过历史仓库同步：%s', root.name)
                return 0
            return sync_outputs(args, root)
        operations = [('enrich', lambda: enrich_all(args, root, state)),
                      ('sync', sync_changed_labels)]
    try:
        for name, operation in operations:
            try:
                returned = operation()
                code = returned if isinstance(returned, int) and not isinstance(returned, bool) else 0
                results.append({"stage": name, "exit_code": code})
                if getattr(args, 'labels_only', False) and code == 1:
                    break
            except (OSError, RuntimeError, ValueError) as exc:
                results.append({"stage": name, "exit_code": 1, "error": str(exc)[:1500]})
                LOG.warning("后台%s失败，核心成绩保留，继续其他后处理：%s", name, exc)
                if getattr(args, 'labels_only', False):
                    break
    finally:
        # Older enrichment helpers use the core outage marker. A background
        # failure must not invalidate a successful extraction on the next run.
        if marker.exists() and (old_error is None or marker.read_bytes() != old_error):
            try:
                atomic_json(root / "postprocess_error.json", json.loads(marker.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
            if old_error is None:
                marker.unlink(missing_ok=True)
            else:
                marker.write_bytes(old_error)
        atomic_json(root / "postprocess_completion.json", {
            "version": "radar-postprocess-completion-v1", "code_version": CODE_VERSION,
            "reservation_id": getattr(args, "live_reservation_id", None),
            "completed_at": datetime.now(timezone.utc).isoformat(), "stages": results,
            "successful": len(results) == len(operations) and all(r["exit_code"] == 0 for r in results)})
    return 1 if any(r["exit_code"] == 1 for r in results) else 2 if any(r["exit_code"] for r in results) else 0


def main(argv=None):
    args = argv if isinstance(argv, argparse.Namespace) else parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == 'backfill-labels':
            from .label_backfill import backfill_runs
            return backfill_runs(args)
        with RunLock(args.run_dir):
            if args.command in {"export", "label", "enrich", "postprocess", "sync", "profile", "score", "taxonomy"}:
                root = args.run_dir.resolve()
                manifest = json.loads((root / "run.json").read_text(encoding="utf-8"))
                if manifest.get("version") != VERSION:
                    raise ValueError("不是此流程的运行目录")
                if args.command == "taxonomy":
                    from .taxonomy import TAXONOMY
                    atomic_json(root / "task_taxonomy.json", TAXONOMY)
                    LOG.info("标签体系已保存：%s", root / "task_taxonomy.json")
                    return 0
                state = json.loads((root / "state.json").read_text(encoding="utf-8"))
                from .table_evidence import source_state
                state = source_state(args, state)
                if args.command == "postprocess":
                    return postprocess(args, root, manifest, state)
                if args.command == "profile":
                    from .tasks import resolve_profile
                    _, path = resolve_profile(args, root)
                    LOG.info("任务需求已保存，可编辑权重和约束：%s", path)
                    return 0
                from .reporting import export_reports
                export_reports(root, manifest, state, min_benchmarks=args.min_benchmarks, xlsx=args.xlsx)
                enrich_result = 0
                if args.command == "enrich":
                    from .catalog_enrichment import enrich_all
                    enrich_result = enrich_all(args, root, state)
                from .tasks import task_outputs
                task_result = task_outputs(args, root, manifest, state, label=args.command == "label")
                sync_outputs(args, root)
                return 1 if enrich_result == 1 else max(enrich_result, task_result)
            root, manifest = initialize(args)
            if args.command == "run":
                (root / "service_error.json").unlink(missing_ok=True)
            benchmark_start, benchmark_end = qualification_window(args, manifest)
            LOG.info("论文检索窗口：[%s, %s)；benchmark首次发布窗口：[%s, %s)，代码版本=%s",
                     manifest["start"], manifest["end"], benchmark_start.isoformat(), benchmark_end.isoformat(), CODE_VERSION)
            result = run(args, root, manifest)
            if (args.command == "run" and not getattr(args, "screen_only", False)
                    and not getattr(args, "core_only", False) and not getattr(args, "pipeline_stage", None)):
                from .tasks import task_outputs
                state = json.loads((root / "state.json").read_text(encoding="utf-8"))
                enrich_result = 0
                if result != 1 and args.enrich_benchmarks:
                    from .catalog_enrichment import enrich_all
                    enrich_result = enrich_all(args, root, state)
                task_result = task_outputs(args, root, manifest, state,
                                           label=1 not in (result, enrich_result) and (args.label_capabilities or bool(args.task_description or args.task_template or args.task_profile)),
                                           score=1 not in (result, enrich_result))
                sync_outputs(args, root)
                return 1 if 1 in (result, enrich_result) else max(result, enrich_result, task_result)
            return result
    except (OSError, RuntimeError, ValueError) as exc:
        from benchmark_tables.deepseek_client import LLMQuotaError
        if isinstance(exc, LLMQuotaError) and "root" in locals() and args.command == "run":
            atomic_json(root / "service_error.json", {"kind": "LLM_QUOTA"})
        LOG.error("新benchmark流程失败：%s", exc)
        return 1
