import json
import re
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE = Path(__file__).resolve().parent
YOUTUBE_DIR = BASE.parent

CONFIG_FILE = BASE / "config.json"
QUOTA_CONFIG_FILE = YOUTUBE_DIR / "quota_config.json"

API_BASE = "https://api.motogp.pulselive.com/motogp/v1"
API_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.motogp.com",
    "Referer": "https://www.motogp.com/",
    "User-Agent": "Mozilla/5.0"
}

CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_quota_config():
    if not QUOTA_CONFIG_FILE.exists():
        return {}

    with QUOTA_CONFIG_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_sources():
    config = load_config()
    result = []

    for source in config.get("youtube_sources", []):
        if source.get("enabled", True) is False:
            continue

        channel_id = source.get("channel_id", "")

        if not CHANNEL_ID_PATTERN.fullmatch(channel_id):
            print(
                f"[MotoGP] Neispravan YouTube ID: "
                f"{source.get('name')} | {channel_id}"
            )
            continue

        result.append({
            "name": source.get("name", "MotoGP Official"),
            "channel_id": channel_id
        })

    return result


# --------------------------------------------------
# API HELPERS
# --------------------------------------------------

def api_get(endpoint, params=None):
    url = f"{API_BASE}/{endpoint.lstrip('/')}"

    response = requests.get(
        url,
        params=params or {},
        headers=API_HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("results", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]

    return data


def parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def event_name(event):
    for key in (
        "sponsored_name",
        "name",
        "short_name",
        "event_name"
    ):
        value = event.get(key)

        if value:
            return str(value)

    circuit = event.get("circuit", {})

    if isinstance(circuit, dict):
        return circuit.get("name", "MotoGP Grand Prix")

    return "MotoGP Grand Prix"


def session_name(session):
    for key in (
        "name",
        "session_name",
        "description",
        "type"
    ):
        value = session.get(key)

        if value:
            return str(value)

    return "MotoGP Session"


# --------------------------------------------------
# SESSION CLASSIFICATION
# --------------------------------------------------

def classify_session(session):
    """
    Prati samo:
    - Race
    - Sprint
    - Qualifying

    Treninzi i warm-up sesije se preskaču.
    """

    raw_type = str(
        session.get("type")
        or session.get("session_type")
        or ""
    ).strip().upper()

    raw_name = session_name(session).upper()

    combined = f"{raw_type} {raw_name}"

    if (
        raw_type in ("RAC", "RACE")
        or "MAIN RACE" in combined
        or "GRAND PRIX" in combined
        or "RACE" in combined
    ):
        return {
            "type": "race",
            "query": "MotoGP race highlights",
            "importance": 2.0
        }

    if (
        raw_type in ("SPR", "SPRINT")
        or "SPRINT" in combined
    ):
        return {
            "type": "sprint",
            "query": "MotoGP sprint highlights",
            "importance": 1.7
        }

    if (
        raw_type in ("Q", "Q1", "Q2", "QUALIFYING")
        or "QUALIFYING" in combined
        or "QUALIFICATION" in combined
        or re.search(r"\bQ[12]\b", combined)
    ):
        return {
            "type": "qualifying",
            "query": "MotoGP qualifying highlights",
            "importance": 1.5
        }

    return None


# --------------------------------------------------
# SEASON AND CATEGORY
# --------------------------------------------------

def get_current_season():
    seasons = api_get("results/seasons")

    if not isinstance(seasons, list) or not seasons:
        raise RuntimeError(
            "MotoGP API nije vratio popis sezona."
        )

    current = next(
        (
            season for season in seasons
            if season.get("current") is True
        ),
        None
    )

    if current is None:
        current = max(
            seasons,
            key=lambda item: int(item.get("year", 0))
        )

    season_uuid = current.get("id")

    if not season_uuid:
        raise RuntimeError(
            "U odgovoru MotoGP API-ja nedostaje season UUID."
        )

    print(
        f"[MotoGP] Sezona: {current.get('year')} "
        f"| UUID: {season_uuid}"
    )

    return current


def get_motogp_category(season_uuid):
    categories = api_get(
        "results/categories",
        {"seasonUuid": season_uuid}
    )

    for category in categories:
        name = str(category.get("name", "")).lower()

        if name.replace("™", "").strip() == "motogp":
            category_uuid = category.get("id")

            if category_uuid:
                print(
                    f"[MotoGP] Pronađena glavna klasa: "
                    f"{category.get('name')}"
                )
                return category_uuid

    raise RuntimeError(
        "MotoGP kategorija nije pronađena u API odgovoru."
    )


# --------------------------------------------------
# EVENTS AND SESSIONS
# --------------------------------------------------

def get_events(season_uuid):
    # Namjerno ne koristimo isFinished=false.
    # Taj parametar može izostaviti aktualni vikend.
    events = api_get(
        "results/events",
        {"seasonUuid": season_uuid}
    )

    print(
        f"[MotoGP] Događaja u sezoni: {len(events)}"
    )

    return events


def get_event_uuid(event):
    return (
        event.get("id")
        or event.get("uuid")
        or event.get("toad_api_uuid")
    )


def get_event_sessions(event_uuid, category_uuid):
    return api_get(
        "results/sessions",
        {
            "eventUuid": event_uuid,
            "categoryUuid": category_uuid
        }
    )


# --------------------------------------------------
# WEEKEND MARKER
# --------------------------------------------------

def make_weekend_marker(event, first_time, last_time):
    name = event_name(event)

    return {
        "domain": "MotoGP",
        "key": (
            f"motogp:weekend_marker:"
            f"{event.get('id') or event.get('toad_api_uuid')}"
        ),
        "query": "",
        "channel_id": "",
        "source_name": "MotoGP Official",
        "event_name": name,
        "event_time": first_time.isoformat(),
        "importance": 0,
        "motogp_weekend": True,
        "skip_search": True
    }


# --------------------------------------------------
# EVENT CANDIDATES
# --------------------------------------------------

def candidates():
    now = datetime.now(timezone.utc)

    quota_config = load_quota_config()

    before_hours = float(
        quota_config.get("event_window_hours_before", 6)
    )

    after_hours = float(
        quota_config.get("event_window_hours_after", 3)
    )

    sources = get_sources()

    if not sources:
        print("[MotoGP] Nema aktivnih YouTube izvora.")
        return []

    season = get_current_season()
    season_uuid = season["id"]

    category_uuid = get_motogp_category(
        season_uuid
    )

    events = get_events(season_uuid)

    result = []

    for event in events:
        event_uuid = get_event_uuid(event)

        if not event_uuid:
            continue

        name = event_name(event)

        try:
            sessions = get_event_sessions(
                event_uuid,
                category_uuid
            )

        except Exception as exc:
            print(
                f"[MotoGP] Greška kod sesija za "
                f"{name}: {exc}"
            )
            continue

        relevant_sessions = []

        for session in sessions:
            classification = classify_session(session)

            if not classification:
                continue

            session_time = parse_datetime(
                session.get("date")
            )

            if not session_time:
                continue

            relevant_sessions.append({
                "session": session,
                "time": session_time,
                "classification": classification
            })

        if not relevant_sessions:
            continue

        relevant_sessions.sort(
            key=lambda item: item["time"]
        )

        first_time = relevant_sessions[0]["time"]
        last_time = relevant_sessions[-1]["time"]

        # Marker označava aktivni GP vikend.
        if (
            first_time - timedelta(hours=24)
            <= now
            <= last_time + timedelta(hours=6)
        ):
            result.append(
                make_weekend_marker(
                    event,
                    first_time,
                    last_time
                )
            )

        for entry in relevant_sessions:
            session = entry["session"]
            session_time = entry["time"]
            classification = entry["classification"]

            if session_time < now - timedelta(
                hours=after_hours
            ):
                continue

            if session_time > now + timedelta(
                hours=before_hours
            ):
                continue

            session_id = session.get("id")

            if not session_id:
                continue

            for source in sources:
                result.append({
                    "domain": "MotoGP",
                    "key": (
                        f"motogp:{event_uuid}:"
                        f"{session_id}:"
                        f"{source['channel_id']}"
                    ),
                    "query": classification["query"],
                    "channel_id": source["channel_id"],
                    "source_name": source["name"],
                    "event_name": (
                        f"{name} - "
                        f"{session_name(session)}"
                    ),
                    "event_time": session_time.isoformat(),
                    "importance": classification["importance"],
                    "session_type": classification["type"],
                    "event_uuid": event_uuid,
                    "session_id": session_id,
                    "fallback": False
                })

    result.sort(
        key=lambda item: float(
            item.get("importance", 0)
        ),
        reverse=True
    )

    print(
        f"[MotoGP] Kandidata za sesije i markere: "
        f"{len(result)}"
    )

    print(
        f"[MotoGP] Stvarnih kandidata: "
        f"{sum(1 for item in result if not item.get('skip_search'))}"
    )

    print(
        f"[MotoGP] Aktivnih vikend markera: "
        f"{sum(1 for item in result if item.get('skip_search'))}"
    )

    return result


# --------------------------------------------------
# FALLBACK CANDIDATES
# --------------------------------------------------

def fallback_candidates():
    sources = get_sources()
    result = []

    queries = [
        ("race-highlights", "MotoGP race highlights", 2.0),
        ("sprint-highlights", "MotoGP sprint highlights", 1.7),
        ("qualifying-highlights", "MotoGP qualifying highlights", 1.5)
    ]

    for source in sources:
        for slug, query, importance in queries:
            result.append({
                "domain": "MotoGP",
                "key": (
                    f"motogp:fallback:"
                    f"{source['channel_id']}:{slug}"
                ),
                "query": query,
                "channel_id": source["channel_id"],
                "source_name": source["name"],
                "event_name": query,
                "event_time": None,
                "importance": importance,
                "fallback": True
            })

    print(
        f"[MotoGP] Fallback kandidata: {len(result)}"
    )

    return result


# --------------------------------------------------
# YOUTUBE VIDEO DURATION
# --------------------------------------------------

def parse_duration(value):
    if not value:
        return 0

    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value
    )

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def get_video_durations(video_ids, api_key):
    result = {}

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "contentDetails",
                "id": ",".join(batch),
                "key": api_key
            },
            timeout=30
        )

        response.raise_for_status()

        for item in response.json().get("items", []):
            video_id = item.get("id")

            duration = item.get(
                "contentDetails",
                {}
            ).get("duration")

            result[video_id] = parse_duration(
                duration
            )

    return result


