# RSS Swipr

Swipe-style RSS reader with local preference learning.  
You can run it as a clean mobile-first experience, and use full desktop controls when needed.

## Quick Start

### Option A: `mise + uv` (recommended)

```bash
git clone https://github.com/philippdubach/rss-swipr.git
cd rss-swipr

mise install
mise run install
mise run dev
```

Open `http://127.0.0.1:5000`.

### Option B: traditional venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Core Workflow

1. Open Settings (gear icon) and import feeds via OPML.
2. Refresh feeds.
3. Swipe or vote on cards to train your preference data.
4. Optionally export training data and upload your own model later.

## Controls

- Keyboard:
  - `←` skip
  - `↑` read later
  - `↓` next
  - `→` favorite
  - `Enter` open original
- Touch:
  - left/right/up/down swipe for actions
  - tap card to open original
- Desktop minimal mode:
  - mouse-clickable directional buttons (up/down/left/right)

## Modes

- `完整`:
  - progress + insights + action bar
- `极简`:
  - focused card reading flow
  - desktop and mobile both supported

## Model Notes

- "No model available" is expected for first-time use.
- App still works without a custom model (fallback recommendation path).
- After enough votes, you can:
  - export training data in Settings
  - train in notebook/Colab
  - upload `.pkl` model in Settings

## Project Structure

```text
app.py
src/
ml/
static/
templates/
notebooks/
```

## Changelog

See `CHANGES.md` for recent integrated updates.

## License

MIT
