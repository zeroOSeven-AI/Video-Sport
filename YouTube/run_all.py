
import os
import json
import re
import requests

from html import unescape
from pathlib import Path
from datetime import datetime, timezone

import Football.main as football
import F1.main as f1

from video_filter import (
    filter_videos,
    classify_video
)

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


# --------------------------------------------------
# YOUTUBE SEARCH + VIDEO FILTER
# --------------------------------------------------

def youtube_search(candidate):
    if not API_KEY:
        raise RuntimeError("Nedostaje YOUTUBE_API_KEY.")

    params = {
        "part": "snippet",
        "channelId": candidate["channel_id"],
        "type": "video",
        "maxResults": 10,
        "order": "date",
        "key": API_KEY
    }

    query = (candidate.get("query") or "").strip()

    if query:
        params["q"] = query

    print(
        f"[YouTube] Upit: "
        f"{query if query else '(bez ključne riječi - najnoviji videozapisi)'}"
    )

    print(f"[YouTube] Kanal: {params['channelId']}")

    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    page_info = data.get("pageInfo", {})

    print(
        f"[YouTube] Ukupno pronađeno: "
        f"{page_info.get('totalResults', 0)}"
    )

    original_items = data.get("items", [])

    print(
        f"[YouTube] Vraćeno rezultata: "
        f"{len(original_items)}"
    )

    filtered_items, stats = filter_videos(
        original_items,
        candidate["domain"],
        API_KEY
    )

    data["items"] = filtered_items

    print("[Filter] Rezultati:")

    print(
        f"[Filter] Prihvaćeno: "
        f"{stats.get('accepted', 0)}/{stats.get('received', 0)}"
    )

    print(
        f"[Filter] Prekratki videozapisi: "
        f"{stats.get('too_short', 0)}"
    )

    print(
        f"[Filter] Shorts: "
        f"{stats.get('shorts', 0)}"
    )

    print(
        f"[Filter] Isključujuće ključne riječi: "
        f"{stats.get('excluded_keyword', 0)}"
    )

    print(
        f"[Filter] Ostalo (Other): "
        f"{stats.get('other', 0)}"
    )

    print(
        f"[Filter] Kategorizirano: "
        f"{stats.get('categorized', 0)}"
    )

    print(
        f"[Filter] Trajanje nije dostupno: "
        f"{stats.get('missing_duration', 0)}"
    )

    return data


# --------------------------------------------------
# OUTPUT FILES
# --------------------------------------------------

def output_file(domain):
    if domain == "Football":
        return BASE / "Football" / "youtube_football.json"

    if domain == "F1":
        return BASE / "F1" / "youtube_f1.json"

    raise ValueError(f"Nepoznata domena: {domain}")


# --------------------------------------------------
# ARCHIVE METADATA
# --------------------------------------------------

def get_archive_metadata(candidate):
    if candidate["domain"] == "F1":
        return F1_ARCHIVE.copy()

    source_name = candidate.get(
        "source_name",
        "Football"
    )

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


# --------------------------------------------------
# VIDEO TAGS
# --------------------------------------------------

def get_video_tags(title, description="", domain="Football"):
    text = unescape(
        f"{title or ''} {description or ''}"
    )

    tags, _ = classify_video(
        text,
        domain
    )

    return tags


def get_video_type(title, tags, domain="Football"):
    text = title or ""

    _, video_type = classify_video(
        text,
        domain
    )

    if video_type != "other":
        return video_type

    # Ako je video već klasificiran kao other,
    # zadržavamo other umjesto generičke kategorije video.
    return "other"


# --------------------------------------------------
# PUBLISHED DATE
# --------------------------------------------------

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


# --------------------------------------------------
# LOAD EXISTING ARCHIVE
# --------------------------------------------------

def load_existing_archive(path):
    """
    Učitava postojeći arhiv.
    Podržava novi JSON format i stari JSONL format.
    """

    if not path.exists():
        return []

    raw = path.read_text(
        encoding="utf-8"
    ).strip()

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
            domain = "F1" if is_f1 else "Football"

            tags = get_video_tags(
                title,
                description,
                domain
            )

            video_type = video.get("type")

            if not video_type:
                video_type = get_video_type(
                    title,
                    tags,
                    domain
                )

            videos.append({
                "video_id": video_id,
                "title": title,
                "published_at": published_at,
                "published_ts": published_timestamp(published_at),
                "duration_seconds": video.get("duration_seconds", 0),
                "thumbnail": (
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                ),
                "source": source_name,
                "source_key": source_key,
                "priority": 3 if is_f1 else 1,
                "logo": (
                    "logo/formula_1.png"
                    if is_f1 else ""
                ),
                "tags": tags,
                "type": video_type,
                "link": f"https://www.youtube.com/watch?v={video_id}"
            })

    return videos


