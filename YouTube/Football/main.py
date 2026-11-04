import json
import requests
from datetime import datetime, timezone

FEED_URL = (
    "https://feedmonster.onefootball.com/feeds/il/en/"
    "competitions/{competition_id}/{season}/matchdaysOverview.json"
)

MATCHDAY_URL = (
    "https://api.onefootball.com/scores-mixer/v1/en/cn/"
    "matchdays/{matchday_id}"
)


def load_config():
    with open("Football/config.json", encoding="utf-8") as f:
        return json.load(f)


def parse_datetime(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except (ValueError, TypeError):
        return None


def get_json(url):
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    response.raise_for_status()
    return response.json()


def candidates(config=None, now=None):
    config = config or load_config()

    if now is None:
        now = datetime.now(timezone.utc)

    result = []

    for league in config["leagues"]:
        url = FEED_URL.format(
            competition_id=league["id"],
            season=league["season"]
        )

        try:
            feed = get_json(url)
        except Exception as exc:
            print(f"[Football] Feed error {league['name']}: {exc}")
            continue

        # Ovaj dio treba prilagoditi stvarnoj strukturi
        # OneFootball JSON odgovora.
        matchdays = feed.get("matchdays", [])

        for matchday in matchdays:
            matchday_id = matchday.get("id")

            if not matchday_id:
                continue

            try:
                data = get_json(
                    MATCHDAY_URL.format(
                        matchday_id=matchday_id
                    )
                )
            except Exception as exc:
                print(f"[Football] Matchday error: {exc}")
                continue

            matches = data.get("matches", [])

            for match in matches:
                home = match.get("homeTeam", {}).get("name")
                away = match.get("awayTeam", {}).get("name")

                kickoff = (
                    match.get("kickoff")
                    or match.get("date")
                    or match.get("startDate")
                )

                event_time = parse_datetime(kickoff)

                if not home or not away or not event_time:
                    continue

                # Uzimamo događaje od 6 sati prije do 6 sati poslije.
                delta = (event_time - now).total_seconds() / 3600

                if not -6 <= delta <= 6:
                    continue

                query = (
                    f"{home} vs {away} football highlights "
                    f"goals match highlights"
                )

                result.append({
                    "domain": "Football",
                    "key": f"football:{home}:{away}:{event_time.isoformat()}",
                    "query": query,
                    "event_time": event_time.isoformat(),
                    "importance": league.get("importance", 1.0),
                    "event_name": f"{home} - {away}"
                })

    return result
