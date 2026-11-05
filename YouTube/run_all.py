
import os
import json
import requests

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

FALLBACK_LEAGUES = [
    "Premier League",
    "LaLiga",
    "Bundesliga",
    "Serie A",
    "Champions League"
]


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
        return BASE / "Football" / "youtube_football.jsonl"

    if domain == "F1":
        return BASE / "F1" / "youtube_f1.jsonl"

    raise ValueError(f"Nepoznata domena: {domain}")


def save_results(candidate, data):
    path = output_file(candidate["domain"])
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "domain": candidate["domain"],
        "event": candidate.get("event_name"),
        "league": candidate.get("league"),
        "source": candidate.get("source_name"),
        "channel_id": candidate.get("channel_id"),
        "query": candidate.get("query"),
        "event_time": candidate.get("event_time"),
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "fallback": candidate.get("fallback", False),
        "videos": []
    }

    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")

        if not video_id:
            continue

        snippet = item.get("snippet", {})

        record["videos"].append({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "channel_title": snippet.get("channelTitle"),
            "channel_id": snippet.get("channelId"),
            "published_at": snippet.get("publishedAt")
        })

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_football_fallback():
    """Fallback pretrage za pet najvažnijih nogometnih natjecanja."""

    if not FOOTBALL_CONFIG.exists():
        print("[Fallback] Football config ne postoji.")
        return []

    with FOOTBALL_CONFIG.open("r", encoding="utf-8") as f:
        config = json.load(f)

    result = []

    for league in config.get("leagues", []):
        league_name = league.get("name")

        if league_name not in FALLBACK_LEAGUES:
            continue

        sources = football.get_sources(config, league_name)

        for source in sources:
            channel_id = source["channel_id"]

            result.append({
                "domain": "Football",
                "key": f"football:fallback:{league_name}:{channel_id}",
                "query": (
                    f'"{league_name}" latest highlights '
                    f"football analysis"
                ),
                "channel_id": channel_id,
                "source_name": source.get("name", league_name),
                "league": league_name,
                "event_name": f"{league_name} - Latest Content",
                "event_time": None,
                "importance": float(league.get("importance", 1.0)),
                "fallback": True
            })

    print(f"[Fallback Football] Kandidata: {len(result)}")
    return result


def build_fallback_candidates():
    """Pokreće se kada nema kandidata za aktualne događaje."""

    result = []

    try:
        f1_fallback = f1.fallback_candidates()
        result.extend(f1_fallback)
        print(f"[Fallback F1] Kandidata: {len(f1_fallback)}")
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

    # 1. Kandidati za nogometne utakmice
    try:
        football_candidates = football.candidates()
        all_candidates.extend(football_candidates)
        print(f"[Football] Kandidata: {len(football_candidates)}")
    except Exception as exc:
        print(f"[Football] Greška: {exc}")

    # 2. Kandidati za F1 sesije
    try:
        f1_candidates = f1.candidates()
        all_candidates.extend(f1_candidates)
        print(f"[F1] Kandidata: {len(f1_candidates)}")
    except Exception as exc:
        print(f"[F1] Greška: {exc}")

    # 3. Fallback samo ako nema kandidata za aktualne događaje
    if not all_candidates:
        print(
            "[Fallback] Nema kandidata za aktualne događaje. "
            "Pripremam F1 i top nogometne lige."
        )
        all_candidates = build_fallback_candidates()

    if not all_candidates:
        print("[System] Nema kandidata za pretraživanje.")
        return

    # 4. Odabir prema kvoti i prioritetima
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

    # 5. YouTube API pretrage
    for candidate in selected:
        domain = candidate["domain"]
        key = candidate["key"]
        is_fallback = candidate.get("fallback", False)

        print(
            f"[{domain}] {candidate.get('event_name', 'Bez naziva')} "
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
            save_results(candidate, data)

            print(
                f"[{domain}] Spremljeno "
                f"{len(data.get('items', []))} videa."
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
