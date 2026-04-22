# Gelbooru Image Parser v0.8

## Features

* Download images by tags
* Auto-sort images by artist
* Fill/update existing artist folders
* Resume downloads using cache
* Tag type detection with caching (reduced API calls)
* Hotkeys support:
  * `p` — pause/resume
  * `q` — stop
* Flexible file naming:
  * original / prefix / numbered
* EXIF tag embedding + TXT fallback
* Improved error handling and stability

## Installation

```bash
pip install requests piexif keyboard
```

## Configuration

Edit in script:

* `API_KEY` — your Gelbooru API key
* `USER_ID` — your user ID
* `DEFAULT_PATH` — output folder

## Usage

Run the script:

```bash
python src\gelbooru_pub.py
```

Choose mode:
1. Download by tags
2. Fill existing artist folders

Follow CLI prompts.

## Notes
* Progress is saved in `cache.json`
* Already downloaded files are skipped
* Unsupported formats (e.g. PNG) save tags to `.txt`
