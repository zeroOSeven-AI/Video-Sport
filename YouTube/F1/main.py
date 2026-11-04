import json
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"

JOLPICA_URL = (
    "https://api.jolpi.ca/ergast/f1/{year}.json"
)


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
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
    return (
        isinstance(channel_id, str)
        and channel_id.startswith("UC")
        and not channel_id.startswith("UC_CHANNEL_ID_")
        and len(channel_id) >= 24
    )


def candidates(now=None):
    config = load_config()

    if now is None:
        now = datetime.now(timezone.utc)

    now = now.astimezone(timezone.utc)

    sources = [
        source
        for source in config.get("youtube_sources", [])
        if source.get("enabled") is True
        and valid_channel_id(source.get("channel_id"))
    ]

    if not sources:
        print("[F1] Nema valjanih YouTube kanala.")
        return []

    data = get_schedule(now.year)

    races = (
        data.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

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

    for race in races:
        race_name = race.get("raceName", "Formula 1")
        circuit = race.get("Circuit", {}).get(
            "circuitName", ""
        )

        for session in sessions:
            session_data = race.get(session)

            if not session_data:
                continue

            date = session_data.get("date")
            time = session_data.get("time", "00:00:00Z")

            if not date:
                continue

            try:
                event_time = datetime.fromisoformat(
                    f"{date}T{time.replace('Z', '+00:00')}"
                )
            except ValueError:
                continue

            if event_time.tzinfo is None:
                event_time = event_time.replace(
                    tzinfo=timezone.utc
                )

            event_time = event_time.astimezone(timezone.utc)

            if not (
                now - timedelta(hours=6)
                <= event_time
                <= now + timedelta(hours=6)
            ):
                continue

            if session == "Race":
                importance = 1.6
            elif session == "Qualifying":
                importance = 1.4
            elif session == "Sprint":
                importance = 1.3
            else:
                importance = 1.0

            for source in sources:
                query = (
                    f"Formula 1 F1 {race_name} "
                    f"{session} highlights"
                )

                key = (
                    f"f1:{race_name}:{session}:"
                    f"{event_time.isoformat()}:"
                    f"{source['channel_id']}"
                )

                result.append({
                    "domain": "F1",
                    "key": key,
                    "query": query,
                    "channel_id": source["channel_id"],
                    "source_name": source["name"],
                    "event_name": f"{race_name} - {session}",
                    "circuit": circuit,
                    "event_time": event_time.isoformat(),
                    "importance": importance
                })

    return result
