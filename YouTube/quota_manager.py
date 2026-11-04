import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "quota_config.json"
STATE_FILE = BASE / "quota_state.json"

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")


def read_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    return read_json(CONFIG_FILE, {})


def load_state():
    state = read_json(STATE_FILE, {})
    today = datetime.now(PACIFIC).date().isoformat()

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


def priority(candidate, now):
    event_time = datetime.fromisoformat(
        candidate["event_time"].replace("Z", "+00:00")
    )

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    minutes = (event_time - now).total_seconds() / 60
    distance = abs(minutes)

    if distance <= 30:
        score = 100
    elif distance <= 120:
        score = 75
    elif 120 < minutes <= 240:
        score = 45
    elif -360 <= minutes < -120:
        score = 30
    else:
        score = 10

    return score * float(candidate.get("importance", 1))


def select_candidates(candidates, state, config, now):
    cap = max(
        0,
        config["daily_limit"] - config["reserve"]
        - state["total_used"]
    )

    slots = min(config["max_per_run"], cap)

    if slots == 0:
        return []

    floors = config["domain_floor"]
    active = {c["domain"] for c in candidates}

    def score(candidate):
        domain = candidate["domain"]
        used = state["domain_used"].get(domain, 0)
        floor = floors.get(domain, 0)

        fairness = 35 if domain in active and used < floor else 0

        return priority(candidate, now) + fairness

    ranked = sorted(candidates, key=score, reverse=True)

    selected = []
    cooldown = timedelta(
        minutes=config["cooldown_minutes"]
    )

    for candidate in ranked:
        if len(selected) >= slots:
            break

        key = candidate["key"]
        last = state["last_query"].get(key)

        if last:
            last_time = datetime.fromisoformat(last)

            if now - last_time < cooldown:
                continue

        selected.append(candidate)

    return selected


def record_success(state, candidate, now):
    domain = candidate["domain"]

    state["total_used"] += 1

    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    state["last_query"][candidate["key"]] = now.isoformat()


def save_state(state):
    write_json(STATE_FILE, state)
