import json
import requests
import re

from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"

FEED_URL = (
    "https://feedmonster.onefootball.com/feeds/il/en/"
    "competitions/{league_id}/{season}/matchdaysOverview.json"
)

MATCHDAY_URL = (
    "https://api.onefootball.com/scores-mixer/v1/en/cn/"
    "matchdays/{matchday_id}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_json(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=25
    )
    response.raise_for_status()
    return response.json()


def parse_time(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def find_matchday_ids(data):
    """Pronalazi ID-jeve matchday objekata u feedu."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                normalized = key.lower().replace("_", "")

                if normalized in (
                    "matchdayid",
                    "matchday_id"
                ):
                    if value is not None:
                        found.add(str(value))

                if normalized == "matchday" and isinstance(value, dict):
                    matchday_id = value.get("id")
                    if matchday_id is not None:
                        found.add(str(matchday_id))

                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return list(found)


def get_team_name(team):
    if isinstance(team, str):
        return team

    if isinstance(team, dict):
        return (
            team.get("name")
            or team.get("shortName")
            or team.get("displayName")
            or team.get("title")
        )

    return None


def extract_matches(data):
    """
    Pokušava pronaći utakmice u različitim OneFootball
    JSON strukturama. Polja treba potvrditi prema stvarnom
    odgovoru endpointa.
    """
    matches = []

    def walk(obj):
        if isinstance(obj, dict):
            home_obj = (
                obj.get("homeTeam")
                or obj.get("home")
                or obj.get("home_team")
            )

            away_obj = (
                obj.get("awayTeam")
                or obj.get("away")
                or obj.get("away_team")
            )

            home = get_team_name(home_obj)
            away = get_team_name(away_obj)

            if home and away:
                time_value = (
                    obj.get("kickoff")
                    or obj.get("date")
                    or obj.get("startDate")
                    or obj.get("utcDate")
                    or obj.get("startTime")
                )

                event_time = parse_time(time_value)

                if event_time:
                    matches.append({
                        "home": home,
                        "away": away,
                        "event_time": event_time
                    })

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    unique = {}

    for match in matches:
        key = (
            match["home"].lower(),
            match["away"].lower(),
            match["event_time"].isoformat()
        )
        unique[key] = match

    return list(unique.values())


def valid_channel_id(channel_id):
    if not isinstance(channel_id, str):
        return False

    if not channel_id.startswith("UC"):
        return False

    if channel_id.startswith("UC_CHANNEL_ID_"):
        return False

    return bool(re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", channel_id))


def get_sources(config, league_name):
    return [
        source
        for source in config.get("youtube_sources", [])
        if source.get("enabled") is True
        and source.get("league_name") == league_name
        and valid_channel_id(source.get("channel_id"))
    ]


def candidates(now=None):
    config = load_config()

    if now is None:
        now = datetime.now(timezone.utc)

    now = now.astimezone(timezone.utc)

    before = timedelta(hours=6)
    after = timedelta(hours=6)

    result = []

    for league in config["leagues"]:
        league_name = league["name"]

        sources = get_sources(config, league_name)

        if not sources:
            print(
                f"[Football] Nema valjanih YouTube kanala: "
                f"{league_name}"
            )
            continue

        feed_url = FEED_URL.format(
            league_id=league["id"],
            season=league["season"]
        )

        try:
            feed = get_json(feed_url)
        except Exception as exc:
            print(
                f"[Football] Greška feeda {league_name}: {exc}"
            )
            continue

        matchday_ids = find_matchday_ids(feed)

        for matchday_id in matchday_ids:
            try:
                matchday = get_json(
                    MATCHDAY_URL.format(
                        matchday_id=matchday_id
                    )
                )
            except Exception as exc:
                print(
                    f"[Football] Matchday {matchday_id}: {exc}"
                )
                continue

            matches = extract_matches(matchday)

            for match in matches:
                event_time = match["event_time"]

                if not now - after <= event_time <= now + before:
                    continue

                home = match["home"]
                away = match["away"]

                for source in sources:
                    query = (
                        f'"{home}" "{away}" '
                        f'{league_name} highlights'
                    )

                    key = (
                        f"football:{league_name}:"
                        f"{home}:{away}:"
                        f"{event_time.isoformat()}:"
                        f"{source['channel_id']}"
                    )

                    result.append({
                        "domain": "Football",
                        "key": key,
                        "query": query,
                        "channel_id": source["channel_id"],
                        "source_name": source["name"],
                        "league": league_name,
                        "event_name": f"{home} - {away}",
                        "event_time": event_time.isoformat(),
                        "importance": float(
                            league.get("importance", 1.0)
                        )
                    })

    return result
