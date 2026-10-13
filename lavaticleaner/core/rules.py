"""Rule loader: cleaning targets are data (JSON), not code."""
from __future__ import annotations

import glob
import json
import os

from .models import ACTIONS, RISKS, Rule

_FIELDS = set(Rule.__dataclass_fields__)


def _build(d: dict) -> Rule:
    for key in ("id", "category", "label"):
        if not d.get(key):
            raise ValueError(f"missing '{key}'")
    unknown = set(d) - _FIELDS
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
    rule = Rule(**d)
    if rule.risk not in RISKS:
        raise ValueError(f"risk must be one of {RISKS}")
    if rule.action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if rule.action == "delete" and not rule.paths:
        raise ValueError("'paths' is required")
    return rule


def load_rules(*dirs: str) -> tuple[list[Rule], list[str]]:
    """Later directories override earlier ones by rule id. Returns (rules, errors)."""
    rules: dict[str, Rule] = {}
    errors: list[str] = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as e:
                errors.append(f"{os.path.basename(f)}: {e}")
                continue
            entries = data.get("rules", []) if isinstance(data, dict) else data
            for entry in entries:
                try:
                    r = _build(entry)
                    rules[r.id] = r
                except (TypeError, ValueError) as e:
                    errors.append(f"{os.path.basename(f)} [{entry.get('id', '?')}]: {e}")
    return list(rules.values()), errors
