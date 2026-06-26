import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urldefrag, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


APP_NAME = "Mariinsky Filter V2"
SCHEMA_VERSION = 2
FILTER_VERSION = "V2.0"

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "scan_audit.json"))
RULES_FILE = Path(os.getenv("RULES_FILE", "rules.json"))
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
PHILHARMONIA_ROOT = "https://www.philharmonia.spb.ru/afisha/grand/"
TZ = ZoneInfo("Europe/Moscow")
HEADERS = {
    "User-Agent": "Mozilla/5.0 MariinskyWatcherV2/2.0 (+https://github.com/fageehamalal-max/mariinsky-watcher)",
    "Accept-Language": "ru,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

EMOJI_NEW = "🐣"
EMOJI_ADDED = "✅"
EMOJI_REMOVED = "⛔"
EMOJI_DATE = "🔸"
MARIINSKY_MARK = "𝄞"

MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
MONTH_NUM = {v: k for k, v in MONTHS.items()}

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
MARIINSKY_VENUES = set(VENUE_BY_CODE.values()) | {
    "Концертный зал Мариинского театра",
    "Японский павильон",
    "Ораниенбаум",
    "Меншиковский дворец",
}
SOURCES = {
    "mariinsky": "Мариинский театр",
    "philharmonia_grand": "СПб филармония, Большой зал",
}

EXTERNAL_STAGE_MARKERS = [
    "Приморская сцена",
    "Владивосток",
    "Владикавказ",
    "РСО-Алания",
]

BAD_TITLES = {
    "еда", "среда", "понедельник", "вторник", "четверг", "пятница", "суббота", "воскресенье",
    "cookie", "cookies", "использование cookies", "согласие на использование cookie", "согласие на использование cookies",
}

FOOTER_RE = re.compile(
    r"^(Для обращений|Справочная служба|По вопросам реализации билетов|Скачать мобильное приложение|Любое использование|Закрыть|Вход в личный кабинет|Официальные билеты|Поделиться)$",
    re.I,
)
MARIINSKY_STOP_RE = re.compile(
    r"^(Возрастная категория(\s*\d+\+?)?|XXXIV\s+Музыкальный фестиваль.*Зв[её]зды белых ночей|Музыкальный фестиваль.*Зв[её]зды белых ночей|Зв[её]зды белых ночей|Краткое содержание|Содержание)$",
    re.I,
)
MENU_RE = re.compile(
    r"^(Афиша и билеты|Подарочные карты|Детям|Визит в театр|Труппа|О театре|Новости|Для прессы|Афиша|Абонементы|Фестивали|Репертуар|Изменения в афише|Выбрать сцену|Все площадки|Все спектакли|Архив афиши|Полная программа)$",
    re.I,
)
NOISE_RE = re.compile(
    r"(@@|купить|заказать|продажа|стоимость|цена|билет|билетов|билеты|касс[аеы]|авторизация|войти|регистрация|личный кабинет|cookie|cookies|согласие на использование|подписаться|поиск|версия для слабовидящих|опрос|для обращений|справочная служба|скачать мобильное приложение|mariinsky\.tv|mariinsky\.fm|правообладател|зв[её]здный состав|блестящий состав|история постановки|описание спектакля)",
    re.I,
)

PHILHARMONIA_FORBIDDEN_QUERY_KEYS = {
    "tag", "tags", "year", "month", "page", "p", "search", "q", "hall", "type", "genre", "series", "abonement",
}
PHILHARMONIA_EVENT_QUERY_KEYS = {"ev_z", "ev_y", "event", "event_id", "id"}

PERFORMER_WORDS = [
    "дириж", "солист", "солистка", "исполн", "состав", "партию", "партия", "сопрано", "тенор", "баритон", "бас",
    "скрипка", "альт", "виолончель", "фортепиано", "орган", "кларнет", "флейта", "хор", "оркестр", "ансамбль",
    "артист", "артисты", "концертмейстер", "режиссер", "режиссёр", "хормейстер",
]
ROLE_WORDS = [
    "дирижер", "дирижёр", "солист", "солистка", "солисты", "исполнитель", "исполнительница", "исполнители",
    "сопрано", "тенор", "баритон", "бас", "скрипка", "альт", "виолончель", "фортепиано", "орган", "кларнет", "флейта",
    "хор", "оркестр", "ансамбль", "артист", "артисты", "концертмейстер", "режиссер", "режиссёр", "хормейстер",
]
ENSEMBLE_WORDS = ["оркестр", "хор", "ансамбль"]

PROGRAM_WORDS = [
    "симфони", "концерт", "сюита", "увертюр", "сонат", "ноктюрн", "реквием", "оратори", "кантат",
    "рапсод", "адажио", "танц", "прелюди", "фуга", "квартет", "квинтет", "месса",
]
PROGRAM_START_WORDS = [
    "концерт", "симфония", "сюита", "увертюра", "соната", "ноктюрн", "реквием", "оратория", "кантата",
    "рапсодия", "адажио", "танец", "прелюдия", "фуга", "квартет", "квинтет", "месса",
]
COMPOSERS = [
    "Бах", "Бетховен", "Брамс", "Верди", "Вагнер", "Моцарт", "Шопен", "Шуберт", "Шуман", "Рахманинов",
    "Прокофьев", "Стравинский", "Римский-Корсаков", "Чайковский", "Дебюсси", "Пуленк", "Дворжак", "Гершвин",
    "Барбер", "Бернстайн", "Копленд", "Пьяццолла", "Респиги", "Глинка", "Мусоргский", "Бородин", "Масканьи",
    "Пуччини", "Россини", "Доницетти", "Беллини", "Бизе", "Гуно", "Массне", "Равель", "Малер", "Брукнер",
]

NON_REPERTOIRE_PATTERNS = [
    "антракт", "без антракта", "с антрактом", "концерт идет", "спектакль идет", "опера идет", "балет идет",
    "представление идет", "продолжительность", "одно отделение", "два отделения", "в одном отделении", "в двух отделениях",
    "без перерыва",
]
CAST_PLACEHOLDER_PATTERNS = [
    "состав исполнителей будет объявлен позднее", "состав будет объявлен позднее", "исполнители будут объявлены позднее",
    "исполнители будут объявлены дополнительно", "состав исполнителей будет объявлен дополнительно", "состав исполнителей уточняется",
    "состав будет уточнен", "состав будет уточнён", "будет объявлен позднее", "будут объявлены позднее",
    "будет объявлен дополнительно", "будут объявлены дополнительно",
]

BALLET_TITLES = {
    "адажио хаммерклавир", "анна каренина", "арлекинада", "бахчисарайский фонтан", "баядерка", "видение розы",
    "вечер балетов", "времена года", "дон кихот", "жар птица", "жар-птица", "жизель", "золушка", "кармен-сюита",
    "карнавал шехеразада", "конек горбунок", "конёк горбунок", "корсар", "лебединое озеро", "легенда о любви",
    "манон", "марко спада", "медный всадник", "пахита", "петрушка", "пламя парижа", "раймонда", "ромео и джульетта",
    "сильфида", "спартак", "спящая красавица", "тысяча и одна ночь", "шехеразада", "шопениана", "щелкунчик",
}
BALLET_GENRE_LINES = {
    "балет", "балеты", "балет в одном действии", "балет в двух действиях", "балет в трех действиях", "балет в трёх действиях",
    "одноактный балет", "одноактные балеты", "вечер балетов", "хореографическая миниатюра", "хореографические миниатюры",
}
OPERA_GENRE_LINES = {
    "опера", "оперы", "опера в одном действии", "опера в двух действиях", "опера в трех действиях", "опера в трёх действиях",
    "опера-буффа", "драма в музыке", "музыкальная драма",
}
OPERA_TITLE_MARKERS = {
    "аида", "набукко", "травиата", "тоска", "богема", "кармен", "фауст", "риголетто", "отелло", "турандот",
    "евгений онегин", "пиковая дама", "царская невеста", "садко", "борис годунов", "хованщина", "князь игорь",
    "золото рейна", "валькирия", "зигфрид", "гибель богов", "летучий голландец", "лоэнгрин", "тристан и изольда",
}
CONCERT_TITLE_MARKERS = ["концерт", "симфонический вечер", "камерный вечер", "реквием", "месса", "оратория", "кантата"]


def load_rules(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid rules JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Rules file must contain a JSON object: {path}")
    return data


def rule_list(rules, name, fallback):
    value = rules.get(name, fallback)
    if not isinstance(value, list):
        raise RuntimeError(f"Rule '{name}' must be a list")
    return value


def rule_set(rules, name, fallback):
    return set(rule_list(rules, name, sorted(fallback) if isinstance(fallback, set) else list(fallback)))


RULES = load_rules(RULES_FILE)
EXTERNAL_STAGE_MARKERS = rule_list(RULES, "external_stage_markers", EXTERNAL_STAGE_MARKERS)
BAD_TITLES = rule_set(RULES, "bad_titles", BAD_TITLES)
PERFORMER_WORDS = rule_list(RULES, "performer_markers", PERFORMER_WORDS)
ROLE_WORDS = rule_list(RULES, "role_markers", ROLE_WORDS)
ENSEMBLE_WORDS = rule_list(RULES, "ensemble_markers", ENSEMBLE_WORDS)
PROGRAM_WORDS = rule_list(RULES, "program_markers", PROGRAM_WORDS)
PROGRAM_START_WORDS = rule_list(RULES, "program_start_markers", PROGRAM_START_WORDS)
COMPOSERS = rule_list(RULES, "composer_aliases", COMPOSERS)
NON_REPERTOIRE_PATTERNS = rule_list(RULES, "non_repertoire_patterns", NON_REPERTOIRE_PATTERNS)
CAST_PLACEHOLDER_PATTERNS = rule_list(RULES, "cast_placeholder_patterns", CAST_PLACEHOLDER_PATTERNS)
BALLET_TITLES = rule_set(RULES, "ballet_titles", BALLET_TITLES)
BALLET_GENRE_LINES = rule_set(RULES, "ballet_genre_lines", BALLET_GENRE_LINES)
OPERA_GENRE_LINES = rule_set(RULES, "opera_genre_lines", OPERA_GENRE_LINES)
OPERA_TITLE_MARKERS = rule_set(RULES, "opera_title_markers", OPERA_TITLE_MARKERS)
CONCERT_TITLE_MARKERS = rule_list(RULES, "concert_title_markers", CONCERT_TITLE_MARKERS)


@dataclass
class ParsedEvent:
    source: str
    url: str
    title: str
    venue: str
    date_text: str
    time_text: str
    event_date: str
    event_type: str
    performers: list[str] = field(default_factory=list)
    program: list[str] = field(default_factory=list)
    digest: str = ""
    skip_reason: str = ""

    def to_state_record(self):
        return asdict(self)


def clean(s):
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def key(s):
    return clean(s).lower().replace("ё", "е")


def canonical_low(s):
    return key(s).replace("cостав", "состав")


def title_key(s):
    s = canonical_low(s)
    s = re.sub(r"[«»\"'()\[\]{}.,:;!?]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_moscow():
    return datetime.now(TZ).date()


def normalize_url(url):
    return urldefrag(url)[0]


def digest_obj(obj):
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def fetch(url):
    last_exc = None
    for attempt in range(1, 4):
        try:
            r = SESSION.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
    raise last_exc


def month_urls(root, months_ahead):
    today = today_moscow()
    urls = [root]
    y, m = today.year, today.month
    for offset in range(months_ahead + 1):
        yy = y + (m - 1 + offset) // 12
        mm = (m - 1 + offset) % 12 + 1
        urls.append(urljoin(root, f"{yy}/{mm}/"))
    return list(dict.fromkeys(urls))


def is_subscription_line(line):
    low = canonical_low(line)
    return "абонемент" in low or "абонементы" in low


def is_non_repertoire_info(line):
    low = canonical_low(line)
    return any(p in low for p in NON_REPERTOIRE_PATTERNS)


def is_cast_placeholder_line(line):
    low = canonical_low(line)
    return any(p in low for p in CAST_PLACEHOLDER_PATTERNS)


def is_noise(line):
    line = clean(line)
    if not line:
        return True
    if is_subscription_line(line) or is_non_repertoire_info(line) or is_cast_placeholder_line(line):
        return True
    return bool(NOISE_RE.search(line)) or bool(MENU_RE.fullmatch(line))


def contains_word(line, words):
    low = key(line)
    return any(w.lower().replace("ё", "е") in low for w in words)


def has_composer(line):
    low = key(line)
    return any(c.lower().replace("ё", "е") in low for c in COMPOSERS)


def html_lines(html_or_soup, stop_re=None):
    soup = BeautifulSoup(html_or_soup, "lxml") if isinstance(html_or_soup, str) else html_or_soup
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    out = []
    prev = None
    for raw in soup.get_text("\n").splitlines():
        line = clean(raw)
        if FOOTER_RE.fullmatch(line):
            break
        if stop_re and stop_re.fullmatch(line):
            break
        if is_noise(line) or line == prev:
            continue
        out.append(line)
        prev = line
    return merge_performer_role_lines(out)


def is_date_line(line):
    return bool(re.search(r"\b\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", key(line)))


def is_time_line(line):
    return bool(re.fullmatch(r"\d{1,2}[:.]\d{2}", clean(line)))


def parse_ru_date(line):
    m = re.search(r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})\b", key(line))
    if not m:
        return None, ""
    d, month_word, y = int(m.group(1)), m.group(2), int(m.group(3))
    month = MONTH_NUM[month_word]
    return date(y, month, d), f"{d} {MONTHS[month]} {y}"


def parse_time(line):
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", clean(line))
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def is_valid_title(title):
    title = clean(title)
    low = canonical_low(title)
    if not title or len(title) < 3:
        return False
    if low in BAD_TITLES or "cookie" in low or "согласие на использование" in low:
        return False
    if is_subscription_line(title) or is_non_repertoire_info(title) or is_cast_placeholder_line(title):
        return False
    if re.fullmatch(r"[\d\W_]+", title) or re.fullmatch(r"\d{1,2}\s+[а-яё]+", low):
        return False
    return True


def title_from_soup(soup, fallback=""):
    for selector in ["h1", "h2", ".title", ".event-title"]:
        for tag in soup.select(selector):
            title = clean(tag.get_text(" ", strip=True))
            if is_valid_title(title):
                return title
    if is_valid_title(fallback):
        return clean(fallback)
    for line in html_lines(soup):
        if is_valid_title(line) and not is_date_line(line) and not is_time_line(line) and line not in MARIINSKY_VENUES:
            return line
    return "Без названия"


def date_text_from_parts(year, month, day):
    y, m, d = int(year), int(month), int(day)
    return date(y, m, d), f"{d} {MONTHS[m]} {y}"


def parse_mariinsky_date(url):
    m = re.search(r"/playbill/playbill/(\d{4})/(\d{1,2})/(\d{1,2})/(\d+)_(\d{4})/", url)
    if not m:
        return None, "", "", "Мариинский театр"
    event_date, date_text = date_text_from_parts(m.group(1), m.group(2), m.group(3))
    time_raw = m.group(5)
    venue = VENUE_BY_CODE.get(m.group(4), "Мариинский театр")
    return event_date, date_text, f"{time_raw[:2]}:{time_raw[2:]}", venue


def date_line(record):
    date_text = clean(record.get("date_text", ""))
    time_text = clean(record.get("time_text", ""))
    if date_text and time_text:
        return f"{EMOJI_DATE} {date_text}. {time_text}"
    if date_text:
        return f"{EMOJI_DATE} {date_text}"
    if time_text:
        return f"{EMOJI_DATE} {time_text}"
    return ""


def source_line(record):
    source = record.get("source", "")
    venue = clean(record.get("venue", ""))
    if source == "mariinsky":
        return f"{MARIINSKY_MARK} {venue or 'Мариинский театр'}"
    if source == "philharmonia_grand":
        return venue or SOURCES["philharmonia_grand"]
    return venue or SOURCES.get(source, "Афиша")


def is_ballet_genre_line(line):
    low = title_key(line)
    if low in BALLET_GENRE_LINES:
        return True
    if low.startswith("вечер балетов"):
        return True
    if re.fullmatch(r"балет(ы)?(\s+в\s+.+\s+действиях?)?", low):
        return True
    return False


def is_opera_genre_line(line):
    low = title_key(line)
    if low in OPERA_GENRE_LINES:
        return True
    if re.fullmatch(r"опера(\s+в\s+.+\s+действиях?)?", low):
        return True
    return False


def is_ballet_event(title, lines):
    t = title_key(title)
    if t in BALLET_TITLES:
        return True, "ballet_title"
    for ballet_title in BALLET_TITLES:
        if t.startswith(ballet_title + " ") or t.endswith(" " + ballet_title):
            return True, "ballet_title_partial"
    for line in lines:
        if is_ballet_genre_line(line):
            return True, "ballet_genre"
    return False, ""


def classify_event(title, lines):
    is_ballet, reason = is_ballet_event(title, lines)
    if is_ballet:
        return "ballet", reason
    t = title_key(title)
    if t in OPERA_TITLE_MARKERS or any(is_opera_genre_line(line) for line in lines):
        return "opera", "opera_marker"
    if has_composer(title) or contains_word(title, PROGRAM_WORDS) or contains_word(title, CONCERT_TITLE_MARKERS):
        return "concert", "title_music_marker"
    if any(has_composer(line) or contains_word(line, PROGRAM_WORDS) or contains_word(line, CONCERT_TITLE_MARKERS) for line in lines[:80]):
        return "concert", "content_music_marker"
    return "unknown", "no_strong_marker"


def looks_like_person_name_single(line):
    line = clean(line).strip("()[]")
    if not line or is_noise(line) or is_date_line(line) or is_time_line(line):
        return False
    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False
    words = [w for w in re.split(r"\s+", line.replace(".", " ")) if w]
    if not (1 <= len(words) <= 4):
        return False
    return all(re.match(r"^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+$", w) for w in words)


def looks_like_person_list(line):
    line = clean(line)
    if not line or is_noise(line):
        return False
    parts = [p for p in re.split(r"\s*,\s*|\s*;\s*", line) if clean(p)]
    if not parts:
        return False
    return all(looks_like_person_name_single(p) for p in parts)


def looks_like_ensemble_phrase(line):
    if is_noise(line) or is_date_line(line) or is_time_line(line):
        return False
    low = key(line)
    return any(w in low for w in ENSEMBLE_WORDS) and not re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low)


def role_only_prefix(line):
    line = clean(line)
    m = re.match(r"^(.+?)\s*[-–—:]\s*$", line)
    if not m:
        return ""
    role = clean(m.group(1))
    return role if contains_word(role, ROLE_WORDS) else ""


def merge_performer_role_lines(lines):
    merged = []
    i = 0
    while i < len(lines):
        line = clean(lines[i])
        role = role_only_prefix(line)
        if role:
            if i + 1 < len(lines):
                nxt = clean(lines[i + 1])
                if looks_like_person_list(nxt) or looks_like_ensemble_phrase(nxt):
                    merged.append(f"{role} — {nxt}")
                    i += 2
                    continue
            i += 1
            continue
        merged.append(line)
        i += 1
    return merged


def is_labeled_performer_line(line):
    m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", clean(line))
    if not m:
        return False
    label, rest = clean(m.group(1)), clean(m.group(2))
    if not rest or is_noise(rest):
        return False
    return contains_word(label, ROLE_WORDS) or contains_word(label, PERFORMER_WORDS)


def starts_like_program_work(line):
    low = key(line)
    return any(low.startswith(w) for w in PROGRAM_START_WORDS) or bool(re.match(r"^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+\.\s+", clean(line)))


def is_ensemble_performer_line(line):
    line = clean(line)
    low = key(line)
    if not contains_word(line, ENSEMBLE_WORDS):
        return False
    if starts_like_program_work(line):
        return False
    if re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low):
        return False
    if re.match(r"^(симфонический|камерный|струнный|духовой|детский|женский|мужской|смешанный)?\s*(оркестр|хор|ансамбль)\b", low):
        return True
    return "мариинск" in low or "филармони" in low or "театра" in low


