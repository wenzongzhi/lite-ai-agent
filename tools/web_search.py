from typing import Protocol

import httpx


class WebSearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> dict: ...


class BraveSearchProvider:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self.client = client

    async def search(self, query: str, max_results: int = 5) -> dict:
        headers = {"X-Subscription-Token": self._api_key, "Accept": "application/json"}
        params = {"q": query, "count": max(1, min(max_results, 20))}
        if self.client is not None:
            response = await self.client.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=15)
        else:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params)
        response.raise_for_status()
        items = response.json().get("web", {}).get("results", [])[:params['count']]
        return {"results": [{"title": str(item.get("title", ""))[:300], "url": str(item.get("url", ""))[:1000],
                             "snippet": str(item.get("description", ""))[:800]} for item in items]}
