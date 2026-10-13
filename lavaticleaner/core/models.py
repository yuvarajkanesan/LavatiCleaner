from __future__ import annotations

from dataclasses import dataclass, field

RISKS = ("safe", "review", "advanced")
ACTIONS = ("delete", "recycle_bin", "clipboard", "flush_dns")
TABS = ("windows", "apps")


@dataclass(slots=True)
class Rule:
    id: str
    category: str                        # group shown in the Cleaner (e.g. "Edge Browser")
    label: str
    risk: str = "safe"
    paths: list = field(default_factory=list)
    include: list = field(default_factory=lambda: ["*"])
    exclude: list = field(default_factory=list)
    min_age_days: float = 0
    requires_closed: list = field(default_factory=list)
    requires_admin: bool = False
    recursive: bool = True
    action: str = "delete"
    dir_name: str | None = None          # match directories by name (e.g. __pycache__)
    skip_dirs: list = field(default_factory=lambda: [".git", "node_modules", ".venv", "venv"])
    quarantine: bool | None = None       # None -> derived from risk
    note: str = ""
    tab: str = "windows"                 # which Cleaner tab lists it: windows | apps
    prune_empty: bool = False            # also remove folders left empty (temp-style rules)

    @property
    def use_quarantine(self) -> bool:
        if self.quarantine is not None:
            return self.quarantine
        return self.risk != "safe"


@dataclass(slots=True)
class Item:
    path: str
    size: int
    mtime: float
    rule_id: str
    n: int = 1                            # file count represented (recycle bin pseudo-item)


@dataclass
class RuleResult:
    rule: Rule
    items: list = field(default_factory=list)
    size: int = 0
    count: int = 0
    roots: list = field(default_factory=list)
    status: str = "ok"                    # ok | needs_admin | managed | empty
    young: int = 0                        # files kept because they are newer than the rule's minimum age
    protected: int = 0                    # files left out: they belong to security/management software
    errors: int = 0
    running: list = field(default_factory=list)   # apps that should be closed first


@dataclass
class Skipped:
    path: str
    reason: str
    size: int = 0
    rule_id: str = ""


@dataclass
class RunReport:
    run_id: str
    dry_run: bool
    label: str = ""
    freed: int = 0
    deleted_files: int = 0
    quarantined: int = 0
    quarantined_bytes: int = 0
    would_free: int = 0
    skipped: list = field(default_factory=list)
    cancelled: bool = False
    seconds: float = 0.0
    by_rule: dict = field(default_factory=dict)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)
