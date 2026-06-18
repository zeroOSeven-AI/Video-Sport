import os
import json
import time
import requests
from datetime import datetime

# Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_FOLDER = "YouTube"
DELAY_SECONDS = 2

SOURCES = {
    "formula_1": {"name": "Formula 1", "id": "UCB_qrNyFAFJGdxK69F8S3FQ"},
    "the_race": {"name": "The Race", "id": "UC9suvGlsc2EFr7SIsgWInXQ"},
    "driver61": {"name": "Driver61", "id": "UCJpChgSOTKT9wdxw5fJ53gQ"},
    "p1_matt_tommy": {"name": "P1 with Matt & Tommy", "id": "UCRXn6VOfHAt8zNf8D3ndFcw"},
    "autosport": {"name": "Autosport", "id": "UCZ0SstM3sS_vD_f6v798pDw"},
    "sky_sports_f1": {"name": "Sky Sports F1", "id": "UCgN40g9_RE93nNfX-vS_uRw"}
}

def get_real_uploads_playlist(channel_id):
    # Dynamically fetch the correct uploads playlist ID from YouTube
    url = f"https://www.googleapis.com/youtube/v3/channels?key={YOUTUBE_API_KEY}&id={channel_id}&part=contentDetails"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if items:
                return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"Failed to fetch playlist ID for {channel_id}: {str(e)}")
    return None

def fetch_and_save_channel(slug, info):
    print(f"Processing source: {info['name']}")
    
    # 1. Get the dynamic, real playlist ID
    uploads_playlist_id = get_real_uploads_playlist(info["id"])
    
    if not uploads_playlist_id:
        print(f"Could not resolve uploads playlist for {info['name']}. Skipping.")
        return

    # 2. Fetch videos from that verified playlist
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YOUTUBE_API_KEY}&playlistId={uploads_playlist_id}&part=snippet,contentDetails&maxResults=10"
    
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Error fetching videos for {info['name']}: {response.text}")
            return
            
        data = response.json()
        video_ids = []
        video_details = []
        
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            v_id = item.get("contentDetails", {}).get("videoId") or snippet.get("resourceId", {}).get("videoId")
            
            if v_id:
                video_ids.append(v_id)
                thumbnails = snippet.get("thumbnails", {})
                thumbnail_url = thumbnails.get("high", {}).get("url") or thumbnails.get("default", {}).get("url", "")
                
                video_details.append({
                    "video_id": v_id,
                    "title": snippet.get("title"),
                    "published_at": snippet.get("publishedAt"),
                    "thumbnail": thumbnail_url
                })
            
        ids_csv = ",".join(video_ids)
        embed_url = f"https://www.youtube.com/embed/{video_ids[0]}?playlist={ids_csv}" if video_ids else ""
        
        output_data = {
            "source_name": info["name"],
            "channel_id": info["id"],
            "playlist_id": uploads_playlist_id,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "video_ids": video_ids,
            "playlist_embed_url": embed_url,
            "videos": video_details
        }
        
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        filename = os.path.join(OUTPUT_FOLDER, f"{slug}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved {filename} with {len(video_ids)} videos.")
        
    except Exception as e:
        print(f"Exception while processing {info['name']}: {str(e)}")

def main():
    if not YOUTUBE_API_KEY:
        print("Missing YOUTUBE_API_KEY environment variable.")
        return

    for i, (slug, info) in enumerate(SOURCES.items()):
        fetch_and_save_channel(slug, info)
        if i < len(SOURCES) - 1:
            time.sleep(DELAY_SECONDS)

if __name__ == "__main__":
    main()
