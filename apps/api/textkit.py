"""Script- and stop-word-based language identification.

Deterministic and dependency-free on purpose. Two callers need the same
answer and neither can afford a model call: the abstain renderer, which has
to name a target language before it can ask for a translation (C3 — the
vague "the language of their question" instruction came back in Turkish for
English *and* Spanish questions), and the acceptance scorer, which scores a
reply's language.

Non-Latin scripts are decided by the script itself, which is unambiguous:
Japanese is the only one of these languages that mixes kana with Han. Latin
script — most of the acceptance set — is separated by a small stop-word
table, longest-distinctive-markers first, with English as both the default
and the tie-break because every fixed template is already written in it.

The table is intentionally small and English-leaning. A wrong answer costs
one extra translation call at worst; the alternative (a heavyweight
detector) buys precision nobody needs on a one-line question.
"""

import re
import unicodedata

DEFAULT_LANGUAGE = "en"

# Ordered: the first marker found in a character's Unicode name wins, so the
# kana markers must precede the Han one they overlap with.
_SCRIPT_MARKERS: tuple[tuple[str, str], ...] = (
    ("HIRAGANA", "ja"),
    ("KATAKANA", "ja"),
    ("HANGUL", "ko"),
    ("CJK", "zh"),
    ("CYRILLIC", "ru"),
    ("GREEK", "el"),
    ("ARABIC", "ar"),
    ("HEBREW", "he"),
    ("THAI", "th"),
    ("DEVANAGARI", "hi"),
    ("LATIN", "latin"),
)

_LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "zh": "Chinese",
}

