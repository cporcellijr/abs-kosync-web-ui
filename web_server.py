from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import logging
from pathlib import Path
from main import SyncManager
import time
import requests
import os
import shutil
import subprocess
import threading
from logging.handlers import RotatingFileHandler
from urllib.parse import urljoin
import html

# ---------------- APP SETUP ----------------

app = Flask(__name__)
app.secret_key = "kosync-queue-secret-unified-app"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

manager = SyncManager()

# ---------------- BOOK LINKER CONFIG ----------------

EBOOK_DIR = Path("/books")  # Mounted C:\Users\cporc\LargeEPUBs
DEST_BASE = Path("/media_books")  # Mounted C:\Media\Books
ABS_AUDIO_ROOT = Path("/audiobooks")  # Mounted D:\Audiobooks - Copy

ABS_API_URL = os.environ.get("ABS_SERVER", "https://audiobookshelf.blackcatmedia.xyz")
ABS_API_TOKEN = os.environ.get("ABS_KEY", "")
ABS_LIBRARY_ID = os.environ.get("ABS_LIBRARY_ID", "dc9e51e4-1a76-4d7e-a929-235988c39a8f")

MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL", "3600"))  # Default 1 hour

LOG_DIR = Path("/data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "unified_app.log"

def setup_file_logging():
    file_handler = RotatingFileHandler(str(LOG_PATH), maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
    logger.addHandler(file_handler)

setup_file_logging()

# ---------------- BOOK LINKER HELPERS ----------------

def safe_folder_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    name = html.escape(str(name).strip())[:150]
    for c in invalid:
        name = name.replace(c, '_')
    return name.strip() or "Unknown"

app.jinja_env.globals['safe_folder_name'] = safe_folder_name

def get_stats(ebooks, audiobooks):
    total = sum(m["file_size_mb"] for m in ebooks) + sum(m.get("file_size_mb", 0) for m in audiobooks)
    return {
        "ebook_count": len(ebooks),
        "audio_count": len(audiobooks),
        "total_count": len(ebooks) + len(audiobooks),
        "total_size_mb": round(total, 2),
    }

def search_abs_audiobooks_linker(query: str):
    """Search ABS for audiobooks - Book Linker version"""
    headers = {"Authorization": f"Bearer {ABS_API_TOKEN}"}
    url = urljoin(ABS_API_URL, f"/api/libraries/{ABS_LIBRARY_ID}/search")
    try:
        r = requests.get(url, headers=headers, params={"q": query}, timeout=15)
        r.raise_for_status()
        results = []
        for entry in r.json().get("book", []):
            item = entry.get("libraryItem", {})
            media = item.get("media", {})
            audio_files = media.get("audioFiles", [])
            if not audio_files: continue
            size_mb = sum(f.get("metadata", {}).get("size", 0) for f in audio_files) / (1024*1024)
            meta = media.get("metadata", {})
            author = meta.get("authorName") or (meta.get("authors") or [{}])[0].get("name") or "Unknown"
            results.append({
                "id": item.get("id"),
                "title": meta.get("title", "Unknown"),
                "author": author,
                "file_size_mb": round(size_mb, 2),
                "num_files": len(audio_files),
            })
        return results
    except Exception as e:
        logger.error(f"ABS search failed: {e}")
        return []

def copy_abs_audiobook_linker(abs_id: str, dest_folder: Path):
    """Copy audiobook files from ABS - Book Linker version"""
    headers = {"Authorization": f"Bearer {ABS_API_TOKEN}"}
    url = urljoin(ABS_API_URL, f"/api/items/{abs_id}")
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        item = r.json()
        audio_files = item.get("media", {}).get("audioFiles", [])
        if not audio_files:
            logger.warning(f"No audio files found for ABS {abs_id}")
            return False
        
        dest_folder.mkdir(parents=True, exist_ok=True)
        copied = 0
        
        for f in audio_files:
            meta = f.get("metadata", {})
            full_path = meta.get("path", "")
            filename = meta.get("filename", "")
            
            logger.info(f"ABS file path: {full_path}")
            logger.info(f"ABS filename: {filename}")
            
            src_path = None
            
            # Strategy 1: Use the path as-is if it exists
            if full_path and Path(full_path).exists():
                src_path = Path(full_path)
                logger.info(f"Found file using full path: {src_path}")
            
            # Strategy 2: Extract relative path from the full path
            elif full_path:
                for base_part in [str(ABS_AUDIO_ROOT), "/audiobooks", "audiobooks"]:
                    if base_part in full_path:
                        rel_part = full_path.split(base_part)[-1].lstrip("\\/")
                        test_path = ABS_AUDIO_ROOT / rel_part
                        if test_path.exists():
                            src_path = test_path
                            logger.info(f"Found file using relative path: {src_path}")
                            break
            
            # Strategy 3: Search for the filename in ABS_AUDIO_ROOT
            if not src_path and filename:
                for found_file in ABS_AUDIO_ROOT.rglob(filename):
                    src_path = found_file
                    logger.info(f"Found file by searching: {src_path}")
                    break
            
            if src_path and src_path.exists():
                shutil.copy2(str(src_path), dest_folder / src_path.name)
                copied += 1
                logger.info(f"Successfully copied: {src_path.name}")
            else:
                logger.error(f"Could not find audio file: {filename} (path: {full_path})")
        
        logger.info(f"Copied {copied}/{len(audio_files)} files from ABS {abs_id}")
        return copied > 0
    except Exception as e:
        logger.error(f"Failed to copy ABS {abs_id}: {e}", exc_info=True)
        return False

def find_local_ebooks(query: str):
    """Find ebooks in LargeEPUBs folder"""
    matches = []
    query_lower = query.lower()
    if not EBOOK_DIR.exists():
        logger.warning(f"EPUB directory does not exist: {EBOOK_DIR}")
        return matches
    
    for epub in EBOOK_DIR.rglob("*.epub"):
        if "(readaloud)" in epub.name.lower():
            continue
        if query_lower in epub.name.lower():
            matches.append({
                "full_path": str(epub),
                "file_name": epub.name,
                "file_size_mb": round(epub.stat().st_size / (1024*1024), 2),
            })
    return matches

def monitor_readaloud_files():
    """
    Monitor /media_books for (readaloud).epub files and process them safely.
    
    CRITICAL SAFETY GUIDELINES FOR FOLDER OPERATIONS:
    =================================================
    This function must be EXTREMELY careful about moving/deleting folders to avoid
    interfering with Storyteller while it's actively processing files.
    
    THE CORE PROBLEM:
    Storyteller can spend HOURS processing a folder (reading epub, matching to audio)
    WITHOUT modifying any files. Traditional modification-time checks WILL FAIL to
    detect this active processing.
    
    Deletion/Move Rules (ALL must pass):
    1. Readaloud File Age: Must be at least MIN_AGE_MINUTES old
    2. Active Process Check: NO processes can have the folder open (lsof check)
    3. Process Name Check: NO node/storyteller processes working on this folder
    4. Folder Age Check: ALL files must be at least MIN_AGE_MINUTES old
    5. Empty Folder Check: Folder must be empty before deletion
    
    Why These Checks Matter:
    - Storyteller reads files for hours without modifying them (mtime won't change!)
    - Moving/deleting folders during processing causes "ENOENT" errors
    - Storyteller loses track of work mid-processing
    - Data corruption and failed sync operations
    
    Safe Processing Flow:
    1. Check readaloud file age (>= MIN_AGE_MINUTES)
    2. Check if ANY process has folder open (lsof +D)
    3. Check for node/storyteller processes mentioning folder name
    4. Check ALL file modification times (>= MIN_AGE_MINUTES)
    5. Move readaloud file to /books
    6. Verify no other files remain
    7. Only then delete the folder
    
    If ANY check fails: Skip ALL operations and log warning for next cycle.
    """
    while True:
        try:
            time.sleep(MONITOR_INTERVAL)
            logger.info("Checking for (readaloud).epub files...")
            
            if not DEST_BASE.exists():
                logger.warning(f"Destination base does not exist: {DEST_BASE}")
                continue
            
            for folder in DEST_BASE.iterdir():
                if not folder.is_dir():
                    continue
                
                readaloud_files = list(folder.glob("*readaloud*.epub"))
                
                if not readaloud_files:
                    continue
                
                for readaloud_file in readaloud_files:
                    logger.info(f"Found readaloud file: {readaloud_file}")
                    
                    # Get the modification time of the readaloud file
                    try:
                        file_mtime = readaloud_file.stat().st_mtime
                        file_age_seconds = time.time() - file_mtime
                        file_age_minutes = file_age_seconds / 60
                        
                        logger.info(f"Readaloud file age: {file_age_minutes:.1f} minutes")
                        
                        # Wait at least 10 minutes after the file was last modified
                        # This ensures Storyteller is completely done
                        MIN_AGE_MINUTES = 10
                        
                        if file_age_minutes < MIN_AGE_MINUTES:
                            logger.info(f"File is only {file_age_minutes:.1f} minutes old, waiting for Storyteller to finish (need {MIN_AGE_MINUTES} min)...")
                            continue
                        
                        # CRITICAL: Check if Storyteller is actively processing this folder
                        # Storyteller can read files for hours without modifying them
                        # So we need to check if any Storyteller process is using this folder
                        
                        folder_name = folder.name
                        storyteller_active = False
                        
                        try:
                            # Check if any process has this folder open
                            # This catches Storyteller even if it's just reading files
                            result = subprocess.run(
                                ['lsof', '+D', str(folder)],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            
                            if result.stdout.strip():
                                logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Folder {folder} is currently in use by a process:")
                                logger.warning(result.stdout[:500])  # Log first 500 chars
                                storyteller_active = True
                        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
                            # lsof might not be available or might timeout
                            # Fall back to checking process names
                            logger.info(f"lsof check failed ({e}), checking process list...")
                            
                            try:
                                # Check if any node/storyteller process mentions this folder
                                ps_result = subprocess.run(
                                    ['ps', 'aux'],
                                    capture_output=True,
                                    text=True,
                                    timeout=5
                                )
                                
                                # Look for the folder name in running processes
                                for line in ps_result.stdout.split('\n'):
                                    if folder_name in line and ('node' in line.lower() or 'storyteller' in line.lower()):
                                        logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Storyteller process found working on {folder_name}")
                                        logger.warning(f"Process: {line[:200]}")
                                        storyteller_active = True
                                        break
                            except Exception as ps_err:
                                logger.warning(f"Process check failed: {ps_err}")
                        
                        if storyteller_active:
                            logger.info(f"Skipping {folder} - Storyteller is actively processing it")
                            continue
                        
                        # Also check if ANY file in the folder was modified recently
                        all_files = list(folder.rglob("*"))
                        if all_files:
                            file_times = [f.stat().st_mtime for f in all_files if f.is_file()]
                            if file_times:
                                newest_file_time = max(file_times)
                                folder_age_minutes = (time.time() - newest_file_time) / 60
                                
                                logger.info(f"Folder last modified: {folder_age_minutes:.1f} minutes ago")
                                
                                if folder_age_minutes < MIN_AGE_MINUTES:
                                    logger.info(f"Folder was modified {folder_age_minutes:.1f} minutes ago, still processing...")
                                    continue
                        
                        # Safe to proceed - nothing has been touched in 10+ minutes
                        dest_path = EBOOK_DIR / readaloud_file.name
                        
                        # Check if destination file already exists
                        if dest_path.exists():
                            logger.warning(f"Destination file already exists: {dest_path}, skipping...")
                            # Check if folder is safe to clean up (no other active files)
                            remaining_files = [f for f in folder.iterdir() if f.is_file()]
                            if remaining_files:
                                logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Duplicate folder has {len(remaining_files)} files, not deleting yet")
                            else:
                                # Folder is empty or only has the duplicate - safe to delete
                                try:
                                    shutil.rmtree(str(folder))
                                    logger.info(f"Ã¢Å“â€¦ Deleted duplicate folder: {folder}")
                                except Exception as cleanup_err:
                                    logger.error(f"Failed to delete duplicate folder: {cleanup_err}")
                            continue
                        
                        # Copy the readaloud file to /books
                        shutil.copy2(str(readaloud_file), str(dest_path))
                        logger.info(f"✅ Copied {readaloud_file.name} to {EBOOK_DIR}")
                        
                        # Delete all OTHER files in the folder (audiobooks + original epub)
                        # LEAVE the readaloud file in place for Storyteller
                        all_files = list(folder.iterdir())
                        deleted_count = 0
                        
                        for file in all_files:
                            if not file.is_file():
                                continue
                            
                            # Skip the readaloud file itself
                            if file == readaloud_file:
                                continue
                            
                            try:
                                file.unlink()
                                logger.info(f"🗑️ Deleted: {file.name}")
                                deleted_count += 1
                            except Exception as del_err:
                                logger.error(f"Failed to delete {file.name}: {del_err}")
                        
                        logger.info(f"✅ Cleanup complete: Deleted {deleted_count} file(s), kept {readaloud_file.name}")
                    except FileNotFoundError as fnf_error:
                        logger.warning(f"File disappeared during processing: {fnf_error}")
                        continue
                    except Exception as e:
                        logger.error(f"Error processing {readaloud_file}: {e}", exc_info=True)
                        
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
                        
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)

# Start monitor thread
monitor_thread = threading.Thread(target=monitor_readaloud_files, daemon=True)
monitor_thread.start()
logger.info("Readaloud monitor started")

# ---------------- ORIGINAL ABS-KOSYNC HELPERS ----------------

def find_ebook_file(filename):
    """Recursively search /books for a matching ebook filename"""
    base = EBOOK_DIR
    matches = list(base.rglob(filename))
    return matches[0] if matches else None

def add_to_abs_collection(abs_client, item_id, collection_name="Synced with KOReader"):
    """Add an audiobook to a collection, creating it if needed"""
    try:
        collections_url = f"{abs_client.base_url}/api/collections"
        r = requests.get(collections_url, headers=abs_client.headers)
        
        if r.status_code != 200:
            logger.error(f"Failed to fetch collections: {r.status_code}")
            return False
        
        collections = r.json().get('collections', [])
        target_collection = None
        
        for coll in collections:
            if coll.get('name') == collection_name:
                target_collection = coll
                break
        
        if not target_collection:
            lib_url = f"{abs_client.base_url}/api/libraries"
            r_lib = requests.get(lib_url, headers=abs_client.headers)
            if r_lib.status_code == 200:
                libraries = r_lib.json().get('libraries', [])
                if libraries:
                    create_payload = {"libraryId": libraries[0]['id'], "name": collection_name}
                    r_create = requests.post(collections_url, headers=abs_client.headers, json=create_payload)
                    if r_create.status_code in [200, 201]:
                        target_collection = r_create.json()
                        logger.info(f"Ã¢Å“â€¦ Created collection '{collection_name}'")
        
        if not target_collection:
            return False
        
        collection_id = target_collection['id']
        add_url = f"{abs_client.base_url}/api/collections/{collection_id}/book"
        r_add = requests.post(add_url, headers=abs_client.headers, json={"id": item_id})
        
        if r_add.status_code in [200, 201]:
            logger.info(f"Ã¢Å“â€¦ Added book to collection '{collection_name}'")
            return True
        else:
            logger.error(f"Failed to add book: {r_add.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error adding to collection: {e}")
        return False

def add_to_booklore_shelf(ebook_filename, shelf_name="Linked to ABS"):
    """Add an ebook to a Booklore shelf by filename"""
    booklore_url = os.environ.get("BOOKLORE_SERVER")
    booklore_user = os.environ.get("BOOKLORE_USER")
    booklore_pass = os.environ.get("BOOKLORE_PASSWORD")
    
    if not all([booklore_url, booklore_user, booklore_pass]):
        logger.debug("Booklore not configured, skipping shelf assignment")
        return False
    
    try:
        booklore_url = booklore_url.rstrip('/')
        
        login_url = f"{booklore_url}/api/v1/auth/login"
        login_payload = {"username": booklore_user, "password": booklore_pass}
        r_login = requests.post(login_url, json=login_payload)
        
        if r_login.status_code != 200:
            logger.error(f"Booklore login failed: {r_login.status_code}")
            return False
        
        tokens = r_login.json()
        jwt_token = tokens.get('refreshToken')
        
        if not jwt_token:
            logger.error("Could not find JWT token in login response")
            return False
        
        headers = {"Authorization": f"Bearer {jwt_token}"}
        
        books_url = f"{booklore_url}/api/v1/books"
        r_books = requests.get(books_url, headers=headers)
        
        if r_books.status_code != 200:
            logger.error(f"Failed to fetch Booklore books: {r_books.status_code}")
            return False
        
        books = r_books.json()
        target_book = None
        
        for book in books:
            if book.get('fileName') == ebook_filename:
                target_book = book
                break
        
        if not target_book:
            logger.warning(f"Book '{ebook_filename}' not found in Booklore")
            return False
        
        book_id = target_book['id']
        
        shelves_url = f"{booklore_url}/api/v1/shelves"
        r_shelves = requests.get(shelves_url, headers=headers)
        
        if r_shelves.status_code != 200:
            logger.error(f"Failed to fetch Booklore shelves: {r_shelves.status_code}")
            return False
        
        shelves = r_shelves.json()
        target_shelf = None
        
        for shelf in shelves:
            if shelf.get('name') == shelf_name:
                target_shelf = shelf
                break
        
        if not target_shelf:
            create_payload = {
                "name": shelf_name,
                "icon": "Ã°Å¸â€œÅ¡",
                "iconType": "PRIME_NG"
            }
            r_create = requests.post(shelves_url, headers=headers, json=create_payload)
            
            if r_create.status_code != 201:
                logger.error(f"Failed to create Booklore shelf: {r_create.status_code}")
                return False
            
            target_shelf = r_create.json()
            logger.info(f"Ã¢Å“â€¦ Created Booklore shelf '{shelf_name}'")
        
        shelf_id = target_shelf['id']
        
        assign_url = f"{booklore_url}/api/v1/books/shelves"
        assign_payload = {
            "bookIds": [book_id],
            "shelvesToAssign": [shelf_id],
            "shelvesToUnassign": []
        }
        
        r_assign = requests.post(assign_url, headers=headers, json=assign_payload)
        
        if r_assign.status_code == 200:
            logger.info(f"Ã¢Å“â€¦ Added book to Booklore shelf '{shelf_name}'")
            return True
        else:
            logger.error(f"Failed to assign book to shelf: {r_assign.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error adding to Booklore shelf: {e}")
        return False

# ---------------- ROUTES: MAIN NAVIGATION ----------------

@app.route('/')
def index():
    """ABS-KoSync Dashboard - Show all mappings with unified three-way progress"""
    manager.db = manager._load_db()
    manager.state = manager._load_state()

    mappings = manager.db.get('mappings', [])

    for mapping in mappings:
        abs_id = mapping.get('abs_id')
        kosync_id = mapping.get('kosync_doc_id')
        ebook_filename = mapping.get('ebook_filename')

        try:
            abs_progress = manager.abs_client.get_progress(abs_id)
            kosync_progress = manager.kosync_client.get_progress(kosync_id)
            storyteller_progress, storyteller_ts = manager.storyteller_db.get_progress(ebook_filename)  # Unpack tuple

            # Handle None from Storyteller
            if storyteller_progress is None:
                storyteller_progress = 0.0
            mapping['storyteller_progress'] = storyteller_progress * 100
            # Store raw values
            mapping['abs_progress'] = abs_progress
            mapping['kosync_progress'] = kosync_progress * 100
            
            # Calculate unified progress (use the furthest ahead as the "main" progress)
            mapping['unified_progress'] = max(
                mapping['kosync_progress'], 
                mapping['storyteller_progress']
            )

            state = manager.state.get(abs_id, {})
            last_updated = state.get('last_updated', 0)

            if last_updated > 0:
                diff = time.time() - last_updated
                if diff < 60:
                    mapping['last_sync'] = f"{int(diff)}s ago"
                elif diff < 3600:
                    mapping['last_sync'] = f"{int(diff / 60)}m ago"
                else:
                    mapping['last_sync'] = f"{int(diff / 3600)}h ago"
            else:
                mapping['last_sync'] = "Never"

            mapping['cover_url'] = (
                f"{manager.abs_client.base_url}/api/items/"
                f"{abs_id}/cover?token={manager.abs_client.token}"
            )

        except Exception as e:
            logger.error(f"Error fetching progress for {mapping.get('abs_title')}: {e}")
            mapping['abs_progress'] = 0
            mapping['kosync_progress'] = 0
            mapping['storyteller_progress'] = 0
            mapping['unified_progress'] = 0
            mapping['last_sync'] = "Error"
            mapping['cover_url'] = None

    return render_template('index.html', mappings=mappings)

# ---------------- ROUTES: BOOK LINKER ----------------

@app.route('/book-linker', methods=['GET', 'POST'])
def book_linker():
    """Book Linker interface"""
    message = session.pop("message", None)
    is_error = session.pop("is_error", False)

    book_name = ""
    ebook_matches = []
    audiobook_matches = []
    stats = None

    if request.method == "POST":
        book_name = request.form["book_name"].strip()
        if book_name:
            ebook_matches = find_local_ebooks(book_name)
            audiobook_matches = search_abs_audiobooks_linker(book_name)
            stats = get_stats(ebook_matches, audiobook_matches)

    return render_template('book_linker.html',
        book_name=book_name,
        ebook_matches=ebook_matches,
        audiobook_matches=audiobook_matches,
        stats=stats,
        message=message,
        is_error=is_error
    )

@app.route('/book-linker/process', methods=['POST'])
def book_linker_process():
    """Process selected ebooks and audiobooks"""
    book_name = request.form.get("book_name", "").strip()
    if not book_name:
        session["message"] = "Error: No book name"
        session["is_error"] = True
        return redirect(url_for('book_linker'))

    selected_ebooks = request.form.getlist("ebook")
    folder_name = book_name
    if selected_ebooks:
        folder_name = Path(selected_ebooks[0]).stem

    safe_name = safe_folder_name(folder_name)
    dest = DEST_BASE / safe_name
    dest.mkdir(parents=True, exist_ok=True)
    count = 0

    for path in selected_ebooks:
        src = Path(path)
        if src.exists():
            shutil.move(str(src), dest / src.name)
            logger.info(f"Moved EPUB: {src.name} to {dest}")
            count += 1

    for abs_id in request.form.getlist("audiobook"):
        if copy_abs_audiobook_linker(abs_id, dest):
            count += 1

    session["message"] = f"Success: {count} items Ã¢â€ â€™ {safe_name}"
    session["is_error"] = False
    return redirect(url_for('book_linker'))

@app.route('/book-linker/trigger-monitor', methods=['POST'])
def trigger_monitor():
    """
    Manually trigger the readaloud monitor check
    
    CRITICAL: This endpoint must use the SAME safety checks as the automatic monitor
    to prevent deleting folders while Storyteller is actively processing them.
    """
    try:
        logger.info("Manual monitor check triggered")
        found = 0
        skipped = 0
        MIN_AGE_MINUTES = 10
        
        if DEST_BASE.exists():
            for folder in DEST_BASE.iterdir():
                if not folder.is_dir():
                    continue
                
                readaloud_files = list(folder.glob("*readaloud*.epub"))
                
                if not readaloud_files:
                    continue
                
                for readaloud_file in readaloud_files:
                    # SAFETY CHECK 1: Check file age
                    file_mtime = readaloud_file.stat().st_mtime
                    file_age_minutes = (time.time() - file_mtime) / 60
                    
                    if file_age_minutes < MIN_AGE_MINUTES:
                        logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Skipping {readaloud_file.name} - too recent ({file_age_minutes:.1f} min)")
                        skipped += 1
                        continue
                    
                    # SAFETY CHECK 2: Check if any process has folder open
                    folder_name = folder.name
                    storyteller_active = False
                    
                    try:
                        result = subprocess.run(
                            ['lsof', '+D', str(folder)],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        
                        if result.stdout.strip():
                            logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Skipping {folder} - folder is in use")
                            logger.warning(result.stdout[:300])
                            storyteller_active = True
                    except Exception as e:
                        # Fallback to process check
                        try:
                            ps_result = subprocess.run(
                                ['ps', 'aux'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            
                            for line in ps_result.stdout.split('\n'):
                                if folder_name in line and ('node' in line.lower() or 'storyteller' in line.lower()):
                                    logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Skipping {folder} - Storyteller process detected")
                                    storyteller_active = True
                                    break
                        except Exception as ps_err:
                            logger.warning(f"Process check failed: {ps_err}")
                    
                    if storyteller_active:
                        skipped += 1
                        continue
                    
                    # SAFETY CHECK 3: Check folder modification time
                    all_files = list(folder.rglob("*"))
                    if all_files:
                        file_times = [f.stat().st_mtime for f in all_files if f.is_file()]
                        if file_times:
                            newest_file_time = max(file_times)
                            folder_age_minutes = (time.time() - newest_file_time) / 60
                            
                            if folder_age_minutes < MIN_AGE_MINUTES:
                                logger.warning(f"Ã¢Å¡Â Ã¯Â¸Â  Skipping {folder} - modified {folder_age_minutes:.1f} min ago")
                                skipped += 1
                                continue
                    
                    # Safe to proceed - copy the file
                    dest_path = EBOOK_DIR / readaloud_file.name
                    
                    if dest_path.exists():
                        logger.warning(f"Destination exists: {dest_path}, skipping...")
                        skipped += 1
                        continue
                    
                    # Copy (don't move) the readaloud file to /books
                    shutil.copy2(str(readaloud_file), str(dest_path))
                    logger.info(f"✅ Copied {readaloud_file.name} to {EBOOK_DIR}")
                    
                    # Delete all OTHER files in the folder (audiobooks + original epub)
                    # LEAVE the readaloud file in place
                    all_files_in_folder = list(folder.iterdir())
                    deleted_count = 0
                    
                    for file in all_files_in_folder:
                        if not file.is_file():
                            continue
                        
                        # Skip the readaloud file itself
                        if file == readaloud_file:
                            continue
                        
                        try:
                            file.unlink()
                            logger.info(f"🗑️ Deleted: {file.name}")
                            deleted_count += 1
                        except Exception as del_err:
                            logger.error(f"Failed to delete {file.name}: {del_err}")
                    
                    logger.info(f"✅ Cleanup complete: Deleted {deleted_count} file(s), kept {readaloud_file.name}")
                    found += 1
                    
        if skipped > 0:
            session["message"] = f"Monitor check complete. Processed {found} file(s), skipped {skipped} (still processing or too recent)."
        else:
            session["message"] = f"Monitor check complete. Processed {found} readaloud file(s)."
        session["is_error"] = False
    except Exception as e:
        logger.error(f"Manual monitor check failed: {e}", exc_info=True)
        session["message"] = f"Monitor check failed: {str(e)}"
        session["is_error"] = True
    
    return redirect(url_for('book_linker'))

# ---------------- ROUTES: SINGLE MATCH ----------------

@app.route('/match', methods=['GET', 'POST'])
def match():
    if request.method == 'POST':
        abs_id = request.form.get('audiobook_id')
        ebook_filename = request.form.get('ebook_filename')

        audiobooks = manager.abs_client.get_all_audiobooks()
        selected_ab = next((ab for ab in audiobooks if ab['id'] == abs_id), None)

        if not selected_ab:
            return "Audiobook not found", 404

        ebook_path = find_ebook_file(ebook_filename)
        if not ebook_path:
            return "Ebook not found", 404

        kosync_doc_id = manager.ebook_parser.get_kosync_id(ebook_path)

        mapping = {
            "abs_id": abs_id,
            "abs_title": manager._get_abs_title(selected_ab),
            "ebook_filename": ebook_filename,
            "kosync_doc_id": kosync_doc_id,
            "transcript_file": None,
            "status": "pending",
        }

        manager.db['mappings'] = [
            m for m in manager.db['mappings'] if m['abs_id'] != abs_id
        ]
        manager.db['mappings'].append(mapping)
        manager._save_db()

        add_to_abs_collection(manager.abs_client, abs_id)
        add_to_booklore_shelf(ebook_filename)

        return redirect(url_for('index'))

    search = request.args.get('search', '').strip().lower()

    audiobooks = manager.abs_client.get_all_audiobooks()
    ebooks = list(EBOOK_DIR.glob("**/*.epub"))

    if search:
        audiobooks = [
            ab for ab in audiobooks
            if search in manager._get_abs_title(ab).lower()
        ]
        ebooks = [eb for eb in ebooks if search in eb.name.lower()]

    for ab in audiobooks:
        ab['cover_url'] = (
            f"{manager.abs_client.base_url}/api/items/"
            f"{ab['id']}/cover?token={manager.abs_client.token}"
        )

    return render_template(
        'match.html',
        audiobooks=audiobooks,
        ebooks=ebooks,
        search=search,
        get_title=manager._get_abs_title,
    )

# ---------------- ROUTES: BATCH MATCH ----------------

@app.route('/batch-match', methods=['GET', 'POST'])
def batch_match():
    if request.method == 'POST':
        action = request.form.get('action')

        logger.info(f"BATCH POST ACTION: {action}")

        if action == 'add_to_queue':
            session.setdefault('queue', [])

            abs_id = request.form.get('audiobook_id')
            ebook_filename = request.form.get('ebook_filename')

            audiobooks = manager.abs_client.get_all_audiobooks()
            selected_ab = next((ab for ab in audiobooks if ab['id'] == abs_id), None)

            if selected_ab and ebook_filename:
                if not any(item['abs_id'] == abs_id for item in session['queue']):
                    session['queue'].append({
                        "abs_id": abs_id,
                        "abs_title": manager._get_abs_title(selected_ab),
                        "ebook_filename": ebook_filename,
                        "cover_url": (
                            f"{manager.abs_client.base_url}/api/items/"
                            f"{abs_id}/cover?token={manager.abs_client.token}"
                        ),
                    })
                    session.modified = True
                    logger.info(f"QUEUE SIZE NOW: {len(session['queue'])}")

            return redirect(url_for('batch_match', search=request.form.get('search', '')))

        elif action == 'remove_from_queue':
            abs_id = request.form.get('abs_id')
            session['queue'] = [
                item for item in session.get('queue', [])
                if item['abs_id'] != abs_id
            ]
            session.modified = True
            return redirect(url_for('batch_match'))

        elif action == 'clear_queue':
            session['queue'] = []
            session.modified = True
            return redirect(url_for('batch_match'))

        elif action == 'process_queue':
            manager.db = manager._load_db()

            for item in session.get('queue', []):
                ebook_path = find_ebook_file(item['ebook_filename'])

                if not ebook_path:
                    logger.error(f"Ebook not found on disk: {item['ebook_filename']}")
                    continue

                kosync_doc_id = manager.ebook_parser.get_kosync_id(ebook_path)
                mapping = {
                    "abs_id": item['abs_id'],
                    "abs_title": item['abs_title'],
                    "ebook_filename": item['ebook_filename'],
                    "kosync_doc_id": kosync_doc_id,
                    "transcript_file": None,
                    "status": "pending",
                }
                manager.db['mappings'] = [
                    m for m in manager.db['mappings']
                    if m['abs_id'] != item['abs_id']
                ]
                manager.db['mappings'].append(mapping)

                add_to_abs_collection(manager.abs_client, item['abs_id'])
                add_to_booklore_shelf(item['ebook_filename'])

                logger.info(f"MAPPED: ABS={item['abs_id']} Ã¢â€ â€™ EPUB={ebook_path}")

            manager._save_db()
            session['queue'] = []
            session.modified = True
            return redirect(url_for('index'))

    search = request.args.get('search', '').strip().lower()

    audiobooks = manager.abs_client.get_all_audiobooks()
    ebooks = list(EBOOK_DIR.glob("**/*.epub"))

    if search:
        audiobooks = [
            ab for ab in audiobooks
            if search in manager._get_abs_title(ab).lower()
        ]
        ebooks = [eb for eb in ebooks if search in eb.name.lower()]

    for ab in audiobooks:
        ab['cover_url'] = (
            f"{manager.abs_client.base_url}/api/items/"
            f"{ab['id']}/cover?token={manager.abs_client.token}"
        )

    ebooks.sort(key=lambda x: x.name.lower())

    return render_template(
        'batch_match.html',
        audiobooks=audiobooks,
        ebooks=ebooks,
        queue=session.get('queue', []),
        search=search,
        get_title=manager._get_abs_title,
    )

# ---------------- ROUTES: DELETE & API ----------------

@app.route('/delete/<abs_id>', methods=['POST'])
def delete_mapping(abs_id):
    manager.db['mappings'] = [
        m for m in manager.db['mappings'] if m['abs_id'] != abs_id
    ]
    manager._save_db()
    return redirect(url_for('index'))

@app.route('/api/status')
def api_status():
    return jsonify(manager.db)

@app.route('/view_log')
def view_log():
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-300:]
        return "<pre>" + "\n".join(html.escape(l) for l in lines) + "</pre>"
    except:
        return "Log not available"

# ---------------- MAIN ----------------

if __name__ == '__main__':
    logger.info("=== Unified ABS Manager Started ===")
    logger.info(f"Book Linker monitoring interval: {MONITOR_INTERVAL} seconds")
    
    # Start the monitoring thread as a daemon
    monitor_thread = threading.Thread(target=monitor_readaloud_files, daemon=True)
    monitor_thread.start()
    logger.info("Ã¢Å“â€¦ Started readaloud file monitoring thread")
    
    app.run(host='0.0.0.0', port=5757, debug=False)