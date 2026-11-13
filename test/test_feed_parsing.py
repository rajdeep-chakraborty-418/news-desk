"""fetch_news: RSS/Atom parsing, dates, image choice, article-page (og:image) parsing."""
import support
from support import TestCase

import fetch_news as fn

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Test &amp; headline</title><link>https://example.com/a</link>
<pubDate>Sat, 07 Nov 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
<media:content url="http://img.example.com/a.jpg" medium="image"/></item>
<item><title>Body image</title><link>https://example.com/b</link>
<description>&lt;img src="//img.example.com/b.png" /&gt; text</description></item>
<item><title>Tracking pixel only</title><link>https://example.com/c</link>
<description>&lt;img src="https://x.com/pixel.gif"&gt;</description>
<enclosure url="https://img.example.com/c.jpg" type="image/jpeg"/></item></channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title><link rel="alternate" href="https://example.com/d"/>
<updated>2026-11-07T09:30:00Z</updated><summary>Short summary</summary></entry></feed>"""
MEDIA = '<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>T</title><link>https://t.example/1</link>{}</item></channel></rss>'


class ParseFeedTest(TestCase):
    def test_rss_fields(self):
        a, b, c = fn.parse_feed(RSS)
        self.assertEqual(a["title"], "Test & headline")
        self.assertEqual(a["summary"], "Hello world")                       # html stripped, entities decoded
        self.assertEqual((a["date"].hour, a["date"].year), (10, 2026))
        self.assertEqual(a["link"], "https://example.com/a")

    def test_image_sources_and_cleaning(self):
        a, b, c = fn.parse_feed(RSS)
        self.assertEqual(a["image"], "https://img.example.com/a.jpg")        # http upgraded to https
        self.assertEqual(b["image"], "https://img.example.com/b.png")        # found in the body html, protocol-relative
        self.assertEqual(c["image"], "https://img.example.com/c.jpg")        # tracking pixel skipped, enclosure used

    def test_atom(self):
        d = fn.parse_feed(ATOM)[0]
        self.assertEqual(d["link"], "https://example.com/d")
        self.assertEqual((d["date"].minute, d["title"], d["summary"]), (30, "Atom story", "Short summary"))
        self.assertIsNone(d["image"])

    def test_story_without_date_has_none(self):
        self.assertIsNone(fn.parse_feed(b"<rss><channel><item><title>x</title><link>https://a.example/1</link></item></channel></rss>")[0]["date"])

    def test_publisher_suffix_removed_from_google_news_titles(self):
        xml = (b'<rss><channel><item><title>Ancient city - National Geographic</title><link>https://n.example/1</link>'
               b'<source url="x">National Geographic</source></item></channel></rss>')
        self.assertEqual(fn.parse_feed(xml)[0]["title"], "Ancient city")

    def test_invalid_xml_raises(self):
        with self.assertRaises(Exception):
            fn.parse_feed(b"<html>not a feed")


class ImageChoiceTest(TestCase):
    def img(self, media):
        return fn.parse_feed(MEDIA.format(media).encode())[0]["image"]

    def test_largest_candidate_wins(self):
        got = self.img('<media:content width="140" url="https://i.example/a.jpg?width=140&amp;s=1"/>'
                       '<media:content width="460" url="https://i.example/a.jpg?width=460&amp;s=2"/>')
        self.assertTrue(got.endswith("width=460&s=2"), got)

    def test_bbc_thumbnails_are_upgraded(self):
        got = self.img('<media:thumbnail width="240" height="135" url="https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/ab12/live/x.jpg"/>')
        self.assertEqual(got, "https://ichef.bbci.co.uk/ace/standard/800/cpsprodpb/ab12/live/x.jpg")

    def test_unknown_size_beats_a_known_tiny_one(self):
        got = self.img('<media:content width="100" url="https://x.example/tiny.jpg"/><media:content url="https://x.example/unknown.jpg"/>')
        self.assertTrue(got.endswith("unknown.jpg"))

    def test_bad_images_are_rejected(self):
        for url in ("https://x.example/1x1.gif", "https://x.example/ads/banner.jpg", "https://x.example/tracking.png"):
            self.assertIsNone(self.img(f'<media:content url="{url}"/>'), url)

    def test_helpers(self):
        from xml.etree.ElementTree import Element
        self.assertEqual(fn.guess_width(Element("m"), "https://i.example/a.jpg?width=640"), 640)
        self.assertEqual(fn.guess_width(Element("m", {"width": "300"}), "https://i.example/a.jpg"), 300)
        self.assertIsNone(fn.clean_image(""))
        self.assertEqual(fn.clean_image("//img.example/a.jpg"), "https://img.example/a.jpg")


class OgImageTest(TestCase):
    PAGE = ('<html><head><meta property="og:title" content="t"><meta content="/img/lead.jpg?x=1&amp;y=2" property="og:image">'
            '<meta name="twitter:image" content="https://t.example/other.jpg"></head></html>')

    def test_finds_and_resolves_the_lead_image(self):
        self.assertEqual(fn.og_image(self.PAGE, "https://news.example/a/b"), "https://news.example/img/lead.jpg?x=1&y=2")

    def test_twitter_image_is_a_fallback(self):
        self.assertEqual(fn.og_image('<meta name="twitter:image" content="https://t.example/o.jpg">', "https://n.example/"),
                         "https://t.example/o.jpg")

    def test_no_image(self):
        self.assertIsNone(fn.og_image("<html><head></head></html>", "https://news.example/"))
