
import json
import re
import unicodedata
import requests

from pathlib import Path


BASE = Path(__file__).resolve().parent
FILTER_CONFIG = BASE / "video_filter.json"

VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"


# ============================================================
# CONFIGURATION
# ============================================================

def load_filter_config():
    if not FILTER_CONFIG.exists():
        raise FileNotFoundError(
            f"Ne mogu pronaći konfiguraciju: {FILTER_CONFIG}"
        )

    with FILTER_CONFIG.open("r", encoding="utf-8") as file:
        return json.load(file)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(value):
    value = str(value or "").lower()

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        char
        for char in value
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


def find_matching_keywords(text, keywords):
    return [
        keyword
        for keyword in keywords
        if contains_keyword(text, keyword)
    ]


# ============================================================
# VIDEO DURATION
# ============================================================

def parse_duration(duration):
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

            duration_seconds = parse_duration(duration_iso)

            if video_id and duration_seconds is not None:
                durations[video_id] = duration_seconds

    return durations


# ============================================================
# YOUTUBE ITEM HELPERS
# ============================================================

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


# ============================================================
# SHORTS DETECTION
# ============================================================

def is_shorts_video(title, description, shorts_keywords):
    title = normalize_text(title)
    description = normalize_text(description)

    # Strong indicators: explicit hashtags.
    strong_keywords = [
        "#shorts",
        "#ytshorts"
    ]

    for keyword in strong_keywords:
        if contains_keyword(title, keyword):
            return True

        if contains_keyword(description, keyword):
            return True

    # Generic Shorts expressions are checked in title only.
    generic_keywords = [
        keyword
        for keyword in shorts_keywords
        if normalize_text(keyword) not in [
            "#shorts",
            "#ytshorts"
        ]
    ]

    for keyword in generic_keywords:
        if contains_keyword(title, keyword):
            return True

    return False


# ============================================================
# CATEGORY CLASSIFICATION
# ============================================================

def get_category_priority(domain):
    priorities = {
        "football": [
            "highlights",
            "goals",
            "review"
        ],

        "f1": [
            "qualifying",
            "race",
            "highlights"
        ],

        "motogp": [
            "sprint",
            "qualifying",
            "race",
            "practice",
            "highlights",
            "build_up"
        ]
    }

    return priorities.get(domain, [])


def classify_video(title, description, domain, config=None):
    if config is None:
        config = load_filter_config()

    domain = domain.lower()

    domain_config = config.get(domain, {})

    categories = domain_config.get(
        "categories", {}
    )

    title = normalize_text(title)
    description = normalize_text(description)

    title_matches = {}
    description_matches = {}

    for category, keywords in categories.items():

        title_found = find_matching_keywords(
            title,
            keywords
        )

        description_found = find_matching_keywords(
            description,
            keywords
        )

        if title_found:
            title_matches[category] = title_found

        if description_found:
            description_matches[category] = description_found

    priority = get_category_priority(domain)

    # Title always has priority.
    for category in priority:
        if category in title_matches:
            return [category], category

    # Description is used as fallback.
    for category in priority:
        if category in description_matches:
            return [category], category

    return ["other"], "other"


# ============================================================
# VIDEO FILTER
# ============================================================

def filter_videos(items, domain, api_key):

    config = load_filter_config()

    domain = domain.lower()

    global_config = config.get("global", {})

    domain_config = config.get(domain, {})

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

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

    require_include = global_config.get(
        "require_include_keyword",
        True
    )

    # --------------------------------------------------------
    # GET VIDEO IDS
    # --------------------------------------------------------

    video_ids = []

    for item in items:

        video_id = get_video_id(item)

        if video_id:
            video_ids.append(video_id)

    durations = get_video_durations(
        video_ids,
        api_key
    )

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # PROCESS VIDEOS
    # --------------------------------------------------------

    for item in items:

        video_id = get_video_id(item)

        if not video_id:
            continue

        duration = durations.get(video_id)

        # Missing duration.
        if duration is None:

            stats["missing_duration"] += 1

            item["filter_rejection"] = "missing_duration"

            continue

        item["duration_seconds"] = duration

        # Minimum duration.
        if duration < min_duration:

            stats["too_short"] += 1

            item["filter_rejection"] = "too_short"

            continue

        # Text.
        title = get_title(item)

        description = get_description(item)

        # ----------------------------------------------------
        # SHORTS
        # ----------------------------------------------------

        if exclude_shorts:

            if is_shorts_video(
                title,
                description,
                shorts_keywords
            ):

                stats["shorts"] += 1

                item["filter_rejection"] = "shorts"

                continue

        # ----------------------------------------------------
        # EXCLUDE KEYWORDS
        # ----------------------------------------------------

        excluded_matches = find_matching_keywords(
            title,
            exclude_keywords
        )

        if excluded_matches:

            stats["excluded_keyword"] += 1

            item["filter_rejection"] = "excluded_keyword"

            item["excluded_keywords"] = excluded_matches

            continue

        # ----------------------------------------------------
        # INCLUDE KEYWORDS
        # ----------------------------------------------------

        matched_title = find_matching_keywords(
            title,
            include_keywords
        )

        matched_description = find_matching_keywords(
            description,
            include_keywords
        )

        matched_keywords = list(
            dict.fromkeys(
                matched_title + matched_description
            )
        )

        if require_include and not matched_keywords:

            stats["other"] += 1

            item["filter_rejection"] = "missing_include_keyword"

            continue

        # ----------------------------------------------------
        # CLASSIFICATION
        # ----------------------------------------------------

        tags, video_type = classify_video(
            title,
            description,
            domain,
            config
        )

        if video_type == "other":

            stats["other"] += 1

            item["filter_rejection"] = "unclassified"

            continue

        # ----------------------------------------------------
        # ACCEPTED VIDEO
        # ----------------------------------------------------

        stats["categorized"] += 1

        item["filter_tags"] = tags

        item["video_type"] = video_type

        item["matched_keywords"] = matched_keywords

        item.pop("filter_rejection", None)

        item.pop("excluded_keywords", None)

        accepted.append(item)

    # --------------------------------------------------------
    # FINAL STATISTICS
    # --------------------------------------------------------

    stats["accepted"] = len(accepted)

    return accepted, stats
