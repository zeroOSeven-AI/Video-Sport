
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "quota_state.json"
CONFIG_FILE = BASE_DIR / "quota_config.json"

PACIFIC = ZoneInfo("America/Los_Angeles")


# --------------------------------------------------
# CONFIGURATION AND TIME
# --------------------------------------------------

def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def now_pacific():
    return datetime.now(PACIFIC)


def today():
    return now_pacific().date().isoformat()


# --------------------------------------------------
# STATE
# --------------------------------------------------

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


def migrate_state(state):
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


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            print("[Quota] Upozorenje: stanje nije moguće pročitati.")
            state = empty_state()
    else:
        state = empty_state()

    if state.get("date") != today():
        print(
            f"[Quota] Novi dan po Pacific vremenu: "
            f"{state.get('date')} -> {today()}"
        )
        state = empty_state()

    return migrate_state(state)


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# --------------------------------------------------
# QUOTA
# --------------------------------------------------

def remaining_quota(state, config):
    """
    daily_limit je broj search.list poziva dnevno,
    a ne broj YouTube API jedinica.
    """

    limit = int(config.get("daily_limit", 100))
    reserve = int(config.get("reserve", 0))
    used = int(state.get("total_used", 0))

    return max(0, limit - reserve - used)


def can_search(state, config):
    return remaining_quota(state, config) > 0


# --------------------------------------------------
# FALLBACK DETECTION
# --------------------------------------------------

def is_fallback_key(query_key):
    if not isinstance(query_key, str):
        return False

    return (
        query_key.startswith("fallback:")
        or ":fallback:" in query_key
    )


def candidate_is_fallback(candidate):
    return (
        bool(candidate.get("fallback", False))
        or is_fallback_key(candidate.get("key", ""))
    )


# --------------------------------------------------
# RECORD SEARCH
# --------------------------------------------------

def record_success(state, domain, query_key, fallback=False):
    """
    Evidentira jedan pokušaj search.list poziva.

    Pozvati jednom neposredno prije YouTube HTTP zahtjeva.
    I neuspjeli HTTP pokušaj troši evidentirani poziv.
    """

    fallback = (
        fallback
        or is_fallback_key(query_key)
    )

    if domain not in ("Football", "F1"):
        domain = "Football"

    state["total_used"] = (
        int(state.get("total_used", 0)) + 1
    )

    state.setdefault("domain_used", {})
    state["domain_used"].setdefault(domain, 0)
    state["domain_used"][domain] += 1

    timestamp = now_pacific().isoformat()

    state.setdefault("last_query", {})
    state["last_query"][query_key] = timestamp

    if fallback:
        state["fallback_used"] = (
            int(state.get("fallback_used", 0)) + 1
        )

        state.setdefault("domain_fallback_used", {})
        state["domain_fallback_used"].setdefault(domain, 0)
        state["domain_fallback_used"][domain] += 1

        state.setdefault("last_fallback", {})
        state["last_fallback"][query_key] = timestamp

    save_state(state)


# --------------------------------------------------
# COOLDOWN
# --------------------------------------------------

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


# --------------------------------------------------
# F1 WEEKEND
# --------------------------------------------------

def is_f1_weekend(candidates):
    """
    F1 weekend marker služi samo za određivanje prioriteta.
    Nikada ne smije postati YouTube pretraga.
    """

    return any(
        candidate.get("domain") == "F1"
        and candidate.get("f1_weekend", False)
        and not candidate_is_fallback(candidate)
        for candidate in candidates
    )


# --------------------------------------------------
# PRIORITY SCORE
# --------------------------------------------------

def candidate_score(candidate, now):
    domain = candidate.get("domain", "Football")
    importance = float(candidate.get("importance", 1.0))

    score = importance * 10

    if candidate_is_fallback(candidate):
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


# --------------------------------------------------
# CANDIDATE SELECTION
# --------------------------------------------------

