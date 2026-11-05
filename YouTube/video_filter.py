
import json
import re
import unicodedata
import requests
from pathlib import Path


BASE = Path(__file__).resolve().parent
FILTER_CONFIG = BASE / "video_filter.json"

VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def load_filter_config():
    if not FILTER_CONFIG.exists():
        raise FileNotFoundError(
            f"Ne mogu pronaći konfiguraciju: {FILTER_CONFIG}"
        )

    with open(FILTER_CONFIG, "r", encoding="utf-8") as file:
        return json.load(file)


def normalize_text(value):
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

    if not text or not keyword:
        return False

    pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"

    return re.search(pattern, text) is not None


def parse_duration(duration):
    """
    Pretvara ISO 8601 trajanje u sekunde.
    Primjer: PT1H2M10S = 3730 sekundi.
    """

    if not duration:
        return None

    pattern = (
        r"P(?:(\d+)D)?"
        r"T?"
        r"(?:(\d+)H)?"
        r"(?:(\d+)M)?"
        r"(?:(\d+(?:\.\d+)?)S)?"
    )

    match = re.fullmatch(pattern, duration)

    if not match:
        return None

    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = float(match.group(4) or 0)

    return int(
        days * 86400
        + hours * 3600
        + minutes * 60
        + seconds
    )


def get_video_durations(video_ids, api_key):
    """
    Dohvaća trajanja preko YouTube videos.list API-ja.
    """

    if not video_ids:
        return {}

    # Ukloni duplikate i podijeli u grupe od najviše 50 ID-jeva.
    unique_ids = list(dict.fromkeys(video_ids))

    durations = {}

    for start in range(0, len(unique_ids), 50):
        batch = unique_ids[start:start + 50]

        params = {
            "part": "contentDetails",
            "id": ",".join(batch),
            "key": api_key
        }

        response = requests.get(
            VIDEOS_API_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        for item in data.get("items", []):
            video_id = item.get("id")

            duration_iso = (
                item.get("contentDetails", {}).get("duration")
            )

            duration_seconds = parse_duration(duration_iso)

            if video_id and duration_seconds is not None:
                durations[video_id] = duration_seconds

    return durations


def get_text(item, fields):
    snippet = item.get("snippet", {})

    values = []

    for field in fields:
        if field == "title":
            values.append(snippet.get("title", ""))

        elif field == "description":
            values.append(snippet.get("description", ""))

        elif field == "channel_title":
            values.append(snippet.get("channelTitle", ""))

    return " ".join(values)


def find_matching_keywords(text, keywords):
    matches = []

    for keyword in keywords:
        if contains_keyword(text, keyword):
            matches.append(keyword)

    return matches


def classify_video(text, domain, config=None):
    """
    Vraća kategoriju samo ako video odgovara željenom sadržaju.

    Football:
      highlights, goals, review

    F1:
      qualifying, race, highlights

    Neprepoznati video dobiva kategoriju other.
    """

    if config is None:
        config = load_filter_config()

    domain = domain.lower()

    domain_config = config.get(domain, {})
    categories = domain_config.get("categories", {})

    category_matches = {}

    for category, keywords in categories.items():
        matches = find_matching_keywords(text, keywords)

        if matches:
            category_matches[category] = matches

    if domain == "football":
        priority = [
            "highlights",
            "goals",
            "review"
        ]

    elif domain == "f1":
        # Kvalifikacije imaju prednost pred općim highlights.
        priority = [
            "qualifying",
            "race",
            "highlights"
        ]

    else:
        priority = []

    for category in priority:
        if category in category_matches:
            return (
                [category],
                category
            )

    return (
        ["other"],
        "other"
    )


def filter_videos(items, domain, api_key):
    """
    Strogo filtrira YouTube rezultate.

    Video se prihvaća samo ako:
    - ima poznato trajanje
    - traje najmanje zadani broj sekundi
    - nije prepoznat kao Shorts
    - ne sadrži isključene teme
    - pripada jednoj od dopuštenih kategorija

    Neprepoznati videi se odbacuju.
    """

    config = load_filter_config()

    domain = domain.lower()

    global_config = config.get("global", {})
    domain_config = config.get(domain, {})

    min_duration = int(
        global_config.get("min_duration_seconds", 180)
    )

    exclude_shorts = global_config.get(
        "exclude_shorts", True
    )

    shorts_keywords = global_config.get(
        "shorts_keywords", []
    )

    check_fields = global_config.get(
        "check_fields",
        ["title", "description"]
    )

    exclude_keywords = domain_config.get(
        "exclude_keywords", []
    )

    include_keywords = domain_config.get(
        "include_keywords", []
    )

    require_include_keyword = global_config.get(
        "require_include_keyword", True
    )

    video_ids = []

    for item in items:
        video_id = item.get("id", {}).get("videoId")

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
        "missing_duration": 0,
        "other": 0,
        "categorized": 0
    }

    for item in items:
        video_id = item.get("id", {}).get("videoId")

        if not video_id:
            continue

        duration = durations.get(video_id)

        if duration is None:
            stats["missing_duration"] += 1
            continue

        if duration < min_duration:
            stats["too_short"] += 1
            continue

        text = normalize_text(
            get_text(item, check_fields)
        )

        # Shorts filter.
        if exclude_shorts:
            is_short = any(
                contains_keyword(text, keyword)
                for keyword in shorts_keywords
            )

            if is_short:
                stats["shorts"] += 1
                continue

        # Isključi neželjene teme.
        excluded = any(
            contains_keyword(text, keyword)
            for keyword in exclude_keywords
        )

        if excluded:
            stats["excluded_keyword"] += 1
            continue

        # Provjeri tražene ključne riječi.
        matched_keywords = find_matching_keywords(
            text,
            include_keywords
        )

        if require_include_keyword and not matched_keywords:
            stats["other"] += 1
            continue

        # Klasifikacija u dopuštene kategorije.
        tags, video_type = classify_video(
            text,
            domain,
            config
        )

        # Neprepoznata kategorija se odbacuje.
        if video_type == "other":
            stats["other"] += 1
            continue

        stats["categorized"] += 1

        # Podaci koje koristi run_all.py.
        item["duration_seconds"] = duration
        item["filter_tags"] = tags
        item["video_type"] = video_type
        item["matched_keywords"] = matched_keywords

        accepted.append(item)

    stats["accepted"] = len(accepted)

    return accepted, stats
