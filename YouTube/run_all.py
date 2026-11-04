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

print("RADNA MAPA:", Path.cwd())
print("BASE:", BASE)
print("FOOTBALL CONFIG:", BASE / "Football" / "config.json")
print("FOOTBALL CONFIG POSTOJI:",
      (BASE / "Football" / "config.json").exists())
print("F1 CONFIG POSTOJI:",
      (BASE / "F1" / "config.json").exists())

API_URL = "https://www.googleapis.com/youtube/v3/search"

API_KEY = os.environ.get("YOUTUBE_API_KEY")


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

    record = {
        "domain": candidate["domain"],
        "event": candidate["event_name"],
        "league": candidate.get("league"),
        "source": candidate["source_name"],
        "channel_id": candidate["channel_id"],
        "query": candidate["query"],
        "event_time": candidate["event_time"],
        "searched_at": datetime.now(
            timezone.utc
        ).isoformat(),
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
        f.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )


def main():
    if not API_KEY:
        raise RuntimeError("GitHub Secret YOUTUBE_API_KEY nije postavljen.")

    all_candidates = []

    try:
        football_candidates = football.candidates()
        all_candidates.extend(football_candidates)
        print(
            f"[Football] Kandidata: {len(football_candidates)}"
        )
    except Exception as exc:
        print(f"[Football] Greška: {exc}")

    try:
        f1_candidates = f1.candidates()
        all_candidates.extend(f1_candidates)
        print(f"[F1] Kandidata: {len(f1_candidates)}")
    except Exception as exc:
        print(f"[F1] Greška: {exc}")

    config = load_config()
    state = load_state()
    now = datetime.now(timezone.utc)

    selected = select_candidates(
        all_candidates,
        state,
        config,
        now
    )

    print(
        f"Odabrano {len(selected)} od "
        f"{len(all_candidates)} kandidata."
    )

    for candidate in selected:
        domain = candidate["domain"]

        print(
            f"[{domain}] {candidate['event_name']} "
            f"| {candidate['source_name']}"
        )

        try:
            data = youtube_search(candidate)

            save_results(candidate, data)

            record_success(
                state,
                candidate,
                datetime.now(timezone.utc)
            )

            save_state(state)

            print(
                f"[{domain}] Spremljeno "
                f"{len(data.get('items', []))} videa."
            )

        except requests.HTTPError as exc:
            print(f"[{domain}] YouTube HTTP greška: {exc}")

            if exc.response is not None:
                print(exc.response.text[:1000])

            # Kod greške kvota se ne troši u lokalnom stanju.
            # Ako je API ipak obradio zahtjev, stvarna kvota
            # može biti potrošena.

        except Exception as exc:
            print(f"[{domain}] Greška: {exc}")

    print("\nZavršno stanje kvote:")
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