def select_candidates(candidates, state, config, now=None):
    """
    PRAVILA:

    1. Ukupni dnevni limit: daily_limit (zadano 100).
    2. Rezerva: reserve (zadano 0).
    3. Najviše max_per_run poziva po pokretanju (zadano 8).
    4. F1 GP vikend: do f1_race_budget stvarnih F1 pretraga dnevno.
    5. Izvan F1 vikenda nogometni događaji imaju prioritet.
    6. Ako nema F1 sesija, F1 fallback može dobiti do 2 mjesta.
    7. Ako nema stvarnih događaja, F1 fallback dobiva prva mjesta.
    8. Fallback ima zaseban dnevni budžet i cooldown.
    9. Stvarni događaji koriste opći cooldown.
    10. skip_search kandidati nikada ne troše kvotu.
    """

    available = remaining_quota(state, config)

    slots = min(
        available,
        int(config.get("max_per_run", 8))
    )

    if slots <= 0:
        print(
            "[Quota] Dosegnut dnevni limit "
            "ili rezervirana kvota."
        )
        return []

    if now is None:
        now = now_pacific()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=PACIFIC)
    else:
        now = now.astimezone(PACIFIC)

    cooldown = int(
        config.get("cooldown_minutes", 180)
    )

    fallback_cooldown = int(
        config.get("fallback_cooldown_hours", 0)
    )

    fallback_budget = int(
        config.get("fallback_budget", 100)
    )

    fallback_used = int(
        state.get("fallback_used", 0)
    )

    fallback_remaining = max(
        0,
        fallback_budget - fallback_used
    )

    active_f1 = is_f1_weekend(candidates)

    print()
    print("[Quota] --------------------------------")
    print(f"[Quota] Pacific datum: {today()}")
    print(f"[Quota] Ukupno iskorišteno: {state.get('total_used', 0)}")
    print(f"[Quota] Preostala kvota: {available}")
    print(f"[Quota] Slobodna mjesta u ovom pokretanju: {slots}")
    print(f"[Quota] Fallback potrošeno: {fallback_used}/{fallback_budget}")
    print(f"[Quota] Fallback preostalo: {fallback_remaining}")
    print(f"[Quota] F1 vikend aktivan: {'DA' if active_f1 else 'NE'}")
    print("[Quota] --------------------------------")

    # ----------------------------------------------
    # FILTER CANDIDATES
    # ----------------------------------------------

    eligible = []

    for candidate in candidates:

        # Interni marker nije YouTube pretraga.
        if candidate.get("skip_search", False):
            continue

        key = candidate.get("key")

        if not key:
            print("[Quota] Odbijen kandidat: nedostaje key.")
            continue

        domain = candidate.get("domain", "Football")

        if domain not in ("Football", "F1"):
            print(f"[Quota] Odbijen {key}: nepoznata domena.")
            continue

        is_fallback = candidate_is_fallback(candidate)

        if is_fallback:
            if fallback_remaining <= 0:
                continue

            if not fallback_cooldown_passed(
                state,
                key,
                fallback_cooldown
            ):
                print(
                    f"[Quota] Odbijen {key}: "
                    f"fallback cooldown ({fallback_cooldown} h)."
                )
                continue

        else:
            if not cooldown_passed(
                state,
                key,
                cooldown
            ):
                print(
                    f"[Quota] Odbijen {key}: "
                    f"opći cooldown ({cooldown} min)."
                )
                continue

        item = candidate.copy()
        item["fallback"] = is_fallback
        item["_score"] = candidate_score(item, now)

        eligible.append(item)

    if not eligible:
        print(
            "[Quota] Nema kandidata nakon provjere "
            "cooldowna i budžeta."
        )
        return []

    # ----------------------------------------------
    # SPLIT CANDIDATES
    # ----------------------------------------------

    football_events = [
        item for item in eligible
        if item.get("domain") == "Football"
        and not item["fallback"]
    ]

    f1_events = [
        item for item in eligible
        if item.get("domain") == "F1"
        and not item["fallback"]
    ]

    football_fallbacks = [
        item for item in eligible
        if item.get("domain") == "Football"
        and item["fallback"]
    ]

    f1_fallbacks = [
        item for item in eligible
        if item.get("domain") == "F1"
        and item["fallback"]
    ]

    has_events = bool(
        football_events or f1_events
    )

    # Fallback se ne koristi ako postoje stvarni
    # događaji iste domene.
    if football_events:
        football_fallbacks = []

    if f1_events or active_f1:
        f1_fallbacks = []

    # ----------------------------------------------
    # SORT
    # ----------------------------------------------

    for pool in (
        football_events,
        f1_events,
        football_fallbacks,
        f1_fallbacks
    ):
        pool.sort(
            key=lambda item: item["_score"],
            reverse=True
        )

    # ----------------------------------------------
    # F1 DAILY EVENT BUDGET
    # ----------------------------------------------

    f1_budget = int(
        config.get("f1_race_budget", 10)
    )

    domain_used = state.get("domain_used", {})
    domain_fallback_used = state.get(
        "domain_fallback_used", {}
    )

    f1_total_used = int(
        domain_used.get("F1", 0)
    )

    f1_fallback_used = int(
        domain_fallback_used.get("F1", 0)
    )

    f1_event_used = max(
        0,
        f1_total_used - f1_fallback_used
    )

    f1_event_remaining = max(
        0,
        f1_budget - f1_event_used
    )

    print(
        f"[Quota] F1 stvarne pretrage: "
        f"{f1_event_used}/{f1_budget}"
    )

    # ----------------------------------------------
    # SELECTION HELPERS
    # ----------------------------------------------

    selected = []
    selected_keys = set()
    selected_fallback_count = 0
    selected_f1_events = 0

    def add_candidates(pool, limit=None):
        nonlocal selected_fallback_count
        nonlocal selected_f1_events
        nonlocal fallback_remaining

        added = 0

        for candidate in pool:

            if len(selected) >= slots:
                break

            if limit is not None and added >= limit:
                break

            key = candidate["key"]

            if key in selected_keys:
                continue

            is_fallback = candidate["fallback"]

            if is_fallback and fallback_remaining <= 0:
                break

            if (
                candidate.get("domain") == "F1"
                and not is_fallback
                and selected_f1_events >= f1_event_remaining
            ):
                continue

            selected.append(candidate)
            selected_keys.add(key)
            added += 1

            if is_fallback:
                selected_fallback_count += 1
                fallback_remaining -= 1

            elif candidate.get("domain") == "F1":
                selected_f1_events += 1

        return added

    # ----------------------------------------------
    # ACTIVE F1 WEEKEND
    # ----------------------------------------------

    if active_f1:

        print("[Quota] Prioritet: aktivni F1 GP vikend.")

        # Prvo stvarne F1 sesije, do dnevnog F1 limita.
        add_candidates(
            f1_events,
            min(f1_event_remaining, slots)
        )

        # Zatim nogometni događaji.
        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            add_candidates(
                football_events,
                remaining_slots
            )

    # ----------------------------------------------
    # OUTSIDE F1 WEEKEND
    # ----------------------------------------------

    elif has_events:

        print(
            "[Quota] Nema aktivnog F1 vikenda. "
            "Prioritet: nogometni događaji."
        )

        # Nogomet uvijek prvi.
        add_candidates(
            football_events,
            slots
        )

        remaining_slots = slots - len(selected)

        # Zatim stvarne F1 sesije, ako ih ima.
        if remaining_slots > 0:
            add_candidates(
                f1_events,
                remaining_slots
            )

        # Ako nema F1 sesija, F1 fallback može dobiti
        # do dva slobodna mjesta. Ne izbacuje već
        # odabrane nogometne događaje.
        remaining_slots = slots - len(selected)

        if remaining_slots > 0 and not f1_events:
            add_candidates(
                f1_fallbacks,
                min(2, remaining_slots)
            )

    # ----------------------------------------------
    # NO REAL EVENTS: FALLBACK MODE
    # ----------------------------------------------

    else:

        print(
            "[Quota] Nema stvarnih događaja. "
            "Pokreće se fallback."
        )

        # F1 dobiva do dva početna mjesta.
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

        # Ostatak dobiva nogomet.
        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            add_candidates(
                football_fallbacks,
                remaining_slots
            )

        # Ako ima još mjesta, dodaj preostale F1 fallbacks.
        remaining_slots = slots - len(selected)

        if remaining_slots > 0:
            add_candidates(
                f1_fallbacks,
                remaining_slots
            )

    # ----------------------------------------------
    # CLEANUP
    # ----------------------------------------------

    for candidate in selected:
        candidate.pop("_score", None)

    # ----------------------------------------------
    # SUMMARY
    # ----------------------------------------------

    selected_f1 = sum(
        1 for item in selected
        if item.get("domain") == "F1"
    )

    selected_football = sum(
        1 for item in selected
        if item.get("domain") == "Football"
    )

    print()
    print("[Quota] ========= REZULTAT ODABIRA =========")
    print(f"[Quota] Odabrano ukupno: {len(selected)}")
    print(f"[Quota] F1 kandidati: {selected_f1}")
    print(f"[Quota] Football kandidati: {selected_football}")
    print(f"[Quota] Fallback kandidati: {selected_fallback_count}")
    print(f"[Quota] Fallback preostalo: {fallback_remaining}")
    print("[Quota] ====================================")
    print()

    return selected
