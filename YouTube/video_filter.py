
import json
import re
import unicodedata
import requests

from pathlib import Path
from datetime import datetime


BASE = Path(__file__).resolve().parent
FILTER_CONFIG = BASE / "video_filter.json"

VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def load_filter_config():
    if not FILTER_CONFIG.exists():
        raise FileNotFoundError(
            f"Nedostaje konfiguracija: {FILTER_CONFIG}"
        )

    with FILTER_CONFIG.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(value):
    """
    Mala slova, uklanjanje dijakritičkih znakova
    i normalizacija razmaka.
    """

    value = str(value or "").lower()

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def contains_keyword(text, keyword):
    text = normalize_text(text)
    keyword = normalize_text(keyword)

    if not keyword:
        return False

    return keyword in text


def parse_duration(duration):
    """
    ISO 8601 trajanje, primjerice:
    PT3M25S = 205 sekundi
    PT1H2M = 3720 sekundi
    """

    if not duration:
        return 0

    match = re.fullmatch(
        r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
        duration
    )

    if not match:
        return 0

    days, hours, minutes, seconds = match.groups()

    total = (
        int(days or 0) * 86400
        + int(hours or 0) * 3600
        + int(minutes or 0) * 60
        + float(seconds or 0)
    )

    return int(total)


def get_video_durations(video_ids, api_key):
    """
    Jedan videos.list poziv za do 50 ID-jeva.
    Ne koristi search.list kvotu.
    """

    if not video_ids:
        return {}

    params = {
        "part": "contentDetails",
        "id": ",".join(video_ids),
        "key": api_key
    }

    response = requests.get(
        VIDEOS_API_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    durations = {}

    for item in data.get("items", []):
        video_id = item.get("id")

        duration = item.get(
            "contentDetails", {}
        ).get("duration")

        durations[video_id] = parse_duration(duration)

    return durations


def get_text(item, fields):
    snippet = item.get("snippet", {})

    parts = []

    for field in fields:
        if field == "title":
            parts.append(snippet.get("title", ""))

        elif field == "description":
            parts.append(snippet.get("description", ""))

        elif field == "channel_title":
            parts.append(snippet.get("channelTitle", ""))

    return normalize_text(" ".join(parts))


def find_matching_keywords(text, keywords):
    return [
        keyword
        for keyword in keywords
        if contains_keyword(text, keyword)
    ]


def classify_video(text, domain, config=None):
    """
    Vraća oznake i kategoriju videa.
    """

    config = config or load_filter_config()

    domain_config = config.get(
        domain.lower(), {}
    )

    categories = domain_config.get("categories", {})

    tags = []

    for category, keywords in categories.items():
        if find_matching_keywords(text, keywords):
            tags.append(category)

    if "highlights" in tags:
        video_type = "highlight"

    elif "goals" in tags:
        video_type = "goals"

    elif "analysis" in tags:
        video_type = "analysis"

    elif "qualifying" in tags:
        video_type = "qualifying"

    elif "onboard" in tags:
        video_type = "onboard"

    elif "team_radio" in tags:
        video_type = "team_radio"

    elif "race" in tags:
        video_type = "race"

    elif "review" in tags:
        video_type = "review"

    else:
        video_type = "video"

    return tags, video_type


def filter_videos(items, domain, api_key):
    """
    Filtrira rezultate:
    - minimalno trajanje
    - Shorts oznake
    - isključujuće ključne riječi
    - obavezne uključujuće ključne riječi
    """

    config = load_filter_config()

    global_config = config.get("global", {})
    domain_config = config.get(domain.lower(), {})

    min_duration = int(
        global_config.get("min_duration_seconds", 180)
    )

    exclude_shorts = global_config.get(
        "exclude_shorts", True
    )

    shorts_keywords = global_config.get(
        "shorts_keywords", []
    )

    include_keywords = domain_config.get(
        "include_keywords", []
    )

    exclude_keywords = domain_config.get(
        "exclude_keywords", []
    )

    fields = global_config.get(
        "check_fields",
        ["title", "description"]
    )

    require_include = global_config.get(
        "require_include_keyword", True
    )

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
    )

    accepted = []

    stats = {
        "received": len(items),
        "accepted": 0,
        "too_short": 0,
        "shorts": 0,
        "excluded_keyword": 0,
        "missing_include_keyword": 0,
        "missing_duration": 0
    }

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

        item["duration_seconds"] = duration

        if duration < min_duration:
            stats["too_short"] += 1
            continue

        text = get_text(item, fields)

        if exclude_shorts and find_matching_keywords(
            text,
            shorts_keywords
        ):
            stats["shorts"] += 1
            continue

        if find_matching_keywords(
            text,
            exclude_keywords
        ):
            stats["excluded_keyword"] += 1
            continue

        matched_include = find_matching_keywords(
            text,
            include_keywords
        )

        if require_include and not matched_include:
            stats["missing_include_keyword"] += 1
            continue

        tags, video_type = classify_video(
            text,
            domain,
            config
        )

        item["filter_tags"] = tags
        item["video_type"] = video_type
        item["matched_keywords"] = matched_include

        accepted.append(item)

    stats["accepted"] = len(accepted)

    return accepted, stats
