
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
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def remaining_quota(state, config):
    limit = int(config.get("daily_limit", 100))
    reserve = int(config.get("reserve", 10))

    return max(
        0,
        limit - reserve - int(state.get("total_used", 0))
    )


def can_search(state, config):
    return remaining_quota(state, config) > 0


def record_success(state, domain, query_key):
    """
    Evidentira jedan pokušaj search.list poziva.
    Pozivati prije slanja zahtjeva kako lokalno stanje
    ne bi podcijenilo potrošnju kod mrežnih grešaka.
    """

    state["total_used"] = (
        int(state.get("total_used", 0)) + 1
    )

    state.setdefault("domain_used", {})
    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    state.setdefault("last_query", {})
    state["last_query"][query_key] = (
        now_pacific().isoformat()
    )

    if query_key.startswith("fallback:") or ":fallback:" in query_key:
        state.setdefault("last_fallback", {})
        state["last_fallback"][query_key] = (
            now_pacific().isoformat()
        )

    save_state(state)


def cooldown_passed(state, query_key, minutes):
    previous = state.get("last_query", {}).get(query_key)

    if not previous:
        return True

    try:
        last = datetime.fromisoformat(previous)
    except (ValueError, TypeError):
        return True

    now = now_pacific()

    if last.tzinfo is None:
        last = last.replace(tzinfo=PACIFIC)

    return now - last >= timedelta(minutes=minutes)


def is_f1_weekend(candidates):
    """
    F1 vikend prepoznaje prema postojanju aktualnih
    F1 sesija u kandidatima.
    """
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
        score += 5

        if domain == "F1":
            score += 5

        return score

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
    Odabire kandidate prema prioritetu.

    Pravila:
    - Bez F1 vikenda: nogomet ima prednost.
    - Tijekom F1 vikenda: do f1_race_budget pretraga za F1.
    - Fallback se obrađuje kada nema aktivnih događaja.
    - Poštuje dnevni limit i cooldown.
    """

    available = remaining_quota(state, config)

    slots = min(
        available,
        int(config.get("max_per_run", 8))
    )

    if slots <= 0:
        print("[Quota] Dosegnut dnevni limit.")
        return []

    if now is None:
        now = now_pacific()

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(PACIFIC)

    cooldown = int(
        config.get("cooldown_minutes", 180)
    )

    eligible = []

    for candidate in candidates:
        key = candidate.get("key")

        if not key:
            continue

        if not cooldown_passed(state, key, cooldown):
            continue

        candidate["_score"] = candidate_score(
            candidate,
            now
        )

        eligible.append(candidate)

    if not eligible:
        return []

    has_events = any(
        not candidate.get("fallback", False)
        for candidate in eligible
    )

    # Fallback ima smisla samo kada nema aktualnih događaja.
    if has_events:
        eligible = [
            candidate
            for candidate in eligible
            if not candidate.get("fallback", False)
        ]

    active_f1 = is_f1_weekend(eligible)

    f1_budget = int(
        config.get("f1_race_budget", 10)
    )

    f1_used_today = int(
        state.get("domain_used", {}).get("F1", 0)
    )

    selected = []

    if active_f1:
        f1_remaining = max(
            0,
            f1_budget - f1_used_today
        )

        f1_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("domain") == "F1"
        ]

        football_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("domain") == "Football"
        ]

        f1_candidates.sort(
            key=lambda item: item["_score"],
            reverse=True
        )

        football_candidates.sort(
            key=lambda item: item["_score"],
            reverse=True
        )

        # F1 dobiva svoj budžet tijekom vikenda.
        selected.extend(
            f1_candidates[:min(f1_remaining, slots)]
        )

        remaining_slots = slots - len(selected)

        # Ostatak ide nogometu.
        selected.extend(
            football_candidates[:remaining_slots]
        )

        # Ako nema nogometnih kandidata, popuni slobodna mjesta F1.
        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            already_selected = {
                item["key"] for item in selected
            }

            selected.extend([
                item
                for item in f1_candidates
                if item["key"] not in already_selected
            ][:remaining_slots])

    else:
        # Kada nema F1 vikenda, nogomet ima prednost.
        football_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("domain") == "Football"
        ]

        f1_candidates = [
            candidate
            for candidate in eligible
            if candidate.get("domain") == "F1"
        ]

        football_candidates.sort(
            key=lambda item: item["_score"],
            reverse=True
        )

        f1_candidates.sort(
            key=lambda item: item["_score"],
            reverse=True
        )

        selected.extend(football_candidates[:slots])

        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            selected.extend(
                f1_candidates[:remaining_slots]
            )

    # Uklanjamo interni score prije vraćanja kandidata.
    for candidate in selected:
        candidate.pop("_score", None)

    print(
        f"[Quota] Iskorišteno danas: "
        f"{state.get('total_used', 0)}"
    )

    print(
        f"[Quota] Preostalo: "
        f"{remaining_quota(state, config)}"
    )

    return selected