# English is first and the argmax keeps an earlier entry on a tie, so a
# language must out-score English outright to win.
_LATIN_STOP_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "a",
            "about",
            "after",
            "all",
            "also",
            "an",
            "and",
            "answer",
            "any",
            "are",
            "as",
            "at",
            "be",
            "because",
            "been",
            "before",
            "being",
            "between",
            "both",
            "but",
            "by",
            "can",
            "could",
            "did",
            "do",
            "does",
            "doing",
            "find",
            "for",
            "from",
            "get",
            "give",
            "go",
            "had",
            "has",
            "have",
            "he",
            "hello",
            "help",
            "her",
            "hey",
            "hi",
            "here",
            "hers",
            "him",
            "his",
            "how",
            "i",
            "if",
            "in",
            "into",
            "is",
            "it",
            "its",
            "just",
            "know",
            "like",
            "many",
            "may",
            "me",
            "might",
            "more",
            "most",
            "much",
            "must",
            "my",
            "name",
            "no",
            "not",
            "now",
            "of",
            "on",
            "one",
            "only",
            "or",
            "other",
            "our",
            "out",
            "over",
            "own",
            "please",
            "say",
            "shall",
            "she",
            "should",
            "so",
            "some",
            "such",
            "tell",
            "thank",
            "thanks",
            "than",
            "that",
            "the",
            "their",
            "them",
            "then",
            "there",
            "these",
            "they",
            "this",
            "those",
            "three",
            "through",
            "to",
            "too",
            "two",
            "under",
            "up",
            "us",
            "very",
            "was",
            "we",
            "were",
            "what",
            "when",
            "where",
            "which",
            "while",
            "who",
            "whom",
            "whose",
            "why",
            "will",
            "with",
            "would",
            "yes",
            "you",
            "your",
        }
    ),
    "es": frozenset(
        {
            "al",
            "algo",
            "alguno",
            "ante",
            "antes",
            "aquel",
            "aquí",
            "así",
            "cada",
            "como",
            "cómo",
            "con",
            "contra",
            "cual",
            "cuál",
            "cuando",
            "cuándo",
            "de",
            "del",
            "desde",
            "dice",
            "donde",
            "dónde",
            "dos",
            "el",
            "él",
            "ella",
            "ellos",
            "en",
            "entre",
            "es",
            "esa",
            "ese",
            "eso",
            "esta",
            "está",
            "están",
            "este",
            "esto",
            "fue",
            "han",
            "hasta",
            "hay",
            "la",
            "las",
            "le",
            "les",
            "lo",
            "los",
            "más",
            "me",
            "mi",
            "mucho",
            "muy",
            "nada",
            "ni",
            "no",
            "nos",
            "o",
            "otro",
            "para",
            "pero",
            "poco",
            "por",
            "porque",
            "que",
            "qué",
            "quien",
            "quién",
            "se",
            "sea",
            "ser",
            "sin",
            "sobre",
            "son",
            "su",
            "sus",
            "también",
            "tanto",
            "tiene",
            "todavía",
            "todo",
            "todos",
            "tu",
            "un",
            "una",
            "uno",
            "y",
            "ya",
        }
    ),
    "fr": frozenset(
        {
            "au",
            "aux",
            "avec",
            "ce",
            "ces",
            "cet",
            "cette",
            "comment",
            "dans",
            "des",
            "deux",
            "du",
            "elle",
            "elles",
            "en",
            "encore",
            "est",
            "et",
            "été",
            "être",
            "fait",
            "ici",
            "il",
            "ils",
            "je",
            "la",
            "le",
            "les",
            "leur",
            "lui",
            "ma",
            "mais",
            "me",
            "même",
            "mes",
            "moins",
            "mon",
            "ne",
            "nos",
            "notre",
            "nous",
            "on",
            "ont",
            "ou",
            "où",
            "par",
            "parce",
            "pas",
            "peut",
            "plus",
            "pour",
            "pourquoi",
            "quand",
            "que",
            "quel",
            "quelle",
            "qui",
            "quoi",
            "sa",
            "sans",
            "se",
            "ses",
            "son",
            "sont",
            "sous",
            "sur",
            "ta",
            "te",
            "tes",
            "toi",
            "ton",
            "tous",
            "tout",
            "très",
            "tu",
            "un",
            "une",
            "vos",
            "votre",
            "vous",
            "y",
        }
    ),
    "de": frozenset(
        {
            "aber",
            "alle",
            "als",
            "also",
            "am",
            "an",
            "auch",
            "auf",
            "aus",
            "bei",
            "bin",
            "bis",
            "bist",
            "da",
            "das",
            "dass",
            "dem",
            "den",
            "der",
            "des",
            "deutsch",
            "die",
            "dies",
            "doch",
            "dort",
            "du",
            "ein",
            "eine",
            "einem",
            "einen",
            "einer",
            "eines",
            "er",
            "es",
            "euer",
            "eure",
            "für",
            "hat",
            "hatte",
            "hier",
            "ihr",
            "im",
            "in",
            "ist",
            "ja",
            "jede",
            "jetzt",
            "kann",
            "kein",
            "können",
            "man",
            "mehr",
            "mein",
            "mit",
            "nach",
            "nicht",
            "noch",
            "nur",
            "oder",
            "ohne",
            "sein",
            "seine",
            "sich",
            "sie",
            "sind",
            "so",
            "über",
            "um",
            "und",
            "uns",
            "unser",
            "vom",
            "von",
            "vor",
            "war",
            "waren",
            "was",
            "weg",
            "weil",
            "welche",
            "welcher",
            "wenn",
            "wer",
            "werden",
            "wie",
            "wieder",
            "will",
            "wir",
            "wird",
            "wo",
            "wurde",
            "zu",
            "zum",
            "zur",
        }
    ),
    # Italian overlaps English on short function words ("a", "in", "no"), so
    # the table leans on content and longer words to out-score English
    # outright — a tie is not enough.
    "it": frozenset(
        {
            "adesso",
            "agli",
            "alla",
            "alle",
            "allo",
            "anche",
            "ancora",
            "cavallo",
            "chiama",
            "chiamato",
            "come",
            "con",
            "cosa",
            "cui",
            "degli",
            "dei",
            "della",
            "delle",
            "dove",
            "già",
            "gli",
            "hanno",
            "libri",
            "libro",
            "mentre",
            "molto",
            "muore",
            "muoiono",
            "nella",
            "oppure",
            "perché",
            "percio",
            "perciò",
            "prima",
            "può",
            "quale",
            "quando",
            "quello",
            "questa",
            "questo",
            "quindi",
            "sono",
            "sulla",
            "sul",
            "tutto",
            "tutti",
            "vive",
            "vissero",
            "vivono",
        }
    ),
    "pt": frozenset(
        {
            "a",
            "ao",
            "aos",
            "as",
            "com",
            "como",
            "da",
            "das",
            "de",
            "do",
            "dos",
            "e",
            "é",
            "ela",
            "ele",
            "eles",
            "em",
            "entre",
            "essa",
            "esse",
            "esta",
            "está",
            "este",
            "eu",
            "foi",
            "há",
            "isso",
            "isto",
            "já",
            "lhe",
            "mais",
            "mas",
            "me",
            "mesmo",
            "meu",
            "muito",
            "na",
            "não",
            "nas",
            "nem",
            "no",
            "nos",
            "nós",
            "num",
            "numa",
            "o",
            "os",
            "ou",
            "para",
            "pela",
            "pelo",
            "por",
            "porque",
            "qual",
            "quando",
            "que",
            "quem",
            "se",
            "sem",
            "ser",
            "seu",
            "seus",
            "só",
            "sob",
            "sobre",
            "sua",
            "suas",
            "também",
            "te",
            "tem",
            "ter",
            "tu",
            "um",
            "uma",
            "você",
        }
    ),
    "nl": frozenset(
        {
            "aan",
            "al",
            "als",
            "altijd",
            "ben",
            "bij",
            "daar",
            "dan",
            "dat",
            "de",
            "deze",
            "die",
            "dit",
            "doch",
            "doen",
            "door",
            "dus",
            "een",
            "eens",
            "en",
            "er",
            "geen",
            "geweest",
            "haar",
            "had",
            "heb",
            "heeft",
            "het",
            "hij",
            "hoe",
            "ik",
            "in",
            "is",
            "je",
            "kan",
            "kon",
            "kunnen",
            "maar",
            "me",
            "meer",
            "men",
            "met",
            "mij",
            "mijn",
            "moet",
            "na",
            "naar",
            "niet",
            "niets",
            "nog",
            "nu",
            "of",
            "om",
            "ons",
            "ook",
            "op",
            "over",
            "te",
            "tot",
            "uit",
            "van",
            "veel",
            "voor",
            "want",
            "waren",
            "was",
            "wat",
            "we",
            "wel",
            "werd",
            "wezen",
            "wie",
            "wij",
            "wil",
            "worden",
            "wordt",
            "zal",
            "ze",
            "zij",
            "zijn",
            "zo",
            "zonder",
            "zou",
        }
    ),
    "pl": frozenset(
        {
            "albo",
            "ale",
            "być",
            "był",
            "była",
            "było",
            "były",
            "chce",
            "choć",
            "co",
            "coś",
            "czy",
            "dla",
            "do",
            "gdy",
            "gdzie",
            "go",
            "i",
            "ich",
            "ile",
            "im",
            "inne",
            "iż",
            "ja",
            "jak",
            "jaki",
            "jakie",
            "jako",
            "je",
            "jest",
            "jeszcze",
            "już",
            "kiedy",
            "kto",
            "która",
            "które",
            "który",
            "lub",
            "ma",
            "mają",
            "mi",
            "mnie",
            "mogą",
            "może",
            "można",
            "mu",
            "my",
            "na",
            "nad",
            "nam",
            "nas",
            "nasz",
            "nawet",
            "nic",
            "nich",
            "nie",
            "nigdy",
            "nim",
            "o",
            "od",
            "oraz",
            "po",
            "pod",
            "podczas",
            "przed",
            "przez",
            "przy",
            "raz",
            "również",
            "sam",
            "się",
            "są",
            "ta",
            "tak",
            "także",
            "te",
            "tego",
            "tej",
            "ten",
            "teraz",
            "też",
            "to",
            "trzeba",
            "tu",
            "tutaj",
            "ty",
            "tych",
            "tylko",
            "tym",
            "w",
            "we",
            "więc",
            "wszystko",
            "z",
            "za",
            "ze",
            "że",
            "żeby",
        }
    ),
    "tr": frozenset(
        {
            "acaba",
            "ancak",
            "artık",
            "aslında",
            "az",
            "belki",
            "ben",
            "bile",
            "bir",
            "biraz",
            "birçok",
            "bu",
            "böyle",
            "da",
            "daha",
            "de",
            "defa",
            "diye",
            "en",
            "gibi",
            "hem",
            "hep",
            "hepsi",
            "her",
            "hiç",
            "için",
            "ile",
            "ise",
            "kez",
            "ki",
            "kim",
            "mı",
            "mi",
            "mu",
            "mü",
            "nasıl",
            "ne",
            "neden",
            "nerde",
            "nerede",
            "niçin",
            "o",
            "olan",
            "olarak",
            "oldu",
            "olmak",
            "olsun",
            "onu",
            "pek",
            "rağmen",
            "sadece",
            "sen",
            "siz",
            "sonra",
            "şey",
            "şu",
            "tüm",
            "ve",
            "veya",
            "ya",
            "yani",
            "yoksa",
        }
    ),
    "tl": frozenset(
        {
            "akin",
            "akinin",
            "ang",
            "ano",
            "ay",
            "batay",
            "bakit",
            "bawat",
            "hindi",
            "hanggang",
            "iba",
            "ibaba",
            "ibabaw",
            "ikaw",
            "inyo",
            "isa",
            "isinulat",
            "ito",
            "iyan",
            "iyon",
            "ka",
            "kanila",
            "kanilang",
            "kailan",
            "kapag",
            "katiyakan",
            "kung",
            "mga",
            "mismo",
            "may",
            "mayroon",
            "mula",
            "na",
            "naging",
            "namin",
            "nang",
            "ng",
            "ni",
            "nila",
            "nito",
            "niya",
            "paano",
            "pag",
            "pagkatapos",
            "pala",
            "para",
            "pareho",
            "pero",
            "rin",
            "sa",
            "saan",
            "sakin",
            "sila",
            "sino",
            "siya",
            "tayo",
            "tulad",
            "una",
            "upang",
            "yung",
        }
    ),
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Markers that belong to exactly one of the Latin-script languages above
# (KI-33). A stop word alone is weak evidence on a short question: "tu" is in
# the es, fr, pt and pl tables alike and "il" in the fr table alone, so a
# question like "Peux-tu résumer Madame Bovary ?" or "Chi è il conte di
# montecristo?" produced a four-way (or one-way, wrong) tie that `max()`
# then resolved by dict order — `es` first, so French read as Spanish.
#
# These are the characters and function words that do not occur in ordinary
# text of the other languages in the table, so a hit is decisive. They are
# matched as substrings of the lower-cased text, which is what lets an
# inflected form ("résumer", "verwandelt") count without listing every ending.
# A language that wins on stop words alone has to clear the margin rule in
# `detect_language` instead, so a missing marker costs precision, never
# correctness.
_DISTINCTIVE: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "what", "who", "how", "why", "which", "whose", "whom",
        "summarize", "summarise", "explain", "describe", "tell me",
        "chapter", "according to", "how many", "does the",
    ),
    "es": (
        "ñ", "¿", "¡", "cómo", "qué", "quién", "cuál", "cuándo", "dónde",
        "porque", "pero", "también", "está", "están", "hay", "muy",
        "cuántos", "cuántas", "dime", "explica", "libro", "mujer", "hombre",
        "capítulo", "cuenta", "historia",
    ),
    "fr": (
        "ç", "œ", "ë", "ï", "û", "ê", "â", "peux", "peut", "pourquoi",
        "quelle", "quel", "où", "très", "même", "être", "résum", "aussi",
        "nous", "vous", "elle", "leurs", "parce", "aujourd", "toujours",
        "après", "avant", "chaque", "premier", "livre", "conte", "réponse",
        "combien", "aujourd'hui",
    ),
    "de": (
        "ß", "ä", "ö", "ü", "warum", "welche", "welcher", "welches",
        "zusammen", "erkläre", "kapitel", "zwischen", "wurde", "wurden",
        "einen", "einem", "seine", "ihrer", "gibt", "heißen", "geschichte",
        "buch", "antwort", "dass", "doch", "über", "sowie", "durch",
        "mehr", "eines", "einer",
    ),
    "it": (
        "chi", "cosa", "quale", "sono", "perché", "perche", "dov'è", "dove",
        "quando", "anche", "molto", "però", "della", "delle", "nel", "gli",
        "questo", "questa", "racconta", "risposta", "libro", "uomo",
        "donna", "quanti", "quante", "conte", "storia", "personaggio",
    ),
    "pt": (
        "ã", "õ", "quem", "escreveu", "porque", "qual", "quando", "onde",
        "resuma", "explique", "livro", "mulher", "homem", "também",
        "muito", "porém", "está", "estão", "não", "são", "foi", "pelo",
        "nossa", "nosso", "capítulo", "história", "obrigado", "obrigada",
    ),
    "nl": (
        "waarom", "samenvatten", "uitleg", "boek", "waarin", "zijn",
        "wordt", "heeft", "waar", "welke", "vrouw", "dame", "vertelt",
        "hoofdstuk", "antwoord", "verhaal", "personage", "waarvan",
    ),
    "pl": (
        "ą", "ę", "ł", "ź", "ż", "który", "która", "które", "jaki", "jakie",
        "dlaczego", "podsumuj", "wyjaśnij", "książka", "kto", "ile",
        "pani", "oraz", "przez", "między", "był", "była", "było", "się",
        "jest", "że", "także", "wszystkich", "każdy", "pierwszy",
        "historia", "postać", "odpowiedź", "rozdział", "czy", "więc",
        "jednak", "gdyż", "również",
    ),
    "tr": (
        "ı", "ğ", "ş", "nedir", "ne", "nasıl", "neden", "hangi",
        "özetle", "açıkla", "kitap", "kaç", "bay", "değil", "için",
        "hakkında", "göre", "var", "olan", "bölüm", "karakter", "cevap",
        "anlat", "şey", "daha", "çok", "kadar", "sonra", "önce",
    ),
    "tl": (
        "sino", "ano", "paano", "bakit", "alin", "buod", "ipaliwanag",
        "aklat", "ilan", "kung", "mga", "ang", "ay", "ito", "iyon",
        "hindi", "para", "may", "wala", "nang", "sapat", "bawat", "isa",
        "dalawa", "tatlo", "bansa", "tauhan", "kabanata", "sagot",
        "kuldang", "mismo", "natin", "ninyo", "kanila",
    ),
}

