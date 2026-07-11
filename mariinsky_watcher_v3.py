import hashlib
import html as html_module
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag
from zoneinfo import ZoneInfo

try:
    import requests
except ModuleNotFoundError:  # Local Codex runtime may only have pip's vendored copy.
    from pip._vendor import requests

try:
    from bs4 import BeautifulSoup
except (ImportError, ModuleNotFoundError):
    BeautifulSoup = None


class _FallbackTag:
    def __init__(self, text="", attrs=None, parent=None):
        self._text = text
        self.attrs = attrs or {}
        self.parent = parent

    def get_text(self, separator=" ", strip=False):
        text = _html_to_text(self._text, separator)
        return text.strip() if strip else text

    def __getitem__(self, key):
        return self.attrs[key]

    def decompose(self):
        return None


class _FallbackSoup:
    def __init__(self, raw_html, _parser=None):
        self.raw_html = str(raw_html or "")

    def __call__(self, _names):
        self.raw_html = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", self.raw_html, flags=re.I | re.S)
        return []

    def get_text(self, separator="\n"):
        return _html_to_text(self.raw_html, separator)

    def select(self, selector):
        if selector.startswith("."):
            class_name = re.escape(selector[1:])
            pattern = rf"<(?P<tag>[a-zA-Z0-9]+)\b[^>]*class=[\"'][^\"']*\b{class_name}\b[^\"']*[\"'][^>]*>(?P<body>.*?)</(?P=tag)>"
        else:
            tag = re.escape(selector)
            pattern = rf"<{tag}\b[^>]*>(?P<body>.*?)</{tag}>"
        return [_FallbackTag(match.group("body")) for match in re.finditer(pattern, self.raw_html, re.I | re.S)]

    def find_all(self, tag_name, href=False):
        if tag_name != "a" or not href:
            return []
        pattern = r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>"
        return [_FallbackTag(match.group("body"), {"href": html_module.unescape(match.group("href"))}) for match in re.finditer(pattern, self.raw_html, re.I | re.S)]


def _html_to_text(raw_html, separator):
    text = re.sub(r"<br\s*/?>", separator, str(raw_html or ""), flags=re.I)
    text = re.sub(r"</(?:p|div|li|h1|h2|h3|section|article|tr)>", separator, text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html_module.unescape(text)


def make_soup(raw_html):
    if BeautifulSoup is not None:
        return BeautifulSoup(raw_html, "lxml")
    return _FallbackSoup(raw_html)


APP_NAME = "Mariinsky Watcher V3"
SCHEMA_VERSION = 3
ENGINE_VERSION = "V3.3-complete"

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "scan_audit.json"))
RUN_MODE = os.getenv("RUN_MODE", "dry_run").strip().lower()
DEBUG_URL = os.getenv("DEBUG_URL", "").strip()
SELF_TEST = os.getenv("SELF_TEST", "0") == "1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
MAX_TELEGRAM_MESSAGES_PER_RUN = int(os.getenv("MAX_TELEGRAM_MESSAGES_PER_RUN", "20"))
PENDING_WARNING_THRESHOLD = int(os.getenv("PENDING_WARNING_THRESHOLD", "500"))
MESSAGE_SEND_DELAY_SECONDS = float(os.getenv("MESSAGE_SEND_DELAY_SECONDS", "1.5"))
MONTHS_AHEAD = int(os.getenv("MONTHS_AHEAD", "8"))

MARIINSKY_ROOT = "https://www.mariinsky.ru/playbill/playbill/"
TZ = ZoneInfo("Europe/Moscow")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 MariinskyWatcherV3/3.0 (+https://github.com/fageehamalal-max/mariinsky-watcher)",
        "Accept-Language": "ru,en;q=0.9",
    }
)

EMOJI_NEW = "🐣"
EMOJI_EVENT = "🎵"
EMOJI_CANCELLED = "❌"
EMOJI_ADDED = "✅"
EMOJI_REMOVED = "⛔"

MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
MONTH_WORD_RE = r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"

VENUE_BY_CODE = {
    "1": "Мариинский театр",
    "2": "Мариинский-2",
    "3": "Концертный зал",
    "4": "Камерные залы",
    "5": "Зал Щедрина",
    "6": "Зал Мусоргского",
    "10": "Зал Стравинского",
    "15": "Мариинский театр",
}

# Внутренние названия площадок остаются стабильными для state.json.
# Эта карта используется только при формировании Telegram-сообщений.
VENUE_DISPLAY = {
    "Мариинский театр": "⚒️Мариинский-1🪏",
    "Мариинский-2": "🔱Мариинский-2🔱",
    "Концертный зал": "🧱Концертный зал🧱",
    "Камерные залы": "Камерный зал",
    "Камерный зал": "Камерный зал",
    "Зал Стравинского": "Зал Стравинского",
}

DETAIL_STOP_HEADERS = {
    "краткое содержание",
    "содержание",
    "либретто",
    "история",
    "история создания",
    "о спектакле",
    "об опере",
    "о произведении",
    "аннотация",
    "возрастная категория",
    "фотогалерея",
    "медиа",
}
PERFORMER_HEADERS = {"исполнители", "исполнитель", "состав исполнителей", "солисты"}
PROGRAM_HEADERS = {"в программе", "программа", "полная программа"}

