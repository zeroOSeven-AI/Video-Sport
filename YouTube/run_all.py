import os
import json
import re

import requests

from html import unescape
from pathlib import Path
from datetime import datetime, timezone

import Football.main as football
import F1.main as f1
import MotoGP.main as motogp

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


# --------------------------------------------------
# PATHS AND CONFIGURATION
# --------------------------------------------------

BASE = Path(__file__).resolve().parent

FOOTBALL_CONFIG = BASE / "Football" / "config.json"
F1_CONFIG = BASE / "F1" / "config.json"
MOTOGP_CONFIG = BASE / "MotoGP" / "config.json"

API_URL = "https://www.googleapis.com/youtube/v3/search"
API_KEY = os.environ.get("YOUTUBE_API_KEY")

MAX_SAVED_VIDEOS = 500

F1_ARCHIVE = {
    "source": "Formula 1",
    "priority": 3,
    "source_key": "formula_1",
    "logo": "logo/formula_1.png"
}

MOTOGP_ARCHIVE = {
    "source": "MotoGP",
    "priority": 2,
    "source_key": "motogp",
    "logo": "logo/motogp.png"
}

CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")

F1_FALLBACK_QUERIES = [
    "Formula 1 race highlights",
    "Formula 1 qualifying highlights",
    "Formula 1 full race"
]

FOOTBALL_FALLBACK_QUERY = "highlights"


# --------------------------------------------------
# CONFIGURATION DIAGNOSTICS
# --------------------------------------------------

def load_json_config(path, label):
    if not path.exists():
        raise FileNotFoundError(
            f"[{label}] Konfiguracija nije pronađena: {path}"
        )

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def print_channel_diagnostics():
    print()
    print("=" * 60)
    print("[CONFIG] PROVJERA YOUTUBE KANALA")
    print("=" * 60)

    football_config = load_json_config(
        FOOTBALL_CONFIG,
        "Football"
    )

    f1_config = load_json_config(
        F1_CONFIG,
        "F1"
    )

    motogp_config = load_json_config(
        MOTOGP_CONFIG,
        "MotoGP"
    )

    print(f"[CONFIG] Football: {FOOTBALL_CONFIG}")
    print(f"[CONFIG] F1: {F1_CONFIG}")
    print(f"[CONFIG] MotoGP: {MOTOGP_CONFIG}")

    configurations = [
        ("Football", football_config),
        ("F1", f1_config),
        ("MotoGP", motogp_config)
    ]

    channel_counts = {}

    for domain, config in configurations:
        print()
        print(f"[CONFIG] {domain.upper()} CHANNELS")

        channels = set()

        for source in config.get("youtube_sources", []):
            name = source.get("name", "Unknown")
            channel_id = source.get("channel_id", "")
            enabled = source.get("enabled", True)

            valid = bool(
                CHANNEL_ID_PATTERN.fullmatch(channel_id)
            )

            status = "OK" if valid else "NEISPRAVAN ID"

            if not enabled:
                status = "ISKLJUČEN"

            print(
                f"[CONFIG {domain}] {status} | "
                f"{name} | {channel_id}"
            )

            if enabled and valid:
                channels.add(channel_id)

        channel_counts[domain] = len(channels)

    print()

    for domain, count in channel_counts.items():
        print(
            f"[CONFIG] Jedinstvenih {domain} kanala: {count}"
        )

    print("=" * 60)
    print()

    return (
        football_config,
        f1_config,
        motogp_config
    )


# --------------------------------------------------
# YOUTUBE SEARCH + VIDEO FILTER
# --------------------------------------------------

