
import os
import json
import re
import requests

from html import unescape
from pathlib import Path
from datetime import datetime, timezone

import Football.main as football
import F1.main as f1

from quota_manager import (
    load_config,
    load_state,
    select_candidates,
    record_success,
    save_state
)


BASE = Path(__file__).resolve().parent
FOOTBALL_CONFIG = BASE / "Football" / "config.json"

API_URL = "https://www.googleapis.com/youtube/v3/search"
API_KEY = os.environ.get("YOUTUBE_API_KEY")

MAX_SAVED_VIDEOS = 500

F1_ARCHIVE = {
    "source": "Formula 1",
    "priority": 3,
    "source_key": "formula_1",
    "logo": "logo/formula_1.png"
}

CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def youtube_search(candidate):
    if not API_KEY:
        raise RuntimeError("Nedostaje YOUTUBE_API_KEY.")

    params = {
        "part": "snippet",
        "q": candidate["query"],
        "channelId": candidate["channel_id"],
        "type": "video",
        "maxResults": 10,
        "order": "date",
        "key": API_KEY
    }

    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def output_file(domain):
    if domain == "Football":
        return BASE / "Football" / "youtube_football.json"

    if domain == "F1":
        return BASE / "F1" / "youtube_f1.json"

    raise ValueError(f"Nepoznata domena: {domain}")


def get_archive_metadata(candidate):
    if candidate["domain"] == "F1":
        return F1_ARCHIVE.copy()

    source_name = candidate.get("source_name", "Football")
    source_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        source_name.lower()
    ).strip("_")

    return {
        "source": source_name,
        "priority": candidate.get("importance", 1),
        "source_key": source_key,
        "logo": f"logo/{source_key}.png"
    }


def get_video_tags(title, description=""):
    text = unescape(
        f"{title or ''} {description or ''}"
    ).lower()

    tags = []

    keywords = {
        "highlights": [
            "highlights",
            "extended highlights",
            "match highlights"
        ],
        "goals": [
            "goals",
            "all goals",
            "every goal"
        ],
        "race": [
            "grand prix",
            "race highlights",
            "race"
        ],
        "qualifying": [
            "qualifying",
            "pole position"
        ],
        "sprint": [
            "sprint"
        ],
        "review": [
            "review",
            "recap",
            "reaction"
        ],
        "analysis": [
            "analysis",
            "tactical analysis"
        ],
        "interview": [
            "interview",
            "press conference"
        ],
        "news": [
            "news",
            "latest news"
        ]
    }

    for tag, phrases in keywords.items():
        if any(phrase in text for phrase in phrases):
            tags.append(tag)

    return tags


def get_video_type(title, tags):
    title_lower = (title or "").lower()

    if "highlights" in tags or "goals" in tags:
        return "highlight"

    if "qualifying" in tags:
        return "qualifying"

    if "sprint" in tags:
        return "sprint"

    if "race" in tags or "grand prix" in title_lower:
        return "race"

    if "interview" in tags:
        return "interview"

    if "analysis" in tags:
        return "analysis"

    if "news" in tags:
        return "news"

    if "review" in tags:
        return "review"

    return "video"


def published_timestamp(published_at):
    if not published_at:
        return 0

    try:
        value = published_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return int(dt.timestamp())

    except (ValueError, TypeError):
        return 0


def load_existing_archive(path):
    """
    Učitava postojeći arhiv.
    Podržava novi JSON format i stari JSONL format.
    """

    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8").strip()

    if not raw:
        return []

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            return data.get("videos", [])

        if isinstance(data, list):
            return data

    except json.JSONDecodeError:
        pass

    videos = []

    for line in raw.splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        for video in record.get("videos", []):
            video_id = video.get("video_id")

            if not video_id:
                continue

            title = video.get("title", "")
            description = video.get("description", "")
            published_at = video.get("published_at")

            source_name = video.get(
                "channel_title",
                record.get("source", "Unknown")
            )

            source_key = re.sub(
                r"[^a-z0-9]+",
                "_",
                source_name.lower()
            ).strip("_")

            is_f1 = record.get("domain") == "F1"

            tags = get_video_tags(title, description)

            videos.append({
                "video_id": video_id,
                "title": title,
                "published_at": published_at,
                "published_ts": published_timestamp(published_at),
                "thumbnail": (
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                ),
                "source": source_name,
                "source_key": source_key,
                "priority": 3 if is_f1 else 1,
                "logo": "logo/formula_1.png" if is_f1 else "",
                "tags": tags,
                "type": get_video_type(title, tags),
                "link": f"https://www.youtube.com/watch?v={video_id}"
            })

    return videos


