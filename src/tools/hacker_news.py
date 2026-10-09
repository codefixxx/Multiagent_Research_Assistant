"""Hacker News Algolia API client for retrieving real-world developer discussions."""

import asyncio
import html
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from src.config import settings
from src.core.logger import logger


class HackerNewsStory(BaseModel):
    """Structured Hacker News discussion thread with community engagement and comments."""

    story_id: str = Field(description="Unique Hacker News item ID.")
    title: str = Field(description="Discussion title.")
    hn_url: str = Field(description="Direct link to Hacker News thread.")
    article_url: str | None = Field(default=None, description="External article URL if linked.")
    points: int = Field(default=0, description="Upvote count.")
    num_comments: int = Field(default=0, description="Total comment count.")
    created_at: str | None = Field(default=None, description="Creation timestamp.")
    comments: list[str] = Field(
        default_factory=list,
        description="Top high-signal developer comments from the thread.",
    )


class HackerNewsClient:
    """Client for the public Hacker News Algolia Search API (https://hn.algolia.com/api/v1)."""

    SEARCH_ENDPOINT = "https://hn.algolia.com/api/v1/search"
    ITEM_ENDPOINT = "https://hn.algolia.com/api/v1/items"

    def __init__(self, timeout: float = 6.0) -> None:
        self.timeout = timeout

    def _strip_html(self, text: str) -> str:
        """Strip HTML tags and unescape common entities from HN comment markup."""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    async def _fetch_story_comments(
        self,
        client: httpx.AsyncClient,
        story_id: str,
        max_comments: int = 3,
    ) -> list[str]:
        """Fetch top parent comments for a specific discussion thread."""
        try:
            res = await client.get(f"{self.ITEM_ENDPOINT}/{story_id}", timeout=self.timeout)
            if res.status_code != 200:
                return []
            data = res.json()
            children = data.get("children", [])
            extracted_comments: list[str] = []
            for child in children:
                raw_text = child.get("text")
                if raw_text:
                    clean = self._strip_html(raw_text)
                    if len(clean) > 20:  # Filter out trivial "thanks" or "+1" comments
                        extracted_comments.append(clean[:400])
                        if len(extracted_comments) >= max_comments:
                            break
            return extracted_comments
        except Exception as e:
            logger.debug("Failed to fetch HN comments", story_id=story_id, error=str(e))
            return []

    async def search_discussions(
        self,
        query: str,
        max_results: int | None = None,
        fetch_comments: bool = True,
    ) -> list[HackerNewsStory]:
        """Search Hacker News stories and retrieve top community insights."""
        limit = max_results or settings.HN_MAX_RESULTS
        params: dict[str, Any] = {
            "query": query,
            "tags": "story",
            "hitsPerPage": limit,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(self.SEARCH_ENDPOINT, params=params)
                if res.status_code != 200:
                    logger.warning(
                        "Hacker News API returned non-200 status",
                        status_code=res.status_code,
                        query=query,
                    )
                    return []

                data = res.json()
                hits = data.get("hits", [])
                if not hits:
                    return []

                stories: list[HackerNewsStory] = []
                comment_tasks = []

                for h in hits:
                    sid = str(h.get("objectID", ""))
                    story = HackerNewsStory(
                        story_id=sid,
                        title=h.get("title", "Untitled Discussion"),
                        hn_url=f"https://news.ycombinator.com/item?id={sid}",
                        article_url=h.get("url"),
                        points=h.get("points") or 0,
                        num_comments=h.get("num_comments") or 0,
                        created_at=h.get("created_at"),
                    )
                    stories.append(story)
                    if fetch_comments and story.num_comments > 0:
                        comment_tasks.append(self._fetch_story_comments(client, sid))
                    else:
                        comment_tasks.append(asyncio.sleep(0, result=[]))

                if comment_tasks:
                    comment_results = await asyncio.gather(*comment_tasks, return_exceptions=True)
                    for story, comments in zip(stories, comment_results, strict=False):
                        if isinstance(comments, list):
                            story.comments = comments

                logger.info(
                    "Hacker News search completed",
                    query=query,
                    stories_found=len(stories),
                )
                return stories

        except httpx.TimeoutException:
            logger.warning("Hacker News API timed out", query=query)
            return []
        except Exception as e:
            logger.warning("Hacker News API query failed", query=query, error=str(e))
            return []

    def format_for_evidence(self, stories: list[HackerNewsStory]) -> str:
        """Format Hacker News stories into clean evidence markdown blocks."""
        if not stories:
            return ""

        sections: list[str] = []
        for i, story in enumerate(stories, 1):
            block = (
                f"### Developer Community Insight [{i}]: {story.title}\n"
                f"- **Community Source:** Hacker News (https://news.ycombinator.com/item?id={story.story_id})\n"
                f"- **Engagement:** {story.points} points | {story.num_comments} comments\n"
            )
            if story.article_url:
                block += f"- **Linked Reference:** {story.article_url}\n"

            if story.comments:
                block += "- **Top Engineering Perspectives / Commentary:**\n"
                for c in story.comments:
                    block += f'  > "{c}"\n'
            else:
                block += "- **Top Engineering Perspectives:** (No top comments recorded)\n"

            sections.append(block)

        return "\n---\n".join(sections)
