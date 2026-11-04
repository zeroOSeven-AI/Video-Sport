import requests
from datetime import datetime, timezone

JOLPICA_URL = (
    "https://api.jolpi.ca/ergast/f1/{year}.json"
)


def get_schedule(year):
    response = requests.get(
        JOLPICA_URL.format(year=year),
        timeout=20
    )

    response.raise_for_status()

    return response.json()


def candidates(now=None):
    if now is None:
        now = datetime.now(timezone.utc)

    year = now.year
    data = get_schedule(year)

    races = (
        data.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    result = []

    session_names = [
        "FirstPractice",
        "SecondPractice",
        "ThirdPractice",
        "Sprint",
        "Qualifying",
        "Race"
    ]

    for race in races:
        race_name = race.get("raceName", "Formula 1")
        circuit = race.get("Circuit", {}).get("circuitName", "")

        for session in session_names:
            session_data = race.get(session)

            if not session_data:
                continue

            date = session_data.get("date")
            time = session_data.get("time", "00:00:00Z")

            if not date:
                continue

            event_time = datetime.fromisoformat(
                f"{date}T{time.replace('Z', '+00:00')}"
            )

            delta = (
                event_time - now
            ).total_seconds() / 3600

            if not -6 <= delta <= 6:
                continue

            query = (
                f"Formula 1 F1 {race_name} "
                f"{session} highlights"
            )

            result.append({
                "domain": "F1",
                "key": (
                    f"f1:{race_name}:{session}:"
                    f"{event_time.isoformat()}"
                ),
                "query": query,
                "event_time": event_time.isoformat(),
                "importance": (
                    1.6 if session == "Race"
                    else 1.4 if session == "Qualifying"
                    else 1.2 if session == "Sprint"
                    else 1.0
                ),
                "event_name": f"{race_name} - {session}"
            })

    return result
