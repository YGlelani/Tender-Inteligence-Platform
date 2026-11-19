"""
Word-level checks used to route chat messages.

Messages are compared word by word, not as substrings, so "profile" no longer
counts as "file". Small typos in key words are corrected ("bussiness" -> "business").
"""
import difflib
import re

MATCH_WORDS = {"match", "matches", "matching", "suit", "suits", "suitable", "recommend", "recommended", "relevant"}
SELF_WORDS = {"my", "me", "our", "us", "mine"}
PROFILE_WORDS = {"profile", "business", "company"}
DOCUMENT_WORDS = {"document", "documents", "attachment", "attachments", "file", "files", "pdf"}
_KEY_WORDS = sorted(MATCH_WORDS | PROFILE_WORDS | DOCUMENT_WORDS)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
# Only words at least this long are typo-corrected; short words such as "pdf" must be exact.
_MIN_TYPO_LENGTH = 5


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def corrected(word: str) -> str:
    """The key word a misspelt word was probably meant to be, or the word unchanged."""
    if word in _KEY_WORDS or len(word) < _MIN_TYPO_LENGTH:
        return word
    close = difflib.get_close_matches(word, _KEY_WORDS, n=1, cutoff=0.8)
    return close[0] if close else word


def has_any(text: str, vocabulary: set[str]) -> bool:
    return any(corrected(word) in vocabulary for word in words(text))


def is_personal(text: str) -> bool:
    """True when the message is about the user ("my", "our", ...), so its answer must not be shared."""
    return any(word in SELF_WORDS for word in words(text))


def wants_matches(text: str) -> bool:
    """True for "5 tenders that match my business profile", "which tenders suit us", "show my matches".

    A correctly spelt match word needs any mention of the user or their business.
    A corrected typo ("march") must be followed directly by "my", "our", "me" or "us",
    so "tenders closing in March for my company" is still treated as a search.
    """
    original = words(text)
    fixed = [corrected(word) for word in original]
    mentions_user = any(word in SELF_WORDS | PROFILE_WORDS for word in fixed)
    for index, (raw, word) in enumerate(zip(original, fixed)):
        if word not in MATCH_WORDS:
            continue
        if raw == word and mentions_user:
            return True
        if index + 1 < len(fixed) and fixed[index + 1] in SELF_WORDS:
            return True
    return False


# Messages that only make sense with the earlier turns: "what about Limpopo?",
# "show the documents for the first one", "tell me more about that tender".
_CONTINUES = re.compile(r"^\s*(?:and|also|what\s+about|how\s+about)\b", re.IGNORECASE)
_REFERS_BACK = re.compile(
    r"\b(?:they|them|those|these|previous|the\s+above|same|instead|which\s+ones?)\b"
    r"|\b(?:that|this)\s+(?:one|tender|tenders|bid|list|document|documents)\b"
    r"|\b(?:about|for|of|on|does|is|was|with)\s+(?:that|this)\b"
    r"|\b(?:that|this)\s*[?.!]*\s*$"
    r"|\b(?:first|second|third|fourth|fifth|last|next|other)\s+(?:one|tender|bid)\b"
    r"|\b(?:number|option)\s*\d{1,2}\b(?![/-])"
    r"|\bmore\s+(?:about|details?|info|information|on)\b|\btell\s+me\s+more\b",
    re.IGNORECASE,
)
# Case-sensitive, so "IT tenders" is still a new request.
_IT = re.compile(r"\b[Ii]ts?\b")


def is_follow_up(text: str) -> bool:
    """True when the message refers back to the conversation instead of asking something new."""
    return bool(_CONTINUES.search(text) or _REFERS_BACK.search(text) or _IT.search(text))


def requested_count(text: str, default: int = 5, maximum: int = 10) -> int:
    """How many results the user asked for ("5 tenders", "five tenders"), within 1..maximum."""
    for word in words(text):
        number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        if number and 1 <= number <= 50:
            return min(number, maximum)
    return default
