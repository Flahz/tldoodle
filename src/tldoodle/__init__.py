"""Turn any markdown article into a narrated stick-figure explainer video.

    uv run tldoodle article.md [--minutes 5] [--now] [--fullscreen | --phone]
    uv run tldoodle             (no article: opens the web page, index.html, to do it all from there)

  1. script  Claude rewrites the article as short spoken sentences, each paired
             with one scene to draw (instructions in prompt.md)  -> script-<id>.json
  2. voice   ElevenLabs reads every sentence                      -> audio/*.mp3
  3. images  OpenAI draws every scene in the style of references/ -> images/*.png
             through its half-price Batch API (--now: right away, full price)
  4. video   ffmpeg shows each image while its sentence plays     -> video.mp4

The video is 16:9 widescreen (--fullscreen, the default). --phone makes it 9:16 for
Reels, TikTok and Shorts instead: the scenes are drawn upright into images-phone/ and
the video is video-phone.mp4, while the script and the voice are shared.

Everything lands in output/<article name>/. Each file is named after a hash of what
produced it, so re-running only makes what's missing: a failed run resumes where it
stopped, an edited article gets a fresh script, and hand-edits to the script JSON
only redo the sentences that changed.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # the project folder; this file is src/tldoodle/__init__.py

# Script: written by the Claude Code CLI, which runs on your Claude plan (no API key).
CLAUDE_MODEL = "sonnet"
WORDS_PER_MINUTE = 150

# Voice: ElevenLabs "Steven - natural and kind", with the voice's own stored settings.
VOICE_ID = "wtQQHWfMy9WeIYuth5ga"
VOICE_MODEL = "eleven_v4"
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.5, "style": 0.41, "use_speaker_boost": True, "speed": 1.09}
# Each sentence's tone shifts (stability, style) away from those settings: lower
# stability and more style sound more animated, the opposite flatter and heavier.
TONES = {
    "neutral": (0.0, 0.0),
    "tense": (-0.15, 0.15),
    "excited": (-0.20, 0.25),
    "shocked": (-0.30, 0.30),
    "somber": (0.10, -0.10),
    "relieved": (0.05, -0.05),
}

# Images: OpenAI, with the pictures in references/ attached to every request.
IMAGE_MODEL = "gpt-image-2.5-flare"
# With 6+ attached images gpt-image-1-mini ignored the prompt (it returned unrelated
# photos); 4 references plus the character sheet works, so stay at that.
MAX_REFS = 4
# References are attached at half size: OpenAI bills input images by their pixels, and
# the style survives (7,680 -> 3,520 input tokens per image, verified 2026-10-18).
REF_WIDTH = 768
STYLE = (
    "draw EXACTLY in the art style of the attached reference images: an extremely simple, clean "
    "stick-figure cartoon with smooth confident solid black outlines of even weight (never shaky, "
    "sketchy or crude); people are stick figures with a round PURE FLAT WHITE head (zero skin tone, "
    "zero shading — only the black outline defines it), a small block of flat solid-colored hair, "
    "tiny dot eyes and one simple mouth line, and thin black stick arms and legs with clearly bent "
    "elbows and knees in a natural readable pose; keep every scene MINIMAL like the references: one "
    "flat-colored background (a flat pastel sky or wall and a flat ground) plus at most one or two "
    "simple objects (a hut, a tree, a rock, a doorway) drawn with the same clean outlines and flat "
    "colors — lots of empty space is good; flat colors only, no shading, no gradients, no texture, "
    "no clutter, no extra background detail, no photorealism, no 3D render, no text, no words, no "
    "letters, no watermark"
)
REFS_NOTE = (
    "Draw this image in EXACTLY the art style of the attached reference image(s) — same line "
    "weight, same simplicity, same flat colors, same kind of background; redraw recurring "
    "characters EXACTLY as they appear there. Do not copy the reference scenes themselves, and do "
    "not add any detail beyond what the reference style uses. "
)
SHEET = (
    "Character reference sheet: every recurring character standing side by side, full body, "
    "facing the viewer, neutral pose, evenly spaced, plain background"
)

# Video: every image is a still held for its sentence, with hard cuts (no motion, no fades).
# Each screen: the video's width and height, and the size its images are drawn at
# (gpt-image-2.5-flare draws any size whose sides are multiples of 16).
SCREENS = {
    "fullscreen": (1920, 1080, "1536x1024"),  # 16:9 for computers and TVs, the default
    "phone": (1080, 1920, "864x1536"),  # 9:16 for Reels, TikTok and Shorts
}
FPS = 30
GAP = 0.5  # seconds of silence between sentences; the image changes halfway through it
TAIL = 1.0  # seconds the last image stays up after the narration ends
RATE = 44100  # audio sample rate, same as ElevenLabs' mp3_44100_128


def digest(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def save(path: Path, data: bytes) -> None:
    """Write through a temp file so an interrupted run never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def api(method: str, url: str, **kwargs) -> requests.Response:
    """An HTTP call with up to 5 attempts and exponential backoff. A rejected request,
    key or id (400/401/403/404/422) fails at once, since retrying can't fix it."""
    for attempt in range(5):
        if attempt:
            time.sleep(3 * 2 ** (attempt - 1))
        try:
            response = requests.request(method, url, timeout=180, **kwargs)
        except requests.RequestException as e:
            error = str(e)
            continue
        if response.ok:
            return response
        error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code in (400, 401, 403, 404, 422):
            break
    raise RuntimeError(f"{url} failed: {error}")


