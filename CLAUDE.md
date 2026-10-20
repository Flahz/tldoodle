# tldoodle — working notes for Claude

Turns any markdown article into a narrated stick-figure explainer video ("too long; doodled"; renamed from yt-auto/ytauto on 2026-10-18; GitHub: Flahz/tldoodle). The user is a visual learner and uses it to understand articles they find online. The whole pipeline is `src/tldoodle/__init__.py` (one file: script → voice → images → video), `prompt.md` (how Claude turns the article into a script) and `references/` (style images). The user doesn't want a Python file at the repo root (2026-10-18); it's a package folder because uv's build backend rejects a lone `src/tldoodle.py` (verified), and `[project.scripts]` makes it the `tldoodle` command. Run: `uv run tldoodle article.md [--minutes N] [--phone]`, or `uv run tldoodle` alone for the web page; the video and per-sentence caches land in `output/<article name>/`. Python is run via `uv run` (there is no bare `python` on PATH).

## Keep it simple (user's explicit wish)

- On 2026-10-18 the user had the old multi-file pipeline (niches, config.yaml, topic picker, storyboard, captions, music, metadata, thumbnails; ~3.9k lines over 15 modules) collapsed into this single file. Don't grow it back: no new modes, niches, config layers or broad features unless asked. Settings are the constants at the top of `src/tldoodle/__init__.py`.
- An earlier attempt to add a whole new `essay`/documentary style was rejected ("keep the figurines with basic images"). Improve the existing look; don't replace it or add cinematic/photoreal styles.
- Prefer small, targeted changes.

## Visual style (user's active preference)

The images must match the **Zenn** YouTube channel (@Zenn0009, e.g. "What Did Ancient Humans Do All Day?").

- **Clean stick-figure cartoon, NOT crude MS-Paint.** Even-weight confident solid black outlines, round white heads with a small block of flat-colored hair, simple faces (dot eyes, simple mouth — expressive but not grotesque), full stick bodies with clearly bent limbs in natural poses. This lives in `STYLE` in `src/tldoodle/__init__.py`. Do not revert it to the old "crude, shaky, messy, plain white background, face fills the whole head" wording.
- **Simple flat-colored scene backgrounds**, not empty white — a pastel sky, flat ground, and one or two simple objects in the same clean line style.
- **Static images — no motion, no animation code at all.** On 2026-07-04 the user had ALL animation removed: no image-to-video, no Ken Burns zoom/pan, no atmosphere overlays. Every image is a still held for its sentence. Do not reintroduce any of it.
- **Instant hard cuts between images — no crossfade/dissolve, no fades.**
- Keep the figures **simple** — "figurines with basic images." No photorealism, 3D, or detailed rendering.
- **Every generation must match the style reference images in `references/`.** They are attached to each OpenAI request via the images/edits endpoint (`style_refs()`, `upload_refs()`, `edit_request()`), plus a character sheet generated once per video. CAUTION: gpt-image-1-mini breaks with 6+ attached images (it ignores the prompt and returns unrelated photos) — keep at most 4 refs + the character sheet (`MAX_REFS`, verified 2026-07-04).

Images render via OpenAI `gpt-image-2.5-flare` (needs `OPENAI_API_KEY` in `.env`), one image per sentence; the user asked for the latest model on 2026-10-18 (it was `gpt-image-1-mini` before). With quality left on auto, flare picks `low` (crisp enough for this flat style).

Screens (`SCREENS`; the user asked for a fullscreen and a phone flag on 2026-10-18): `--fullscreen` (the default) is 16:9, images drawn at 1536x1024 and cropped to 1920x1080 as always. `--phone` is 9:16 for Reels/TikTok: scenes drawn upright at exactly 864x1536 (flare takes any size with sides divisible by 16) into `images-phone/`, rendered to `video-phone.mp4`; script and audio are shared. Verified 2026-10-18: flare fills the tall frame and keeps the characters mid-frame with no prompt change. The character sheet is always 1536x1024 (cast side by side), one per images folder.

