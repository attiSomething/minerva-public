"""AI-assisted organizing and editing: suggestions the user accepts or
ignores. Nothing here changes a file; the page applies a suggestion through
the same endpoints a manual edit uses."""

import difflib
import json
import re

from . import ai

SUGGEST_SYSTEM = """You help a writer organize their archive of poems, stories, essays and journal entries.
Given one piece of their writing, suggest how to file it. Answer with only a JSON object:
{"title": "...", "category": "...", "project": "TAG or null", "reason": "one short sentence"}
- title: the piece's own title if it has one, otherwise a short, fitting title in the writer's words (no quotes, no file-name characters).
- category: exactly one of the categories you are given.
- project: the tag of one of the given projects only if the piece clearly belongs to it, otherwise null."""

FILE_SYSTEM = """You help a writer file transcribed journal entries into their archive.
For each entry, suggest a title and a category. Answer with only a JSON array, one object per entry, in the same order:
[{"num": 1, "title": "...", "category": "..."}]
- title: the entry's own title if it has one, otherwise a short, fitting title drawn from its words (no quotes, no file-name characters).
- category: exactly one of the categories you are given. Journal-style diary writing usually belongs in Nonfiction."""

PROOFREAD_SYSTEM = """You proofread a writer's own work. Fix only clear mistakes: misspellings, typos, doubled or missing words, and obvious transcription errors.
Keep everything else exactly as written: the writer's voice, word choice, line breaks, stanza breaks, capitalization style, punctuation style, and any header lines at the top.
Do not rewrite, rephrase, modernize, shorten or explain. If a word in [square brackets] is a transcriber's guess and the right word is obvious from context, replace the bracketed guess with it; otherwise leave it.
Reply with only the corrected text, nothing before or after it."""


def _json_from(reply, opener):
    """Pull the first JSON object or array out of a model reply."""
    text = (reply or "").strip()
    text = re.sub(r"^```\w*\n|\n```$", "", text)
    closer = "}" if opener == "{" else "]"
    start, end = text.find(opener), text.rfind(closer)
    if start < 0 or end <= start:
        raise ai.ProviderError("The model's answer wasn't in the expected format. Try again.")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        raise ai.ProviderError("The model's answer wasn't in the expected format. Try again.")


def suggest_metadata(settings, key, title, category, project, content, categories, projects):
    project_lines = "\n".join(f"- {p['tag']}: {p['name']}" for p in projects) or "(none)"
    prompt = (f"Categories: {', '.join(categories)}\n"
              f"Projects:\n{project_lines}\n\n"
              f"Currently filed as: title {title!r}, category {category!r}, project {project or 'none'}.\n\n"
              f"The piece:\n<<<\n{content[:12000]}\n>>>")
    data = _json_from(ai.complete(settings["provider"], settings["model"], key,
                                  SUGGEST_SYSTEM, prompt, max_tokens=1000), "{")
    tags = {p["tag"] for p in projects}
    project = data.get("project")
    return {
        "title": str(data.get("title") or "").strip() or title,
        "category": data.get("category") if data.get("category") in categories else category,
        "project": project if project in tags else None,
        "reason": str(data.get("reason") or "").strip(),
    }


def suggest_filing(settings, key, entries, categories):
    """entries: [{num, title, date, body}] -> {num: {title, category}}"""
    out = {}
    for i in range(0, len(entries), 12):
        batch = entries[i:i + 12]
        listing = "\n\n".join(
            f"ENTRY {e['num']}" + (f" (titled {e['title']!r})" if e.get("title") else "") +
            (f", dated {e['date']}" if e.get("date") else "") + f":\n{e['body'][:1500]}"
            for e in batch)
        prompt = f"Categories: {', '.join(categories)}\n\n{listing}"
        data = _json_from(ai.complete(settings["provider"], settings["model"], key,
                                      FILE_SYSTEM, prompt, max_tokens=3000), "[")
        for item in data if isinstance(data, list) else []:
            try:
                num = int(item.get("num"))
            except (TypeError, ValueError, AttributeError):
                continue
            out[num] = {"title": str(item.get("title") or "").strip(),
                        "category": item.get("category") if item.get("category") in categories else None}
    return out


def proofread(settings, key, content):
    corrected = ai.complete(settings["provider"], settings["model"], key, PROOFREAD_SYSTEM,
                            f"<<<\n{content}\n>>>", max_tokens=16000)
    corrected = corrected.strip("\n")
    corrected = re.sub(r"^<<<\n?|\n?>>>$", "", corrected)
    if content.endswith("\n") and not corrected.endswith("\n"):
        corrected += "\n"
    return {"text": corrected, "changes": word_diff(content, corrected)}


def word_diff(a, b):
    """A word-level diff as [[op, text], ...] with op in eq/del/ins, keeping
    whitespace so the page can show it inline."""
    ta, tb = re.findall(r"\s+|[^\s]+", a), re.findall(r"\s+|[^\s]+", b)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(["eq", "".join(ta[i1:i2])])
        else:
            if i2 > i1:
                ops.append(["del", "".join(ta[i1:i2])])
            if j2 > j1:
                ops.append(["ins", "".join(tb[j1:j2])])
    return ops
