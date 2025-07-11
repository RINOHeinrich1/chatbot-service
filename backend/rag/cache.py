import json
_cache = {}


def get_cache(query, docs):
    key = (query, json.dumps(docs, sort_keys=True))
    return _cache.get(key)

def set_cache(query, docs, result):
    key = (query, json.dumps(docs, sort_keys=True))
    _cache[key] = result