# A marker is worth this many stop words. It has to be more than 1, or a
# single shared word ("tu", "il") can outvote a language-exclusive hit on a
# short question; it is deliberately not so large that one marker outranks a
# long, clearly non-English sentence.
_MARKER_WEIGHT = 3

# A language must lead the runner-up by at least this much to be returned at
# all. An exact tie is a tie, and is undetectable rather than a guess.
_TIE_MARGIN = 1


def _script_of(char: str) -> str | None:
    """The script bucket for one character, or None if it has no name."""
    try:
        name = unicodedata.name(char)
    except ValueError:
        return None
    for marker, script in _SCRIPT_MARKERS:
        if marker in name:
            return script
    return None


def _dominant_script(text: str) -> str | None:
    """The non-Latin script covering most of the letters, if any.

    Majority rather than presence: an English answer may quote a Chinese book
    title, and the reverse, so one stray quoted run must not flip the answer.
    """
    counts = _script_counts(text)
    total = sum(counts.values())
    non_latin = {s: n for s, n in counts.items() if s != "latin"}
    if not total or not non_latin:
        return None
    script, count = max(non_latin.items(), key=lambda item: item[1])
    return script if count * 2 > total else None


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for char in text:
        script = _script_of(char) if char.isalpha() else None
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    return counts


