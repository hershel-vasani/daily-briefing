# Daily Briefing

A free, automated morning briefing — local weather, news (local/national/world),
and yesterday's sports scores (Detroit teams, Michigan State, and national) —
spoken in a natural neural voice (Microsoft "Libby", British English).

## How it works

1. **GitHub Actions** runs `daily_briefing.py` every morning (7 AM Detroit time).
2. The script fetches weather, news, and sports from free public sources.
3. `edge-tts` turns the text into an MP3 using Microsoft's free neural voices.
4. The MP3 (`daily_briefing.mp3`) is committed back to this repo.
5. An **iPhone Shortcut** downloads the MP3 and plays it on demand:
   *"Hey Siri, Daily Update."*

No servers to keep on, no API keys, no cost.

## Files

- `daily_briefing.py` — fetches everything and prints the spoken text
- `.github/workflows/briefing.yml` — the daily schedule + voice synthesis
- `daily_briefing.mp3` — the latest generated briefing (updated daily)

## Changing the voice

Edit the `--voice` flag in the workflow. Options include
`en-GB-LibbyNeural`, `en-GB-RyanNeural`, `en-US-AriaNeural`, `en-US-GuyNeural`.
