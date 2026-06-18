import os
import json
import time
import requests
from datetime import datetime

# Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_FOLDER = "YouTube"
DELAY_SECONDS = 3  # Time to wait between each channel request

# Dictionary of sources with their clean filenames and YouTube Channel IDs
SOURCES = {
    "formula_1": {"name": "Formula 1", "id": "UCB_qrNyFAFJGdxK69F8S3FQ"},
    "the_race": {"name": "The Race", "id": "UC9suvGlsc2EFr7SIsgWInXQ"},
    "driver61": {"name": "Driver61", "id": "UCJpChgSOTKT9wdxw5fJ53gQ"},
    "p1_matt_tommy": {"name": "P1 with Matt & Tommy", "id": "UCRXn6VOfHAt8zNf8D3ndFcw"},
    "autosport": {"name": "Autosport", "id": "UCZ0SstM3sS_vD_f6v798pDw"},
    "sky_sports_f1": {"name": "Sky Sports F1", "id": "UCgN40g9_RE93nNfX-vS_uRw"}
}

def fetch_and_save_channel(slug, info):
    print(f"Processing source: {info['name']}")
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={info['id']}&part=id,snippet&order=date&maxResults=10&type=video"
    
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Error fetching {info['name']}: {response.text}")
            return
            
        data = response.json()
        video_ids = []
        video_details = []
        
        for item in data.get("items", []):
            v_id = item["id"]["videoId"]
            video_ids.append(v_id)
            video_details.append({
                "video_id": v_id,
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["high"]["url"]
            })
            
        # Creating a custom playlist embed URL
        ids_csv = ",".join(video_ids)
        embed_url = f"https://www.youtube.com/embed/{video_ids[0]}?playlist={ids_csv}" if video_ids else ""
        
        output_data = {
            "source_name": info["name"],
            "channel_id": info["id"],
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "video_ids": video_ids,
            "playlist_embed_url": embed_url,
            "videos": video_details
        }
        
        # Ensure the output directory exists
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        
        # Save to the specific YouTube folder
        filename = os.path.join(OUTPUT_FOLDER, f"{slug}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved {filename}")
        
    except Exception as e:
        print(f"Exception while processing {info['name']}: {str(e)}")

def main():
    if not YOUTUBE_API_KEY:
        print("Missing YOUTUBE_API_KEY environment variable.")
        return

    # Loop through each source with a delay in between
    for i, (slug, info) in enumerate(SOURCES.items()):
        fetch_and_save_channel(slug, info)
        
        # If it's not the last channel, wait for a few seconds before the next request
        if i < len(SOURCES) - 1:
            print(f"Waiting {DELAY_SECONDS} seconds before the next request...")
            time.sleep(DELAY_SECONDS)

if __name__ == "__main__":
    main()