def youtube_search(candidate):
    if not API_KEY:
        raise RuntimeError(
            "Nedostaje YOUTUBE_API_KEY."
        )

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
        f"[YouTube] Upit: {query or '(bez ključne riječi)'}"
    )

    print(
        f"[YouTube] Kanal: {params['channelId']}"
    )

    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    page_info = data.get("pageInfo", {})
    original_items = data.get("items", [])

    print(
        f"[YouTube] Ukupno pronađeno: "
        f"{page_info.get('totalResults', 0)}"
    )

    print(
        f"[YouTube] Vraćeno rezultata: "
        f"{len(original_items)}"
    )

    if candidate["domain"] == "MotoGP":
        filtered_items, stats = motogp.filter_videos(
            original_items,
            API_KEY
        )
    else:
        filtered_items, stats = filter_videos(
            original_items,
            candidate["domain"],
            API_KEY
        )

    data["items"] = filtered_items

    print("[Filter] Rezultati:")

    print(
        f"[Filter] Prihvaćeno: "
        f"{stats.get('accepted', 0)}/"
        f"{stats.get('received', 0)}"
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

    if domain == "MotoGP":
        return BASE / "MotoGP" / "youtube_motogp.json"

    raise ValueError(
        f"Nepoznata domena: {domain}"
    )


# --------------------------------------------------
# ARCHIVE METADATA
# --------------------------------------------------

def get_archive_metadata(candidate):
    domain = candidate["domain"]

    if domain == "F1":
        return F1_ARCHIVE.copy()

    if domain == "MotoGP":
        return MOTOGP_ARCHIVE.copy()

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

def get_video_tags(
    title,
    description="",
    domain="Football"
):
    text = unescape(
        f"{title or ''} {description or ''}"
    )

    if domain == "MotoGP":
        tags, _ = motogp.classify_video(title or "")
        return tags

    tags, _ = classify_video(
        text,
        domain
    )

    return tags


def get_video_type(
    title,
    tags,
    domain="Football"
):
    if domain == "MotoGP":
        _, video_type = motogp.classify_video(
            title or ""
        )
    else:
        _, video_type = classify_video(
            title or "",
            domain
        )

    return (
        video_type
        if video_type != "other"
        else "other"
    )


# --------------------------------------------------
# PUBLISHED DATE
# --------------------------------------------------

def published_timestamp(published_at):
    if not published_at:
        return 0

    try:
        value = published_at.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return int(dt.timestamp())

    except (ValueError, TypeError):
        return 0


# --------------------------------------------------
# LOAD EXISTING ARCHIVE
# --------------------------------------------------

def load_existing_archive(path, domain):
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

        record_domain = record.get("domain", domain)

        if record_domain not in (
            "Football",
            "F1",
            "MotoGP"
        ):
            record_domain = domain

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

            tags = get_video_tags(
                title,
                description,
                record_domain
            )

            video_type = video.get("type")

            if not video_type:
                video_type = get_video_type(
                    title,
                    tags,
                    record_domain
                )

            if record_domain == "F1":
                priority = 3
                logo = "logo/formula_1.png"
            elif record_domain == "MotoGP":
                priority = 2
                logo = "logo/motogp.png"
            else:
                priority = 1
                logo = ""

            videos.append({
                "video_id": video_id,
                "title": title,
                "published_at": published_at,
                "published_ts": published_timestamp(
                    published_at
                ),
                "duration_seconds": video.get(
                    "duration_seconds",
                    0
                ),
                "thumbnail": (
                    f"https://i.ytimg.com/vi/"
                    f"{video_id}/hqdefault.jpg"
                ),
                "source": source_name,
                "source_key": source_key,
                "priority": priority,
                "logo": logo,
                "tags": tags,
                "type": video_type,
                "link": (
                    f"https://www.youtube.com/watch"
                    f"?v={video_id}"
                )
            })

    return videos


# --------------------------------------------------
# SAVE RESULTS
# --------------------------------------------------

def save_results(candidate, data):
    domain = candidate["domain"]

    path = output_file(domain)

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    metadata = get_archive_metadata(candidate)

    videos = load_existing_archive(
        path,
        domain
    )

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
            "id",
            {}
        ).get("videoId")

        if not video_id:
            continue

        snippet = item.get(
            "snippet",
            {}
        )

        title = unescape(
            snippet.get("title", "")
        )

        description = unescape(
            snippet.get("description", "")
        )

        published_at = snippet.get(
            "publishedAt"
        )

        tags = item.get(
            "filter_tags",
            ["other"]
        )

        video_type = item.get(
            "video_type",
            "other"
        )

        if not video_type or video_type == "video":
            video_type = "other"

        video = {
            "video_id": video_id,
            "title": title,
            "published_at": published_at,
            "published_ts": published_timestamp(
                published_at
            ),
            "duration_seconds": item.get(
                "duration_seconds",
                0
            ),
            "thumbnail": (
                f"https://i.ytimg.com/vi/"
                f"{video_id}/hqdefault.jpg"
            ),
            "source": metadata["source"],
            "source_key": metadata["source_key"],
            "priority": metadata["priority"],
            "logo": metadata["logo"],
            "tags": tags,
            "type": video_type,
            "matched_keywords": item.get(
                "matched_keywords",
                []
            ),
            "link": (
                f"https://www.youtube.com/watch"
                f"?v={video_id}"
            )
        }

        if video_id in videos_by_id:
            updated_count += 1
        else:
            new_count += 1

        videos_by_id[video_id] = video
        saved_count += 1

    merged_videos = sorted(
        videos_by_id.values(),
        key=lambda video: video.get(
            "published_ts",
            0
        ),
        reverse=True
    )[:MAX_SAVED_VIDEOS]

    archive = {
        "source": metadata["source"],
        "priority": metadata["priority"],
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "videos": merged_videos
    }

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            archive,
            file,
            ensure_ascii=False,
            indent=4
        )

    print(
        f"[Arhiva] Novi videozapisi: {new_count}"
    )

    print(
        f"[Arhiva] Već postojeći ažurirani: "
        f"{updated_count}"
    )

    print(
        f"[Arhiva] Ukupno u arhivi: "
        f"{len(merged_videos)}"
    )

    print(
        f"[Arhiva] Datoteka: {path}"
    )

    return saved_count