def _is_japanese(text: str) -> bool:
    """Any kana at all settles it.

    Chinese and Japanese share the Han characters, so a Han-majority string is
    ambiguous between the two. Kana never appear in Chinese and always appear
    in a Japanese sentence of any length — including one that quotes several
    Han-only proper nouns — so their presence is the stronger signal, and it
    has to be checked before the Han majority (C3: "孫悟空の兵器は何か？" is
    two-thirds Han and still Japanese).
    """
    # Both kana markers resolve to "ja", so this is "contains any kana".
    return any(_script_of(char) == "ja" for char in text)


def _stop_word_scores(text: str) -> dict[str, int]:
    scores: dict[str, int] = dict.fromkeys(_LATIN_STOP_WORDS, 0)
    for word in _WORD.findall(text.lower()):
        for code, stop_words in _LATIN_STOP_WORDS.items():
            if word in stop_words:
                scores[code] += 1
    return scores


def _marker_hit(marker: str, words: frozenset[str], text: str) -> bool:
    """Does one distinctive marker occur in `text`?

    A single-character marker is an orthographic clue and is matched anywhere
    in the text (`ç`, `ß`, `ł`). A longer marker is matched against whole
    words only, exact for short ones and as a prefix for long ones — that is
    what lets an inflected form count ("résumer" for `résum`) without letting a
    short fragment match inside an unrelated word, which is how a plain
    substring test read French's `var` inside "Bovary" and answered `tr`.
    """
    if len(marker) == 1:
        return marker in text
    if marker in words:
        return True
    return len(marker) >= 4 and any(word.startswith(marker) for word in words)