def openai(method: str, path: str, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    return api(method, f"https://api.openai.com/v1{path}", headers=headers, **kwargs)


def write_script(article: str, minutes: float, folder: Path) -> dict:
    """Have Claude turn the article into sections of lines, each {"say", "tone", "draw"}."""
    prompt = (
        (ROOT / "prompt.md").read_text()
        .replace("{words}", str(round(minutes * WORDS_PER_MINUTE)))
        .replace("{minutes}", f"{minutes:g}")
        .replace("{article}", article)  # last, so nothing inside the article gets replaced
    )
    path = folder / f"script-{digest(prompt)}.json"
    if path.exists():
        return json.loads(path.read_text())
    print(f"Writing a ~{minutes:g}-minute script with Claude...", flush=True)
    retry_note, reply = "", ""
    for _ in range(3):
        result = subprocess.run(
            ["claude", "-p", "--model", CLAUDE_MODEL],
            input=prompt + retry_note, capture_output=True, text=True, timeout=900,
        )
        reply = result.stdout or result.stderr
        try:
            script = json.loads(reply[reply.find("{") : reply.rfind("}") + 1])
            lines = [line for section in script["sections"] for line in section["lines"]]
            if not lines or not all(line["say"].strip() and line["draw"].strip() for line in lines):
                raise ValueError("every line needs a non-empty 'say' and 'draw'")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            retry_note = f"\n\nYour previous reply was unusable ({e}). Reply with ONLY the corrected JSON object."
            continue
        save(path, json.dumps(script, indent=2, ensure_ascii=False).encode())
        return script
    raise RuntimeError(f"Claude never returned a usable script. Last reply: {reply[:500]}")


def voice(lines: list[dict], folder: Path) -> list[Path]:
    """One mp3 per sentence. Each request also carries the neighbouring sentences as
    context, so the delivery flows even though every sentence is voiced separately."""
    paths = []
    for i, line in enumerate(lines):
        d_stability, d_style = TONES.get(str(line.get("tone")).lower(), (0.0, 0.0))
        settings = {
            **VOICE_SETTINGS,
            "stability": min(1.0, max(0.0, VOICE_SETTINGS["stability"] + d_stability)),
            "style": min(1.0, max(0.0, VOICE_SETTINGS["style"] + d_style)),
        }
        payload = {"text": line["say"], "model_id": VOICE_MODEL, "voice_settings": settings}
        if i > 0:
            payload["previous_text"] = lines[i - 1]["say"]
        if i + 1 < len(lines):
            payload["next_text"] = lines[i + 1]["say"]
        path = folder / f"{digest(VOICE_ID + json.dumps(payload, sort_keys=True))}.mp3"
        if not path.exists():
            print(f"  sentence {i + 1}/{len(lines)}", flush=True)
            response = api(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                json=payload,
            )
            save(path, response.content)
        paths.append(path)
    return paths


def style_refs() -> list[Path]:
    images = (p for p in (ROOT / "references").iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    return sorted(images)[:MAX_REFS]


def picture_prompt(scene: str, cast: str) -> str:
    return f"{REFS_NOTE}{STYLE}.{cast} Scene: {scene}"


def image_path(prompt: str, refs: list[Path], folder: Path) -> Path:
    """Where an image is cached: named after everything that shapes it."""
    key = f"{IMAGE_MODEL}|{REF_WIDTH}|{prompt}|" + "".join(hashlib.sha1(p.read_bytes()).hexdigest() for p in refs)
    return folder / f"{digest(key)}.png"


def upload(data: bytes, name: str, purpose: str) -> str:
    """Store a file with OpenAI for a week (it's deleted after that) and return its id."""
    form = {"purpose": purpose, "expires_after[anchor]": "created_at", "expires_after[seconds]": str(7 * 86400)}
    return openai("POST", "/files", data=form, files={"file": (name, data)}).json()["id"]


def upload_refs(refs: list[Path]) -> list[str]:
    """Upload half-size copies of the references once; every request points at them by id."""
    ids = []
    for ref in refs:
        small = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", ref, "-vf", f"scale={REF_WIDTH}:-2", "-f", "image2pipe", "-c:v", "png", "-"],
            stdout=subprocess.PIPE, check=True,
        ).stdout
        ids.append(upload(small, f"{ref.stem}.png", "vision"))
    return ids


def edit_request(prompt: str, ref_ids: list[str], size: str) -> dict:
    return {"model": IMAGE_MODEL, "prompt": prompt, "size": size, "images": [{"file_id": i} for i in ref_ids]}


def draw_now(prompt: str, ref_ids: list[str], path: Path, size: str) -> None:
    """One image of `size` ("1536x1024"), drawn right away at full price."""
    response = openai("POST", "/images/edits", json=edit_request(prompt, ref_ids, size))
    save(path, base64.b64decode(response.json()["data"][0]["b64_json"]))


def draw_batch(jobs: dict[Path, str], refs: list[Path], folder: Path, size: str) -> None:
    """Draw every job through OpenAI's Batch API: half price, but it can take a while.
    The batch id is kept in batch.json, so an interrupted run picks the same batch back
    up instead of paying for a new one."""
    state = folder / "batch.json"
    if not state.exists():
        ref_ids = upload_refs(refs)
        requests_jsonl = "\n".join(
            json.dumps({"custom_id": path.stem, "method": "POST", "url": "/v1/images/edits",
                        "body": edit_request(prompt, ref_ids, size)})
            for path, prompt in jobs.items()
        )
        input_id = upload(requests_jsonl.encode(), "images.jsonl", "batch")
        batch = openai("POST", "/batches", json={"input_file_id": input_id, "endpoint": "/v1/images/edits",
                                                 "completion_window": "24h"})
        save(state, batch.json()["id"].encode())
    batch_id = state.read_text()
    print(f"  OpenAI batch {batch_id}: usually done in minutes, at most 24h. "
          "Ctrl-C is safe, re-run the same command to pick it back up.", flush=True)
    shown = ""
    while True:
        batch = openai("GET", f"/batches/{batch_id}").json()
        counts = batch.get("request_counts") or {}
        status = f"  batch {batch['status']}: {counts.get('completed', 0)}/{counts.get('total') or len(jobs)} images"
        if status != shown:
            print(status, flush=True)
            shown = status
        if batch["status"] in ("completed", "failed", "expired", "cancelled"):
            break
        time.sleep(30)
    if batch["status"] != "completed":
        print(f"  batch {batch['status']}: {json.dumps(batch.get('errors'))[:300]}", flush=True)
    if batch.get("output_file_id"):
        for line in openai("GET", f"/files/{batch['output_file_id']}/content").text.splitlines():
            result = json.loads(line)
            body = (result.get("response") or {}).get("body") or {}
            if body.get("data"):
                save(folder / f"{result['custom_id']}.png", base64.b64decode(body["data"][0]["b64_json"]))
    state.unlink()


def images(script: dict, lines: list[dict], folder: Path, now: bool, size: str) -> list[Path]:
    """One image of `size` per sentence, drawn through the half-price Batch API (or right away if `now`)."""
    refs = style_refs()
    if not refs:
        raise RuntimeError("references/ has no images to copy the style from")
    cast = "; ".join(
        f"{c['name'].strip()}: {c['look'].strip()}"
        for c in script.get("characters") or []
        if c.get("name") and c.get("look")
    )
    if cast:
        cast = (
            " RECURRING CHARACTERS — whenever the scene shows one of them, draw them EXACTLY like this, "
            f"identical design every time: {cast}. Only draw the characters the scene names."
        )
        # a sheet of the whole cast, attached to every scene, keeps the characters identical across shots
        sheet = image_path(picture_prompt(SHEET, cast), refs, folder)
        try:
            if not sheet.exists():
                print("  character sheet", flush=True)
                # always wide, whatever the screen: the whole cast stands side by side
                draw_now(picture_prompt(SHEET, cast), upload_refs(refs), sheet, "1536x1024")
            refs = refs + [sheet]
        except (RuntimeError, KeyError, ValueError) as e:
            print(f"  character sheet failed, drawing without it: {e}", flush=True)

    prompts = [picture_prompt(line["draw"], cast) for line in lines]
    paths = [image_path(prompt, refs, folder) for prompt in prompts]
    jobs = {path: prompt for path, prompt in zip(paths, prompts) if not path.exists()}
    if jobs and now:
        ref_ids = upload_refs(refs)

        def job(item: tuple[Path, str]) -> None:
            label = f"image {paths.index(item[0]) + 1}/{len(paths)}"
            try:
                draw_now(item[1], ref_ids, item[0], size)
                print(f"  {label}", flush=True)
            except (RuntimeError, KeyError, ValueError) as e:
                print(f"  {label} failed: {e}", flush=True)

        pool = ThreadPoolExecutor(max_workers=4)
        try:
            list(pool.map(job, jobs.items()))
        finally:
            pool.shutdown(cancel_futures=True)  # on Ctrl-C, don't keep paying for queued images
    elif jobs:
        draw_batch(jobs, refs, folder, size)

    drawn = [path if path.exists() else None for path in paths]
    if not any(drawn):
        raise RuntimeError("no image could be drawn")
    if None in drawn:
        print(f"  {drawn.count(None)} image(s) missing, the previous image stands in. Re-run to retry them.", flush=True)
    filled, last = [], next(p for p in drawn if p)
    for path in drawn:
        last = path or last
        filled.append(last)
    return filled


def render(audio: list[Path], pictures: list[Path], out: Path, width: int, height: int) -> None:
    """Show picture i exactly as long as sentence i plays, plus half a GAP of silence
    on either side, so every cut lands in the pause between two sentences."""
    pad = bytes(round(RATE * GAP / 2) * 2)  # silence as 16-bit mono samples
    narration, durations = bytearray(), []
    for clip in audio:
        speech = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", clip, "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
            stdout=subprocess.PIPE, check=True,
        ).stdout
        narration += pad + speech + pad
        durations.append((2 * len(pad) + len(speech)) / (2 * RATE))
    narration += bytes(round(RATE * TAIL) * 2)
    durations[-1] += TAIL

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with wave.open(str(tmp / "narration.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(narration)
        # First give every picture the exact same size and pixel format: OpenAI returns
        # some images as RGBA, and a format change mid-stream makes ffmpeg drop frames.
        timeline = []
        for i, (picture, duration) in enumerate(zip(pictures, durations)):
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-i", picture, "-vf",
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgb24",
                    tmp / f"{i}.png",
                ],
                check=True,
            )
            timeline.append(f"file '{i}.png'\nduration {duration:.6f}")
        # ffmpeg's concat format; the last picture is listed twice or its duration is ignored
        (tmp / "pictures.txt").write_text(
            "ffconcat version 1.0\n" + "\n".join(timeline) + f"\nfile '{len(pictures) - 1}.png'\n"
        )
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-f", "concat", "-i", tmp / "pictures.txt", "-i", tmp / "narration.wav",
                "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-tune", "stillimage", "-crf", "20",
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", out,
            ],
            check=True,
        )


