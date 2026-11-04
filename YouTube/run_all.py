import os
import json
import requests

import Football.main as football
import F1.main as f1

from quota_manager import (
    run_quota_selection,
    record_usage,
    save_usage
)

API_URL = "https://www.googleapis.com/youtube/v3/search"

API_KEY = os.environ.get("YOUTUBE_API_KEY")


def youtube_search(query):
    if not API_KEY:
        raise RuntimeError("Nedostaje YOUTUBE_API_KEY")

    params = {
        "part": "snippet",
        "q": query,
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


def save_results(domain, candidate, data):
    os.makedirs(domain, exist_ok=True)

    filename = (
        "youtube_football.jsonl"
        if domain == "Football"
        else "youtube_f1.jsonl"
    )

    path = os.path.join(domain, filename)

    record = {
        "domain": domain,
        "event": candidate["event_name"],
        "query": candidate["query"],
        "searched_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "videos": data.get("items", [])
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )


def main():
    all_candidates = []

    try:
        all_candidates.extend(football.candidates())
    except Exception as exc:
        print(f"[Football] Discovery error: {exc}")

    try:
        all_candidates.extend(f1.candidates())
    except Exception as exc:
        print(f"[F1] Discovery error: {exc}")

    selected, state, now = run_quota_selection(
        all_candidates
    )

    print(
        f"Odabrano {len(selected)} pretraga "
        f"od ukupno {len(all_candidates)} kandidata."
    )

    for candidate in selected:
        domain = candidate["domain"]

        try:
            print(
                f"[{domain}] {candidate['event_name']}"
            )

            data = youtube_search(candidate["query"])

            save_results(domain, candidate, data)

            record_usage(state, candidate, now)

        except Exception as exc:
            print(f"[{domain}] Search error: {exc}")

    save_usage(state)

    print("Stanje kvote:")
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