# --------------------------------------------------
# SAVE RESULTS
# --------------------------------------------------

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

    saved_count = 0
    new_count = 0
    updated_count = 0

    for item in data.get("items", []):
        video_id = item.get(
            "id", {}
        ).get("videoId")

        if not video_id:
            continue

        snippet = item.get("snippet", {})

        title = unescape(
            snippet.get("title", "")
        )

        description = unescape(
            snippet.get("description", "")
        )

        published_at = snippet.get("publishedAt")

        # Koristimo oznake iz filtra.
        tags = item.get("filter_tags", ["other"])

        video_type = item.get(
            "video_type",
            "other"
        )

        # Za svaki slučaj: nepoznata kategorija postaje other.
        if not video_type or video_type == "video":
            video_type = "other"

        video = {
            "video_id": video_id,
            "title": title,
            "published_at": published_at,
            "published_ts": published_timestamp(published_at),
            "duration_seconds": item.get("duration_seconds", 0),
            "thumbnail": (
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            ),
            "source": metadata["source"],
            "source_key": metadata["source_key"],
            "priority": metadata["priority"],
            "logo": metadata["logo"],
            "tags": tags,
            "type": video_type,
            "matched_keywords": item.get(
                "matched_keywords", []
            ),
            "link": f"https://www.youtube.com/watch?v={video_id}"
        }

        if video_id in videos_by_id:
            updated_count += 1
        else:
            new_count += 1

        videos_by_id[video_id] = video
        saved_count += 1

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

    print(f"[Arhiva] Novi videozapisi: {new_count}")
    print(f"[Arhiva] Već postojeći ažurirani: {updated_count}")
    print(f"[Arhiva] Ukupno u arhivi: {len(merged_videos)}")

    return saved_count


# --------------------------------------------------
# FOOTBALL FALLBACK
# --------------------------------------------------

def build_football_fallback():
    """
    Fallback pretrage za uključene lige.
    Svaki YouTube kanal pretražuje se samo jednom.
    """

    if not FOOTBALL_CONFIG.exists():
        print(
            "[Fallback Football] Football config ne postoji."
        )
        return []

    with FOOTBALL_CONFIG.open(
        "r",
        encoding="utf-8"
    ) as f:
        config = json.load(f)

    result = []
    seen_channels = set()
    included_leagues = set()

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
            sources = football.get_sources(
                config,
                league_name
            )

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

            # Isti kanal ne pretražujemo dvaput.
            if channel_id in seen_channels:
                print(
                    f"[Fallback Football] Preskačem dupli kanal: "
                    f"{source.get('name', league_name)} "
                    f"({league_name})"
                )
                continue

            seen_channels.add(channel_id)
            included_leagues.add(league_name)

            result.append({
                "domain": "Football",
                "key": (
                    f"football:fallback:{league_name}:{channel_id}"
                ),
                "query": "",
                "channel_id": channel_id,
                "source_name": source.get(
                    "name",
                    league_name
                ),
                "league": league_name,
                "event_name": (
                    f"{league_name} - Latest Content"
                ),
                "event_time": None,
                "importance": float(
                    league.get("importance", 1.0)
                ),
                "fallback": True
            })

    print(
        f"[Fallback Football] Uključene lige: "
        f"{len(included_leagues)}"
    )

    print(
        f"[Fallback Football] Jedinstvenih kanala: "
        f"{len(result)}"
    )

    print(
        f"[Fallback Football] Kandidata: {len(result)}"
    )

    return result


# --------------------------------------------------
# ALL FALLBACK CANDIDATES
# --------------------------------------------------

def build_fallback_candidates():
    result = []

    try:
        f1_fallback = f1.fallback_candidates()

        result.extend(f1_fallback)

        print(
            f"[Fallback F1] Kandidata: "
            f"{len(f1_fallback)}"
        )

    except Exception as exc:
        print(f"[Fallback F1] Greška: {exc}")

    try:
        football_fallback = build_football_fallback()

        result.extend(football_fallback)

    except Exception as exc:
        print(f"[Fallback Football] Greška: {exc}")

    print(
        f"[Fallback] Ukupno pripremljenih kandidata: "
        f"{len(result)}"
    )

    return result