def is_ballet_or_opera_staff_line(line):
    low = key(line)
    if "балет" not in low and "опера" not in low:
        return False
    return contains_word(line, ["артист", "артисты", "труппа", "солист", "солисты", "исполн"])


def is_performer_line(line):
    line = clean(line)
    if is_noise(line) or role_only_prefix(line) or is_cast_placeholder_line(line):
        return False
    if is_labeled_performer_line(line) or is_ensemble_performer_line(line) or is_ballet_or_opera_staff_line(line):
        return True
    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False
    return contains_word(line, PERFORMER_WORDS) or (line.startswith(":") and "," in line)


def is_program_line(line, title):
    line = clean(line)
    if is_noise(line) or is_subscription_line(line) or is_non_repertoire_info(line) or is_cast_placeholder_line(line):
        return False
    if is_date_line(line) or is_time_line(line) or key(line) == key(title):
        return False
    if line in MARIINSKY_VENUES or is_ballet_genre_line(line) or is_opera_genre_line(line):
        return False
    if is_performer_line(line):
        return False
    if "балет" in key(line) and not (contains_word(line, PROGRAM_WORDS) or has_composer(line)):
        return False
    return contains_word(line, PROGRAM_WORDS) or has_composer(line) or "«" in line or "»" in line


def split_people(text):
    text = clean(text).strip(" :;,-–—")
    return [clean(x) for x in re.split(r"\s*,\s*|\s*;\s*", text) if clean(x)]