def _marker_hits(text: str) -> dict[str, int]:
    """How many distinctive markers each Latin language finds in `text`.

    A marker is a character or word that does not occur in ordinary text of
    the other languages in the table, so one hit is worth more than any
    number of shared stop words. Counted, not boolean, so a question with two
    French markers outranks a single one.
    """
    lowered = text.lower()
    words = frozenset(_WORD.findall(lowered))
    hits: dict[str, int] = {}
    for code, markers in _DISTINCTIVE.items():
        count = sum(1 for marker in markers if _marker_hit(marker, words, lowered))
        if count:
            hits[code] = count
    return hits


def _latin_language(text: str) -> str | None:
    """The Latin-script language of `text`, or None when it is not decidable.

    One weighted score per language: a stop-word hit is 1, a distinctive
    marker is `_MARKER_WEIGHT`, so language-exclusive evidence outranks the
    shared vocabulary that produced KI-33's wrong answers. English is the
    template's own language and wins by default — a non-English language has
    to out-score it, never merely match it.

    A tie is never resolved by dict order. The tables are keyed by language,
    so first-wins would silently answer in whatever language happened to be
    written first: that is exactly how "Peux-tu résumer Madame Bovary ?" came
    back as `es` (only `tu` matched, in the es, fr, pt and pl tables alike) and
    "Chi è il conte di montecristo?" as `fr` (only `il`). An exact tie is a
    tie — the function returns None, which every caller already reads as "no
    signal, do not act on it".
    """
    scores = _stop_word_scores(text)
    for code, count in _marker_hits(text).items():
        scores[code] += _MARKER_WEIGHT * count
    english = scores[DEFAULT_LANGUAGE]
    candidates = [code for code in scores if code != DEFAULT_LANGUAGE and scores[code]]
    if not candidates:
        # No non-English signal at all: English if it has any, else nothing.
        return DEFAULT_LANGUAGE if english else None
    top = max(scores[code] for code in candidates)
    if top - english < _TIE_MARGIN:
        # English leads or ties, so there is no evidence it is not English.
        # A tie *below* English lands here too, and is English — not a
        # non-English tie, which is a different question.
        return DEFAULT_LANGUAGE
    leaders = [code for code in candidates if scores[code] == top]
    if len(leaders) > 1:
        # A tie the markers could not break is a tie, not a coin flip.
        return None
    winner = leaders[0]
    runner_up = max((scores[code] for code in candidates if code != winner), default=0)
    if top - runner_up < _TIE_MARGIN:
        return None
    return winner


def detect_language(text: str) -> str | None:
    """The ISO-639-1 code for `text`, or None if it carries no usable signal.

    None means "don't act on it" — an empty question, a bare number or
    product code, or a short question whose only evidence is shared between
    several languages (KI-33) — not "English". A renderer must not offer to
    translate into a language it guessed, so callers check for None before
    using the result.
    """
    if not text.strip():
        return None
    if _is_japanese(text):
        return "ja"
    script = _dominant_script(text)
    if script is not None:
        return script
    return _latin_language(text)


def language_name(code: str | None) -> str:
    """The English name to put in a prompt ("Translate into Spanish")."""
    return _LANGUAGE_NAMES.get(code or "", "English")


def target_language(text: str) -> tuple[str, str]:
    """(code, English name) for `text`, defaulting to English when undetectable."""
    code = detect_language(text) or DEFAULT_LANGUAGE
    return code, language_name(code)
