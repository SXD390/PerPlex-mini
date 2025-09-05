import re

def keyword_score(q: str, md: str) -> float:
    q_words = {w for w in re.findall(r"\w+", q.lower()) if len(w) > 2}
    d_words = re.findall(r"\w+", md.lower())
    if not q_words or not d_words:
        return 0.0
    hits = sum(1 for w in d_words if w in q_words)
    return hits / max(1, len(d_words))