def performer_items_from_line(line):
    line = clean(line)
    if not line or role_only_prefix(line) or is_subscription_line(line) or is_non_repertoire_info(line) or is_cast_placeholder_line(line):
        return []
    if line.startswith(":"):
        return split_people(line[1:])
    m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", line)
    if m:
        label, rest = clean(m.group(1)), clean(m.group(2))
        people = split_people(rest)
        if not people:
            return []
        if contains_word(label, PERFORMER_WORDS):
            if len(people) > 1:
                return [f"{label} — {p}" for p in people]
            return [f"{label} — {people[0]}"]
        return [line]
    if "," in line and not contains_word(line, PROGRAM_WORDS):
        return split_people(line)
    return [line]


def uniq(items):
    out = []
    seen = set()
    for item in items:
        item = clean(item)
        k = key(item)
        if item and k not in seen:
            out.append(item)
            seen.add(k)
    return out


def filter_items(items):
    return uniq([
        x for x in items
        if clean(x)
        and not is_subscription_line(x)
        and not is_non_repertoire_info(x)
        and not is_cast_placeholder_line(x)
        and not is_noise(x)
    ])


def extract_performers(lines):
    items = []
    for line in lines:
        if is_performer_line(line):
            items.extend(performer_items_from_line(line))
    return filter_items(items)