MENU_RE = re.compile(
    r"^(Афиша и билеты|Подарочные карты|Детям|Визит в театр|Труппа|О театре|Новости|Для прессы|Афиша|Абонементы|Фестивали|Репертуар|Изменения в афише|Выбрать сцену|Все площадки|Все спектакли|Архив афиши|Полная программа|Поделиться)$",
    re.I,
)
FOOTER_RE = re.compile(
    r"^(Для обращений|Справочная служба|По вопросам реализации билетов|Скачать мобильное приложение|Любое использование|Закрыть|Вход в личный кабинет|Официальные билеты)$",
    re.I,
)
NOISE_RE = re.compile(
    r"(cookie|cookies|согласие на использование|купить|билет|билетов|билеты|касс[аеы]|личный кабинет|авторизация|подписаться|поиск|версия для слабовидящих|mariinsky\.tv|mariinsky\.fm)",
    re.I,
)

EXTERNAL_STAGE_MARKERS = [
    "Приморская сцена",
    "Владивосток",
    "Владикавказ",
    "РСО-Алания",
    "Северо-Осетинский",
]

BAD_TITLES = {
    "афиша",
    "афиша и билеты",
    "главная",
    "репертуар",
    "cookie",
    "cookies",
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
}

KNOWN_OPERA_TITLES = {
    "аида",
    "борис годунов",
    "богема",
    "валькирия",
    "джоконда",
    "евгений онегин",
    "зигфрид",
    "кармен",
    "князь игорь",
    "лоэнгрин",
    "летучая мышь",
    "набукко",
    "отелло",
    "парсифаль",
    "пиковая дама",
    "риголетто",
    "садко",
    "тоска",
    "травиата",
    "тристан и изольда",
    "турандот",
    "фауст",
    "хованщина",
    "царская невеста",
}
KNOWN_BALLET_TITLES = {
    "адажио хаммерклавир",
    "анна каренина",
    "арлекинада",
    "баядерка",
    "бахчисарайский фонтан",
    "вечер балетов",
    "дон кихот",
    "жизель",
    "золушка",
    "кармен-сюита",
    "конек горбунок",
    "конёк горбунок",
    "корсар",
    "лебединое озеро",
    "манон",
    "медный всадник",
    "раймонда",
    "ромео и джульетта",
    "сильфида",
    "спартак",
    "спящая красавица",
    "щелкунчик",
}

OPERA_MARKERS = [
    "опера",
    "оперетта",
    "оперетты",
    "моноопера",
    "опера-буффа",
    "драма в музыке",
    "музыкальная драма",
]
CONCERT_MARKERS = ["концерт", "месса", "кантата", "оратория", "реквием", "симфония", "вокальный"]
BALLET_MARKERS = [
    "балет",
    "балета",
    "балеты",
    "гала-концерт балета",
    "артисты балета",
    "театр балета",
    "хореография",
    "хореограф",
    "па-де-де",
    "вариация",
]

ROLE_WORDS = [
    "дирижер",
    "дирижёр",
    "солист",
    "солистка",
    "солисты",
    "сопрано",
    "меццо-сопрано",
    "тенор",
    "баритон",
    "бас",
    "концертмейстер",
    "ответственный концертмейстер",
    "хор",
    "оркестр",
    "ансамбль",
    "хормейстер",
]
PRODUCTION_CREDIT_WORDS = [
    "постановка",
    "режиссер",
    "режиссёр",
    "хореография",
    "хореограф",
    "сценография",
    "костюмы",
    "свет",
    "либретто",
]
HISTORY_OR_DESCRIPTION_STARTS = [
    "первое исполнение",
    "мировая премьера",
    "премьера состоялась",
    "история постановки",
    "описание спектакля",
    "краткое содержание",
    "смешанный хор и четыре солиста",
]
ENSEMBLE_MARKERS = [
    "Хор Мариинского театра",
    "Женский хор Мариинского театра",
    "Симфонический оркестр Мариинского театра",
    "Солисты оперы",
]
PROGRAM_WORDS = [
    "симфони",
    "концерт",
    "сюита",
    "увертюр",
    "сонат",
    "ноктюрн",
    "реквием",
    "оратори",
    "кантат",
    "рапсод",
    "адажио",
    "прелюди",
    "фуга",
    "квартет",
    "квинтет",
    "месса",
]
COMPOSERS = [
    "Бах",
    "Бетховен",
    "Брамс",
    "Верди",
    "Вагнер",
    "Моцарт",
    "Шопен",
    "Шуберт",
    "Шуман",
    "Рахманинов",
    "Прокофьев",
    "Стравинский",
    "Римский-Корсаков",
    "Чайковский",
    "Дебюсси",
    "Пуленк",
    "Дворжак",
    "Гершвин",
    "Бернстайн",
    "Глинка",
    "Мусоргский",
    "Бородин",
    "Понкьелли",
    "Пуччини",
    "Россини",
    "Бизе",
    "Малер",
    "Шостакович",
]


@dataclass
class EventRecord:
    source: str
    url: str
    title: str
    venue: str
    venue_source: str
    date_text: str
    time_text: str
    event_date: str
    event_type: str
    classification_source: str
    classification_confidence: str
    performers: list[str] = field(default_factory=list)
    performers_source: str = "none"
    main_roles: list[str] = field(default_factory=list)
    main_roles_source: str = "none"
    program: list[str] = field(default_factory=list)
    program_source: str = "none"
    cancelled: bool = False
    cancellation_source: str = ""
    digest: str = ""

    def to_state_record(self):
        return asdict(self)


@dataclass
class Classification:
    status: str
    event_type: str
    source: str
    confidence: str
    skip_reason: str = ""
    ballet_markers_found: list[str] = field(default_factory=list)
    included_despite_ballet_words: bool = False


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_dash(value):
    return clean(value).replace(" - ", " — ").replace(" – ", " — ").replace(" — ", " — ")


