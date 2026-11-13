"""Conservative vocabulary aliases; never infer equipment or access scope."""
import re
import unicodedata


def normalize(question: str) -> str:
    text = unicodedata.normalize('NFKC', question).strip()
    replacements = [
        (r'wall\s*loss(?:\s*(?:percent|percentage))?|두께\s*감소율|감육\s*율|감육\s*률', '감육률'),
        (r'최소\s*두께|최소\s*잔존\s*두께|minimum\s+(?:wall\s+)?thickness', '최소두께'),
        (r'튜브|전열관|\btubes?\b', 'Tube'),
        (r'퍼센트|프로|percent', '%'),
        (r'크거나\s*같은|이거나\s*큰', '이상'),
        (r'작거나\s*같은|이거나\s*작은', '이하'),
        (r'보다\s*큰|넘는', '초과'),
        (r'보다\s*작은', '미만'),
        (r'종합\s*현황|검사\s*현황|검사\s*결과\s*정리|summary', '요약'),
        (r'감육(?:률)?이?\s*(?:제일|가장)\s*(?:큰|높은|심한)', '감육이 가장 심한'),
        (r'\btop\s*(\d+)', r'상위 \1개'),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r'(감육률\s*\d+(?:\.\d+)?)\s*%?\s*(이상|초과|이하|미만)', r'\1% \2', text)
    return re.sub(r'\s+', ' ', text).strip()
