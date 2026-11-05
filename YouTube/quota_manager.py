
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


def now_pacific():
    return datetime.now(PACIFIC)


def today():
    return now_pacific().date().isoformat()


def empty_state():
    return {
        "date": today(),
        "total_used": 0,
        "fallback_used": 0,
        "domain_used": {
            "Football": 0,
            "F1": 0
        },
        "last_query": {},
        "last_fallback": {}
    }


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    else:
        state = {}

    if state.get("date") != today():
        state = empty_state()

    state.setdefault("total_used", 0)
    state.setdefault("fallback_used", 0)
    state.setdefault("domain_used", {})
    state.setdefault("last_query", {})
    state.setdefault("last_fallback", {})

    state["domain_used"].setdefault("Football", 0)
    state["domain_used"].setdefault("F1", 0)

    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def remaining_quota(state, config):
    limit = int(config.get("daily_limit", 100))
    reserve = int(config.get("reserve", 10))
    return max(0, limit - reserve - int(state.get("total_used", 0)))


def can_search(state, config):
    return remaining_quota(state, config) > 0


def is_fallback_key(query_key):
    return query_key.startswith("fallback:") or ":fallback:" in query_key


def record_success(state, domain, query_key, fallback=False):
    """
    Evidentira jedan pokušaj search.list poziva.
    Poziva se prije slanja HTTP zahtjeva, kako lokalni brojač
    ne bi podcijenio potrošnju ako odgovor izostane.
    """
    fallback = fallback or is_fallback_key(query_key)

    state["total_used"] = int(state.get("total_used", 0)) + 1

    state.setdefault("domain_used", {})
    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    timestamp = now_pacific().isoformat()

    state.setdefault("last_query", {})
    state["last_query"][query_key] = timestamp

    if fallback:
        state["fallback_used"] = int(state.get("fallback_used", 0)) + 1
        state.setdefault("last_fallback", {})
        state["last_fallback"][query_key] = timestamp

    save_state(state)


def cooldown_passed(state, query_key, minutes):
    previous = state.get("last_query", {}).get(query_key)

    if not previous:
        return True

    try:
        last = datetime.fromisoformat(previous)
    except (ValueError, TypeError):
        return True

    if last.tzinfo is None:
        last = last.replace(tzinfo=PACIFIC)

    return now_pacific() - last >= timedelta(minutes=minutes)


def fallback_cooldown_passed(state, query_key, hours):
    previous = state.get("last_fallback", {}).get(query_key)

    if not previous:
        return True

    try:
        last = datetime.fromisoformat(previous)
    except (ValueError, TypeError):
        return True

    if last.tzinfo is None:
        last = last.replace(tzinfo=PACIFIC)

    return now_pacific() - last >= timedelta(hours=hours)


def is_f1_weekend(candidates):
    return any(
        candidate.get("domain") == "F1"
        and not candidate.get("fallback", False)
        for candidate in candidates
    )


def candidate_score(candidate, now):
    domain = candidate.get("domain", "Football")
    importance = float(candidate.get("importance", 1.0))
    score = importance * 10

    if candidate.get("fallback"):
        return score + 5 + (5 if domain == "F1" else 0)

    event_time = candidate.get("event_time")

    if event_time:
        try:
            event = datetime.fromisoformat(event_time)

            if event.tzinfo is None:
                event = event.replace(tzinfo=PACIFIC)

            event = event.astimezone(PACIFIC)
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

    return score


def select_candidates(candidates, state, config, now=None):
    """
    Odabir kandidata uz poštovanje:
    - dnevne YouTube kvote i rezerve
    - maksimalnog broja pretraga po pokretanju
    - općeg cooldowna
    - posebnog fallback cooldowna i budžeta
    - F1 dnevnog budžeta tijekom F1 vikenda
    """

    available = remaining_quota(state, config)
    slots = min(available, int(config.get("max_per_run", 8)))

    if slots <= 0:
        print("[Quota] Dosegnut dnevni limit.")
        return []

    if now is None:
        now = now_pacific()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=PACIFIC)
    else:
        now = now.astimezone(PACIFIC)

    cooldown = int(config.get("cooldown_minutes", 180))
    fallback_cooldown = int(config.get("fallback_cooldown_hours", 12))
    fallback_budget = int(config.get("fallback_budget", 10))
    fallback_remaining = max(
        0,
        fallback_budget - int(state.get("fallback_used", 0))
    )

    eligible = []

    for candidate in candidates:
        key = candidate.get("key")
        if not key:
            continue

        is_fallback = candidate.get("fallback", False)

        if not cooldown_passed(state, key, cooldown):
            continue

        if is_fallback:
            if fallback_remaining <= 0:
                continue
            if not fallback_cooldown_passed(state, key, fallback_cooldown):
                continue

        candidate["_score"] = candidate_score(candidate, now)
        eligible.append(candidate)

    if not eligible:
        print("[Quota] Nema kandidata nakon provjere cooldowna i budžeta.")
        return []

    has_events = any(
        not candidate.get("fallback", False)
        for candidate in eligible
    )

    # Ako postoje aktualni događaji, fallback se ne koristi.
    if has_events:
        eligible = [
            candidate for candidate in eligible
            if not candidate.get("fallback", False)
        ]

    active_f1 = is_f1_weekend(eligible)

    selected = []

    football_candidates = [
        c for c in eligible if c.get("domain") == "Football"
    ]
    f1_candidates = [
        c for c in eligible if c.get("domain") == "F1"
    ]

    football_candidates.sort(key=lambda c: c["_score"], reverse=True)
    f1_candidates.sort(key=lambda c: c["_score"], reverse=True)

    if active_f1:
        f1_budget = int(config.get("f1_race_budget", 10))
        f1_used = int(state.get("domain_used", {}).get("F1", 0))
        f1_remaining = max(0, f1_budget - f1_used)

        selected.extend(f1_candidates[:min(f1_remaining, slots)])

        remaining_slots = slots - len(selected)
        selected.extend(football_candidates[:remaining_slots])

        remaining_slots = slots - len(selected)
        if remaining_slots > 0:
            already_selected = {c["key"] for c in selected}
            remaining_f1 = [
                c for c in f1_candidates
                if c["key"] not in already_selected
            ]
            selected.extend(remaining_f1[:remaining_slots])

    else:
        # Izvan F1 vikenda nogomet ima prednost.
        selected.extend(football_candidates[:slots])

        remaining_slots = slots - len(selected)
        if remaining_slots > 0:
            selected.extend(f1_candidates[:remaining_slots])

    for candidate in selected:
        candidate.pop("_score", None)

    print(f"[Quota] Iskorišteno danas: {state.get('total_used', 0)}")
    print(f"[Quota] Preostalo: {remaining_quota(state, config)}")
    print(
        f"[Quota] Fallback iskorišteno: "
        f"{state.get('fallback_used', 0)}/{fallback_budget}"
    )

    return selected