def key(value):
    return clean(value).lower().replace("ё", "е")


def title_key(value):
    value = key(value)
    value = re.sub(r"[«»\"'()\[\]{}.,:;!?]+", " ", value)
    value = value.replace("—", " ").replace("–", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


def marker_in_text(text, marker):
    low = key(text)
    marker = key(marker)
    if len(marker) <= 4:
        return bool(re.search(rf"(?<![а-яёa-z]){re.escape(marker)}(?![а-яёa-z])", low, re.I))
    return marker in low


def contains_any(text, markers):
    return any(marker_in_text(text, marker) for marker in markers)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_moscow():
    return datetime.now(TZ).date()


def normalize_url(url):
    return urldefrag(url)[0]


def digest_obj(obj):
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def event_core(record):
    return {
        "title": clean(record.get("title", "")),
        "venue": clean(record.get("venue", "")),
        "date_text": clean(record.get("date_text", "")),
        "time_text": clean(record.get("time_text", "")),
        "event_type": clean(record.get("event_type", "")),
        "performers": list(record.get("performers", []) or []),
        "main_roles": list(record.get("main_roles", []) or []),
        "program": list(record.get("program", []) or []),
        "cancelled": bool(record.get("cancelled", False)),
    }


def with_digest(record):
    record["digest"] = digest_obj(event_core(record))
    return record


def fetch_page(url):
    last_exc = None
    for attempt in range(1, 4):
        try:
            response = SESSION.get(url, timeout=30)
            response.raise_for_status()
            if not response.encoding or response.encoding.lower() in {"ascii", "iso-8859-1"}:
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
    raise last_exc


def month_urls(root=MARIINSKY_ROOT, months_ahead=MONTHS_AHEAD):
    today = today_moscow()
    urls = [root]
    for offset in range(months_ahead + 1):
        total = today.month - 1 + offset
        year = today.year + total // 12
        month = total % 12 + 1
        urls.append(urljoin(root, f"{year}/{month}/"))
    return list(dict.fromkeys(urls))


def is_noise(line):
    line = clean(line)
    if not line:
        return True
    return bool(MENU_RE.fullmatch(line) or FOOTER_RE.fullmatch(line) or NOISE_RE.search(line))


def html_lines(html_or_soup):
    soup = make_soup(html_or_soup) if isinstance(html_or_soup, str) else html_or_soup
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    out = []
    prev = None
    for raw in soup.get_text("\n").splitlines():
        line = clean(raw)
        if not line or line == prev:
            continue
        if FOOTER_RE.fullmatch(line):
            break
        if is_noise(line):
            continue
        out.append(line)
        prev = line
    return merge_broken_role_lines(out)


def is_date_line(line):
    return bool(re.search(rf"\b\d{{1,2}}\s+{MONTH_WORD_RE}\b", key(line)))


def is_time_line(line):
    return bool(re.fullmatch(r"\d{1,2}[:.]\d{2}", clean(line)))


def normalize_time_text(value):
    value = clean(value).replace(".", ":")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return ""
    hour, minute = (int(part) for part in match.groups())
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def extract_page_time(lines, title=""):
    """Extract the public event time from the detail page.

    The time displayed on the page is authoritative. The time encoded in the
    URL is used only when the page does not expose a valid time near its title.
    """
    wanted_title = title_key(title)
    title_index = None
    if wanted_title:
        for index, line in enumerate(lines[:80]):
            if title_key(line) == wanted_title:
                title_index = index
                break

    search_end = min(len(lines), 40)
    if title_index is not None:
        search_end = min(search_end, title_index + 1)

    candidates = []
    for line in lines[:search_end]:
        normalized = normalize_time_text(line)
        if normalized:
            candidates.append(normalized)

    if candidates:
        return candidates[-1]

    for line in lines[:40]:
        normalized = normalize_time_text(line)
        if normalized:
            return normalized

    return ""


def parse_mariinsky_url_parts(url):
    m = re.search(r"/playbill/playbill/(\d{4})/(\d{1,2})/(\d{1,2})/(\d+)_(\d{4})/", url)
    if not m:
        return None, "", "", "Мариинский театр", "fallback"
    year, month, day, venue_code, time_raw = m.groups()
    dt = date(int(year), int(month), int(day))
    date_text = f"{int(day)} {MONTHS[int(month)]} {year}"
    venue = VENUE_BY_CODE.get(venue_code, "Мариинский театр")
    time_text = f"{time_raw[:2]}:{time_raw[2:]}"
    return dt, date_text, time_text, venue, "url_code"


def is_valid_title(title):
    title = clean(title)
    low = title_key(title)
    if len(title) < 3 or low in BAD_TITLES:
        return False
    if is_noise(title) or is_date_line(title) or is_time_line(title):
        return False
    if re.fullmatch(r"[\d\W_]+", title):
        return False
    return True


def title_from_soup(soup, fallback=""):
    for selector in ["h1", "h2", ".title", ".event-title", ".concert-title", ".event__title"]:
        for tag in soup.select(selector):
            title = clean(tag.get_text(" ", strip=True))
            if is_valid_title(title):
                return title
    if is_valid_title(fallback):
        return clean(fallback)
    for line in html_lines(soup):
        if is_valid_title(line):
            return line
    return "Без названия"


def infer_list_type(text):
    low = key(text)
    if contains_any(low, OPERA_MARKERS):
        return "opera"
    if contains_any(low, CONCERT_MARKERS):
        return "concert"
    if contains_any(low, BALLET_MARKERS):
        return "ballet"
    return ""


def extract_playbill_links(html, base_url=MARIINSKY_ROOT):
    soup = make_soup(html)
    links = {}
    for a_tag in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, a_tag["href"]))
        if not re.search(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_\d{4}/", href):
            continue
        text_parts = [clean(a_tag.get_text(" ", strip=True))]
        parent = a_tag
        for _ in range(3):
            parent = parent.parent
            if parent is None:
                break
            parent_text = clean(parent.get_text(" ", strip=True))
            if parent_text:
                text_parts.append(parent_text)
        list_text = clean(" ".join(text_parts))
        links[href] = {"url": href, "list_text": list_text, "list_type": infer_list_type(list_text)}
    return list(links.values())


def find_section(lines, headers, max_lines=120):
    for index, line in enumerate(lines):
        low = title_key(line)
        if low not in headers:
            continue
        section = []
        for next_line in lines[index + 1 : index + 1 + max_lines]:
            next_low = title_key(next_line)
            if next_low in headers or next_low in PERFORMER_HEADERS or next_low in PROGRAM_HEADERS:
                break
            if next_low in DETAIL_STOP_HEADERS or any(next_low.startswith(x) for x in DETAIL_STOP_HEADERS):
                break
            section.append(next_line)
        return section
    return []


def merge_broken_role_lines(lines):
    out = []
    index = 0
    while index < len(lines):
        line = clean(lines[index])
        if re.search(r"(?:—|–|-)\s*$", line) and index + 1 < len(lines):
            merged = re.sub(r"(?:—|–|-)\s*$", " — ", line) + clean(lines[index + 1])
            out.append(normalize_dash(merged))
            index += 2
            continue
        out.append(normalize_dash(line))
        index += 1
    return out


def is_history_or_description(line):
    low = key(line)
    return any(low.startswith(start) for start in HISTORY_OR_DESCRIPTION_STARTS)


def is_role_line(line):
    line = normalize_dash(line)
    if "—" not in line or is_history_or_description(line):
        return False
    left, right = [clean(x) for x in line.split("—", 1)]
    if not left or not right:
        return False
    low_left = key(left)
    if any(word in low_left for word in PRODUCTION_CREDIT_WORDS):
        return False
    if any(word in low_left for word in ROLE_WORDS):
        return True
    # Opera roles often have custom character names rather than generic role words.
    return bool(re.fullmatch(r"[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9 .,'-]{1,45}", left)) and looks_like_person_or_ensemble(right)


def looks_like_person_or_ensemble(line):
    if any(marker in line for marker in ENSEMBLE_MARKERS):
        return True
    words = [w for w in re.split(r"\s+", clean(line)) if w]
    capitals = [w for w in words if re.match(r"^[А-ЯЁA-Z]", w)]
    return len(capitals) >= 1 and len(clean(line)) <= 120


def is_ensemble_line(line):
    return any(marker in clean(line) for marker in ENSEMBLE_MARKERS)


def split_participation(line):
    text = clean(re.sub(r"^При участии\s*", "", clean(line), flags=re.I))
    text = re.sub(r"^[:—–-]\s*", "", text)
    if not text:
        return []
    parts = re.split(r"\s*(?:,|;|\s+и\s+)\s*", text)
    return [clean(part) for part in parts if clean(part)]


def person_compare_key(line):
    text = key(line)
    if "—" in text:
        text = text.split("—", 1)[1]
    text = re.sub(r"\([^)]*\)", " ", text)
    words = [w for w in re.split(r"[^а-яёa-z-]+", text) if len(w) > 2]
    if not words:
        return title_key(line)
    last = words[-1]
    suffix_replacements = [
        ("овой", "ов"),
        ("евой", "ев"),
        ("иной", "ин"),
        ("ской", "ск"),
        ("цкой", "цк"),
        ("ой", ""),
        ("а", ""),
        ("я", ""),
        ("ы", ""),
        ("и", ""),
    ]
    for suffix, replacement in suffix_replacements:
        if last.endswith(suffix) and len(last) > len(suffix) + 3:
            last = last[: -len(suffix)] + replacement
            break
    return last


def dedupe_preserve_order(items, key_func=title_key):
    out = []
    seen = set()
    for item in items:
        item = clean(item)
        if not item:
            continue
        item_key = key_func(item)
        if item_key in seen:
            continue
        out.append(item)
        seen.add(item_key)
    return out


def extract_performers_from_lines(lines):
    lines = merge_broken_role_lines(lines)
    role_lines = []
    participants = []
    ensembles = []
    for line in lines:
        if is_history_or_description(line):
            continue
        low = key(line)
        if low.startswith("при участии"):
            participants.extend(split_participation(line))
            continue
        if is_role_line(line):
            role_lines.append(normalize_dash(line))
            continue
        if is_ensemble_line(line) and len(line) < 150:
            ensembles.append(clean(line))
    performer_keys = {person_compare_key(line) for line in role_lines}
    participants = [p for p in participants if person_compare_key(p) not in performer_keys]
    return dedupe_preserve_order(role_lines + ensembles + participants, person_compare_key)


def extract_list_main_roles(list_text):
    m = re.search(r"В главных партиях[:\s]+(.+?)(?:Дириж[её]р|При участии|Мариинский|Концертный зал|$)", list_text, re.I)
    if not m:
        return []
    raw = clean(m.group(1))
    return dedupe_preserve_order([clean(x) for x in re.split(r"\s*(?:,|;|\s+и\s+)\s*", raw) if clean(x)], person_compare_key)


def extract_list_performers(list_text):
    lines = []
    for m in re.finditer(r"(Дириж[её]р\s*(?:—|–|-)\s*[А-ЯЁ][^,.;]+)", list_text, re.I):
        lines.append(normalize_dash(m.group(1)))
    for m in re.finditer(r"При участии\s+(.+?)(?:Мариинский|Концертный зал|$)", list_text, re.I):
        lines.extend(split_participation("При участии " + m.group(1)))
    return dedupe_preserve_order(lines, person_compare_key)


def has_composer(line):
    return any(key(composer) in key(line) for composer in COMPOSERS)


def is_program_line(line, title=""):
    if is_role_line(line) or is_ensemble_line(line) or is_history_or_description(line):
        return False
    low = key(line)
    if title_key(line) == title_key(title):
        return False
    return has_composer(line) or any(word in low for word in PROGRAM_WORDS)


def extract_program_and_performers(lines, title=""):
    program = []
    performers = []
    for line in merge_broken_role_lines(lines):
        if is_role_line(line) or is_ensemble_line(line):
            performers.append(normalize_dash(line))
        elif is_program_line(line, title):
            program.append(clean(line))
    return dedupe_preserve_order(program), dedupe_preserve_order(performers, person_compare_key)


def detect_cancellation(title, list_text="", lines=None):
    lines = lines or []
    patterns = [
        re.compile(r"\bотмен[её]н(?:а|о|ы)?\b", re.I),
        re.compile(r"\bотмена\b", re.I),
        re.compile(r"\bне состоится\b", re.I),
    ]

    direct_sources = [("title", clean(title)), ("list_card", clean(list_text))]
    for source, text in direct_sources:
        if text and any(pattern.search(text) for pattern in patterns):
            return True, source

    # На детальной странице проверяем только короткие верхние строки,
    # чтобы историческая справка об отменённых постановках не дала ложный статус.
    for line in [clean(x) for x in lines[:25]]:
        if not line or len(line) > 140 or is_history_or_description(line):
            continue
        if any(pattern.search(line) for pattern in patterns):
            return True, "detail_page"

    return False, ""


def classify_event(title, list_type="", lines=None):
    lines = lines or []
    title_low = title_key(title)
    combined = "\n".join([title, *lines[:80]])
    ballet_markers = [m for m in BALLET_MARKERS if marker_in_text(combined, m)]

    if list_type == "opera":
        return Classification("included", "opera", "list_opera", "high", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))
    if list_type == "concert":
        return Classification("included", "concert", "list_concert", "high", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))
    if list_type == "ballet":
        return Classification("skipped", "ballet", "list_ballet", "high", "clear_ballet", ballet_markers)
    if title_low in KNOWN_OPERA_TITLES:
        return Classification("included", "opera", "known_opera_title", "high", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))
    if any(marker_in_text(line, marker) for marker in OPERA_MARKERS for line in [title, *lines[:40]]):
        return Classification("included", "opera", "genre_opera", "high", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))
    if any(marker_in_text(line, marker) for marker in CONCERT_MARKERS for line in [title, *lines[:40]]):
        return Classification("included", "concert", "concert_indicator", "medium", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))
    if title_low in KNOWN_BALLET_TITLES or any(is_clear_ballet_genre(line) for line in lines[:30]):
        return Classification("skipped", "ballet", "ballet_indicator", "high", "clear_ballet", ballet_markers)
    return Classification("included", "unknown", "ambiguous_not_ballet", "low", ballet_markers_found=ballet_markers, included_despite_ballet_words=bool(ballet_markers))


