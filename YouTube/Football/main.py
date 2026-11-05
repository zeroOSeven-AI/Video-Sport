
import json
import requests
import re

from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE = Path(__file__).resolve().parent
YOUTUBE_DIR = BASE.parent

CONFIG_FILE = BASE / "config.json"
QUOTA_CONFIG_FILE = YOUTUBE_DIR / "quota_config.json"

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


def load_quota_config():
    if not QUOTA_CONFIG_FILE.exists():
        return {
            "event_window_hours_before": 6,
            "event_window_hours_after": 3
        }

    with QUOTA_CONFIG_FILE.open("r", encoding="utf-8") as f:
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


def normalize_name(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip().casefold()
    )


def find_matchday_ids(data):
    """
    Pronalazi matchday ID-jeve u više mogućih
    OneFootball struktura JSON feeda.

    Podržava:
    - matchdayId
    - matchday_id
    - matchday.id
    - matchdays[].id
    - matchdayOverview[].id
    - objekte čiji kontekst ili naziv označava matchday.
    """

    found = set()

    id_keys = {
        "matchdayid",
        "matchday_id",
        "matchday",
        "match_day_id"
    }

    matchday_container_keys = {
        "matchday",
        "matchdays",
        "matchdayoverview",
        "matchdaysoverview",
        "matchday_overview",
        "matchday_list"
    }

    def walk(obj, path=""):
        if isinstance(obj, dict):
            normalized_items = {
                re.sub(r"[^a-z0-9]", "", str(key).lower()): (
                    key, value
                )
                for key, value in obj.items()
            }

            # Bez obzira na dubinu, traži eksplicitni matchday ID.
            for normalized_key, (original_key, value) in normalized_items.items():
                if normalized_key in {
                    "matchdayid",
                    "matchday_id",
                    "matchday"
                }:
                    if isinstance(value, (str, int)):
                        if str(value).strip():
                            found.add(str(value).strip())

                    elif isinstance(value, dict):
                        possible_id = (
                            value.get("id")
                            or value.get("matchdayId")
                            or value.get("matchday_id")
                        )

                        if possible_id is not None:
                            found.add(str(possible_id))

            # Ako se nalazimo unutar matchday objekta,
            # njegov obični "id" također može biti ID kola.
            path_lower = path.lower()

            in_matchday_context = any(
                word in path_lower
                for word in (
                    "matchday",
                    "matchdays",
                    "matchdayoverview"
                )
            )

            if in_matchday_context:
                possible_id = obj.get("id")

                if possible_id is not None:
                    if isinstance(possible_id, (str, int)):
                        found.add(str(possible_id))

            # Rekurzivni obilazak svih vrijednosti.
            for key, value in obj.items():
                normalized_key = re.sub(
                    r"[^a-z0-9]",
                    "",
                    str(key).lower()
                )

                next_path = (
                    f"{path}.{normalized_key}"
                    if path
                    else normalized_key
                )

                if (
                    normalized_key in matchday_container_keys
                    and isinstance(value, dict)
                ):
                    possible_id = (
                        value.get("id")
                        or value.get("matchdayId")
                        or value.get("matchday_id")
                    )

                    if possible_id is not None:
                        found.add(str(possible_id))

                walk(value, next_path)

        elif isinstance(obj, list):
            for item in obj:
                walk(item, path)

    walk(data)

    return sorted(found)


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
                    or obj.get("kickoffTime")
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
            normalize_name(match["home"]),
            normalize_name(match["away"]),
            match["event_time"].isoformat()
        )

        unique[key] = match

    return list(unique.values())


def valid_channel_id(channel_id):
    if not isinstance(channel_id, str):
        return False

    return bool(
        re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id)
    )


def get_sources(config, league_name):
    target = normalize_name(league_name)

    sources = []

    for source in config.get("youtube_sources", []):
        if source.get("enabled") is not True:
            continue

        source_league = normalize_name(
            source.get("league_name")
        )

        if source_league != target:
            continue

        channel_id = source.get("channel_id")

        if not valid_channel_id(channel_id):
            continue

        sources.append(source)

    return sources


def print_feed_diagnostics(feed, league_name):
    """
    Ispisuje strukturu feeda kada ID kola nije pronađen.
    Ne ispisuje cijeli feed kako log ne bi postao prevelik.
    """

    print(
        f"[Football][Debug] Struktura feeda za {league_name}:"
    )

    if isinstance(feed, dict):
        print(
            "[Football][Debug] Top-level ključevi: "
            + ", ".join(str(key) for key in list(feed.keys())[:40])
        )

        for key, value in feed.items():
            if isinstance(value, list):
                print(
                    f"[Football][Debug] {key}: lista "
                    f"({len(value)} elemenata)"
                )

                if value and isinstance(value[0], dict):
                    print(
                        f"[Football][Debug] {key}[0] ključevi: "
                        + ", ".join(
                            str(k) for k in list(value[0].keys())[:30]
                        )
                    )

            elif isinstance(value, dict):
                print(
                    f"[Football][Debug] {key}: objekt "
                    f"({', '.join(str(k) for k in list(value.keys())[:20])})"
                )

    else:
        print(
            f"[Football][Debug] Neočekivani tip feeda: "
            f"{type(feed).__name__}"
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

    result = []
    seen = set()

    for league in config.get("leagues", []):
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

        if not matchday_ids:
            print(
                f"[Football] Nema pronađenih matchday ID-jeva: "
                f"{league_name}"
            )

            print_feed_diagnostics(feed, league_name)
            continue

        print(
            f"[Football] {league_name}: "
            f"pronađeno {len(matchday_ids)} matchday ID-jeva."
        )

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

            if not matches:
                print(
                    f"[Football] Matchday {matchday_id}: "
                    f"nisu pronađene utakmice."
                )
                continue

            active_matches = [
                match for match in matches
                if now - after
                <= match["event_time"]
                <= now + before
            ]

            if not active_matches:
                continue

            for source in sources:
                channel_id = source["channel_id"]

                match_names = [
                    f'"{match["home"]}" "{match["away"]}"'
                    for match in active_matches
                ]

                query = (
                    f"({' OR '.join(match_names)}) "
                    f'"{league_name}" highlights'
                )

                match_keys = sorted(
                    match["event_time"].isoformat()
                    + ":"
                    + normalize_name(match["home"])
                    + ":"
                    + normalize_name(match["away"])
                    for match in active_matches
                )

                key = (
                    f"football:{league_name}:"
                    f"{matchday_id}:{channel_id}"
                )

                if key in seen:
                    continue

                seen.add(key)

                importance = float(
                    league.get("importance", 1.0)
                )

                closest_match = min(
                    active_matches,
                    key=lambda match: abs(
                        (
                            match["event_time"] - now
                        ).total_seconds()
                    )
                )

                result.append({
                    "domain": "Football",
                    "key": key,
                    "query": query,
                    "channel_id": channel_id,
                    "source_name": source.get(
                        "name",
                        league_name
                    ),
                    "league": league_name,
                    "matchday_id": str(matchday_id),
                    "event_name": (
                        f"{len(active_matches)} utakmica: "
                        + ", ".join(
                            f'{m["home"]} - {m["away"]}'
                            for m in active_matches
                        )
                    ),
                    "event_time": (
                        closest_match["event_time"].isoformat()
                    ),
                    "event_times": match_keys,
                    "importance": importance
                })

    print(
        f"[Football] Kandidata: {len(result)}"
    )

    return result
