from __future__ import annotations

import math

from numbers import Real

import re

from .taxonomy import TAXONOMY_VERSION, SUPPORTED_TAXONOMY_VERSIONS, label_ids

PROFILE_VERSION = "task-profile-v1"

_CONSTRAINT_KEYS = {"language", "modality", "knowledge_access", "min_context_tokens"}

def _text(value, name, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{name} 必须是{'可空' if empty else '非空'}字符串")
    return value.strip()

def _labels(values, layer):
    if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
        raise ValueError(f"{layer} 必须为标签ID数组")
    if len(values) != len(set(values)) or not set(values) <= label_ids(layer):
        raise ValueError(f"{layer} 存在重复或未知标签")
    return sorted(values)

def _language(value, unknown):
    if (not isinstance(value, str) or (value in {"any", "unknown"} and value != unknown)
            or not (value == unknown or re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value))):
        raise ValueError("language 必须为语言代码，或明确的 any/unknown")
    return value

def _context(value, key):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
        raise ValueError(f"{key} 必须为正整数或null")
    return value

def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict) or profile.get("schema_version") != PROFILE_VERSION:
        raise ValueError("任务profile schema_version不匹配")
    if profile.get("taxonomy_version") not in SUPPORTED_TAXONOMY_VERSIONS:
        raise ValueError("任务profile taxonomy_version不匹配")
    allowed = {"schema_version", "taxonomy_version", "description", "domains", "tasks", "capabilities", "constraints", "weight_basis", "assumptions"}
    if set(profile) - allowed:
        raise ValueError("任务profile含未知字段")
    result = {"schema_version": PROFILE_VERSION, "taxonomy_version": TAXONOMY_VERSION,
              "description": _text(profile.get("description"), "description"),
              "domains": _labels(profile.get("domains"), "domains"), "tasks": _labels(profile.get("tasks"), "tasks")}
    capabilities = profile.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("至少需要一个能力权重")
    seen = set()
    normalized = []
    for item in capabilities:
        if not isinstance(item, dict) or set(item) != {"id", "weight", "rationale"}:
            raise ValueError("能力项必须包含id/weight/rationale")
        label, weight = item["id"], item["weight"]
        if not isinstance(label, str) or label not in label_ids("capabilities") or label in seen:
            raise ValueError("能力ID未知或重复")
        try:
            valid_weight = not isinstance(weight, bool) and isinstance(weight, Real) and math.isfinite(weight) and weight > 0
        except (OverflowError, TypeError, ValueError):
            valid_weight = False
        if not valid_weight:
            raise ValueError("能力权重必须为有限正数")
        seen.add(label)
        normalized.append({"id": label, "weight": float(weight), "rationale": _text(item["rationale"], "rationale")})
    total = sum(item["weight"] for item in normalized)
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("能力权重之和必须为1，不会自动放大剩余能力")
    constraints = profile.get("constraints")
    if not isinstance(constraints, dict) or set(constraints) != _CONSTRAINT_KEYS:
        raise ValueError("constraints字段必须完整且不含未知字段")
    constraints = dict(constraints)
    _language(constraints["language"], "any")
    from .task_constraints import valid_modality
    if not valid_modality(constraints["modality"]):
        raise ValueError("任务modality非法")
    if constraints["knowledge_access"] not in {"any", "closed_book", "retrieval", "tools"}:
        raise ValueError("任务knowledge_access非法")
    _context(constraints["min_context_tokens"], "min_context_tokens")
    if profile.get("weight_basis") not in {"llm_proposed", "user_specified"}:
        raise ValueError("weight_basis非法")
    assumptions = profile.get("assumptions", [])
    if not isinstance(assumptions, list) or not all(isinstance(value, str) and value.strip() for value in assumptions):
        raise ValueError("assumptions必须为非空字符串数组，可为空数组")
    result.update(capabilities=normalized, constraints=constraints, weight_basis=profile["weight_basis"], assumptions=list(assumptions))
    return result