def is_clear_ballet_genre(line):
    low = title_key(line)
    return low in {"балет", "балеты", "вечер балетов", "одноактный балет"} or bool(re.fullmatch(r"балет(ы)?(\s+в\s+.+\s+действиях?)?", low))


def build_audit_item(url, title="", status="failed", **extra):
    item = {
        "url": url,
        "title": title,
        "venue": extra.pop("venue", ""),
        "venue_source": extra.pop("venue_source", ""),
        "date_text": extra.pop("date_text", ""),
        "time_text": extra.pop("time_text", ""),
        "time_source": extra.pop("time_source", ""),
        "status": status,
        "event_type": extra.pop("event_type", ""),
        "classification_source": extra.pop("classification_source", ""),
        "classification_confidence": extra.pop("classification_confidence", ""),
        "sections_found": extra.pop("sections_found", []),
        "performers_source": extra.pop("performers_source", "none"),
        "performers_preview": extra.pop("performers_preview", []),
        "main_roles_preview": extra.pop("main_roles_preview", []),
        "program_preview": extra.pop("program_preview", []),
        "ballet_markers_found": extra.pop("ballet_markers_found", []),
        "included_despite_ballet_words": extra.pop("included_despite_ballet_words", False),
        "skip_reason": extra.pop("skip_reason", ""),
        "cancelled": extra.pop("cancelled", False),
        "cancellation_source": extra.pop("cancellation_source", ""),
    }
    item.update(extra)
    return item