Cost (user asked to optimize it, 2026-10-18): most of an image's price is the attached references, billed by pixels. They're uploaded once per run as half-size copies (`REF_WIDTH`, input tokens 7,680 → 3,520 per image; files auto-expire after a week) and referenced by `file_id`. Scenes then go through the Batch API (50% off; batch id kept in `images/batch.json` so Ctrl-C + re-run resumes instead of paying twice); `--now` draws synchronously at full price. Roughly $0.07 → $0.018 per image. OpenAI's image endpoints don't do prompt caching (none reported even with identical uploaded refs), and ElevenLabs has no batch or cache discount; the local hash cache is what prevents paying twice.

Web page (user asked on 2026-10-18 for "un fichier html", and chose one page plus `uv run tldoodle` over a separate server file): `uv run tldoodle` with no article serves `src/tldoodle/index.html` on 127.0.0.1:8765 (stdlib `http.server`: `Page`, `serve()` in `__init__.py`), opens the browser, and makes each video by running the same `tldoodle` command as a subprocess per screen; one job at a time, Cancel = SIGINT to its process group (like Ctrl-C, so it resumes). The page is in English (the user had it switched from French, 2026-10-18). The user wants it minimal: the article is only ever pasted in (no link to `articles/`), kept as `output/<name>/<name>.md` so the command's stem-named folder is the same on every run, and the page neither lists nor plays videos (both removed at the user's request, 2026-10-18); a finished job just names its files and offers Show in Finder. It follows progress by reading the command's prints (`STARTS` and the regexes in index.html: "Writing a", "Voicing with", "Drawing with", "Rendering", "  sentence i/N", "  image i/N", "  batch S: c/N images", "error:"): keep those prints in sync. Its endpoints spend money, so it only answers its own page (Host, Origin and Sec-Fetch-Site checks; POSTs must be JSON).

## Voice (user's active preference, 2026-07-04)

- ElevenLabs voice `wtQQHWfMy9WeIYuth5ga` ("Steven - natural and kind") on **`eleven_v4`** with the voice's own stored settings (`VOICE_SETTINGS`: stability 0.5, similarity 0.5, style 0.41, speaker_boost, speed 1.09). The user asked for the latest model on 2026-10-18 (it was `eleven_multilingual_v2`, the originally approved sound); v4 accepts the same voice_settings and `previous_text`/`next_text` and costs the same credits (verified). Don't change the model or re-tune the settings without asking.
- **Per-sentence emotion**: every script line carries a `tone` (`neutral`/`tense`/`excited`/`shocked`/`somber`/`relieved`, chosen by Claude per `prompt.md`); `voice()` shifts stability/style per sentence via `TONES`, so the delivery follows the ideas instead of staying monotone. Each request also sends the neighbouring sentences as `previous_text`/`next_text` for continuity.

## Gotchas (verified)

- `uv run tldoodle ...` makes PAID calls (ElevenLabs, OpenAI) whenever `.env` has keys. Test offline by importing `tldoodle` and stubbing `tldoodle.api`.
- The character note in `images()` must say to draw only the characters the scene names: otherwise gpt-image-2.5-flare puts the whole cast into every image (verified 2026-10-18).
- OpenAI sometimes returns RGBA PNGs among RGB ones. `render()` therefore converts every picture to the same size and pixel format before joining them; feeding mixed formats straight into ffmpeg's concat input silently drops frames around the change (verified 2026-10-18).
- Testing the web page: headless Chrome won't lay a page out narrower than 500px (whatever `--window-size` says), so check the phone layout inside a 390px-wide same-origin iframe. Started in the background (`nohup ... &`), the server ignores SIGINT, so stop it with SIGTERM.

## Previewing a change to the look

Render a sample still (~$0.04) before a full run (size `"864x1536"` for a phone still):

```bash
uv run python -c '
import pathlib, tldoodle
tldoodle.load_dotenv(tldoodle.ROOT / ".env")
tldoodle.draw_now(tldoodle.picture_prompt("SCENE DESCRIPTION", ""), tldoodle.upload_refs(tldoodle.style_refs()), pathlib.Path("/tmp/sample.png"), "1536x1024")'
```