def extract_program(lines, title):
    return filter_items([line for line in lines if is_program_line(line, title)])


def build_event_record(source, url, title, venue, event_date, date_text, time_text, lines, event_type, skip_reason=""):
    performers = extract_performers(lines)
    program = extract_program(lines, title)
    core = {
        "title": clean(title),
        "venue": clean(venue),
        "date_text": clean(date_text),
        "time_text": clean(time_text),
        "event_type": event_type,
        "performers": performers,
        "program": program,
    }
    return ParsedEvent(
        source=source,
        url=url,
        title=core["title"] or "Без названия",
        venue=core["venue"],
        date_text=core["date_text"],
        time_text=core["time_text"],
        event_date=event_date.isoformat() if isinstance(event_date, date) else "",
        event_type=event_type,
        performers=performers,
        program=program,
        digest=digest_obj(core),
        skip_reason=skip_reason,
    )


def audit_item(url, source, status, reason, title="", venue="", date_text="", time_text="", event_type="", performers_count=0, program_count=0, error=""):
    return {
        "url": url,
        "source": source,
        "status": status,
        "reason": reason,
        "title": clean(title),
        "venue": clean(venue),
        "date_text": clean(date_text),
        "time_text": clean(time_text),
        "event_type": event_type,
        "performers_count": performers_count,
        "program_count": program_count,
        "error": clean(error),
    }