def parse_mariinsky_event(url, list_text="", list_type="", html=None):
    url = normalize_url(url)
    html = html if html is not None else fetch_page(url)
    soup = make_soup(html)
    lines = html_lines(soup)
    title = title_from_soup(soup, fallback=list_text)
    event_dt, date_text, url_time_text, venue, venue_source = parse_mariinsky_url_parts(url)
    page_time_text = extract_page_time(lines, title)
    time_text = page_time_text or url_time_text
    time_source = "detail_page" if page_time_text else "url_code"
    cancelled, cancellation_source = detect_cancellation(title, list_text, lines)
    sections_found = []
    if find_section(lines, PERFORMER_HEADERS):
        sections_found.append("Исполнители")
    if find_section(lines, PROGRAM_HEADERS):
        sections_found.append("В программе")

    if any(marker in "\n".join(lines[:80]) for marker in EXTERNAL_STAGE_MARKERS):
        audit = build_audit_item(url, title, "skipped", venue=venue, venue_source=venue_source, date_text=date_text, time_text=time_text, time_source=time_source, skip_reason="external_stage")
        return None, audit

    classification = classify_event(title, list_type, lines)
    if classification.status == "skipped":
        audit = build_audit_item(
            url,
            title,
            "skipped",
            venue=venue,
            venue_source=venue_source,
            date_text=date_text,
            time_text=time_text,
            time_source=time_source,
            event_type=classification.event_type,
            classification_source=classification.source,
            classification_confidence=classification.confidence,
            sections_found=sections_found,
            ballet_markers_found=classification.ballet_markers_found,
            skip_reason=classification.skip_reason,
        )
        return None, audit

    performer_section = find_section(lines, PERFORMER_HEADERS)
    program_section = find_section(lines, PROGRAM_HEADERS)
    detail_performers = extract_performers_from_lines(performer_section)
    program, program_performers = extract_program_and_performers(program_section, title)
    list_performers = extract_list_performers(list_text)
    performers = dedupe_preserve_order(detail_performers + program_performers + list_performers, person_compare_key)
    performers_source = "detail_section" if detail_performers else "program_adjacent" if program_performers else "list_card" if list_performers else "none"

    main_roles = extract_list_main_roles(list_text)
    role_keys = {person_compare_key(line) for line in performers}
    main_roles = [role for role in main_roles if person_compare_key(role) not in role_keys]
    main_roles_source = "list_main_roles" if main_roles else "none"
    program_source = "detail_program_section" if program else "none"

    record = EventRecord(
        source="mariinsky",
        url=url,
        title=title,
        venue=venue,
        venue_source=venue_source,
        date_text=date_text,
        time_text=time_text,
        event_date=event_dt.isoformat() if event_dt else "",
        event_type=classification.event_type,
        classification_source=classification.source,
        classification_confidence=classification.confidence,
        performers=performers,
        performers_source=performers_source,
        main_roles=main_roles,
        main_roles_source=main_roles_source,
        program=program,
        program_source=program_source,
        cancelled=cancelled,
        cancellation_source=cancellation_source,
    )
    state_record = with_digest(record.to_state_record())
    record.digest = state_record["digest"]
    audit = build_audit_item(
        url,
        title,
        "included",
        venue=venue,
        venue_source=venue_source,
        date_text=date_text,
        time_text=time_text,
        time_source=time_source,
        event_type=classification.event_type,
        classification_source=classification.source,
        classification_confidence=classification.confidence,
        sections_found=sections_found,
        performers_source=performers_source,
        performers_preview=performers[:8],
        main_roles_preview=main_roles[:8],
        program_preview=program[:8],
        ballet_markers_found=classification.ballet_markers_found,
        included_despite_ballet_words=classification.included_despite_ballet_words,
        skip_reason="",
        cancelled=cancelled,
        cancellation_source=cancellation_source,
    )
    return record, audit


