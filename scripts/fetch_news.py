#!/usr/bin/env python3
"""AI Frontier: collect verified publication timestamps from public feeds/APIs.

No HTML scraping or LLM-generated news. Data is a static JSON artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

LOG = logging.getLogger("ai-frontier")
UTC = timezone.utc
BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "site" / "data" / "news.json"
USER_AGENT = "AIFrontierBot/1.0 (public-RSS-collector; GitHub Actions)"
MAX_ITEMS_PER_FEED = 30
MAX_AGE_DAYS = {"official": 45, "industry": 30, "papers": 14, "opensource": 30}
CATEGORY_LIMIT = {"official": 80, "industry": 100, "papers": 110, "opensource": 110}
OPEN_LICENSES = {"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "isc", "cc-by-4.0", "cc0-1.0", "unlicense"}

SOURCES = [
    {"id": "openai", "name": "OpenAI", "category": "official", "kind": "rss", "url": "https://openai.com/news/rss.xml"},
    {"id": "deepmind", "name": "Google DeepMind", "category": "official", "kind": "rss", "url": "https://deepmind.google/blog/rss.xml"},
    {"id": "google-ai", "name": "Google AI", "category": "official", "kind": "rss", "url": "https://blog.google/technology/ai/rss/"},
    {"id": "mistral", "name": "Mistral AI", "category": "official", "kind": "rss", "url": "https://mistral.ai/news/rss"},
    {"id": "techcrunch", "name": "TechCrunch AI", "category": "industry", "kind": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"id": "the-verge", "name": "The Verge AI", "category": "industry", "kind": "rss", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"id": "ars-technica", "name": "Ars Technica AI", "category": "industry", "kind": "rss", "url": "https://arstechnica.com/ai/feed/"},
    {"id": "mit-ai", "name": "MIT News AI", "category": "industry", "kind": "rss", "url": "https://news.mit.edu/rss/topic/artificial-intelligence2"},
    {"id": "arxiv-ai", "name": "arXiv · cs.AI", "category": "papers", "kind": "rss", "url": "https://rss.arxiv.org/rss/cs.AI"},
    {"id": "arxiv-lg", "name": "arXiv · cs.LG", "category": "papers", "kind": "rss", "url": "https://rss.arxiv.org/rss/cs.LG"},
    {"id": "arxiv-cv", "name": "arXiv · cs.CV", "category": "papers", "kind": "rss", "url": "https://rss.arxiv.org/rss/cs.CV"},
    {"id": "hf-blog", "name": "Hugging Face Blog", "category": "opensource", "kind": "rss", "url": "https://huggingface.co/blog/feed.xml"},
    {"id": "github-vllm", "name": "GitHub · vLLM", "category": "opensource", "kind": "rss", "url": "https://github.com/vllm-project/vllm/releases.atom"},
    {"id": "github-transformers", "name": "GitHub · Transformers", "category": "opensource", "kind": "rss", "url": "https://github.com/huggingface/transformers/releases.atom"},
    {"id": "github-ollama", "name": "GitHub · Ollama", "category": "opensource", "kind": "rss", "url": "https://github.com/ollama/ollama/releases.atom"},
    {"id": "github-llamacpp", "name": "GitHub · llama.cpp", "category": "opensource", "kind": "rss", "url": "https://github.com/ggml-org/llama.cpp/releases.atom"},
    {"id": "hf-models", "name": "Hugging Face · Models", "category": "opensource", "kind": "hf_models", "url": "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=80"},
]


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def clean_text(value: Any, length: int = 320) -> str:
    extractor = TextExtractor()
    try:
        extractor.feed(str(value or ""))
    except Exception:
        return ""
    value = html.unescape(" ".join(extractor.parts))
    value = re.sub(r"\s+", " ", value).strip()
    return value[: length - 1] + "…" if len(value) > length else value


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    date = None
    text = str(value).strip()
    try:
        date = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if date is None:
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_url(link: str, base: str = "") -> str:
    link = urllib.parse.urljoin(base, html.unescape(str(link or "")).strip())
    p = urllib.parse.urlsplit(link)
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        return ""
    # Tracking parameters do not represent distinct articles.
    params = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
              if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ref", "source"}]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urllib.parse.urlencode(params), ""))


def local(tag: str) -> str:
    return tag.split("}", 1)[-1].split(":")[-1].lower()


def get_child(node: ET.Element, *names: str) -> str:
    names = set(names)
    for child in node:
        if local(child.tag) in names:
            # Element text may contain nested XHTML for Atom content.
            return "".join(child.itertext()).strip()
    return ""


def get_link(node: ET.Element, base_url: str) -> str:
    for child in node:
        if local(child.tag) != "link":
            continue
        rel = child.attrib.get("rel", "alternate")
        if rel in ("alternate", ""):
            return canonical_url(child.attrib.get("href") or (child.text or ""), base_url)
    guid = get_child(node, "guid", "id")
    return canonical_url(guid, base_url) if guid.startswith("http") else ""


def make_item(*, title: str, url: str, source: dict[str, str], date: datetime | None,
              summary: str, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if date is None or not url or not title:
        return None  # Never pretend that fetch/first-seen time is publication time.
    age = now - date
    if age > timedelta(days=MAX_AGE_DAYS[source["category"]]) or age < -timedelta(hours=24):
        return None
    result: dict[str, Any] = {
        "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:20],
        "title": clean_text(title, 220), "url": url,
        "source": source["name"], "source_id": source["id"],
        "category": source["category"], "published_at": iso(date),
        "summary": clean_text(summary, 280),
    }
    if extra:
        result.update(extra)
    return result


def parse_feed(raw: bytes, source: dict[str, str], now: datetime) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    nodes = [node for node in root.iter() if local(node.tag) in ("item", "entry")]
    if not nodes:
        # arXiv and other publishers may have a valid but empty feed on holidays.
        if local(root.tag) in ("rss", "rdf", "feed") or "rdf-syntax-ns" in root.tag:
            return []
        raise ValueError("不是有效的 RSS/Atom 文档")
    articles = []
    for node in nodes[: MAX_ITEMS_PER_FEED * 2]:
        title = get_child(node, "title")
        url = get_link(node, source["url"])
        date = None
        # Prefer original publication date over the updated timestamp.
        date_type = "published"
        for name in ("published", "pubdate", "date", "issued", "updated"):
            value = get_child(node, name)
            date = parse_date(value)
            if date is not None:
                if name == "updated":
                    date_type = "updated"
                break
        summary = get_child(node, "summary", "description", "subtitle", "content", "encoded")
        article = make_item(title=title, url=url, source=source, date=date, summary=summary, now=now,
                            extra={"date_type": date_type})
        if article:
            articles.append(article)
    return articles[:MAX_ITEMS_PER_FEED]


def parse_hf_models(raw: bytes, source: dict[str, str], now: datetime) -> list[dict[str, Any]]:
    models = json.loads(raw)
    if not isinstance(models, list):
        raise ValueError("Hugging Face API 返回格式不正确")
    articles = []
    for model in models:
        if not isinstance(model, dict) or model.get("private") or model.get("gated"):
            continue
        model_id = model.get("id") or model.get("modelId")
        tags = model.get("tags") or []
        licenses = [t.removeprefix("license:") for t in tags if isinstance(t, str) and t.startswith("license:")]
        matching = sorted(OPEN_LICENSES.intersection(licenses))
        if not model_id or not matching:
            continue
        date = parse_date(model.get("createdAt"))  # Never use lastModified as publish date.
        url = canonical_url("https://huggingface.co/" + urllib.parse.quote(model_id, safe="/"))
        summary = f"新模型仓库 · 许可证：{matching[0]} · 喜欢数：{model.get('likes', 0)}"
        article = make_item(title=f"新模型：{model_id}", url=url, source=source, date=date,
                            summary=summary, now=now, extra={"item_type": "model", "date_type": "created"})
        if article:
            articles.append(article)
    return articles[:20]


def download(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml;q=0.9"}
    last_exc = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=16) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = response.read(4_000_001)
                if len(payload) > 4_000_000:
                    raise ValueError("响应过大")
                return payload
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(0.6)
    raise RuntimeError(str(last_exc))


def fetch_source(source: dict[str, str], now: datetime) -> list[dict[str, Any]]:
    raw = download(source["url"])
    return parse_hf_models(raw, source, now) if source["kind"] == "hf_models" else parse_feed(raw, source, now)


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: set[str] = set()
    by_title: set[tuple[str, str]] = set()
    out = []
    for item in sorted(items, key=lambda item: item.get("published_at", ""), reverse=True):
        fingerprint = (item["category"], re.sub(r"\W+", "", item["title"].casefold()))
        if item["id"] in by_id or fingerprint in by_title:
            continue
        by_id.add(item["id"])
        by_title.add(fingerprint)
        out.append(item)
    return out


def load_previous(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"items": []}


def assemble(previous: dict[str, Any], responses: dict[str, list[dict[str, Any]] | Exception],
             now: datetime) -> dict[str, Any]:
    previous_items = previous.get("items", [])
    healthy_items = []
    sources = []
    good_count = 0
    for source in SOURCES:
        value = responses.get(source["id"], RuntimeError("未执行"))
        success = not isinstance(value, Exception)
        if success:
            healthy_items.extend(value)
            good_count += 1
        sources.append({
            "id": source["id"], "name": source["name"], "category": source["category"],
            "url": source["url"], "ok": success,
            "count": len(value) if success else 0,
            "message": "正常" if success else clean_text(str(value), 100) or "采集失败",
        })
    # Keep previously fetched articles, including on partial/total source failure.
    pool = list(healthy_items)
    for old in previous_items:
        if not isinstance(old, dict):
            continue
        category = old.get("category")
        date = parse_date(old.get("published_at"))
        if category not in MAX_AGE_DAYS or date is None:
            continue
        if now - timedelta(days=MAX_AGE_DAYS[category]) <= date <= now + timedelta(hours=24):
            if old.get("url") and old.get("id") and old.get("title"):
                pool.append(old)
    merged = deduplicate(pool)
    limits = {key: 0 for key in CATEGORY_LIMIT}
    keep = []
    for item in merged:
        cat = item["category"]
        if limits[cat] < CATEGORY_LIMIT[cat]:
            keep.append(item)
            limits[cat] += 1
    state = "ok" if good_count == len(SOURCES) else ("partial" if good_count else "error")
    return {
        "schema_version": 1,
        "last_attempt_at": iso(now),
        "last_success_at": iso(now) if good_count else previous.get("last_success_at"),
        "status": state,
        "successful_sources": good_count,
        "total_sources": len(SOURCES),
        "items": keep,
        "sources": sources,
    }


def run(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    now = datetime.now(UTC)
    previous = load_previous(output)
    responses: dict[str, list[dict[str, Any]] | Exception] = {}
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {executor.submit(fetch_source, source, now): source for source in SOURCES}
        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                responses[source["id"]] = result
                LOG.info("OK %-21s  %d items", source["name"], len(result))
            except Exception as exc:
                responses[source["id"]] = exc
                LOG.warning("FAIL %-21s %s", source["name"], exc)
    result = assemble(previous, responses, now)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write protects against partial/corrupt files on interrupted runs.
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    LOG.info("state=%s items=%d sources=%d/%d", result["status"], len(result["items"]),
             result["successful_sources"], result["total_sources"])
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Fetch AI Frontier public news sources")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()
    data = run(args.output)
    # Initial collection with all sources failing is a setup failure.
    if not data["successful_sources"] and not data["items"]:
        raise SystemExit("采集失败：所有来源不可用且没有历史缓存")


if __name__ == "__main__":
    main()