def parse_mariinsky_event(url, fallback=""):
    event_date, date_text, time_text, venue = parse_mariinsky_date(url)
    soup = BeautifulSoup(fetch(url), "lxml")
    lines = html_lines(soup, stop_re=MARIINSKY_STOP_RE)
    title = title_from_soup(soup, fallback)

    if not is_valid_title(title):
        return None, audit_item(
            url, "mariinsky", "skipped", "bad_title",
            title=title, venue=venue, date_text=date_text, time_text=time_text
        )

    for v in MARIINSKY_VENUES:
        if any(v.lower() == line.lower() for line in lines):
            venue = v
            break

    external_stage_check_lines = [venue, title] + list(lines[:20])
    if any(
        key(marker) not in {"рсо", "алания"}
        and key(marker)
        and key(marker) in key(line)
        for marker in EXTERNAL_STAGE_MARKERS
        for line in external_stage_check_lines
    ):
        return None, audit_item(
            url, "mariinsky", "skipped", "external_stage",
            title=title, venue=venue, date_text=date_text, time_text=time_text
        )

    event_type, class_reason = classify_event(title, lines)

    if event_type == "ballet":
        return None, audit_item(
            url, "mariinsky", "skipped", class_reason,
            title=title, venue=venue, date_text=date_text, time_text=time_text, event_type=event_type
        )

    rec = build_event_record("mariinsky", url, title, venue, event_date, date_text, time_text, lines, event_type)

    return rec, audit_item(
        url, "mariinsky", "included", class_reason,
        title=rec.title, venue=rec.venue, date_text=rec.date_text, time_text=rec.time_text,
        event_type=rec.event_type, performers_count=len(rec.performers), program_count=len(rec.program)
    )


def is_philharmonia_event_url(url):
    parsed = urlparse(url)
    path = parsed.path or ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    keys = set(query.keys())
    if not path.startswith("/afisha/grand/"):
        return False
    if keys & PHILHARMONIA_FORBIDDEN_QUERY_KEYS:
        return False
    if parsed.query:
        return bool(keys & PHILHARMONIA_EVENT_QUERY_KEYS)
    if path.rstrip("/") == "/afisha/grand":
        return False
    tail = path[len("/afisha/grand/"):].strip("/")
    return bool(tail and (re.search(r"(^|/)\d{3,}($|/)", tail) or (len(tail.split("/")) >= 2 and re.search(r"\d", tail))))