def scan_all():
    audit = {
        "app": APP_NAME,
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "run_mode": RUN_MODE,
        "run_at": now_utc(),
        "source_errors": [],
        "items": [],
        "summary": {},
    }
    link_map = {}
    for month_url in month_urls():
        try:
            for link in extract_playbill_links(fetch_page(month_url), month_url):
                link_map[link["url"]] = link
        except Exception as exc:
            audit["source_errors"].append({"url": month_url, "error": f"{type(exc).__name__}: {exc}"})
    events = {}
    seen_urls = set(link_map)
    failed_urls = set()
    for url, link in sorted(link_map.items()):
        try:
            record, item = parse_mariinsky_event(url, link.get("list_text", ""), link.get("list_type", ""))
            audit["items"].append(item)
            if record:
                events[url] = record.to_state_record()
        except Exception as exc:
            failed_urls.add(url)
            audit["items"].append(build_audit_item(url, status="failed", error=f"{type(exc).__name__}: {exc}"))
    audit["scan_complete"] = not audit["source_errors"]
    audit["summary"]["mariinsky"] = {
        "links_found": len(link_map),
        "included": sum(1 for item in audit["items"] if item["status"] == "included"),
        "skipped": sum(1 for item in audit["items"] if item["status"] == "skipped"),
        "failed": sum(1 for item in audit["items"] if item["status"] == "failed"),
        "scan_complete": audit["scan_complete"],
    }
    return {"mariinsky": events}, {"mariinsky": seen_urls}, {"mariinsky": failed_urls}, audit


def venue_line(record):
    venue = clean(record.get("venue", "")) or "Мариинский театр"
    return VENUE_DISPLAY.get(venue, venue)


