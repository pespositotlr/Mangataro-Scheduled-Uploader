import requests
import json
import os
import zipfile
import re
import tempfile
import argparse
import decimal
import tomllib
import time
import pytz
from pathlib import Path
from bs4 import BeautifulSoup
from rich.progress import Progress, BarColumn, DownloadColumn, TextColumn
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from datetime import datetime

# --- Config & Helpers ---
def load_config(file_path="config.toml"):
    with open(file_path, "rb") as f:
        return tomllib.load(f)
        
def get_session():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return session

def get_manga_id(session, manga_name):
    if os.path.exists("series_map.json"):
        with open("series_map.json", "r") as f:
            mapping = json.load(f)
            if manga_name in mapping: return mapping[manga_name]

    print(f"Searching for ID for {manga_name}...")
    res = session.get(f"https://hub.mangataro.org/chapters/search-manga?search={manga_name}&limit=1")
    manga_id = int(res.json()["data"][0]["ID"])
    
    mapping = {}
    if os.path.exists("series_map.json"):
        with open("series_map.json", "r") as f: mapping = json.load(f)
    mapping[manga_name] = manga_id
    with open("series_map.json", "w") as f: json.dump(mapping, f)
    return manga_id

def find_chapter_id(session, manga_id, chapter_number):
    url = f"https://hub.mangataro.org/chapters?manga_id={manga_id}&search={chapter_number}"
    res = session.get(url)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    for row in soup.select('table.table tbody tr'):
        if str(chapter_number) in row.get_text():
            edit_link = row.find('a', title='Edit')
            if edit_link and edit_link.has_attr('href'):
                return int(edit_link['href'].split('/')[-1])
    return None
    
def get_chapter_url(session, manga_id, chapter_number):
    url = f"https://hub.mangataro.org/chapters?manga_id={manga_id}&search={chapter_number}"
    res = session.get(url)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Locate the row that matches the chapter number
    for row in soup.select('table.table tbody tr'):
        # Check if the row contains the correct chapter number
        ch_div = row.select_one('td div.font-mono')
        if ch_div and str(float(chapter_number)).rstrip('0').rstrip('.') == ch_div.get_text().strip():
            # Find the "View" link (the one with the external link icon/title='View')
            view_link = row.find('a', title='View')
            if view_link and view_link.has_attr('href'):
                return view_link['href']
    return None
    
def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

# --- Branch 1: Update Existing ---
def upload_or_edit(session, zip_path, metadata, chapter_id):
    edit_url = f"https://hub.mangataro.org/chapters/edit/{chapter_id}"
    res_page = session.get(edit_url)
    
    soup = BeautifulSoup(res_page.text, 'html.parser')
    token_element = soup.find('input', {'name': 'csrf_token'})
    if not token_element:
        print("CRITICAL: Could not fetch fresh CSRF token.")
        return None
    metadata['csrf_token'] = token_element['value']
    
    url = f"https://hub.mangataro.org/chapters/update/{chapter_id}"

    # Open the zip file directly
    with open(zip_path, 'rb') as f:
        # Prepare fields as a list of tuples
        fields = [(k, str(v)) for k, v in metadata.items()]
        
        # Add the zip file as a single entity
        # We use 'application/zip' as the mime type
        fields.append(('chapter_images[]', (os.path.basename(zip_path), f, 'application/zip')))
            
        # Create MultipartEncoder
        encoder = MultipartEncoder(fields=fields)
        
        # Setup Progress Bar
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
        ) as progress:
            task = progress.add_task("Uploading ZIP file...", total=encoder.len)
            
            def callback(monitor):
                progress.update(task, completed=monitor.bytes_read)
            
            monitor = MultipartEncoderMonitor(encoder, callback)
            
            # Send POST
            res = session.post(
                url, 
                data=monitor, 
                headers={'Content-Type': monitor.content_type}
            )
            
        return res