# --------------------------------------------------
# FOOTBALL FALLBACK
# --------------------------------------------------

def build_football_fallback():
    if not FOOTBALL_CONFIG.exists():
        print(
            "[Fallback Football] "
            f"Config ne postoji: {FOOTBALL_CONFIG}"
        )
        return []

    with FOOTBALL_CONFIG.open(
        "r",
        encoding="utf-8"
    ) as file:
        config = json.load(file)

    channels = {}

    print()
    print("[DEBUG Football] UČITANI KANALI")

    for source in config.get(
        "youtube_sources",
        []
    ):
        if source.get("enabled", True) is False:
            continue

        channel_id = source.get(
            "channel_id",
            ""
        )

        if not CHANNEL_ID_PATTERN.fullmatch(
            channel_id
        ):
            print(
                f"[DEBUG Football] NEISPRAVAN ID: "
                f"{source.get('name')} | {channel_id}"
            )
            continue

        league_name = source.get(
            "league_name",
            "Unknown"
        )

        source_name = source.get(
            "name",
            league_name
        )

        print(
            f"[DEBUG Football] {source_name} | "
            f"{league_name} | CHANNEL ID: {channel_id}"
        )

        if channel_id not in channels:
            channels[channel_id] = {
                "channel_id": channel_id,
                "source_name": source_name,
                "leagues": [],
                "importance": 1.0
            }

        entry = channels[channel_id]

        if league_name not in entry["leagues"]:
            entry["leagues"].append(league_name)

    league_importance = {
        league.get("name"): float(
            league.get("importance", 1.0)
        )
        for league in config.get("leagues", [])
    }

    result = []

    for channel_id, source in channels.items():
        leagues = source["leagues"]

        source["importance"] = max(
            [
                league_importance.get(
                    league,
                    1.0
                )
                for league in leagues
            ] or [1.0]
        )

        league_label = " / ".join(leagues)

        print(
            f"[DEBUG Football] KANDIDAT: "
            f"{source['source_name']} | "
            f"{league_label} | "
            f"CHANNEL ID: {channel_id}"
        )

        result.append({
            "domain": "Football",
            "key": f"football:fallback:{channel_id}",
            "query": FOOTBALL_FALLBACK_QUERY,
            "channel_id": channel_id,
            "source_name": source["source_name"],
            "leagues": leagues,
            "league": league_label,
            "event_name": (
                f"{league_label} - Match Highlights"
            ),
            "event_time": None,
            "importance": source["importance"],
            "fallback": True
        })

    print(
        f"[Fallback Football] "
        f"Jedinstvenih kanala: {len(result)}"
    )

    print(
        f"[Fallback Football] Kandidata: {len(result)}"
    )

    return result


# --------------------------------------------------
# F1 FALLBACK
# --------------------------------------------------

def build_f1_fallback():
    try:
        original_candidates = (
            f1.fallback_candidates()
        )

    except Exception as exc:
        print(
            f"[Fallback F1] Greška: {exc}"
        )
        return []

    if not original_candidates:
        print(
            "[Fallback F1] Nema konfiguriranih izvora."
        )
        return []

    sources_by_channel = {}

    for candidate in original_candidates:
        channel_id = candidate.get(
            "channel_id",
            ""
        )

        if not CHANNEL_ID_PATTERN.fullmatch(
            channel_id
        ):
            continue

        if channel_id not in sources_by_channel:
            sources_by_channel[channel_id] = (
                candidate.copy()
            )

    result = []

    slugs = [
        "race-highlights",
        "qualifying-highlights",
        "full-race"
    ]

    for channel_id, source in sources_by_channel.items():
        print(
            f"[DEBUG F1] {source.get('source_name')} | "
            f"CHANNEL ID: {channel_id}"
        )

        for index, query in enumerate(
            F1_FALLBACK_QUERIES
        ):
            candidate = source.copy()

            candidate.update({
                "domain": "F1",
                "key": (
                    f"f1:fallback:{channel_id}:"
                    f"{slugs[index]}"
                ),
                "query": query,
                "channel_id": channel_id,
                "source_name": "Formula 1 Official",
                "event_name": query,
                "fallback": True
            })

            result.append(candidate)

    print(
        f"[Fallback F1] Kandidata: {len(result)}"
    )

    return result


# --------------------------------------------------
# MOTOGP FALLBACK
# --------------------------------------------------

