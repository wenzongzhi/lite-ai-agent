from memory.search import search_memory


def memory_search(repository, openid: str, query: str) -> dict:
    matches = search_memory(repository, openid, query, limit=5)
    return {"matches": [{**match, "content": match['content'][:400],
                         "truncated": len(match['content']) > 400} for match in matches]}