def parse_philharmonia_event(url, fallback=""):
    if not is_philharmonia_event_url(url):
        return None, audit_item(url, "philharmonia_grand", "skipped", "not_event_url")
    soup = BeautifulSoup(fetch(url), "lxml")
    lines = html_lines(soup)
    title = title_from_soup(soup, fallback)
    if not is_valid_title(title):
        return None, audit_item(url, "philharmonia_grand", "skipped", "bad_title", title=title)
    event_date = None
    date_text = ""
    time_text = ""
    for line in lines[:80]:
        if not date_text:
            event_date, date_text = parse_ru_date(line)
        if not time_text:
            time_text = parse_time(line)
    if not date_text or not time_text:
        return None, audit_item(url, "philharmonia_grand", "skipped", "missing_date_or_time", title=title, date_text=date_text, time_text=time_text)
    event_type, class_reason = classify_event(title, lines)
    if event_type == "ballet":
        event_type = "concert"
        class_reason = "philharmonia_treat_ballet_reference_as_concert"
    rec = build_event_record("philharmonia_grand", url, title, SOURCES["philharmonia_grand"], event_date, date_text, time_text, lines, event_type)
    return rec, audit_item(
        url, "philharmonia_grand", "included", class_reason,
        title=rec.title, venue=rec.venue, date_text=rec.date_text, time_text=rec.time_text,
        event_type=rec.event_type, performers_count=len(rec.performers), program_count=len(rec.program)
    )


def extract_mariinsky_links_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    pat = re.compile(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_\d{4}/")
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if not pat.search(href):
            continue
        url = normalize_url(urljoin(base_url, href))
        text = clean(a.get_text(" ", strip=True))
        out.setdefault(url, text if is_valid_title(text) else "")
    return out


def extract_philharmonia_links_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        url = normalize_url(urljoin(base_url, a.get("href") or ""))
        if not is_philharmonia_event_url(url):
            continue
        text = clean(a.get_text(" ", strip=True))
        out.setdefault(url, text if is_valid_title(text) else "")
    return out


def collect_mariinsky_links(audit):
    links = {}
    for url in month_urls(MARIINSKY_ROOT, MONTHS_AHEAD):
        try:
            links.update(extract_mariinsky_links_from_html(fetch(url), url))
        except Exception as exc:
            audit["source_errors"].append({"source": "mariinsky", "url": url, "error": f"{type(exc).__name__}: {exc}"})
    return links


def collect_philharmonia_links(audit):
    try:
        return extract_philharmonia_links_from_html(fetch(PHILHARMONIA_ROOT), PHILHARMONIA_ROOT)
    except Exception as exc:
        audit["source_errors"].append({"source": "philharmonia_grand", "url": PHILHARMONIA_ROOT, "error": f"{type(exc).__name__}: {exc}"})
        return {}


def read_source(source, links, parser, audit):
    events = {}
    seen_urls = set(links.keys())
    failed_urls = set()
    for url, fallback in sorted(links.items()):
        try:
            rec, item = parser(url, fallback)
            audit["items"].append(item)
            if rec:
                events[url] = rec.to_state_record()
            time.sleep(0.2)
        except Exception as exc:
            failed_urls.add(url)
            audit["items"].append(audit_item(url, source, "failed", "fetch_or_parse_failed", error=f"{type(exc).__name__}: {exc}"))
    return events, seen_urls, failed_urls


def scan_all():
    audit = {
        "app": APP_NAME,
        "engine_version": "V2",
        "schema_version": SCHEMA_VERSION,
        "filter_version": FILTER_VERSION,
        "run_mode": RUN_MODE,
        "run_at": now_utc(),
        "source_errors": [],
        "items": [],
        "summary": {},
    }
    mariinsky_links = collect_mariinsky_links(audit)
    philharmonia_links = collect_philharmonia_links(audit)
    scanned = {}
    seen_urls = {}
    failed_urls = {}
    scanned["mariinsky"], seen_urls["mariinsky"], failed_urls["mariinsky"] = read_source("mariinsky", mariinsky_links, parse_mariinsky_event, audit)
    scanned["philharmonia_grand"], seen_urls["philharmonia_grand"], failed_urls["philharmonia_grand"] = read_source("philharmonia_grand", philharmonia_links, parse_philharmonia_event, audit)
    for source in SOURCES:
        source_items = [x for x in audit["items"] if x["source"] == source]
        audit["summary"][source] = {
            "links_found": len(mariinsky_links if source == "mariinsky" else philharmonia_links),
            "included": sum(1 for x in source_items if x["status"] == "included"),
            "skipped": sum(1 for x in source_items if x["status"] == "skipped"),
            "failed": sum(1 for x in source_items if x["status"] == "failed"),
        }
    return scanned, seen_urls, failed_urls, audit


def parse_event_date(record):
    try:
        return date.fromisoformat(record.get("event_date", ""))
    except Exception:
        return None


def is_future_removed(record):
    event_date = parse_event_date(record)
    if event_date is None:
        return True
    return event_date > today_moscow()


def set_diff(old_items, new_items):
    old_items = filter_items(old_items or [])
    new_items = filter_items(new_items or [])
    old_map = {key(x): clean(x) for x in old_items if clean(x)}
    new_map = {key(x): clean(x) for x in new_items if clean(x)}
    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]
    return added, removed


def section_added_removed(title, added, removed):
    added = filter_items(added)
    removed = filter_items(removed)
    if not added and not removed:
        return ""
    parts = [title, ""]
    if added:
        parts += [f"{EMOJI_ADDED} Добавлено:"] + added + [""]
    if removed:
        parts += [f"{EMOJI_REMOVED} Удалено:"] + removed + [""]
    while parts and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)


