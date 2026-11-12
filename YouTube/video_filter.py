
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

    with FILTER_CONFIG.open("r", encoding="utf-8") as file:
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

    pattern = (
        r"(?<!\w)"
        + re.escape(keyword)
        + r"(?!\w)"
    )

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
    Maksimalno 50 ID-jeva po API pozivu.
    """

    if not video_ids:
        return {}

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

            duration_seconds = parse_duration(
                duration_iso
            )

            if video_id and duration_seconds is not None:
                durations[video_id] = duration_seconds

    return durations


def get_video_id(item):
    video_id = item.get("id", {})

    if isinstance(video_id, dict):
        return video_id.get("videoId")

    return None


def get_title(item):
    return normalize_text(
        item.get("snippet", {}).get("title", "")
    )


def get_description(item):
    return normalize_text(
        item.get("snippet", {}).get("description", "")
    )


def find_matching_keywords(text, keywords):
    matches = []

    for keyword in keywords:
        if contains_keyword(text, keyword):
            matches.append(keyword)

    return matches


def classify_video(text, domain, config=None):
    """
    Klasificira video prema naslovu.

    Football:
      highlights, goals, review

    F1:
      qualifying, race, highlights

    MotoGP:
      sprint, qualifying, race, highlights

    Neprepoznati video dobiva kategoriju other.
    """

    if config is None:
        config = load_filter_config()

    domain = domain.lower()

    domain_config = config.get(domain, {})

    categories = domain_config.get(
        "categories",
        {}
    )

    category_matches = {}

    for category, keywords in categories.items():
        matches = find_matching_keywords(
            text,
            keywords
        )

        if matches:
            category_matches[category] = matches

    if domain == "football":
        priority = [
            "highlights",
            "goals",
            "review"
        ]

    elif domain == "f1":
        priority = [
            "qualifying",
            "race",
            "highlights"
        ]

    elif domain == "motogp":
        priority = [
            "sprint",
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
    Strogi filter videozapisa.

    Prihvaća samo videozapise koji:
    - imaju poznato trajanje
    - traju najmanje zadani broj sekundi
    - nisu prepoznati kao Shorts
    - nemaju isključujuće riječi u NASLOVU
    - odgovaraju dopuštenoj kategoriji

    Minimalno trajanje:
    - Football: 180 sekundi
    - F1: 180 sekundi
    - MotoGP: 120 sekundi

    Naslov se koristi za klasifikaciju i isključivanje.
    Opis se koristi samo za dodatnu provjeru Shortsa.
    """

    config = load_filter_config()

    domain = domain.lower()

    global_config = config.get(
        "global",
        {}
    )

    domain_config = config.get(
        domain,
        {}
    )

    # Disciplina može imati vlastiti minimum trajanja.
    # Ako ga nema, koristi se globalna vrijednost.
    min_duration = int(
        domain_config.get(
            "min_duration_seconds",
            global_config.get(
                "min_duration_seconds",
                180
            )
        )
    )

    exclude_shorts = global_config.get(
        "exclude_shorts",
        True
    )

    shorts_keywords = global_config.get(
        "shorts_keywords",
        []
    )

    exclude_keywords = domain_config.get(
        "exclude_keywords",
        []
    )

    include_keywords = domain_config.get(
        "include_keywords",
        []
    )

    video_ids = []

    for item in items:
        video_id = get_video_id(item)

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
        video_id = get_video_id(item)

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

        title = get_title(item)
        description = get_description(item)

        # Shorts provjera koristi naslov i opis.
        if exclude_shorts:
            shorts_text = (
                title + " " + description
            )

            is_short = any(
                contains_keyword(
                    shorts_text,
                    keyword
                )
                for keyword in shorts_keywords
            )

            if is_short:
                stats["shorts"] += 1
                continue

        # Isključujuće riječi provjeravaju se samo u naslovu.
        excluded = any(
            contains_keyword(
                title,
                keyword
            )
            for keyword in exclude_keywords
        )

        if excluded:
            stats["excluded_keyword"] += 1
            continue

        # Uvjetne ključne riječi provjeravaju se samo u naslovu.
        matched_keywords = find_matching_keywords(
            title,
            include_keywords
        )

        if not matched_keywords:
            stats["other"] += 1
            continue

        # Klasifikacija također koristi samo naslov.
        tags, video_type = classify_video(
            title,
            domain,
            config
        )

        if video_type == "other":
            stats["other"] += 1
            continue

        stats["categorized"] += 1

        item["filter_tags"] = tags
        item["video_type"] = video_type
        item["matched_keywords"] = matched_keywords

        accepted.append(item)

    stats["accepted"] = len(accepted)

    return accepted, stats