def save_results(candidate, data):
    path = output_file(candidate["domain"])
    path.parent.mkdir(parents=True, exist_ok=True)

    metadata = get_archive_metadata(candidate)

    videos = load_existing_archive(path)

    videos_by_id = {
        video["video_id"]: video
        for video in videos
        if video.get("video_id")
    }

    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")

        if not video_id:
            continue

        snippet = item.get("snippet", {})

        title = unescape(snippet.get("title", ""))
        description = unescape(
            snippet.get("description", "")
        )
        published_at = snippet.get("publishedAt")

        tags = get_video_tags(title, description)

        video = {
            "video_id": video_id,
            "title": title,
            "published_at": published_at,
            "published_ts": published_timestamp(published_at),
            "thumbnail": (
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            ),
            "source": metadata["source"],
            "source_key": metadata["source_key"],
            "priority": metadata["priority"],
            "logo": metadata["logo"],
            "tags": tags,
            "type": get_video_type(title, tags),
            "link": f"https://www.youtube.com/watch?v={video_id}"
        }

        videos_by_id[video_id] = video

    merged_videos = sorted(
        videos_by_id.values(),
        key=lambda video: video.get("published_ts", 0),
        reverse=True
    )

    merged_videos = merged_videos[:MAX_SAVED_VIDEOS]

    archive = {
        "source": metadata["source"],
        "priority": metadata["priority"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": merged_videos
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            archive,
            f,
            ensure_ascii=False,
            indent=4
        )

    return len(data.get("items", []))


def build_football_fallback():
    """
    Fallback pretrage za sve uključene lige iz Football/config.json.
    Nema više fiksnog popisa od pet liga.
    """

    if not FOOTBALL_CONFIG.exists():
        print("[Fallback] Football config ne postoji.")
        return []

    with FOOTBALL_CONFIG.open("r", encoding="utf-8") as f:
        config = json.load(f)

    result = []

    for league in config.get("leagues", []):
        league_name = league.get("name")

        if not league_name:
            continue

        if league.get("enabled", True) is False:
            print(
                f"[Fallback Football] Preskačem isključenu ligu: "
                f"{league_name}"
            )
            continue

        try:
            sources = football.get_sources(config, league_name)
        except Exception as exc:
            print(
                f"[Fallback Football] Greška pri učitavanju izvora "
                f"za {league_name}: {exc}"
            )
            continue

        for source in sources:
            channel_id = source.get("channel_id", "")

            if not CHANNEL_ID_PATTERN.fullmatch(channel_id):
                print(
                    f"[Fallback Football] Neispravan channel ID: "
                    f"{source.get('name', league_name)} "
                    f"({league_name})"
                )
                continue

            result.append({
                "domain": "Football",
                "key": (
                    f"football:fallback:{league_name}:{channel_id}"
                ),
                "query": (
                    f'"{league_name}" latest highlights '
                    f"football goals analysis"
                ),
                "channel_id": channel_id,
                "source_name": source.get("name", league_name),
                "league": league_name,
                "event_name": f"{league_name} - Latest Content",
                "event_time": None,
                "importance": float(
                    league.get("importance", 1.0)
                ),
                "fallback": True
            })

    print(
        f"[Fallback Football] Uključene lige: "
        f"{len({item['league'] for item in result})}"
    )
    print(
        f"[Fallback Football] Kandidata: {len(result)}"
    )

    return result


def build_fallback_candidates():
    """Priprema F1 i svih uključenih nogometnih liga."""

    result = []

    try:
        f1_fallback = f1.fallback_candidates()
        result.extend(f1_fallback)

        print(
            f"[Fallback F1] Kandidata: {len(f1_fallback)}"
        )

    except Exception as exc:
        print(f"[Fallback F1] Greška: {exc}")

    try:
        football_fallback = build_football_fallback()
        result.extend(football_fallback)

    except Exception as exc:
        print(f"[Fallback Football] Greška: {exc}")

    return result


def main():
    if not API_KEY:
        raise RuntimeError(
            "GitHub Secret YOUTUBE_API_KEY nije postavljen."
        )

    config = load_config()
    state = load_state()

    all_candidates = []

    # 1. Kandidati za nogometne utakmice.
    try:
        football_candidates = football.candidates()
        all_candidates.extend(football_candidates)

        print(
            f"[Football] Kandidata: {len(football_candidates)}"
        )

    except Exception as exc:
        print(f"[Football] Greška: {exc}")

    # 2. Kandidati za F1 sesije i aktivni GP vikend.
    try:
        f1_candidates = f1.candidates()
        all_candidates.extend(f1_candidates)

        print(
            f"[F1] Kandidata: {len(f1_candidates)}"
        )

    except Exception as exc:
        print(f"[F1] Greška: {exc}")

    # 3. Fallback samo ako nema kandidata za aktualne događaje.
    if not all_candidates:
        print(
            "[Fallback] Nema kandidata za aktualne događaje. "
            "Pripremam F1 i sve uključene nogometne lige."
        )

        all_candidates = build_fallback_candidates()

    if not all_candidates:
        print("[System] Nema kandidata za pretraživanje.")
        return

    # 4. Odabir prema kvoti i prioritetima.
    selected = select_candidates(
        all_candidates,
        state,
        config
    )

    print(
        f"[System] Odabrano {len(selected)} od "
        f"{len(all_candidates)} kandidata."
    )

    if not selected:
        print("[System] Nema pretraga za ovo pokretanje.")
        return

    # 5. YouTube API pretrage.
    for candidate in selected:
        domain = candidate["domain"]
        key = candidate["key"]
        is_fallback = candidate.get("fallback", False)

        print(
            f"[{domain}] "
            f"{candidate.get('event_name', 'Bez naziva')} "
            f"| {candidate.get('source_name', 'Nepoznat izvor')}"
        )

        # Brojimo pokušaj prije HTTP zahtjeva.
        record_success(
            state,
            domain,
            key,
            fallback=is_fallback
        )

        try:
            data = youtube_search(candidate)
            saved_count = save_results(candidate, data)

            print(
                f"[{domain}] Obrađeno "
                f"{saved_count} rezultata."
            )

        except requests.HTTPError as exc:
            print(f"[{domain}] YouTube HTTP greška: {exc}")

            if exc.response is not None:
                print(exc.response.text[:1000])

        except requests.RequestException as exc:
            print(f"[{domain}] Mrežna greška: {exc}")

        except Exception as exc:
            print(f"[{domain}] Greška: {exc}")

        finally:
            save_state(state)

    print("\n[System] Završno stanje kvote:")
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