def before_after(title, old, new):
    old = clean(old)
    new = clean(new)
    if old == new:
        return ""
    return "\n".join([title, "", f"{EMOJI_REMOVED} Было:", old or "—", "", f"{EMOJI_ADDED} Стало:", new or "—"])


def format_new(record):
    parts = [source_line(record), f"{EMOJI_NEW} Новое событие", "", f"Название: {record.get('title', 'Без названия')}"]
    dt = date_line(record)
    if dt:
        parts.append(dt)
    parts += ["", f"Ссылка: {record.get('url', '')}"]
    return "\n".join(parts).strip()


def format_removed(record):
    parts = [source_line(record), f"{EMOJI_REMOVED} Событие исчезло", "", f"Название: {record.get('title', 'Без названия')}"]
    dt = date_line(record)
    if dt:
        parts.append(dt)
    parts += ["", f"Ссылка: {record.get('url', '')}"]
    return "\n".join(parts).strip()


def change_sections(old, new):
    sections = [
        x for x in [
            before_after("Изменение названия:", old.get("title", ""), new.get("title", "")),
            before_after("Изменение даты / времени:", date_line(old), date_line(new)),
            before_after("Изменение площадки:", source_line(old), source_line(new)),
        ] if x
    ]
    perf_added, perf_removed = set_diff(old.get("performers", []), new.get("performers", []))
    prog_added, prog_removed = set_diff(old.get("program", []), new.get("program", []))
    for section in [
        section_added_removed("Изменение в составе:", perf_added, perf_removed),
        section_added_removed("Изменение в программе:", prog_added, prog_removed),
    ]:
        if section:
            sections.append(section)
    return sections


def format_changed(old, new):
    sections = change_sections(old, new)
    if not sections:
        return ""
    parts = [source_line(new), "", f"Название: {new.get('title', 'Без названия')}"]
    dt = date_line(new)
    if dt:
        parts.append(dt)
    parts.append(sections[0])
    for section in sections[1:]:
        parts += ["", section]
    parts += ["", f"Ссылка: {new.get('url', '')}"]
    return "\n".join(parts).strip()


def default_state():
    return {
        "app": APP_NAME,
        "engine_version": "V2",
        "schema_version": SCHEMA_VERSION,
        "filter_version": FILTER_VERSION,
        "updated_at": now_utc(),
        "sources": {s: {"events": {}} for s in SOURCES},
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
    state.setdefault("sources", {})
    state.setdefault("pending_messages", [])
    for source in SOURCES:
        state["sources"].setdefault(source, {}).setdefault("events", {})
    return state


def is_uninitialized_state(state):
    if not isinstance(state, dict):
        return True
    if state.get("app") or state.get("engine_version") or state.get("updated_at"):
        return False
    sources = state.get("sources", {})
    if not isinstance(sources, dict):
        return True
    return not any(
        source_data.get("events")
        for source_data in sources.values()
        if isinstance(source_data, dict)
    )


def save_state(state):
    state["app"] = APP_NAME
    state["engine_version"] = "V2"
    state["schema_version"] = SCHEMA_VERSION
    state["filter_version"] = FILTER_VERSION
    state["updated_at"] = now_utc()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def save_audit(audit):
    AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def build_messages(old_events, new_events, seen_urls, failed_urls):
    messages = []
    for url, new in sorted(new_events.items()):
        old = old_events.get(url)
        if old is None:
            messages.append(format_new(new))
        elif old.get("digest") != new.get("digest"):
            msg = format_changed(old, new)
            if msg:
                messages.append(msg)
    for url, old in sorted(old_events.items()):
        if url in new_events or url in failed_urls or url in seen_urls:
            continue
        if is_future_removed(old):
            messages.append(format_removed(old))
    return messages


def add_pending(state, messages):
    state.setdefault("pending_messages", []).extend(messages)
    if len(state["pending_messages"]) > PENDING_WARNING_THRESHOLD:
        print(f"WARNING: pending_messages is {len(state['pending_messages'])}, above threshold {PENDING_WARNING_THRESHOLD}. Nothing was truncated.")


def chunks(text, limit=3900):
    if len(text) <= limit:
        return [text]
    out = []
    cur = ""
    for block in text.split("\n\n"):
        nxt = block if not cur else cur + "\n\n" + block
        if len(nxt) <= limit:
            cur = nxt
        else:
            if cur:
                out.append(cur)
            cur = block
    if cur:
        out.append(cur)
    return out


def send_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets are missing; message was not sent.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in chunks(text):
        for attempt in range(1, 5):
            response = SESSION.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True}, timeout=30)
            if response.status_code == 429:
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after") or 30)
                except (ValueError, TypeError, requests.RequestException):
                    retry_after = 30
                print(f"Telegram rate limit. Sleeping {retry_after} seconds before retry.")
                time.sleep(retry_after)
                continue
            try:
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt >= 4:
                    raise
                time.sleep(2 * attempt)
        else:
            raise RuntimeError("Telegram message was not sent after retries.")


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
    if "mariinsky.ru" in url:
        rec, item = parse_mariinsky_event(normalize_url(url), "")
    elif "philharmonia.spb.ru" in url:
        rec, item = parse_philharmonia_event(normalize_url(url), "")
    else:
        raise ValueError("Unsupported DEBUG_URL")
    payload = {"audit": item, "record": rec.to_state_record() if rec else None}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main():
    if RUN_MODE not in {"dry_run", "bootstrap", "live"}:
        raise RuntimeError("RUN_MODE must be dry_run, bootstrap, or live")
    if DEBUG_URL:
        debug_single_url(DEBUG_URL)
        return
    scanned, seen_urls, failed_urls, audit = scan_all()
    save_audit(audit)
    old_state = load_state()
    if old_state is None or is_uninitialized_state(old_state):
        new_state = default_state()
        for source in SOURCES:
            new_state["sources"][source]["events"] = scanned[source]
        if RUN_MODE == "dry_run":
            print("DRY_RUN: no state exists. Current scan was audited but state was not created.")
            return
        save_state(new_state)
        print("No previous V2 state. Baseline created without Telegram messages.")
        return
    messages = []
    for source in SOURCES:
        old_events = old_state.get("sources", {}).get(source, {}).get("events", {})
        messages.extend(build_messages(old_events, scanned[source], seen_urls[source], failed_urls[source]))
    audit["would_notify_count"] = len(messages)
    audit["would_notify_preview"] = messages[:20]
    save_audit(audit)
    if RUN_MODE == "dry_run":
        print(f"DRY_RUN: would queue {len(messages)} messages. State was not changed.")
        for msg in messages[:20]:
            print("--- WOULD NOTIFY ---")
            print(msg)
        return
    for source in SOURCES:
        old_state.setdefault("sources", {}).setdefault(source, {})["events"] = scanned[source]
    if RUN_MODE == "bootstrap":
        save_state(old_state)
        print(f"BOOTSTRAP: state refreshed. {len(messages)} possible messages were not queued or sent.")
        return
    if messages:
        add_pending(old_state, messages)
        print(f"Queued messages: {len(messages)}. Pending total: {len(old_state.get('pending_messages', []))}")
    else:
        print("No repertoire-significant changes.")
    try:
        sent = flush_pending(old_state)
    except Exception as exc:
        print(f"Telegram send stopped: {type(exc).__name__}: {exc}")
        sent = 0
    save_state(old_state)
    print(f"Telegram messages sent this run: {sent}. Pending left: {len(old_state.get('pending_messages', []))}")


