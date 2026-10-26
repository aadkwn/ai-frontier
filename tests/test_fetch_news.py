import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_news import (SOURCES, assemble, canonical_url, clean_text, deduplicate,
                        iso, make_item, parse_date, parse_feed, parse_hf_models)

NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
RSS_SOURCE = SOURCES[0]
ATOM_SOURCE = next(src for src in SOURCES if src['id'] == 'github-vllm')
HF_SOURCE = next(src for src in SOURCES if src['id'] == 'hf-models')


class TestNewsCollector(unittest.TestCase):
    def test_rfc822_and_iso_dates(self):
        self.assertEqual(iso(parse_date('Mon, 26 Oct 2026 07:00:00 GMT')), '2026-10-26T07:00:00Z')
        self.assertEqual(iso(parse_date('2026-10-26T16:00:00+09:00')), '2026-10-26T07:00:00Z')
        self.assertIsNone(parse_date('nonsense'))

    def test_sanitizes_tracking_and_summary_html(self):
        self.assertEqual(canonical_url('https://example.com/post?utm_source=x&id=1#comments'), 'https://example.com/post?id=1')
        self.assertEqual(clean_text('<p>Hello <b>AI</b> <script>bad()</script></p>'), 'Hello AI')

    def test_rss_published_and_missing_date(self):
        xml = b'''<rss version="2.0"><channel>
            <item><title>Official model update</title><link>https://openai.com/news/model</link>
              <pubDate>Mon, 26 Oct 2026 07:00:00 GMT</pubDate><description><![CDATA[<b>Official source</b>]]></description></item>
            <item><title>No real date</title><link>https://openai.com/news/nodate</link></item>
        </channel></rss>'''
        items = parse_feed(xml, RSS_SOURCE, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['summary'], 'Official source')
        self.assertEqual(items[0]['date_type'], 'published')

    def test_atom_updated_is_not_mislabeled_as_published(self):
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>v0.12</title><link rel="alternate" href="https://github.com/vllm-project/vllm/releases/tag/v0.12"/>
          <updated>2026-10-26T07:00:00Z</updated><summary>Changes</summary></entry></feed>'''
        items = parse_feed(atom, ATOM_SOURCE, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['date_type'], 'updated')
        self.assertIn('v0.12', items[0]['title'])

    def test_empty_valid_rss_is_success(self):
        self.assertEqual(parse_feed(b'<rss><channel><title>empty</title></channel></rss>', RSS_SOURCE, NOW), [])

    def test_rejects_unknown_or_future_publication_date(self):
        valid = make_item(title='AI', url='https://example.com/ai', source=RSS_SOURCE,
                          date=NOW, summary='', now=NOW)
        self.assertIsNotNone(valid)
        self.assertIsNone(make_item(title='AI', url='https://example.com/ai', source=RSS_SOURCE,
                          date=NOW + timedelta(days=3), summary='', now=NOW))
        self.assertIsNone(make_item(title='AI', url='https://example.com/ai', source=RSS_SOURCE,
                          date=None, summary='', now=NOW))

    def test_dedup_same_title_and_link(self):
        a = make_item(title='A  new  model', url='https://example.com/a', source=RSS_SOURCE, date=NOW, summary='', now=NOW)
        b = make_item(title='A new model!', url='https://example.com/b', source=RSS_SOURCE, date=NOW, summary='', now=NOW)
        self.assertEqual(len(deduplicate([a, b, a])), 1)

    def test_hf_only_open_license_and_created_date(self):
        import json
        models = [
          {'id': 'foo/model', 'createdAt': '2026-10-26T07:00:00Z', 'tags': ['license:apache-2.0'], 'likes': 17},
          {'id': 'foo/gated', 'createdAt': '2026-10-26T07:00:00Z', 'tags': ['license:mit'], 'gated': True},
          {'id': 'foo/unknown', 'createdAt': '2026-10-26T07:00:00Z', 'tags': ['license:other']}
        ]
        items = parse_hf_models(json.dumps(models).encode(), HF_SOURCE, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['date_type'], 'created')
        self.assertEqual(items[0]['title'], '新模型：foo/model')

    def test_failed_sources_keep_history_and_report_failure(self):
        old = make_item(title='Still valid', url='https://openai.com/post', source=RSS_SOURCE,
                        date=NOW - timedelta(days=1), summary='', now=NOW)
        result = assemble({'items': [old], 'last_success_at': '2026-10-25T08:00:00Z'},
                          {src['id']: RuntimeError('blocked') for src in SOURCES}, NOW)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['last_success_at'], '2026-10-25T08:00:00Z')
        self.assertEqual(len(result['items']), 1)

    def test_partial_source_success(self):
        responses = {src['id']: RuntimeError('fail') for src in SOURCES}
        responses[RSS_SOURCE['id']] = []
        result = assemble({'items': []}, responses, NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['successful_sources'], 1)


if __name__ == '__main__':
    unittest.main()