def suffix(screen: str) -> str:
    """What sets a screen's files apart: nothing for fullscreen (images/, video.mp4), "-phone" for the phone."""
    return "" if screen == "fullscreen" else f"-{screen}"


# The web page (index.html): `uv run tldoodle` with no article shows it to this computer only, at
# http://127.0.0.1:8765. It makes each video by running this same command in the background,
# exactly as from a terminal, and follows its output; one video at a time.
PAGE_PORT = 8765
job: dict = {}  # the video the page is making (or made last), as the page shows it
job_lock = threading.Lock()
process: subprocess.Popen | None = None


def make_videos(article: Path, screens: list[str], minutes: float | None, now: bool) -> None:
    """Run the command once per screen, in turn: the second run reuses the script and the voice."""
    global process
    for screen in screens:
        args = [str(Path(sys.executable).with_name("tldoodle")), str(article), f"--{screen}"]
        if minutes:
            args += ["--minutes", f"{minutes:g}"]
        if now:
            args.append("--now")
        with job_lock:
            if job["status"] != "running":  # cancelled
                return
            job["screen"] = screen
            job["log"].append(f"$ tldoodle {article.relative_to(ROOT)} {' '.join(args[2:])}")
            try:  # in its own session, so cancelling can Ctrl-C it along with its own subprocesses
                process = subprocess.Popen(
                    args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", env={**os.environ, "PYTHONUNBUFFERED": "1"}, start_new_session=True,
                )
            except OSError as e:
                job["log"].append(f"error: {e}")
                job["status"] = "failed"
                return
        for line in process.stdout:
            with job_lock:
                job["log"].append(line.rstrip())
        failed = process.wait() != 0
        with job_lock:
            if job["status"] != "running":
                return
            if failed:
                job["status"] = "failed"
                return
    with job_lock:
        job["status"] = "done"