# --------------------------------------------------
# MOTO GP VIDEO FILTER
# --------------------------------------------------

EXCLUDED_TERMS = [
    "interview",
    "reaction",
    "reacts",
    "news",
    "analysis",
    "podcast",
    "press conference",
    "behind the scenes",
    "onboard",
    "on board",
    "team radio",
    "watchalong",
    "watch along",
    "preview",
    "prediction",
    "rumour",
    "rumor",
    "transfer",
    "crash compilation",
    "funny moments",
    "gameplay",
    "gaming",
    "live timing",
    "livestream",
    "live stream",
    "practice highlights",
    "free practice",
    "warm up",
    "warm-up",
    "fp1",
    "fp2",
    "fp3"
]


def classify_video(title):
    text = str(title or "").lower()

    if any(term in text for term in EXCLUDED_TERMS):
        return [], "other"

    if (
        "sprint" in text
        and (
            "highlight" in text
            or "recap" in text
            or "full race" in text
        )
    ):
        return ["sprint", "highlights"], "sprint"

    if (
        "qualifying" in text
        and (
            "highlight" in text
            or "recap" in text
            or "full" in text
        )
    ) or re.search(r"\bq[12]\s+highlights\b", text):
        return ["qualifying", "highlights"], "qualifying"

    if (
        "race highlights" in text
        or "race recap" in text
        or "full race" in text
        or "grand prix highlights" in text
    ):
        return ["race", "highlights"], "race"

    return [], "other"