# --- Branch 2: Store New ---
def store_single(session, zip_path, metadata):
    # 1. Fetch CSRF
    add_page = session.get("https://hub.mangataro.org/chapters/create")
    soup = BeautifulSoup(add_page.text, 'html.parser')
    token_element = soup.find('input', {'name': 'csrf_token'})
    metadata['csrf_token'] = token_element['value']
    
    url = "https://hub.mangataro.org/chapters/store-single"
    
    # 2. Use the ZIP directly as 'chapter_zip'
    with open(zip_path, 'rb') as f:
        # Prepare fields as a LIST OF TUPLES
        fields = [(k, str(v)) for k, v in metadata.items()]
        fields.append(('chapter_zip', (os.path.basename(zip_path), f, 'application/zip')))
            
        encoder = MultipartEncoder(fields=fields)
        
        # 3. Retry Logic
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                # 1. RE-CREATE the encoder and monitor inside the loop
                # This ensures the file pointer is fresh for every attempt
                encoder = MultipartEncoder(fields={'file': ('filename', open(zip_path, 'rb'))})
                
                with Progress(...) as progress:
                    task = progress.add_task("Uploading...", total=encoder.len)
                    monitor = MultipartEncoderMonitor(encoder, lambda m: progress.update(task, completed=m.bytes_read))
                    
                    # 2. Use a NEW session or at least clear cookies/headers if needed
                    res = session.post(url, data=monitor, headers={'Content-Type': monitor.content_type}, timeout=300)
                
                if res.status_code == 200:
                    return res
                else:
                    print(f"Attempt {attempt} failed (Status: {res.status_code})")
                    
            except Exception as e:
                print(f"Attempt {attempt} failed with error: {e}")
            
            # Cleanup and wait
            if attempt < max_attempts:
                print("Waiting 60 seconds before retrying...")
                time.sleep(60)
        
        return None # Return None if all attempts fail

def authenticate(session, email, password):
    res_get = session.get("https://hub.mangataro.org/")
    csrf_token = BeautifulSoup(res_get.text, 'html.parser').find('input', {'name': 'csrf_token'})['value']
    res_post = session.post("https://hub.mangataro.org/auth", data={'csrf_token': csrf_token, 'email': email, 'password': password})
    return res_post.status_code == 200

# --- Main Entry Point ---
if __name__ == "__main__":
    # 1. Load the config file
    config = load_config()
    
    # Access values from the config
    email = config['auth']['email']
    password = config['auth']['password']
    group_id = config['settings']['group_id']
    
    parser = argparse.ArgumentParser()
    parser.add_argument("manga_name")
    parser.add_argument("chapter_num", type=float)
    parser.add_argument("chapter_title")
    parser.add_argument("zip_path")
    parser.add_argument("--schedule", help="Schedule time (YYYY-MM-DD HH:MM:SS)", default=None)
    args = parser.parse_args()
    
    # --- NEW YORK SCHEDULING LOGIC ---
    if args.schedule:
        ny_tz = pytz.timezone('America/New_York')
        # Parse the input string into a datetime object
        try:
            # Try full format first
            target_dt_naive = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Fall back to shorter format
            target_dt_naive = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M")
        # Localize the naive datetime to NY time
        target_dt_ny = ny_tz.localize(target_dt_naive)
        
        # Get current time in NY
        now_ny = datetime.now(ny_tz)
        
        wait_seconds = (target_dt_ny - now_ny).total_seconds()
        
        if wait_seconds > 0:
            print(f"Scheduled for {args.schedule} NY Time. Waiting {int(wait_seconds)} seconds...")
            time.sleep(wait_seconds)
        else:
            print("Scheduled time is in the past. Running immediately.")

    session = get_session()
    if authenticate(session, email, password):
        manga_id = get_manga_id(session, args.manga_name)
        formatted_ch_num = int(args.chapter_num) if args.chapter_num.is_integer() else args.chapter_num
        ch_id = find_chapter_id(session, manga_id, formatted_ch_num)
        
        meta = {
            'manga_id': manga_id,
            'group_id': group_id,
            'chapter_number': formatted_ch_num, # Clean format
            'language': 'en',
            'chapter_title': args.chapter_title,
            'post_status': 'publish',
            'chapter_type': 'media'
        }

        if ch_id:
            print(f"Chapter {formatted_ch_num} exists (ID: {ch_id}). Updating...")
            session.get(f"https://hub.mangataro.org/chapters/delete-images/{ch_id}")
            res = upload_or_edit(session, args.zip_path, meta, ch_id)
        else:
            print(f"Chapter {args.chapter_num} not found. Creating new...")
            res = store_single(session, args.zip_path, meta)
        
        print(f"Final Status: {res.status_code}")
        
        if res.status_code == 200:
            chapter_url = get_chapter_url(session, manga_id, formatted_ch_num)
            if chapter_url:
                print(f"Upload Successful! View here: {chapter_url}")
            else:
                print("Upload successful, but could not retrieve the public URL.")