def start_job(body: dict) -> dict:
    """Keep the pasted article as output/<name>/<name>.md (the command names the video's folder after
    the file, so a second run finds everything the first one made), then make a video per screen."""
    text = str(body.get("text") or "").strip()
    plain = unicodedata.normalize("NFKD", str(body.get("name") or "")).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60].strip("-")
    asked, minutes = body.get("screens"), body.get("minutes")
    screens = [s for s in SCREENS if isinstance(asked, list) and s in asked]
    if not text:
        raise ValueError("Paste the article's text first.")
    if not name:
        raise ValueError("Give the article a name.")
    if not screens:
        raise ValueError("Pick at least one format.")
    if minutes is not None and not (isinstance(minutes, (int, float)) and 0 < minutes <= 60):
        raise ValueError("The length must be between 0 and 60 minutes.")
    article = ROOT / "output" / name / f"{name}.md"
    if article.exists() and article.read_text(errors="replace").strip() != text:
        raise ValueError(f"Another article is already called “{name}”: pick another name.")
    with job_lock:
        if job.get("status") == "running":
            raise ValueError("A video is already being made: wait for it to finish, or cancel it.")
        save(article, (text + "\n").encode())
        first = next(line for line in text.splitlines() if line.strip()).strip().lstrip("#").strip()
        job.clear()
        job.update(id=int(time.time() * 1000), article=name, title=first or name, screens=screens, screen=screens[0],
                   status="running", log=[])
    threading.Thread(target=make_videos, args=(article, screens, minutes, bool(body.get("now"))), daemon=True).start()
    return {}