def filter_videos(items, api_key):
    stats = {
        "received": len(items),
        "accepted": 0,
        "too_short": 0,
        "shorts": 0,
        "excluded_keyword": 0,
        "other": 0,
        "missing_duration": 0
    }

    video_ids = []

    for item in items:
        video_id = item.get(
            "id", {}
        ).get("videoId")

        if video_id:
            video_ids.append(video_id)

    durations = get_video_durations(
        video_ids,
        api_key
    ) if video_ids else {}

    accepted = []

    for item in items:
        video_id = item.get(
            "id", {}
        ).get("videoId")

        if not video_id:
            continue

        duration = durations.get(video_id)

        if duration is None:
            stats["missing_duration"] += 1
            continue

        if duration < 180:
            stats["too_short"] += 1
            continue

        snippet = item.get("snippet", {})

        title = snippet.get("title", "")
        description = snippet.get("description", "")

        combined = f"{title} {description}".lower()

        if (
            "#shorts" in combined
            or "#short" in combined
            or re.search(r"\bshorts\b", title.lower())
        ):
            stats["shorts"] += 1
            continue

        if any(
            term in combined
            for term in EXCLUDED_TERMS
        ):
            stats["excluded_keyword"] += 1
            continue

        tags, video_type = classify_video(title)

        if video_type == "other":
            stats["other"] += 1
            continue

        item["duration_seconds"] = duration
        item["filter_tags"] = tags
        item["video_type"] = video_type
        item["matched_keywords"] = tags

        accepted.append(item)
        stats["accepted"] += 1

    stats["categorized"] = stats["accepted"]

    return accepted, stats
