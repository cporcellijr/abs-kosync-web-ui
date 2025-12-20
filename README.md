Web UI for ABS-KoSync Bridge
# ABS-KoSync Web UI

A web interface for [abs-kosync-bridge](https://github.com/J-Lich/abs-kosync-bridge) to easily manage audiobook/ebook sync mappings between Audiobookshelf and KOReader.

## Features

- 📚 Visual book matching with cover art
- 📊 Real-time progress tracking
- 🎨 Beautiful, modern interface
- 🔄 Auto-refresh every 30 seconds
- 🔍 Search and filter books
- 📱 Responsive design

<img width="1469" height="842" alt="image" src="https://github.com/user-attachments/assets/4e4de939-858a-4a23-b2d2-90f71a8db90a" />

<img width="1603" height="737" alt="image" src="https://github.com/user-attachments/assets/cb098523-ed56-4090-bc23-c34cc5afec2a" />

## Prerequisites

- Running [Audiobookshelf](https://github.com/advplyr/audiobookshelf) instance
- Running [KOSync](https://github.com/koreader/koreader-sync-server) server
- Running [abs-kosync-bridge](https://github.com/J-Lich/abs-kosync-bridge) daemon

## Installation

### Option 1: Separate Container (Recommended)

Run the web UI alongside your existing abs-kosync daemon:

1. Clone this repository:
```bash
git clone https://github.com/cporcellijr/abs-kosync-web-ui.git

```

2. Edit `docker-compose.yml` with your settings:
   - Update volume paths for your books and data directories
   - Set your Audiobookshelf and KOSync credentials
   - Adjust port if needed (default: 8080)


3. Access the web UI at `http://localhost:8080`


## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ABS_SERVER` | Audiobookshelf server URL | Yes |
| `ABS_KEY` | Audiobookshelf API key | Yes |
| `KOSYNC_SERVER` | KOSync server URL | Yes |
| `KOSYNC_USER` | KOSync username | Yes |
| `KOSYNC_KEY` | KOSync password | Yes |
| `TZ` | Timezone (default: America/New_York) | No |
| `LOG_LEVEL` | Log level (default: INFO) | No |

### Volumes

- `/books` - Directory containing your EPUB files
- `/data` - Shared data directory with abs-kosync daemon (contains mapping_db.json)

## Usage

1. **Add a Mapping:**
   - Click "Add New Mapping"
   - Use the search box to filter books
   - Click on an audiobook cover to select it
   - Choose the matching EPUB from the dropdown
   - Click "Create Mapping"

2. **Monitor Progress:**
   - The homepage shows all active mappings
   - Progress bars update automatically
   - See audiobook time and ebook percentage side-by-side
   - Last sync time displayed for each book

3. **Delete a Mapping:**
   - Click the "Delete" button on any mapping card
   - Confirm the deletion

## Docker Compose Example
```yaml
services:
  # Your existing abs-kosync daemon
  abs-kosync-daemon:
    image: 00jlich/abs-kosync-bridge:latest
    container_name: abs_kosync_daemon
    environment:
      - ABS_SERVER=https://audiobookshelf.example.com
      - ABS_KEY=your-api-key
      - KOSYNC_SERVER=https://kosync.example.com
      - KOSYNC_USER=username
      - KOSYNC_KEY=password
    volumes:
      - /path/to/books:/books
      - /path/to/data:/data
    restart: unless-stopped

  # Web UI (this project)
  abs-kosync-web:
    build: .
    container_name: abs_kosync_web
    environment:
      - ABS_SERVER=https://audiobookshelf.example.com
      - ABS_KEY=your-api-key
      - KOSYNC_SERVER=https://kosync.example.com
      - KOSYNC_USER=username
      - KOSYNC_KEY=password
    volumes:
      - /path/to/books:/books
      - /path/to/data:/data  # Must be same as daemon!
    ports:
      - "8080:5757"
    restart: unless-stopped
```

## Updating

When the base abs-kosync-bridge image is updated:
```bash
docker pull 00jlich/abs-kosync-bridge:latest
docker compose build --no-cache
docker compose up -d
```



## Credits

- Built on top of [abs-kosync-bridge](https://github.com/J-Lich/abs-kosync-bridge) by 00jlich
