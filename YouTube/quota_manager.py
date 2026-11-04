import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

CONFIG_FILE = "quota_config.json"
STATE_FILE = "quota_state.json"


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today_pacific():
    return datetime.now(PACIFIC).date().isoformat()


def load_state():
    state = load_json(STATE_FILE, {})

    today = today_pacific()

    if state.get("date") != today:
        state = {
            "date": today,
            "total_used": 0,
            "domain_used": {
                "Football": 0,
                "F1": 0
            },
            "last_query": {}
        }

    return state


def priority_for_candidate(candidate, now):
    event_time = candidate["event_time"]

    if isinstance(event_time, str):
        event_time = datetime.fromisoformat(
            event_time.replace("Z", "+00:00")
        )

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    minutes = (event_time - now).total_seconds() / 60
    distance = abs(minutes)

    if distance <= 30:
        priority = 100
    elif distance <= 120:
        priority = 75
    elif minutes > 120 and minutes <= 240:
        priority = 45
    elif minutes < -120 and minutes >= -360:
        priority = 30
    else:
        priority = 10

    importance = candidate.get("importance", 1.0)

    return priority * importance


def select_candidates(candidates, config, state, now):
    daily_cap = config["daily_limit"] - config["reserve"]
    remaining = max(0, daily_cap - state["total_used"])

    max_per_run = min(
        config["max_per_run"],
        remaining
    )

    if max_per_run <= 0:
        return []

    used = state["domain_used"]

    active_domains = {
        c["domain"] for c in candidates
    }

    floors = config["domain_floor"]

    def score(candidate):
        domain = candidate["domain"]

        base = priority_for_candidate(candidate, now)

        floor = floors.get(domain, 0)
        domain_used = used.get(domain, 0)

        fairness_boost = 0

        if domain in active_domains and domain_used < floor:
            fairness_boost = 35

        return base + fairness_boost

    ranked = sorted(
        candidates,
        key=score,
        reverse=True
    )

    selected = []
    selected_keys = set()

    cooldown = timedelta(
        minutes=config["cooldown_minutes"]
    )

    for candidate in ranked:
        if len(selected) >= max_per_run:
            break

        domain = candidate["domain"]
        key = candidate["key"]

        if key in selected_keys:
            continue

        last_query = state["last_query"].get(key)

        if last_query:
            last_time = datetime.fromisoformat(last_query)

            if now - last_time < cooldown:
                continue

        selected.append(candidate)
        selected_keys.add(key)

    return selected


def record_usage(state, candidate, now):
    domain = candidate["domain"]
    key = candidate["key"]

    state["total_used"] += 1

    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    state["last_query"][key] = now.isoformat()


def run_quota_selection(candidates):
    config = load_json(CONFIG_FILE, {})
    state = load_state()

    now = datetime.now(UTC)

    selected = select_candidates(
        candidates,
        config,
        state,
        now
    )

    return selected, state, now


def save_usage(state):
    save_json(STATE_FILE, state)
