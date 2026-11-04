
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "quota_state.json"
CONFIG_FILE = BASE_DIR / "quota_config.json"

PACIFIC = ZoneInfo("America/Los_Angeles")


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def today():
    return datetime.now(PACIFIC).date().isoformat()


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            state = {}
    else:
        state = {}

    if state.get("date") != today():
        state = {
            "date": today(),
            "total_used": 0,
            "domain_used": {
                "Football": 0,
                "F1": 0
            },
            "last_query": {},
            "last_fallback": {}
        }

    state.setdefault("total_used", 0)
    state.setdefault("domain_used", {})
    state.setdefault("last_query", {})
    state.setdefault("last_fallback", {})

    return state


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def remaining_quota(state, config):
    limit = config["daily_limit"] - config["reserve"]
    return max(0, limit - state["total_used"])


def can_search(state, config):
    return remaining_quota(state, config) > 0


def record_success(state, domain, query_key):
    """
    Pozvati nakon uspješnog search.list zahtjeva.
    Jedan poziv = jedan search.list zahtjev.
    """

    state["total_used"] += 1

    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    state["last_query"][query_key] = (
        datetime.now(PACIFIC).isoformat()
    )

    save_state(state)


def cooldown_passed(state, query_key, minutes):
    previous = state["last_query"].get(query_key)

    if not previous:
        return True

    try:
        last = datetime.fromisoformat(previous)
    except ValueError:
        return True

    now = datetime.now(PACIFIC)

    if last.tzinfo is None:
        last = last.replace(tzinfo=PACIFIC)

    return now - last >= timedelta(minutes=minutes)


def select_candidates(candidates, state, config):
    """
    Kandidat treba imati:
      domain: Football ili F1
      key: jedinstveni ključ pretrage
      importance: važnost događaja
      event_time: ISO datum/vrijeme ili None

    Dodatna polja kandidata ostaju sačuvana.
    """

    available = remaining_quota(state, config)

    slots = min(
        available,
        config.get("max_per_run", 8)
    )

    if slots <= 0:
        return []

    now = datetime.now(PACIFIC)
    eligible = []

    cooldown = config.get("cooldown_minutes", 180)

    for candidate in candidates:
        key = candidate.get("key")

        if not key:
            continue

        if not cooldown_passed(state, key, cooldown):
            continue

        domain = candidate.get("domain", "Football")
        importance = float(candidate.get("importance", 1.0))

        score = importance * 10

        event_time = candidate.get("event_time")

        if event_time:
            try:
                event = datetime.fromisoformat(event_time)

                if event.tzinfo is None:
                    event = event.replace(tzinfo=PACIFIC)

                hours = (event - now).total_seconds() / 3600

                if 0 <= hours <= 1:
                    score += 100
                elif 0 <= hours <= 3:
                    score += 70
                elif 0 <= hours <= 6:
                    score += 40
                elif -3 <= hours < 0:
                    score += 80
                elif -6 <= hours < -3:
                    score += 30

            except (ValueError, TypeError):
                pass

        if domain == "F1":
            score += 5

        candidate["_score"] = score
        eligible.append(candidate)

    eligible.sort(
        key=lambda item: item["_score"],
        reverse=True
    )

    selected = eligible[:slots]

    for candidate in selected:
        candidate.pop("_score", None)

    return selected
