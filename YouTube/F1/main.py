
import json
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE = Path(__file__).resolve().parent
YOUTUBE_DIR = BASE.parent

CONFIG_FILE = BASE / "config.json"
QUOTA_CONFIG_FILE = YOUTUBE_DIR / "quota_config.json"

JOLPICA_URL = (
    "https://api.jolpi.ca/ergast/f1/{year}.json"
)

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
    date = session_data.get("date")
    time = session_data.get("time", "00:00:00Z")

    if not date:
        return None

    try:
        event_time = datetime.fromisoformat(
            f"{date}T{time.replace('Z', '+00:00')}"
        )

        if event_time.tzinfo is None:
            event_time = event_time.replace(
                tzinfo=timezone.utc
            )

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


def candidates(now=None):
    config = load_config()
    quota_config = load_quota_config()

    if now is None:
        now = datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    before = timedelta(
        hours=float(
            quota_config.get("event_window_hours_before", 6)
        )
    )

    after = timedelta(
        hours=float(
            quota_config.get("event_window_hours_after", 3)
        )
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

    sessions = config.get(
        "sessions",
        [
            "FirstPractice",
            "SecondPractice",
            "ThirdPractice",
            "Sprint",
            "Qualifying",
            "Race"
        ]
    )

    result = []
    seen = set()

    for race in races:
        race_name = race.get(
            "raceName",
            "Formula 1"
        )

        circuit = race.get(
            "Circuit", {}
        ).get(
            "circuitName",
            ""
        )

        for session in sessions:
            session_data = race.get(session)

            if not session_data:
                continue

            event_time = parse_session_time(session_data)

            if not event_time:
                continue

            if not (
                now - after
                <= event_time
                <= now + before
            ):
                continue

            importance = SESSION_IMPORTANCE.get(
                session,
                1.0
            )

            session_name = SESSION_NAMES.get(
                session,
                session
            )

            for source in sources:
                channel_id = source["channel_id"]

                key = (
                    f"f1:{race_name}:{session}:"
                    f"{event_time.isoformat()}:"
                    f"{channel_id}"
                )

                if key in seen:
                    continue

                seen.add(key)

                query = (
                    f'"{race_name}" Formula 1 '
                    f'{session_name} highlights'
                )

                result.append({
                    "domain": "F1",
                    "key": key,
                    "query": query,
                    "channel_id": channel_id,
                    "source_name": source.get(
                        "name",
                        "Formula 1"
                    ),
                    "event_name": (
                        f"{race_name} - {session_name}"
                    ),
                    "circuit": circuit,
                    "event_time": event_time.isoformat(),
                    "importance": importance
                })

    result.sort(
        key=lambda item: (
            -item["importance"],
            item["event_time"]
        )
    )

    print(f"[F1] Kandidata: {len(result)}")

    return result


def fallback_candidates():
    """
    Koristi se kada nema aktualnih F1 sesija.
    Vraća tri različita tipa F1 sadržaja.
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
                "key": (
                    item["key"]
                    + ":"
                    + source["channel_id"]
                ),
                "query": item["query"],
                "channel_id": source["channel_id"],
                "source_name": source.get(
                    "name",
                    "Formula 1"
                ),
                "event_name": "Formula 1 - Latest Content",
                "event_time": None,
                "importance": 1.0,
                "fallback": True
            })

    return result
