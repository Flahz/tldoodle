# tldoodle

Too long; doodled. When an article is too long to read, tldoodle gives you the idea of it
as a short narrated stick-figure video: a TL;DR you watch instead of read. Claude writes the
script, ElevenLabs reads it out loud, and OpenAI draws one simple image per sentence.

## Setup

1. Install the tools: `brew install uv ffmpeg`, plus the `claude` CLI ([Claude Code](https://claude.com/claude-code)).
2. Copy the env file: `cp .env.example .env`
3. Open `.env` and fill in your keys: `ELEVENLABS_API_KEY` and `OPENAI_API_KEY`.

## Usage

Give it the path to your markdown file, for example `articles/my-article.md`:

```bash
uv run tldoodle path/to/article.md               # make the video -> output/article/video.mp4
uv run tldoodle path/to/article.md --phone       # vertical 9:16 video for TikTok, Reels and Shorts -> video-phone.mp4
uv run tldoodle path/to/article.md --minutes 3   # choose the length (default: scales with the article)
uv run tldoodle path/to/article.md --now         # draw the images right away (full price) instead of in a half-price batch
uv run tldoodle --help                           # list every option
uv run tldoodle                                  # no file: open a web page to do all of this with clicks
```

On the web page you paste the article's text, pick the format and follow each step while
the video is made. The text is kept with its video, in `output/<name>/`.

## Cost

Every run makes paid API calls: ElevenLabs for the narration (billed in credits per
character) and OpenAI for the drawings (about $0.018 per image in the default batch, about
$0.07 with `--now`; one image per sentence). Everything is cached in `output/<name>/`, so
re-running the same article only pays for what changed.

## License

MIT, see [LICENSE](LICENSE). Pull requests are welcome.
