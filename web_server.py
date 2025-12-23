from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import logging
from pathlib import Path
from main import SyncManager
import time
import requests

# ---------------- APP SETUP ----------------

app = Flask(__name__)

# 🔒 MUST be static or sessions (queue) will never persist
app.secret_key = "kosync-queue-secret"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

manager = SyncManager()

# ---------------- HELPERS ----------------

def find_ebook_file(filename):
    """Recursively search /books for a matching ebook filename"""
    base = Path("/books")
    matches = list(base.rglob(filename))
    return matches[0] if matches else None

def add_to_abs_collection(abs_client, item_id, collection_name="Synced with KOReader"):
    """Add an audiobook to a collection, creating it if needed"""
    try:
        # Get all collections
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
        
        # Create collection if it doesn't exist
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
                        logger.info(f"✅ Created collection '{collection_name}'")
        
        if not target_collection:
            return False
        
        # Add book to collection
        collection_id = target_collection['id']
        add_url = f"{abs_client.base_url}/api/collections/{collection_id}/book"
        r_add = requests.post(add_url, headers=abs_client.headers, json={"id": item_id})
        
        if r_add.status_code in [200, 201]:
            logger.info(f"✅ Added book to collection '{collection_name}'")
            return True
        else:
            logger.error(f"Failed to add book: {r_add.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error adding to collection: {e}")
        return False
# ---------------- INDEX ----------------

@app.route('/')
def index():
    """Show all mappings with progress and cover art"""
    manager.db = manager._load_db()
    manager.state = manager._load_state()

    mappings = manager.db.get('mappings', [])

    for mapping in mappings:
        abs_id = mapping.get('abs_id')
        kosync_id = mapping.get('kosync_doc_id')

        try:
            abs_progress = manager.abs_client.get_progress(abs_id)
            kosync_progress = manager.kosync_client.get_progress(kosync_id)

            mapping['abs_progress'] = abs_progress
            mapping['kosync_progress'] = kosync_progress * 100

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
            mapping['last_sync'] = "Error"
            mapping['cover_url'] = None

    return render_template('index.html', mappings=mappings)

# ---------------- SINGLE MATCH ----------------

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

        return redirect(url_for('index'))

    search = request.args.get('search', '').strip().lower()

    audiobooks = manager.abs_client.get_all_audiobooks()
    ebooks = list(Path("/books").glob("**/*.epub"))

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

# ---------------- BATCH MATCH ----------------

@app.route('/batch-match', methods=['GET', 'POST'])
def batch_match():
    if request.method == 'POST':
        action = request.form.get('action')

        logger.info(f"BATCH POST ACTION: {action}")
        logger.info(f"FORM DATA: {dict(request.form)}")

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

                logger.info(
                    f"MAPPED: ABS={item['abs_id']} → EPUB={ebook_path}"
                )

            manager._save_db()
            session['queue'] = []
            session.modified = True
            return redirect(url_for('index'))

    # GET
    search = request.args.get('search', '').strip().lower()

    audiobooks = manager.abs_client.get_all_audiobooks()
    ebooks = list(Path("/books").glob("**/*.epub"))

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

# ---------------- DELETE ----------------

@app.route('/delete/<abs_id>', methods=['POST'])
def delete_mapping(abs_id):
    manager.db['mappings'] = [
        m for m in manager.db['mappings'] if m['abs_id'] != abs_id
    ]
    manager._save_db()
    return redirect(url_for('index'))

# ---------------- API ----------------

@app.route('/api/status')
def api_status():
    return jsonify(manager.db)

# ---------------- MAIN ----------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5757, debug=False)