def build_motogp_fallback():
    try:
        result = motogp.fallback_candidates()

    except Exception as exc:
        print(
            f"[Fallback MotoGP] Greška: {exc}"
        )
        return []

    print(
        f"[Fallback MotoGP] Kandidata: {len(result)}"
    )

    return result


# --------------------------------------------------
# ALL FALLBACK CANDIDATES
# --------------------------------------------------

def build_fallback_candidates():
    result = []

    result.extend(
        build_f1_fallback()
    )

    result.extend(
        build_motogp_fallback()
    )

    result.extend(
        build_football_fallback()
    )

    print(
        f"[Fallback] Ukupno pripremljenih kandidata: "
        f"{len(result)}"
    )

    return result


# --------------------------------------------------
# CANDIDATE DEDUPLICATION
# --------------------------------------------------

def deduplicate_candidates(candidates):
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

    # 1. Provjeri konfiguracije.
    print_channel_diagnostics()

    # 2. Učitaj kvote i stanje.
    config = load_config()
    state = load_state()

    all_candidates = []

    # 3. FOOTBALL EVENT CANDIDATES
    try:
        football_candidates = football.candidates()

        all_candidates.extend(
            football_candidates
        )

        print(
            f"[Football] Kandidata za događaje: "
            f"{len(football_candidates)}"
        )

    except Exception as exc:
        print(
            f"[Football] Greška: {exc}"
        )

    # 4. F1 EVENT CANDIDATES
    try:
        f1_candidates = f1.candidates()

        all_candidates.extend(
            f1_candidates
        )

        print(
            f"[F1] Kandidata za događaje i vikend markere: "
            f"{len(f1_candidates)}"
        )

    except Exception as exc:
        print(
            f"[F1] Greška: {exc}"
        )

    # 5. MOTOGP EVENT CANDIDATES
    try:
        motogp_candidates = motogp.candidates()

        all_candidates.extend(
            motogp_candidates
        )

        print(
            f"[MotoGP] Kandidata za sesije i vikend markere: "
            f"{len(motogp_candidates)}"
        )

    except Exception as exc:
        print(
            f"[MotoGP] Greška: {exc}"
        )

    # 6. FALLBACK CANDIDATES
    print()
    print(
        "[System] Pripremam fallback kandidate."
    )

    fallback_candidates = (
        build_fallback_candidates()
    )

    all_candidates.extend(
        fallback_candidates
    )

    # 7. DEDUPLICATION
    all_candidates = deduplicate_candidates(
        all_candidates
    )

    print()
    print(
        "[System] ------------------------------"
    )

    print(
        f"[System] Ukupno kandidata: "
        f"{len(all_candidates)}"
    )

    for domain in ("Football", "F1", "MotoGP"):
        count = sum(
            1 for candidate in all_candidates
            if candidate.get("domain") == domain
            and not candidate.get("fallback", False)
            and not candidate.get("skip_search", False)
        )

        print(
            f"[System] Stvarni {domain} kandidati: {count}"
        )

    print(
        f"[System] Fallback kandidati: "
        f"{sum(1 for c in all_candidates if c.get('fallback', False))}"
    )

    print(
        f"[System] F1 vikend markeri: "
        f"{sum(1 for c in all_candidates if c.get('f1_weekend', False))}"
    )

    print(
        f"[System] MotoGP vikend markeri: "
        f"{sum(1 for c in all_candidates if c.get('motogp_weekend', False))}"
    )

    print(
        "[System] ------------------------------"
    )

    if not all_candidates:
        print(
            "[System] Nema kandidata za pretraživanje."
        )
        return

    # 8. QUOTA AND PRIORITY SELECTION
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
        print(
            "[System] Nema pretraga za ovo pokretanje."
        )
        return

    # 9. YOUTUBE SEARCH + FILTER + SAVE
    for candidate in selected:
        domain = candidate["domain"]
        key = candidate["key"]

        is_fallback = candidate.get(
            "fallback",
            False
        )

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

        print(
            f"[{domain}] KORISTI CHANNEL ID: "
            f"{candidate.get('channel_id', 'NEMA')}"
        )

        record_success(
            state,
            domain,
            key,
            fallback=is_fallback
        )

        try:
            data = youtube_search(
                candidate
            )

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
            print(
                f"[{domain}] YouTube HTTP greška: {exc}"
            )

            if exc.response is not None:
                print(
                    f"[{domain}] Odgovor API-ja: "
                    f"{exc.response.text[:1500]}"
                )

        except requests.RequestException as exc:
            print(
                f"[{domain}] Mrežna greška: {exc}"
            )

        except Exception as exc:
            print(
                f"[{domain}] Greška: {exc}"
            )

        finally:
            save_state(state)

    # 10. FINAL QUOTA STATE
    print()
    print(
        "[System] Završno stanje kvote:"
    )

    print(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