def date_line(record, is_cancelled=False):
    date_text = clean(record.get("date_text", ""))
    time_text = clean(record.get("time_text", ""))

    # Год хранится в state.json, но в Telegram не выводится.
    date_text = re.sub(r"\s+\d{4}\s*$", "", date_text)

    date_symbol = "🔻" if is_cancelled else "🔷"
    time_symbol = "🔻" if is_cancelled else "🔹"

    if date_text and time_text:
        return f"{date_symbol}{date_text}{time_symbol}{time_text}"
    if date_text:
        return f"{date_symbol}{date_text}"
    if time_text:
        return f"{time_symbol}{time_text}"
    return ""


def header_lines(record, title=None):
    title = clean(title if title is not None else record.get("title", "Без названия"))
    lines = [venue_line(record), f"{EMOJI_EVENT}{title}"]
    dt = date_line(record)
    if dt:
        lines.append(dt)
    return lines


def link_line(record):
    return f"ℹ️ {record.get('url', '')}"


def format_new(record):
    title = clean(record.get("title", "Без названия"))
    parts = [venue_line(record), f"{EMOJI_NEW}{title}"]
    dt = date_line(record)
    if dt:
        parts.append(dt)
    parts += ["", link_line(record)]
    return "\n".join(parts).strip()


def format_removed(record):
    title = clean(record.get("title", "Без названия"))
    parts = [venue_line(record), f"{EMOJI_CANCELLED}{title}"]
    dt = date_line(record, is_cancelled=True)
    if dt:
        parts.append(dt)
    parts += ["", link_line(record)]
    return "\n".join(parts).strip()


def format_cancelled(record):
    return format_removed(record)


def format_replacement(old, new):
    title = f"{clean(old.get('title', ''))} → {clean(new.get('title', ''))}"
    parts = header_lines(new, title=title)
    parts += [
        "",
        "Замена спектакля:",
        "",
        f"{EMOJI_REMOVED} Было:",
        clean(old.get("title", "")) or "—",
        "",
        f"{EMOJI_ADDED} Стало:",
        clean(new.get("title", "")) or "—",
        "",
        link_line(new),
    ]
    return "\n".join(parts).strip()


def normalized_set_diff(old_items, new_items, key_func=title_key):
    old_map = {key_func(item): clean(item) for item in old_items or [] if clean(item)}
    new_map = {key_func(item): clean(item) for item in new_items or [] if clean(item)}
    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]
    return added, removed


def section_added_removed(title, added, removed):
    added = [x for x in added if clean(x)]
    removed = [x for x in removed if clean(x)]
    if not added and not removed:
        return ""
    parts = [title, ""]
    if added:
        parts += [f"{EMOJI_ADDED} Добавлено:", *added, ""]
    if removed:
        parts += [f"{EMOJI_REMOVED} Удалено:", *removed, ""]
    while parts and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)


def before_after(title, old_value, new_value):
    old_value = clean(old_value)
    new_value = clean(new_value)
    if old_value == new_value:
        return ""
    return "\n".join([title, "", f"{EMOJI_REMOVED} Было:", old_value or "—", "", f"{EMOJI_ADDED} Стало:", new_value or "—"])


def change_sections(old, new):
    sections = []
    for section in [
        before_after("Изменение даты / времени:", date_line(old), date_line(new)),
        before_after("Изменение площадки:", old.get("venue", ""), new.get("venue", "")),
    ]:
        if section:
            sections.append(section)
    perf_added, perf_removed = normalized_set_diff(old.get("performers", []), new.get("performers", []), person_compare_key)
    role_added, role_removed = normalized_set_diff(old.get("main_roles", []), new.get("main_roles", []), person_compare_key)
    prog_added, prog_removed = normalized_set_diff(old.get("program", []), new.get("program", []), title_key)
    for section in [
        section_added_removed("Изменение в составе:", perf_added, perf_removed),
        section_added_removed("Изменение в главных партиях:", role_added, role_removed),
        section_added_removed("Изменение в программе:", prog_added, prog_removed),
    ]:
        if section:
            sections.append(section)
    return sections


def format_changed(old, new):
    if not bool(old.get("cancelled", False)) and bool(new.get("cancelled", False)):
        return format_cancelled(new)
    if clean(old.get("title", "")) != clean(new.get("title", "")):
        return format_replacement(old, new)
    sections = change_sections(old, new)
    if not sections:
        return ""
    parts = header_lines(new)
    for section in sections:
        parts += ["", section]
    parts += ["", link_line(new)]
    return "\n".join(parts).strip()


def parse_event_date(record):
    try:
        return date.fromisoformat(record.get("event_date", ""))
    except Exception:
        return None


def is_future_removed(record):
    event_date = parse_event_date(record)
    return event_date is None or event_date > today_moscow()


def build_messages(old_events, new_events, seen_urls=None, failed_urls=None, allow_removals=True):
    seen_urls = set(seen_urls or [])
    failed_urls = set(failed_urls or [])
    messages = []
    for url, new in sorted((new_events or {}).items()):
        old = (old_events or {}).get(url)
        if old is None:
            messages.append(format_cancelled(new) if new.get("cancelled", False) else format_new(new))
        elif old.get("digest") != new.get("digest"):
            message = format_changed(old, new)
            if message:
                messages.append(message)
    if allow_removals:
        for url, old in sorted((old_events or {}).items()):
            if url in (new_events or {}) or url in seen_urls or url in failed_urls:
                continue
            if is_future_removed(old):
                messages.append(format_removed(old))
    return messages


def default_state():
    return {
        "app": APP_NAME,
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "updated_at": now_utc(),
        "sources": {"mariinsky": {"events": {}}},
        "pending_messages": [],
    }


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    state.setdefault("sources", {}).setdefault("mariinsky", {}).setdefault("events", {})
    state.setdefault("pending_messages", [])
    return state


