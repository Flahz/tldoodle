Here is an article:

<article>
{article}
</article>

Turn this article into the script for a short explainer video made for a visual learner. A warm narrator reads your script one sentence at a time, and while each sentence plays, ONE simple stick-figure drawing illustrates it on screen. After watching, the viewer should truly understand the article.

LENGTH: about {words} words of narration in total (~{minutes} minutes at 150 words per minute).

WHAT TO SAY: teach the article, faithfully
- Cover the article's real substance, usually in its own order: the core idea, how it works, the key examples, numbers and conclusions. If it can't all fit, keep what a reader most needs and drop minor asides.
- Stay true to it. Never invent facts, numbers, quotes or claims. When the author argues an opinion, present it as theirs ("the author argues...").
- Make it click: start from the question or problem the article answers, explain every piece of jargon in plain words the first time it comes up, use everyday analogies, and say WHY each point matters, not just what it is. Link each idea to the one before.
- Say in words what can't be read aloud: describe what code, formulas, tables and diagrams do or show. Never read out code, URLs, file paths or citations. Skip links, image captions, ads, navigation, author bios and sign-up boxes.
- Write the narration in the article's language, with numbers, symbols and abbreviations written the way a person would say them.

SENTENCES: every sentence becomes one image on screen
- One idea per sentence, 6 to 16 words. Short sentences mean faster image changes and a video that's easier to follow.
- Sound like a person explaining something to a friend: clear, curious, warm. No "welcome back", no "in this video", no "like and subscribe", no markdown, no emoji.
- To stress ONE key word, write it in ALL CAPS, at most once per section.

STRUCTURE
- First section, heading "Intro": 2-4 sentences. Open on the question, problem or surprising fact at the heart of the article, then say what the viewer is about to understand.
- Then one section per main idea of the article, each with a short heading.
- Last section, heading "Recap": 3-5 sentences that restate the key takeaways so they stick.

TONE: how the narrator's voice colors each sentence
Every line has a "tone":
- "neutral": plain explanation (the default).
- "excited": a surprising, impressive or fun fact.
- "tense": a problem, a risk, a mystery or an open question.
- "shocked": one of the 1-3 biggest reveals of the whole video, never in the Intro.
- "somber": a serious cost, a limitation, a sad or sobering fact.
- "relieved": a solution, a problem resolved, the moment an explanation clicks.
Give about a third of the lines a non-neutral tone, so the voice follows the ideas instead of droning.

CHARACTERS: so the drawings stay consistent
- List 1-3 recurring characters: usually a curious guide who walks through the ideas, plus the article's main actors (a real person, a group, or a personified thing like "THE SERVER" or "THE CELL").
- Give each a short ALL-CAPS "name" and a "look" of 8-15 words that locks their appearance: a stick figure with a plain white round head (no skin tone), plus exactly ONE memorable color detail no other character shares, with clothing named precisely (e.g. "stick figure, plain white round head, short brown hair, green striped scarf").
- Every "draw" that shows a character must use their exact NAME.

DRAW: what's on screen during the sentence (the most important part)
- Make THAT sentence's idea visible. If the sentence names a concrete thing, show that thing. If it's abstract, turn it into a simple physical picture a child would get: data → letters or boxes being carried; a bottleneck → a crowd squeezing through one narrow door; growth → a figure climbing ever-taller stairs; a trade-off → a figure balancing a seesaw; memory → a figure filing papers into a cabinet.
- Most images show a character doing something and reacting, with the expression named ("curious raised eyebrow", "confused frown", "delighted grin").
- Every image is a full simple scene: name a flat-colored backdrop (pastel sky, warm beige wall), a ground line, and one or two simple props. Never a figure floating on a blank background.
- No text in the image at all: no words, letters, numbers, labels, logos or charts with values. Show amounts with sizes, heights, piles or counts of objects instead.
- If a screen, sign or board appears, say exactly what simple picture is ON it ("a laptop screen showing a big red X"), otherwise it renders blank.
- Consecutive images must look clearly different: change at least two of camera distance, camera angle, setting and main subject.
- Places are simple drawn settings, never real or photographic ones, and no brand names.
- No lighting effects (glows, shadows, light beams, dark rooms): everything is flat color.
- No art-style words ("cartoon", "drawing", "cinematic", "4k"): the style is added automatically. Under 25 words, self-contained (never "same as before"), always in English.

OUTPUT: only valid JSON, no markdown fences, no commentary, exactly this shape:
{
  "title": "short, clear title for the video",
  "characters": [{"name": "THE GUIDE", "look": "stick figure, plain white round head, short brown hair, green striped scarf"}],
  "sections": [
    {"heading": "Intro", "lines": [
      {"say": "One spoken sentence.", "tone": "neutral", "draw": "One scene for that sentence."}
    ]}
  ]
}
