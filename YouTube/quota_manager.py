
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
        "domain_fallback_used": {
            "Football": 0,
            "F1": 0
        },
        "last_query": {},
        "last_fallback": {}
    }


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
        print(
            f"[Quota] Novi dan po Pacific vremenu: "
            f"{state.get('date')} -> {today()}. Resetiram dnevno stanje."
        )
        state = empty_state()

    state.setdefault("total_used", 0)
    state.setdefault("fallback_used", 0)
    state.setdefault("domain_used", {})
    state.setdefault("domain_fallback_used", {})
    state.setdefault("last_query", {})
    state.setdefault("last_fallback", {})

    for domain in ("Football", "F1"):
        state["domain_used"].setdefault(domain, 0)
        state["domain_fallback_used"].setdefault(domain, 0)

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
    used = int(state.get("total_used", 0))

    return max(0, limit - reserve - used)


def can_search(state, config):
    return remaining_quota(state, config) > 0


def is_fallback_key(query_key):
    return (
        query_key.startswith("fallback:")
        or ":fallback:" in query_key
    )


def record_success(state, domain, query_key, fallback=False):
    """
    Evidentira pokušaj YouTube search.list poziva.
    Poziva se prije HTTP zahtjeva radi konzervativnog
    praćenja potrošnje kvote.
    """

    fallback = fallback or is_fallback_key(query_key)

    state["total_used"] = int(
        state.get("total_used", 0)
    ) + 1

    state.setdefault("domain_used", {})
    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    timestamp = now_pacific().isoformat()

    state.setdefault("last_query", {})
    state["last_query"][query_key] = timestamp

    if fallback:
        state["fallback_used"] = int(
            state.get("fallback_used", 0)
        ) + 1

        state.setdefault("domain_fallback_used", {})
        state["domain_fallback_used"].setdefault(domain, 0)
        state["domain_fallback_used"][domain] += 1

        state.setdefault("last_fallback", {})
        state["last_fallback"][query_key] = timestamp

    save_state(state)


def parse_timestamp(value):
    try:
        last = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None

    if last.tzinfo is None:
        last = last.replace(tzinfo=PACIFIC)

    return last.astimezone(PACIFIC)


def cooldown_passed(state, query_key, minutes):
    previous = state.get("last_query", {}).get(query_key)

    if not previous:
        return True

    last = parse_timestamp(previous)

    if last is None:
        return True

    return (
        now_pacific() - last
        >= timedelta(minutes=minutes)
    )


def fallback_cooldown_passed(state, query_key, hours):
    previous = state.get("last_fallback", {}).get(query_key)

    if not previous:
        return True

    last = parse_timestamp(previous)

    if last is None:
        return True

    return (
        now_pacific() - last
        >= timedelta(hours=hours)
    )


def is_f1_weekend(candidates):
    return any(
        candidate.get("domain") == "F1"
        and candidate.get("f1_weekend", False)
        and not candidate.get("fallback", False)
        for candidate in candidates
    )