def save_state(state):
    state["app"] = APP_NAME
    state["schema_version"] = SCHEMA_VERSION
    state["engine_version"] = ENGINE_VERSION
    state["updated_at"] = now_utc()
    state.setdefault("sources", {}).setdefault("mariinsky", {}).setdefault("events", {})
    state.setdefault("pending_messages", [])
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def save_audit(audit):
    AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def add_pending(state, messages):
    state.setdefault("pending_messages", []).extend([m for m in messages if clean(m)])
    if len(state["pending_messages"]) > PENDING_WARNING_THRESHOLD:
        print(f"WARNING: pending_messages is {len(state['pending_messages'])}, above threshold {PENDING_WARNING_THRESHOLD}.")


def chunks(text, limit=3900):
    if len(text) <= limit:
        return [text]
    out = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                out.append(current)
            current = block
    if current:
        out.append(current)
    return out


def send_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets are missing; message was not sent.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    receipts = []

    for chunk in chunks(text):
        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Telegram returned invalid JSON.") from exc

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError(f"Telegram API rejected the message: {payload!r}")

        result = payload.get("result") or {}
        chat = result.get("chat") or {}
        receipt = {
            "message_id": result.get("message_id"),
            "chat_id": chat.get("id"),
        }
        receipts.append(receipt)
        print(
            "Telegram delivered: "
            f"message_id={receipt['message_id']} "
            f"chat_id={receipt['chat_id']}"
        )

    return receipts


def flush_pending(state):
    pending = state.setdefault("pending_messages", [])
    sent = 0
    while pending and sent < MAX_TELEGRAM_MESSAGES_PER_RUN:
        send_message(pending[0])
        pending.pop(0)
        sent += 1
        if pending and MESSAGE_SEND_DELAY_SECONDS > 0:
            time.sleep(MESSAGE_SEND_DELAY_SECONDS)
    return sent


def debug_single_url(url):
    record, audit = parse_mariinsky_event(normalize_url(url), "")
    payload = {
        "audit": audit,
        "record": record.to_state_record() if record else None,
        "debug": {
            "raw_title": audit.get("title", ""),
            "venue": audit.get("venue", ""),
            "venue_source": audit.get("venue_source", ""),
            "date_text": audit.get("date_text", ""),
            "time_text": audit.get("time_text", ""),
            "time_source": audit.get("time_source", ""),
            "sections_found": audit.get("sections_found", []),
            "performers": audit.get("performers_preview", []),
            "main_roles": audit.get("main_roles_preview", []),
            "program": audit.get("program_preview", []),
            "classification_source": audit.get("classification_source", ""),
            "skip_reason": audit.get("skip_reason", ""),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main():
    if RUN_MODE not in {"dry_run", "bootstrap", "live"}:
        raise RuntimeError("RUN_MODE must be dry_run, bootstrap, or live")
    if DEBUG_URL:
        debug_single_url(DEBUG_URL)
        return

    scanned, seen_urls, failed_urls, audit = scan_all()
    old_state = load_state()
    old_events = (old_state or default_state())["sources"]["mariinsky"]["events"]
    scan_complete = bool(audit.get("scan_complete", False))
    messages = build_messages(
        old_events,
        scanned["mariinsky"],
        seen_urls["mariinsky"],
        failed_urls["mariinsky"],
        allow_removals=scan_complete,
    )
    audit["would_notify_count"] = len(messages)
    audit["would_notify_preview"] = messages[:20]
    save_audit(audit)

    if old_state is None:
        new_state = default_state()
        new_state["sources"]["mariinsky"]["events"] = scanned["mariinsky"]
        if RUN_MODE == "dry_run":
            print("DRY_RUN: no state exists. Current scan was audited but state was not created.")
            return
        if not scan_complete:
            print("ERROR: initial baseline was not created because the scan was incomplete.")
            return
        save_state(new_state)
        print("No previous V3 state. Baseline created without Telegram messages.")
        return

    if RUN_MODE == "dry_run":
        print(f"DRY_RUN: would queue {len(messages)} messages. State was not changed.")
        for message in messages[:20]:
            print("--- WOULD NOTIFY ---")
            print(message)
        return

    if scan_complete:
        next_events = scanned["mariinsky"]
        audit["state_update_strategy"] = "replace"
    else:
        next_events = dict(old_events)
        next_events.update(scanned["mariinsky"])
        audit["state_update_strategy"] = "merge_preserve_missing"
        print(
            "WARNING: incomplete scan; missing events were preserved and "
            "removal notifications were suppressed."
        )

    old_state["sources"]["mariinsky"]["events"] = next_events
    save_audit(audit)

    if RUN_MODE == "bootstrap":
        old_state["pending_messages"] = []
        save_state(old_state)
        print(f"BOOTSTRAP: state refreshed. Pending cleared. {len(messages)} possible messages were not queued or sent.")
        return

    add_pending(old_state, messages)
    try:
        sent = flush_pending(old_state)
    except Exception as exc:
        print(f"Telegram send stopped: {type(exc).__name__}: {exc}")
        sent = 0
    save_state(old_state)
    print(f"Telegram messages sent this run: {sent}. Pending left: {len(old_state.get('pending_messages', []))}")


def run_self_tests():
    from test_mariinsky_watcher_v3 import run_all_tests

    run_all_tests()
    print("SELF_TEST_OK")


if __name__ == "__main__":
    if SELF_TEST:
        run_self_tests()
    else:
        main()
