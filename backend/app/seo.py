import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "to", "of", "in", "on", "for", "with", "at", "by",
    "from", "up", "about", "into", "over", "after", "i", "you", "he", "she",
    "it", "we", "they", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "me", "him", "them", "us", "so",
    "just", "like", "not", "do", "does", "did", "have", "has", "had", "as",
    "if", "then", "than", "there", "here", "what", "when", "where", "who",
    "how", "which", "will", "would", "can", "could", "should", "im", "its",
    "yeah", "okay", "ok", "um", "uh", "gonna", "know", "get", "got", "really",
}

EVERGREEN_TAGS = {
    "instagram": ["reels", "reelsinstagram", "viral", "trending", "explore", "fyp"],
    "youtube": ["shorts", "youtubeshorts", "viral", "trending"],
    "tiktok": ["fyp", "foryoupage", "viral", "trending", "tiktok"],
}

HOOK_TEMPLATES = [
    "You Won't Believe What Happened Next — {kw}",
    "This {kw} Moment Went Viral for a Reason",
    "Wait For It... {kw}",
    "Nobody Talks About This {kw} Truth",
    "The {kw} Clip Everyone's Sharing",
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def extract_keywords(text: str, top_n: int = 6) -> list[str]:
    words = [w for w in _tokenize(text) if w not in STOPWORDS and len(w) > 2]
    counts = Counter(words)
    return [w for w, _ in counts.most_common(top_n)]


def generate_titles(text: str, keywords: list[str]) -> list[str]:
    if not keywords:
        keywords = ["This"]
    titles = []
    for i, template in enumerate(HOOK_TEMPLATES[:3]):
        kw = keywords[i % len(keywords)].capitalize()
        titles.append(template.format(kw=kw))
    return titles


def generate_hashtags(keywords: list[str], platform: str) -> list[str]:
    platform = platform.lower()
    base = EVERGREEN_TAGS.get(platform, EVERGREEN_TAGS["instagram"])
    keyword_tags = [re.sub(r"[^a-z0-9]", "", k.lower()) for k in keywords]
    keyword_tags = [t for t in keyword_tags if t]
    combined = list(dict.fromkeys(keyword_tags + base))
    return [f"#{tag}" for tag in combined[:12]]


def generate_description(text: str, keywords: list[str], hashtags: list[str]) -> str:
    snippet = text.strip()
    if len(snippet) > 160:
        snippet = snippet[:157].rsplit(" ", 1)[0] + "..."
    tag_line = " ".join(hashtags[:8])
    return f"{snippet}\n\n{tag_line}"


def generate_seo(text: str) -> dict:
    keywords = extract_keywords(text)
    titles = generate_titles(text, keywords)
    hashtags = {
        "instagram": generate_hashtags(keywords, "instagram"),
        "youtube": generate_hashtags(keywords, "youtube"),
        "tiktok": generate_hashtags(keywords, "tiktok"),
    }
    description = generate_description(text, keywords, hashtags["instagram"])
    return {
        "keywords": keywords,
        "titles": titles,
        "hashtags": hashtags,
        "description": description,
    }
