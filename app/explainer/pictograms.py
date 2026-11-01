"""Pictogram choice by label keywords (the template owns the drawing)."""

from typing import cast

from app.explainer.anchors import tokens
from app.scenes.models import Pictogram

KEYWORDS: dict[str, tuple[str, ...]] = {
    "warning": ("warning", "risk", "legacy", "break", "error", "bug", "danger", "fail", "outage"),
    "browser": ("browser", "web", "website", "site", "page", "chrome", "frontend", "dashboard"),
    "mobile": ("mobile", "ios", "android", "app", "apps"),
    "server": ("server", "backend", "worker", "workers", "service", "api", "host", "infra"),
    "database": ("database", "storage", "sql", "data", "warehouse", "memory", "cache"),
    "card": ("billing", "payment", "payments", "card", "checkout", "invoice", "money", "price"),
    "search": ("search", "find", "query", "lookup", "discover"),
    "user": ("admin", "user", "account", "profile", "person", "owner"),
    "people": ("people", "team", "users", "humans", "staff", "engineers", "customers", "crowd"),
    "clock": ("time", "hours", "days", "clock", "schedule", "deadline", "slow", "wait"),
    "key": ("access", "key", "password", "auth", "login", "permission", "secret", "token"),
    "cloud": ("cloud", "computer", "online", "remote", "hosted"),
    "flask": ("test", "tests", "testing", "experiment", "lab", "eval", "benchmark"),
    "code": ("code", "dev", "developer", "script", "repo", "commit", "program", "pull"),
    "chip": ("chip", "cpu", "hardware", "gpu", "model", "silicon", "processor"),
    "message": ("message", "chat", "text", "email", "slack", "mail", "reply", "inbox"),
    "phone": ("call", "voice", "phone", "dial", "speak"),
    "shield": ("safe", "safety", "security", "guard", "control", "protect", "approval", "rules"),
    "plug": ("plugin", "plugins", "integration", "connect", "connector", "extension"),
    "gear": ("settings", "config", "process", "pipeline", "workflow", "automation", "tool"),
    "bolt": ("fast", "speed", "power", "instant", "boost", "energy"),
    "doc": ("doc", "docs", "file", "report", "document", "paper", "notes", "slide", "deck"),
}


def pictogram_for(label: str, fallback: str = "doc") -> Pictogram:
    """Best pictogram for a label; ties go to the earlier (more specific) entry."""
    wanted = set(tokens(label))
    best, score = fallback, 0
    for name, words in KEYWORDS.items():
        hits = len(wanted & set(words))
        if hits > score:
            best, score = name, hits
    return cast(Pictogram, best)
