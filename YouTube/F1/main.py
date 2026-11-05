
import json
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE = Path(__file__).resolve().parent
YOUTUBE_DIR = BASE.parent

CONFIG_FILE = BASE / "config.json"
QUOTA_CONFIG_FILE = YOUTUBE_DIR / "quota_config.json"

JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/{year}.json"

SESSION_IMPORTANCE = {
    "Race": 2.0,
    "Qualifying": 1.6,
    "Sprint": 1.5,
    "ThirdPractice": 1.2,
    "SecondPractice": 1.1,
    "FirstPractice": 1.0
}

SESSION_NAMES = {
    "Race": "Race",
    "Qualifying": "Qualifying",
    "Sprint": "Sprint",
    "ThirdPractice": "Third Practice",
    "SecondPractice": "Second Practice",
    "FirstPractice": "First Practice"
}

DEFAULT_SESSIONS = [
    "FirstPractice",
    "SecondPractice",
    "ThirdPractice",
    "Sprint",
    "Qualifying",
    "Race"
]


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_quota_config():
    if not QUOTA_CONFIG_FILE.exists():
        return {
            "event_window_hours_before": 6,
            "event_window_hours_after": 3
        }

    with QUOTA_CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_schedule(year):
    response = requests.get(
        JOLPICA_URL.format(year=year),
        params={"limit": 100},
        timeout=25
    )
    response.raise_for_status()
    return response.json()


def valid_channel_id(channel_id):
    import re

    return (
        isinstance(channel_id, str)
        and bool(re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id))
    )


def parse_session_time(session_data):
    if not isinstance(session_data, dict):
        return None

    date = session_data.get("date")
    time = session_data.get("time", "00:00:00Z")

    if not date:
        return None

    try:
        event_time = datetime.fromisoformat(
            f"{date}T{time.replace('Z', '+00:00')}"
        )

        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        return event_time.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def get_sources(config):
    return [
        source
        for source in config.get("youtube_sources", [])
        if source.get("enabled") is True
        and valid_channel_id(source.get("channel_id"))
    ]


def get_races(year):
    data = get_schedule(year)

    return (
        data.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )


def get_race_sessions(race, sessions):
    result = []

    for session in sessions:
        session_data = race.get(session)

        if not session_data:
            continue

        event_time = parse_session_time(session_data)

        if event_time:
            result.append((session, event_time))

    return result


def is_race_weekend_active(race, sessions, now):
    """
    Vikend traje od prve zakazane sesije do 6 sati
    nakon posljednje zakazane sesije.
    """
    race_sessions = get_race_sessions(race, sessions)

    if not race_sessions:
        return False

    start_time = min(event_time for _, event_time in race_sessions)
    end_time = max(event_time for _, event_time in race_sessions)

    weekend_end = end_time + timedelta(hours=6)

    return start_time <= now <= weekend_end


def make_weekend_marker(race, now, sources):
    """
    Interni marker. Ne predstavlja YouTube pretragu i ne troši kvotu.
    Služi samo da quota_manager zna da je F1 vikend aktivan.
    """
    race_name = race.get("raceName", "Formula 1")
    round_number = race.get("round", "unknown")

    return {
        "domain": "F1",
        "key": f"f1:weekend_marker:{round_number}:{race_name}",
        "query": "",
        "channel_id": sources[0]["channel_id"],
        "source_name": sources[0].get("name", "Formula 1"),
        "event_name": f"{race_name} - Active Grand Prix Weekend",
        "event_time": None,
        "importance": 0,
        "fallback": False,
        "f1_weekend": True,
        "skip_search": True
    }


def candidates(now=None):
    config = load_config()
    quota_config = load_quota_config()

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    before = timedelta(
        hours=float(quota_config.get("event_window_hours_before", 6))
    )
    after = timedelta(
        hours=float(quota_config.get("event_window_hours_after", 3))
    )

    sources = get_sources(config)

    if not sources:
        print("[F1] Nema valjanih YouTube kanala.")
        return []

    try:
        races = get_races(now.year)
    except Exception as exc:
        print(f"[F1] Greška pri dohvaćanju rasporeda: {exc}")
        return []

    sessions = config.get("sessions", DEFAULT_SESSIONS)

    result = []
    seen = set()
    active_weekends = []

    for race in races:
        race_name = race.get("raceName", "Formula 1")
        circuit = race.get("Circuit", {}).get("circuitName", "")

        race_sessions = get_race_sessions(race, sessions)

        if not race_sessions:
            continue

        # Prepoznaj cijeli Grand Prix vikend, ne samo pojedinu sesiju.
        if is_race_weekend_active(race, sessions, now):
            active_weekends.append(race)
            result.append(
                make_weekend_marker(race, now, sources)
            )

        # Stvarne pretrage stvaramo samo u zadanom prozoru.
        for session, event_time in race_sessions:
            if not (now - after <= event_time <= now + before):
                continue

            importance = SESSION_IMPORTANCE.get(session, 1.0)
            session_name = SESSION_NAMES.get(session, session)

            for source in sources:
                channel_id = source["channel_id"]

                key = (
                    f"f1:{race_name}:{session}:"
                    f"{event_time.isoformat()}:{channel_id}"
                )

                if key in seen:
                    continue

                seen.add(key)

                result.append({
                    "domain": "F1",
                    "key": key,
                    "query": (
                        f'"{race_name}" Formula 1 '
                        f'{session_name} highlights'
                    ),
                    "channel_id": channel_id,
                    "source_name": source.get("name", "Formula 1"),
                    "event_name": f"{race_name} - {session_name}",
                    "circuit": circuit,
                    "event_time": event_time.isoformat(),
                    "importance": importance,
                    "fallback": False
                })

    result.sort(
        key=lambda item: (
            item.get("skip_search", False),
            -item.get("importance", 0),
            item.get("event_time") or ""
        )
    )

    print(f"[F1] Aktivnih Grand Prix vikenda: {len(active_weekends)}")
    print(
        f"[F1] Kandidata za stvarne pretrage: "
        f"{sum(not c.get('skip_search', False) for c in result)}"
    )

    return result


def fallback_candidates():
    """
    Koristi se kada nema aktualnih događaja.
    Vraća tri tipa F1 sadržaja po službenom kanalu.
    """
    config = load_config()
    sources = get_sources(config)

    if not sources:
        return []

    fallback_queries = [
        {
            "key": "f1:fallback:latest_news",
            "query": "Formula 1 latest news analysis"
        },
        {
            "key": "f1:fallback:technical",
            "query": "Formula 1 technical analysis car updates"
        },
        {
            "key": "f1:fallback:interviews",
            "query": "Formula 1 driver interviews latest"
        }
    ]

    result = []

    for source in sources:
        for item in fallback_queries:
            result.append({
                "domain": "F1",
                "key": item["key"] + ":" + source["channel_id"],
                "query": item["query"],
                "channel_id": source["channel_id"],
                "source_name": source.get("name", "Formula 1"),
                "event_name": "Formula 1 - Latest Content",
                "event_time": None,
                "importance": 1.0,
                "fallback": True
            })

    return result
