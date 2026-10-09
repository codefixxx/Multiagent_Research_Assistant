"""Unit tests for Hacker News developer forum discussions client and evidence integration."""

import httpx
import pytest

from src.tools.evidence_collector import EvidenceCollector
from src.tools.hacker_news import HackerNewsClient, HackerNewsStory
from src.tools.search import MockSearchClient, MultiSearchClient


def test_hn_story_model():
    story = HackerNewsStory(
        story_id="12345",
        title="PostgreSQL vs MySQL Performance in 2026",
        hn_url="https://news.ycombinator.com/item?id=12345",
        points=142,
        num_comments=88,
        comments=[
            "We migrated 50TB and query planner improvements in Postgres were night and day."
        ],
    )
    assert story.story_id == "12345"
    assert story.points == 142
    assert len(story.comments) == 1


def test_strip_html():
    client = HackerNewsClient()
    raw = "<p>This is <i>awesome</i> &amp; &quot;reliable&quot; &#x27;fast&#x27; &gt; 100.</p>"
    clean = client._strip_html(raw)
    assert clean == "This is awesome & \"reliable\" 'fast' > 100."


@pytest.mark.asyncio
async def test_search_discussions_success(monkeypatch):
    class MockSearchResponse:
        status_code = 200

        def json(self):
            return {
                "hits": [
                    {
                        "objectID": "99901",
                        "title": "PostgreSQL 17 Released",
                        "url": "https://postgresql.org/about/news/17",
                        "points": 350,
                        "num_comments": 120,
                        "created_at": "2026-09-01T12:00:00Z",
                    }
                ]
            }

    class MockItemResponse:
        status_code = 200

        def json(self):
            return {
                "children": [
                    {
                        "text": "<p>The logical replication failover slots make high availability much simpler now.</p>"
                    },
                    {
                        "text": "+1"  # Too short, should be filtered out
                    },
                ]
            }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            if "items" in url:
                return MockItemResponse()
            return MockSearchResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = HackerNewsClient()
    stories = await client.search_discussions("PostgreSQL 17", max_results=1)

    assert len(stories) == 1
    assert stories[0].story_id == "99901"
    assert stories[0].title == "PostgreSQL 17 Released"
    assert stories[0].points == 350
    assert len(stories[0].comments) == 1
    assert "logical replication" in stories[0].comments[0]

    md = client.format_for_evidence(stories)
    assert "### Developer Community Insight [1]: PostgreSQL 17 Released" in md
    assert "Hacker News (https://news.ycombinator.com/item?id=99901)" in md
    assert "350 points | 120 comments" in md
    assert "The logical replication failover slots" in md


@pytest.mark.asyncio
async def test_search_discussions_api_error(monkeypatch):
    class MockErrorResponse:
        status_code = 500

        def json(self):
            return {}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return MockErrorResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = HackerNewsClient()
    stories = await client.search_discussions("Error Query")
    assert stories == []


@pytest.mark.asyncio
async def test_evidence_collector_hn_integration():
    class DummyHNClient:
        async def search_discussions(self, query: str):
            return [
                HackerNewsStory(
                    story_id="555",
                    title="Real world microservices failure modes",
                    hn_url="https://news.ycombinator.com/item?id=555",
                    points=200,
                    num_comments=50,
                    comments=[
                        "Cascading timeouts without circuit breakers took down the entire cluster."
                    ],
                )
            ]

        def format_for_evidence(self, stories):
            return "### Developer Community Insight: Cascading timeouts warning"

    collector = EvidenceCollector(
        search_client=MultiSearchClient(mock_client=MockSearchClient()),
        hn_client=DummyHNClient(),
        enable_hacker_news=True,
    )

    result = await collector.collect_evidence_for_queries(
        queries=["microservices failure modes"],
        deep_scrape=False,
    )

    assert result.status.value == "success"
    assert "Real-World Developer Discussions (Hacker News)" in result.formatted_context
    assert "Cascading timeouts warning" in result.formatted_context
