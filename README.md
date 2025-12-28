# ABS-KoSync Enhanced v1.0.5

Three-way sync between Audiobookshelf ↔ KOReader ↔ Storyteller with web UI and AI transcription.

![Dashboard](https://github.com/user-attachments/assets/4e4de939-858a-4a23-b2d2-90f71a8db90a)

## What's New in This Version

### v1.0.4 - Latest
- ✅ **Filter by Currently Reading** - Show only books in progress (0-99%)
- ✅ **Sort Options** - Sort by Title, Progress, Status, or Last Sync
- ✅ **Booklore Integration** - Auto-add matched books to Booklore shelf
- ✅ **Persistent Preferences** - Filter and sort settings saved in browser

### v1.0.3
- ✅ **ABS Collection Auto-Add** - Matched books automatically added to "Synced with KOReader" collection

### v1.0.0
- ✅ **3-Way Sync** - Storyteller integration alongside ABS ↔ KoSync
- ✅ **Book Linker** - Automated workflow for Storyteller processing
- ✅ **AI Transcription** - Whisper-based audio transcription for accurate sync
- ✅ **Web UI** - Visual dashboard with cover art and progress tracking
- ✅ **Batch Matching** - Queue multiple books for sync setup

## Features

📚 Visual book matching with cover art  
📊 Real-time 3-way progress tracking  
🎨 Beautiful, modern interface  
🔄 Auto-refresh every 30 seconds  
🔍 Search and filter books  
📱 Responsive design  
🤖 AI-powered audio transcription  
🏷️ Auto-organize in ABS collections  
📖 Auto-organize in Booklore shelves  
⚡ Smart filtering and sorting with saved preferences  

## Prerequisites

- Running [Audiobookshelf](https://github.com/advplyr/audiobookshelf) instance
- Running [KOSync](https://github.com/koreader/koreader-sync-server) server
- (Optional) Running [Storyteller](https://github.com/smoores-dev/storyteller) for word highlighting
- (Optional) Running [Booklore](https://github.com/Booklore-Development/booklore) for ebook management

## Quick Start

1. **Clone the repository:**
```bash
git clone https://github.com/cporcellijr/abs-kosync-enhanced.git
cd abs-kosync-enhanced
```

2. **Edit `docker-compose.yml`** with your settings (see Configuration below)

3. **Start the container:**
```bash
docker compose up -d
```

4. **Access the web UI** at `http://localhost:8080`

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| **Core Settings** | | | |
| `ABS_SERVER` | Audiobookshelf server URL | Yes | - |
| `ABS_KEY` | Audiobookshelf API key | Yes | - |
| `KOSYNC_SERVER` | KOSync server URL | Yes | - |
| `KOSYNC_USER` | KOSync username | Yes | - |
| `KOSYNC_KEY` | KOSync password | Yes | - |
| `TZ` | Timezone | No | America/New_York |
| `LOG_LEVEL` | Logging level | No | INFO |
| **Storyteller** | | | |
| `STORYTELLER_DB_PATH` | Path to Storyteller database | No | - |
| `STORYTELLER_USER_ID` | Your Storyteller user UUID | No | - |
| `MONITOR_INTERVAL` | Readaloud check interval (seconds) | No | 3600 |
| **Booklore** *(v1.0.4+)* | | | |
| `BOOKLORE_SERVER` | Booklore server URL | No | - |
| `BOOKLORE_USER` | Booklore username | No | - |
| `BOOKLORE_PASSWORD` | Booklore password | No | - |
| `BOOKLORE_SHELF_NAME` | Shelf name for synced books | No | "Linked to ABS" |

### Required Volumes

| Mount Point | Purpose | Example |
|-------------|---------|---------|
| `/books` | Your EPUB collection | `/path/to/LargeEPUBs` |
| `/data` | Sync state and mappings | `/path/to/abs_kosync/data` |
| `/media_books` | Storyteller processing folder | `/path/to/Books` |
| `/audiobooks` | Audiobookshelf library root | `/path/to/Audiobooks` |
| `/storyteller_data` | Storyteller database location | `/path/to/Storyteller` |

### Finding Your Storyteller User ID
```bash
# Connect to Storyteller database
sqlite3 /path/to/storyteller.db

# Get your user ID
SELECT id, username FROM user;
```

## Complete Docker Compose Example
```yaml
services:
  abs-kosync-web:
    build: .
    container_name: abs_kosync_web
    restart: unless-stopped
    command: python /app/web_server.py
    environment:
      # Core Settings
      - TZ=America/New_York
      - LOG_LEVEL=INFO
      
      # Audiobookshelf
      - ABS_SERVER=https://audiobookshelf.example.com
      - ABS_KEY=your_abs_api_key
      
      # KOSync
      - KOSYNC_SERVER=https://kosync.example.com
      - KOSYNC_USER=your_username
      - KOSYNC_KEY=your_password
      
      # Storyteller Integration (Optional)
      - STORYTELLER_DB_PATH=/storyteller_data/storyteller.db
      - STORYTELLER_USER_ID=your-uuid-from-db
      - MONITOR_INTERVAL=3600
      
      # Booklore Integration (Optional - v1.0.4+)
      - BOOKLORE_SERVER=https://booklore.example.com
      - BOOKLORE_USER=your_booklore_username
      - BOOKLORE_PASSWORD=your_booklore_password
      - BOOKLORE_SHELF_NAME=Linked to ABS
      
    volumes:
      # Core sync data
      - ./data:/data
      
      # Book locations
      - /path/to/LargeEPUBs:/books
      - /path/to/Audiobooks:/audiobooks
      
      # Storyteller integration (Optional)
      - /path/to/Books:/media_books
      - /path/to/Storyteller:/storyteller_data
      
      # File overrides (see Technical Details)
      - ./main.py:/app/src/main.py
      - ./storyteller_db.py:/app/src/storyteller_db.py
      - ./web_server.py:/app/web_server.py
      - ./templates:/app/templates
      
    ports:
      - 8080:5757
    networks:
      - your-network

networks:
  your-network:
    external: true
```

## Usage

### Adding a Sync Mapping

1. Click **"Single Match"** or **"Batch Match"**
2. Use search to filter books
3. Click an audiobook cover to select it
4. Choose the matching EPUB from dropdown
5. Click **"Create Mapping"**

**Auto-Organization:**
- ✅ Book automatically added to ABS collection "Synced with KOReader"
- ✅ Book automatically added to Booklore shelf (if configured)

### Dashboard Controls (v1.0.4+)

**Sort Options:**
- Title (A-Z)
- Progress (highest to lowest)
- Status (active, pending, failed)
- Last Sync (most recent first)

**Filter:**
- Toggle "Show Only Currently Reading" to see books with 0-99% progress
- Settings persist across page refreshes

### Book Linker Workflow

The Book Linker automates Storyteller processing:

1. Navigate to **"Book Linker"**
2. Search for a book title/author
3. Select EPUB(s) and audiobook(s)
4. Click **"Process Selected"**
5. Files are copied to `/media_books` for Storyteller
6. Monitor automatically detects completed `(readaloud).epub` files
7. Processed files moved back to `/books` and cleanup occurs

**Manual Check:** Click **"Check Now"** to trigger monitor immediately (default: checks hourly)

### Monitoring Progress

- Dashboard shows all active mappings with unified progress bars
- Three-way progress display: 🎧 Audiobook | 📖 KOReader | 📚 Storyteller
- Auto-refreshes every 30 seconds
- Sort by title, progress, status, or last sync time
- Filter to show only currently reading books

## Technical Details

### How 3-Way Sync Works

This enhanced version modifies the original 2-way sync to include Storyteller:

**Original:** ABS ↔ KoSync (2-way)  
**Enhanced:** ABS ↔ KoSync ↔ Storyteller (3-way)

**Key Changes:**
- `main.py` - Enhanced with Storyteller sync logic
- `storyteller_db.py` - New Storyteller database client
- `web_server.py` - Web UI with Book Linker and integrations
- `transcriber.py` - AI transcription for text matching
- `ebook_utils.py` - Enhanced EPUB parsing
- `api_clients.py` - Enhanced with ABS collection and Booklore support

### Repository Structure
```
abs-kosync-enhanced/
├── README.md
├── dockerfile              # Builds on base image, adds Flask
├── docker-compose.yml
│
# Core sync files (override base image):
├── main.py                 # ⚠️ Enhanced 3-way sync
├── storyteller_db.py       # New Storyteller integration
├── api_clients.py          # Enhanced with integrations
├── ebook_utils.py          # Enhanced EPUB parsing
├── transcriber.py          # AI transcription
│
# Web UI files:
├── web_server.py          # Flask web server + Book Linker
└── templates/
    ├── index.html         # Dashboard with sort/filter
    ├── match.html         # Single mapping
    ├── batch_match.html   # Batch queue
    └── book_linker.html   # Storyteller workflow
```

### Why Volume Overrides?

The base `00jlich/abs-kosync-bridge` image only supports 2-way sync. To add Storyteller:

1. We override `main.py` with our enhanced 3-way version
2. We add `storyteller_db.py` as a new dependency
3. We add `web_server.py` for the web interface

This approach lets you:
- ✅ Pull upstream updates from the base image
- ✅ Keep your enhancements separate
- ✅ Easily enable/disable features

### Auto-Organization Features

**ABS Collections (v1.0.3+):**
When you create a mapping, the audiobook is automatically added to a collection named "Synced with KOReader" in Audiobookshelf. The collection is created if it doesn't exist.

**Booklore Shelves (v1.0.4+):**
When you create a mapping, the ebook is automatically added to a Booklore shelf (default: "Linked to ABS"). Configure with:
- `BOOKLORE_SERVER` - Your Booklore instance URL
- `BOOKLORE_USER` - Your Booklore username
- `BOOKLORE_PASSWORD` - Your Booklore password
- `BOOKLORE_SHELF_NAME` - Custom shelf name (optional)

If Booklore is not configured, this feature is silently skipped.

## Updating
```bash
# Pull latest base image
docker pull 00jlich/abs-kosync-bridge:latest

# Rebuild with your enhancements
docker compose build --no-cache

# Restart
docker compose up -d
```

## Troubleshooting

### Storyteller sync not working
- Verify `STORYTELLER_DB_PATH` points to actual database
- Check `STORYTELLER_USER_ID` matches your user in the database
- Ensure `/storyteller_data` volume is mounted correctly

### Book Linker files not moving
- Check monitor logs: `docker logs abs_kosync_web`
- Verify `/media_books` and `/audiobooks` volumes are correct
- Files must be >10 minutes old before processing (safety check)

### Transcription failing
- Large audiobooks are auto-split into 45min chunks
- Check available RAM (transcription is memory-intensive)
- Review logs for specific errors

### Booklore integration not working
- Verify all `BOOKLORE_*` environment variables are set
- Check Booklore server is accessible from container
- Ensure ebook filename in `/books` matches filename in Booklore
- Check logs for authentication errors

### ABS collection not created
- Verify `ABS_KEY` has permission to create collections
- Check logs for API errors
- Ensure ABS server is accessible

## Credits

Built on [abs-kosync-bridge](https://github.com/J-Lich/abs-kosync-bridge) by 00jlich

## License

MIT
