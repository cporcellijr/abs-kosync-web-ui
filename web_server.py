from flask import Flask, render_template, request, redirect, url_for, jsonify
import logging
from pathlib import Path
from main import SyncManager
import time

app = Flask(__name__)
logger = logging.getLogger(__name__)

manager = SyncManager()

@app.route('/')
def index():
    """Show all mappings with progress and cover art"""
    mappings = manager.db.get('mappings', [])
    
    # Enhance each mapping with real-time data
    for mapping in mappings:
        abs_id = mapping.get('abs_id')
        kosync_id = mapping.get('kosync_doc_id')
        
        # Get current progress
        try:
            abs_progress = manager.abs_client.get_progress(abs_id)
            kosync_progress = manager.kosync_client.get_progress(kosync_id)
            
            mapping['abs_progress'] = abs_progress
            mapping['kosync_progress'] = kosync_progress * 100  # Convert to percentage
            
            # Get last sync time from state
            state = manager.state.get(abs_id, {})
            last_updated = state.get('last_updated', 0)
            if last_updated > 0:
                time_diff = time.time() - last_updated
                if time_diff < 60:
                    mapping['last_sync'] = f"{int(time_diff)}s ago"
                elif time_diff < 3600:
                    mapping['last_sync'] = f"{int(time_diff/60)}m ago"
                else:
                    mapping['last_sync'] = f"{int(time_diff/3600)}h ago"
            else:
                mapping['last_sync'] = "Never"
            
            # Get cover URL from Audiobookshelf
            mapping['cover_url'] = f"{manager.abs_client.base_url}/api/items/{abs_id}/cover?token={manager.abs_client.token}"
            
        except Exception as e:
            logger.error(f"Error fetching progress for {mapping.get('abs_title')}: {e}")
            mapping['abs_progress'] = 0
            mapping['kosync_progress'] = 0
            mapping['last_sync'] = "Error"
            mapping['cover_url'] = None
    
    return render_template('index.html', mappings=mappings)

@app.route('/match', methods=['GET', 'POST'])
def match():
    if request.method == 'POST':
        abs_id = request.form.get('audiobook_id')
        ebook_filename = request.form.get('ebook_filename')
        
        # Find the selected items
        audiobooks = manager.abs_client.get_all_audiobooks()
        selected_ab = next((ab for ab in audiobooks if ab['id'] == abs_id), None)
        
        if not selected_ab:
            return "Audiobook not found", 404
        
        ebook_path = Path(f"/books/{ebook_filename}")
        if not ebook_path.exists():
            return "Ebook not found", 404
        
        # Create mapping
        kosync_doc_id = manager.ebook_parser.get_kosync_id(ebook_path)
        final_title = manager._get_abs_title(selected_ab)
        
        mapping = {
            "abs_id": selected_ab['id'],
            "abs_title": final_title,
            "ebook_filename": ebook_filename,
            "kosync_doc_id": kosync_doc_id,
            "transcript_file": None,
            "status": "pending"
        }
        
        # Remove existing mapping if any
        manager.db['mappings'] = [m for m in manager.db['mappings'] 
                                   if m['abs_id'] != selected_ab['id']]
        manager.db['mappings'].append(mapping)
        manager._save_db()
        
        return redirect(url_for('index'))
    
    # GET request - show matching form
    search = request.args.get('search', '').strip().lower()
    
    audiobooks = manager.abs_client.get_all_audiobooks()
    ebooks = list(Path("/books").glob("**/*.epub"))
    
    if search:
        audiobooks = [ab for ab in audiobooks 
                     if search in manager._get_abs_title(ab).lower()]
        ebooks = [eb for eb in ebooks if search in eb.name.lower()]
    
    # Add cover URLs to audiobooks
    for ab in audiobooks:
        ab['cover_url'] = f"{manager.abs_client.base_url}/api/items/{ab['id']}/cover?token={manager.abs_client.token}"
    
    return render_template('match.html', 
                         audiobooks=audiobooks, 
                         ebooks=ebooks,
                         search=search,
                         get_title=manager._get_abs_title)

@app.route('/delete/<abs_id>', methods=['POST'])
def delete_mapping(abs_id):
    manager.db['mappings'] = [m for m in manager.db['mappings'] 
                             if m['abs_id'] != abs_id]
    manager._save_db()
    return redirect(url_for('index'))

@app.route('/api/status')
def api_status():
    """API endpoint for status checks"""
    return jsonify(manager.db)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5757, debug=False)