def cancel_job(body: dict | None = None) -> dict:
    """Stop the page's video the way Ctrl-C would: whatever is already made stays made."""
    with job_lock:
        if job.get("status") == "running":
            job["status"] = "cancelled"
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
    return {}


def job_news(query: dict) -> dict:
    """The page's video, with only the output lines the page hasn't seen yet."""
    with job_lock:
        if not job:
            return {"job": None}
        since = int(query.get("log", ["0"])[0]) if query.get("id", [""])[0] == str(job["id"]) else 0
        return {"job": {**job, "log": job["log"][since:]}}


def reveal(body: dict) -> dict:
    """Show a video in the Finder."""
    video = (ROOT / "output" / str(body.get("article")) / str(body.get("file"))).resolve()
    if video.suffix != ".mp4" or not video.is_relative_to(ROOT / "output") or not video.is_file():
        raise ValueError("Video not found.")
    subprocess.run(["open", "-R", video], check=False)
    return {}


class Page(BaseHTTPRequestHandler):
    """Answers index.html and what it asks for, and nothing to any other website."""

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if not self.trusted():
            return
        if url.path == "/":
            self.reply(Path(__file__).with_name("index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/job":
            self.answer(lambda: job_news(parse_qs(url.query)))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        action = {"/api/generate": start_job, "/api/cancel": cancel_job, "/api/reveal": reveal}.get(urlparse(self.path).path)
        if not self.trusted():
            return
        if not action:
            return self.send_error(404)
        # JSON only: a browser won't send JSON from another website without asking first (this never agrees)
        if self.headers.get_content_type() != "application/json":
            return self.send_error(415)
        self.answer(lambda: action(self.read_json()))

    def trusted(self) -> bool:
        """Only this computer's own page: not another website, nor a web address made to point here."""
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if (self.headers.get("Host") not in hosts or (origin and origin.removeprefix("http://") not in hosts)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.send_error(403)
            return False
        return True

    def read_json(self) -> dict:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("bad request")
        return body

    def answer(self, make_reply) -> None:
        """Reply with make_reply()'s JSON, or with its ValueError's message for the page to show."""
        try:
            data, status = make_reply(), 200
        except ValueError as e:
            data, status = {"error": str(e)}, 400
        self.reply(json.dumps(data).encode(), "application/json", status)

    def reply(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        pass  # the page asks for news every second; keep the terminal quiet


def serve() -> None:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), Page)
    except OSError:  # the port is taken (by another tldoodle page?): any free one will do
        server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"The page is at {url} (Ctrl-C here to stop it)", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cancel_job()  # a video still being made stops as with Ctrl-C; asking for it again resumes it
        if process and process.poll() is None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn a markdown article into a stick-figure explainer video.")
    parser.add_argument("article", type=Path, nargs="?", metavar="path/to/article.md",
                        help="path to the markdown file to explain (none: open the web page)")
    parser.add_argument("--minutes", type=float, help="target length (default: scales with the article, 1.5-10 min)")
    parser.add_argument("--now", action="store_true", help="draw images right away at full price instead of in a half-price batch")
    screen = parser.add_mutually_exclusive_group()
    screen.add_argument("--fullscreen", dest="screen", action="store_const", const="fullscreen", default="fullscreen",
                        help="16:9 widescreen video for computers and TVs (the default)")
    screen.add_argument("--phone", dest="screen", action="store_const", const="phone",
                        help="9:16 vertical video for phones, like Reels, TikTok and Shorts")
    args = parser.parse_args()
    if args.article is None:
        return serve()

    load_dotenv(ROOT / ".env")
    missing = [key for key in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY") if not os.environ.get(key)]
    if missing:
        sys.exit(f"error: add {' and '.join(missing)} to {ROOT / '.env'} (see .env.example)")

    article = args.article.read_text()
    # by default the narration is about half as long as the article itself
    minutes = round(args.minutes or min(10.0, max(1.5, len(article.split()) / 2 / WORDS_PER_MINUTE)), 1)
    folder = ROOT / "output" / args.article.stem
    width, height, size = SCREENS[args.screen]

    script = write_script(article, minutes, folder)
    lines = [line for section in script["sections"] for line in section["lines"]]
    print(f"\"{script.get('title', args.article.stem)}\": {len(lines)} sentences, one image each")
    print("Voicing with ElevenLabs...", flush=True)
    audio = voice(lines, folder / "audio")
    print("Drawing with OpenAI...", flush=True)
    pictures = images(script, lines, folder / f"images{suffix(args.screen)}", args.now, size)
    print("Rendering the video...", flush=True)
    video = folder / f"video{suffix(args.screen)}.mp4"
    render(audio, pictures, video, width, height)
    print(f"Done: {video}")


def cli() -> None:
    """The `tldoodle` command (see pyproject.toml): main(), with errors shown as one line."""
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        sys.exit(f"error: {e}")