def run_self_tests():
    assert SCHEMA_VERSION == 2
    assert FILTER_VERSION == "V2.0"
    assert "опера" not in PROGRAM_WORDS
    assert "балет" not in PROGRAM_WORDS
    assert date_line({"date_text": "22 июля 2026", "time_text": "20:00"}) == "🔸 22 июля 2026. 20:00"

    event_type, reason = classify_event("Бетховен. Торжественная месса", ["Солисты оперы", "Хор", "Симфонический оркестр Мариинского театра"])
    assert event_type == "concert", (event_type, reason)
    assert not is_ballet_event("Бетховен. Торжественная месса", ["Сюита из балета «Весна в Аппалачах»"])[0]
    assert is_ballet_event("Лебединое озеро", ["Дирижер — Андрей Иванов"])[0]
    assert is_ballet_event("Спящая красавица", ["Балет", "Дирижер — Валерий Овсяников"])[0]
    assert is_ballet_event("Марко Спада", ["Дирижер — Иванов"])[0]
    assert classify_event("Аида", ["Опера", "Дирижер — Валерий Гергиев"])[0] == "opera"
    assert is_performer_line("Солисты оперы Мариинского театра")
    assert not is_program_line("Опера в четырех действиях", "Аида")
    assert is_program_line("Бетховен. Торжественная месса", "Бетховен. Торжественная месса") is False
    assert is_program_line("Бетховен. Месса до мажор", "Концерт")
    assert is_program_line("Копленд. Сюита из балета «Весна в Аппалачах»", "Симфонический вечер")

    lines = html_lines("""
    <html><body>
    <h1>Бетховен. Торжественная месса</h1>
    <p>Мариинский-2</p>
    <p>Солист –</p>
    <p>Лоренц Настурика-Гершовичи</p>
    <p>Солисты оперы, Хор, Детский хор и Симфонический оркестр Мариинского театра</p>
    <p>Концерт идет без антракта</p>
    <p>Полная программа</p>
    <p>Бетховен. Торжественная месса</p>
    <p>Возрастная категория 6+</p>
    </body></html>
    """, stop_re=MARIINSKY_STOP_RE)
    text = "\n".join(lines)
    assert "Солист — Лоренц Настурика-Гершовичи" in text
    assert "Концерт идет без антракта" not in text
    assert "Полная программа" not in text
    assert "Бетховен. Торжественная месса" in text
    performers = extract_performers(lines)
    assert "Солист — Лоренц Настурика-Гершовичи" in performers
    assert any("Солисты оперы" in x for x in performers)

    old = {}
    new = {"u": {"url": "u", "source": "mariinsky", "title": "Новый концерт", "venue": "Мариинский-2", "date_text": "22 июля 2026", "time_text": "20:00", "event_date": "2026-07-22", "performers": [], "program": [], "digest": "1"}}
    msgs = build_messages(old, new, set(new), set())
    assert len(msgs) == 1 and "Новое событие" in msgs[0]
    state = default_state()
    add_pending(state, ["x"] * (PENDING_WARNING_THRESHOLD + 1))
    assert len(state["pending_messages"]) == PENDING_WARNING_THRESHOLD + 1
    print("SELF_TEST_OK")


if __name__ == "__main__":
    if SELF_TEST:
        run_self_tests()
    else:
        main()
