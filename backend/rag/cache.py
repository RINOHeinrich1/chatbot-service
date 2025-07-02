_cache = {}

def get_cache(query, docs):
    return _cache.get((query, tuple(docs)))

def set_cache(query, docs, answer):
    _cache[(query, tuple(docs))] = answer