# --------------------------------------------------
# CANDIDATE DEDUPLICATION
# --------------------------------------------------

def deduplicate_candidates(candidates):
    """
    Uklanja duplikate prema candidate key vrijednosti.
    """

    result = []
    seen = set()

    for candidate in candidates:
        key = candidate.get("key")

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(candidate)

    return result


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if not API_KEY:
        raise RuntimeError(
            "GitHub Secret YOUTUBE_API_KEY nije postavljen."
        )

    config = load_config()
    state = load_state()

    all_candidates = []

    # ----------------------------------------------
    # 1. FOOTBALL EVENT CANDIDATES
    # ----------------------------------------------

    try:
        football_candidates = football.candidates()

        all_candidates.extend(football_candidates)

        print(
            f"[Football] Kandidata za događaje: "
            f"{len(football_candidates)}"
        )

    except Exception as exc:
        print(f"[Football] Greška: {exc}")

    # ----------------------------------------------
    # 2. F1 EVENT CANDIDATES
    # ----------------------------------------------

    try:
        f1_candidates = f1.candidates()

        all_candidates.extend(f1_candidates)

        print(
            f"[F1] Kandidata za događaje i vikend markere: "
            f"{len(f1_candidates)}"
        )

    except Exception as exc:
        print(f"[F1] Greška: {exc}")

    # ----------------------------------------------
    # 3. FALLBACK CANDIDATES
    # ----------------------------------------------

    print()
    print("[System] Pripremam fallback kandidate.")

    fallback_candidates = build_fallback_candidates()

    all_candidates.extend(fallback_candidates)

    # ----------------------------------------------
    # 4. DEDUPLICATION
    # ----------------------------------------------

    all_candidates = deduplicate_candidates(all_candidates)

    print()
    print("[System] ------------------------------")

    print(f"[System] Ukupno kandidata: {len(all_candidates)}")

    print(
        f"[System] Stvarni Football/F1 kandidati: "
        f"{sum(1 for c in all_candidates if not c.get('fallback', False) and not c.get('skip_search', False))}"
    )

    print(
        f"[System] Fallback kandidati: "
        f"{sum(1 for c in all_candidates if c.get('fallback', False))}"
    )

    print(
        f"[System] F1 vikend markeri: "
        f"{sum(1 for c in all_candidates if c.get('skip_search', False))}"
    )

    print("[System] ------------------------------")

    if not all_candidates:
        print("[System] Nema kandidata za pretraživanje.")
        return

    # ----------------------------------------------
    # 5. QUOTA AND PRIORITY SELECTION
    # ----------------------------------------------

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

    # ----------------------------------------------
    # 6. YOUTUBE SEARCH + FILTER + SAVE
    # ----------------------------------------------

    for candidate in selected:
        domain = candidate["domain"]
        key = candidate["key"]

        is_fallback = candidate.get("fallback", False)

        print()
        print(
            f"[{domain}] "
            f"{candidate.get('event_name', 'Bez naziva')} "
            f"| {candidate.get('source_name', 'Nepoznat izvor')}"
        )

        print(
            f"[{domain}] Vrsta: "
            f"{'FALLBACK' if is_fallback else 'DOGAĐAJ'}"
        )

        # Evidentiramo pokušaj prije HTTP zahtjeva.
        record_success(
            state,
            domain,
            key,
            fallback=is_fallback
        )

        try:
            data = youtube_search(candidate)

            saved_count = save_results(
                candidate,
                data
            )

            print(
                f"[{domain}] Prihvaćeno za arhivu: "
                f"{saved_count}"
            )

            if not data.get("items"):
                print(
                    f"[{domain}] Nema videozapisa koji "
                    f"prolaze filter."
                )

        except requests.HTTPError as exc:
            print(f"[{domain}] YouTube HTTP greška: {exc}")

            if exc.response is not None:
                print(
                    f"[{domain}] Odgovor API-ja: "
                    f"{exc.response.text[:1500]}"
                )

        except requests.RequestException as exc:
            print(f"[{domain}] Mrežna greška: {exc}")

        except Exception as exc:
            print(f"[{domain}] Greška: {exc}")

        finally:
            save_state(state)

    # ----------------------------------------------
    # 7. FINAL QUOTA STATE
    # ----------------------------------------------

    print()
    print("[System] Završno stanje kvote:")

    print(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