def candidate_score(candidate, now):
    domain = candidate.get("domain", "Football")
    importance = float(candidate.get("importance", 1.0))

    score = importance * 10

    if candidate.get("fallback", False):
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

            hours = (
                event - now
            ).total_seconds() / 3600

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
    - max_per_run
    - općeg cooldowna
    - fallback cooldowna
    - fallback_budget
    - f1_race_budget samo za stvarne F1 event pretrage
    - prioriteta nogometa izvan F1 vikenda

    F1 fallback pretrage NE troše f1_race_budget.
    """

    available = remaining_quota(state, config)

    slots = min(
        available,
        int(config.get("max_per_run", 8))
    )

    if slots <= 0:
        print("[Quota] Dosegnut dnevni limit ili rezervirana kvota.")
        return []

    if now is None:
        now = now_pacific()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=PACIFIC)
    else:
        now = now.astimezone(PACIFIC)

    cooldown = int(config.get("cooldown_minutes", 180))

    fallback_cooldown = int(
        config.get("fallback_cooldown_hours", 12)
    )

    fallback_budget = int(
        config.get("fallback_budget", 10)
    )

    fallback_used = int(
        state.get("fallback_used", 0)
    )

    fallback_remaining = max(
        0,
        fallback_budget - fallback_used
    )

    active_f1 = is_f1_weekend(candidates)

    print(f"[Quota] Pacific datum: {today()}")
    print(f"[Quota] Ukupno iskorišteno: {state.get('total_used', 0)}")
    print(f"[Quota] Preostala kvota: {available}")
    print(f"[Quota] Slobodna mjesta za pokretanje: {slots}")
    print(
        f"[Quota] Fallback budžet: "
        f"{fallback_used}/{fallback_budget}"
    )
    print(f"[Quota] Fallback preostalo: {fallback_remaining}")
    print(f"[Quota] F1 vikend aktivan: {'DA' if active_f1 else 'NE'}")

    eligible = []

    for candidate in candidates:
        if candidate.get("skip_search", False):
            continue

        key = candidate.get("key")

        if not key:
            print("[Quota] Odbijen kandidat bez query key vrijednosti.")
            continue

        domain = candidate.get("domain", "Football")
        is_fallback = candidate.get("fallback", False)

        if not cooldown_passed(state, key, cooldown):
            print(f"[Quota] Odbijen {key}: opći cooldown.")
            continue

        if is_fallback:
            if fallback_remaining <= 0:
                print(f"[Quota] Odbijen {key}: fallback budžet potrošen.")
                continue

            if not fallback_cooldown_passed(
                state,
                key,
                fallback_cooldown
            ):
                print(f"[Quota] Odbijen {key}: fallback cooldown.")
                continue

        candidate_copy = candidate.copy()

        candidate_copy["_score"] = candidate_score(
            candidate_copy,
            now
        )

        eligible.append(candidate_copy)

    if not eligible:
        print(
            "[Quota] Nema kandidata nakon provjere "
            "cooldowna i budžeta."
        )
        return []

    # Ako postoje dostupni stvarni događaji,
    # fallback se ne koristi u istom pokretanju.
    has_events = any(
        not candidate.get("fallback", False)
        for candidate in eligible
    )

    if has_events:
        eligible = [
            candidate for candidate in eligible
            if not candidate.get("fallback", False)
        ]

    football_candidates = [
        candidate for candidate in eligible
        if candidate.get("domain") == "Football"
    ]

    f1_candidates = [
        candidate for candidate in eligible
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

    selected = []
    selected_keys = set()
    selected_fallback_count = 0

    def add_candidates(pool, limit):
        nonlocal selected_fallback_count

        added = 0

        for candidate in pool:
            if len(selected) >= slots:
                break

            key = candidate["key"]

            if key in selected_keys:
                continue

            is_fallback = candidate.get("fallback", False)

            if is_fallback:
                if selected_fallback_count >= fallback_remaining:
                    continue

            selected.append(candidate)
            selected_keys.add(key)

            if is_fallback:
                selected_fallback_count += 1

            added += 1

            if added >= limit:
                break

        return added

    if active_f1:
        # F1 GP vikend: budžet se računa samo za stvarne
        # F1 event pretrage, ne za fallback.
        f1_budget = int(
            config.get("f1_race_budget", 10)
        )

        f1_total = int(
            state.get("domain_used", {}).get("F1", 0)
        )

        f1_fallback_total = int(
            state.get("domain_fallback_used", {}).get("F1", 0)
        )

        f1_event_used = max(
            0,
            f1_total - f1_fallback_total
        )

        f1_remaining = max(
            0,
            f1_budget - f1_event_used
        )

        print(
            f"[Quota] F1 event budžet: "
            f"{f1_event_used}/{f1_budget}"
        )

        add_candidates(
            f1_candidates,
            min(f1_remaining, slots)
        )

        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            add_candidates(
                football_candidates,
                remaining_slots
            )

        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            add_candidates(
                f1_candidates,
                remaining_slots
            )

    else:
        if has_events:
            # Izvan F1 vikenda: nogomet ima prioritet.
            add_candidates(
                football_candidates,
                slots
            )

            remaining_slots = slots - len(selected)

            if remaining_slots > 0:
                add_candidates(
                    f1_candidates,
                    remaining_slots
                )

        else:
            # Nema stvarnih događaja: fallback.
            # Nogomet zadržava prioritet, ali F1 dobiva
            # do dva mjesta kako ne bi stalno bio preskočen.
            f1_fallbacks = [
                item for item in f1_candidates
                if item.get("fallback", False)
            ]

            football_fallbacks = [
                item for item in football_candidates
                if item.get("fallback", False)
            ]

            f1_reserved = min(
                2,
                len(f1_fallbacks),
                slots,
                fallback_remaining
            )

            if f1_reserved > 0:
                add_candidates(
                    f1_fallbacks,
                    f1_reserved
                )

            remaining_slots = slots - len(selected)

            if remaining_slots > 0:
                add_candidates(
                    football_fallbacks,
                    remaining_slots
                )

            remaining_slots = slots - len(selected)

            if remaining_slots > 0:
                add_candidates(
                    f1_fallbacks,
                    remaining_slots
                )

    for candidate in selected:
        candidate.pop("_score", None)

    print(f"[Quota] Odabrano kandidata: {len(selected)}")
    print(
        f"[Quota] Odabrani fallback kandidati: "
        f"{selected_fallback_count}"
    )

    print(
        f"[Quota] F1 ukupno pretraga danas: "
        f"{state.get('domain_used', {}).get('F1', 0)}"
    )

    print(
        f"[Quota] F1 fallback pretraga danas: "
        f"{state.get('domain_fallback_used', {}).get('F1', 0)}"
    )

    print(
        f"[Quota] Football ukupno pretraga danas: "
        f"{state.get('domain_used', {}).get('Football', 0)}"
    )

    return selected
