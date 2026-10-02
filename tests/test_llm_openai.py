import json

import pytest

from fyt import llm
from fyt.config import Config, LLMConfig

SCRIPT = {
    "title": "The Queen Who Lost Three Kingdoms",
    "description": "Mary's story.",
    "tags": ["history"],
    "thumbnail_text": "Lost it all",
    "thumbnail_kicker": "Mary",
    "thumbnail_query": "castle",
    "scenes": [{"narration": "She was queen at six days old.", "type": "title", "heading": "Queen at 6 days"}],
    "sources": [],
}


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self.body, self.headers, self.text = status, body, headers or {}, json.dumps(body)

    def json(self):
        return self.body


def reply(content):
    return Resp(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return Config(format="short", llm=LLMConfig(provider="openai"))


def test_openai_script_retries_on_bad_json_and_rate_limit(cfg, monkeypatch):
    calls = []
    answers = [Resp(429, {}, {"retry-after": "1"}), reply('{"title": "missing fields"}'), reply(json.dumps(SCRIPT))]

    def post(url, headers, json, timeout):
        assert url == "https://api.groq.com/openai/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test"
        assert json["response_format"] == {"type": "json_object"}
        calls.append(json["messages"])
        return answers.pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    script = llm.write_script(cfg, "Mary, Queen of Scots", "x" * 50000, from_wikipedia=True)
    assert script.title == SCRIPT["title"]
    assert "never copy" in calls[0][0]["content"].lower()  # Wikipedia rules in the system prompt
    assert len(calls[0][1]["content"]) < 7000  # notes trimmed for free-tier limits
    assert "did not match the schema" in calls[-1][-1]["content"]
    assert len(calls[-1]) == 2  # retries don't resend the rejected reply


def test_openai_retries_when_groq_rejects_invalid_json(cfg, monkeypatch):
    bodies = []
    rejected = Resp(400, {"error": {"code": "json_validate_failed", "failed_generation": "max completion tokens reached"}})
    answers = [rejected, reply(json.dumps(SCRIPT))]

    def post(url, headers, json, timeout):
        bodies.append(json)
        return answers.pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    script = llm.write_script(cfg, "Darth Vader in Ukrainian politics", "x" * 5000, from_wikipedia=True)
    assert script.title == SCRIPT["title"]
    assert bodies[0]["reasoning_effort"] == "low"  # leaves gpt-oss room to finish the JSON
    assert len(bodies) == 2


def test_openai_needs_key(cfg, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(llm.ClaudeError, match="GROQ_API_KEY"):
        llm.write_script(cfg, "t", "notes")


def test_openai_script_shrinks_notes_when_request_too_large(cfg, monkeypatch):
    sizes = []
    answers = [Resp(413, {"error": {"message": "Request too large"}}), reply(json.dumps(SCRIPT))]

    def post(url, headers, json, timeout):
        assert json["max_tokens"] <= 3000
        sizes.append(len(json["messages"][1]["content"]))
        return answers.pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    script = llm.write_script(cfg, "Mount Rushmore", "x" * 50000, from_wikipedia=True)
    assert script.title == SCRIPT["title"]
    assert sizes[1] < sizes[0] - 2000  # second try sent half the notes


def test_split_notes_covers_the_article_in_order():
    notes = "\n".join(f"paragraph {i} " + "x" * 90 for i in range(100))
    chunks = llm.split_notes(notes, 4, 6000)
    assert len(chunks) == 4
    assert chunks[0].startswith("paragraph 0") and "paragraph 99" in chunks[-1]
    assert all(len(c) <= 6000 for c in chunks)
    assert all(c.startswith("paragraph") for c in chunks)  # cut at line breaks


def test_long_script_is_written_chapter_by_chapter(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    cfg = Config(format="long", target_minutes=4, llm=LLMConfig(provider="openai"))
    n = llm.chapter_count(cfg)
    outline = {k: v for k, v in SCRIPT.items() if k != "scenes"}
    outline["chapters"] = [{"heading": f"Part {i}", "angle": "why"} for i in range(1, n + 1)]
    answers = [reply(json.dumps(outline))] + [
        reply(json.dumps({"scenes": [{"narration": f"Chapter {i} line.", "type": "statement", "image": i}]}))
        for i in range(1, n + 1)
    ]
    prompts = []

    def post(url, headers, json, timeout):
        prompts.append(json["messages"][1]["content"])
        assert json["max_tokens"] <= 3000  # each request fits Groq's free per-minute limit
        return answers.pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    notes = "\n".join(f"fact {i} " + "y" * 200 for i in range(200))
    script = llm.write_script(cfg, "Mary", notes, from_wikipedia=True, images="1. a\n2. b")
    assert len(prompts) == n + 1
    assert all(len(p) < 9000 for p in prompts)
    assert [s.narration for s in script.scenes] == [f"Chapter {i} line." for i in range(1, n + 1)]
    assert [(c.title, c.scene) for c in script.chapters] == [(f"Part {i}", i - 1) for i in range(1, n + 1)]
    assert "Chapter 1 line." in prompts[2]  # the next chapter continues from the last one
    assert "Images already used (don't reuse): 1" in prompts[2]
    assert "fact 0 " in prompts[1] and "fact 0 " not in prompts[-1]  # each chapter gets its own part of the notes
    assert "fact 140" in prompts[-1] and "fact 140" not in prompts[1]


def test_falls_back_to_the_next_model_when_one_keeps_failing(cfg, monkeypatch):
    cfg.llm.fallback_models = ["llama-3.3-70b-versatile"]
    models = []

    def post(url, headers, json, timeout):
        models.append(json["model"])
        if json["model"] == cfg.llm.model:
            return Resp(503, {"error": "over capacity"})
        return reply(__import__("json").dumps(SCRIPT))

    monkeypatch.setattr(llm.requests, "post", post)
    script = llm.write_script(cfg, "Mary", "notes")
    assert script.title == SCRIPT["title"]
    assert models[-1] == "llama-3.3-70b-versatile" and models.count(cfg.llm.model) == 8
