import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urldefrag, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

APP_NAME = "Mariinsky Filter V2"
SCHEMA_VERSION = 2
FILTER_VERSION = "V2.7.1-meaningful-diff-only"

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "scan_audit.json"))
RUN_MODE = os.getenv("RUN_MODE", "dry_run").strip().lower()
DEBUG_URL = os.getenv("DEBUG_URL", "").strip()
SELF_TEST = os.getenv("SELF_TEST", "0") == "1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
MAX_TELEGRAM_MESSAGES_PER_RUN = int(os.getenv("MAX_TELEGRAM_MESSAGES_PER_RUN", "20"))
MESSAGE_SEND_DELAY_SECONDS = float(os.getenv("MESSAGE_SEND_DELAY_SECONDS", "1.5"))
MONTHS_AHEAD = int(os.getenv("MONTHS_AHEAD", "8"))

MARIINSKY_ROOT = "https://www.mariinsky.ru/playbill/playbill/"
PHILHARMONIA_ROOTS = [
    "https://www.philharmonia.spb.ru/afisha/grand/",
    "https://philharmonia.spb.ru/afisha/grand/",
]
TZ = ZoneInfo("Europe/Moscow")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 MariinskyWatcherV2/2.7.1 (+https://github.com/fageehamalal-max/mariinsky-watcher)",
    "Accept-Language": "ru,en;q=0.9",
})

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

BAD_TITLES = {
    "афиша", "афиша и билеты", "большой зал", "главная", "репертуар",
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    "cookie", "cookies", "использование cookies", "согласие на использование cookie", "согласие на использование cookies",
}

EXTERNAL_STAGE_MARKERS = ["Приморская сцена", "Владивосток", "Владикавказ", "РСО-Алания"]

MENU_RE = re.compile(
    r"^(Афиша и билеты|Подарочные карты|Детям|Визит в театр|Труппа|О театре|Новости|Для прессы|Афиша|Абонементы|Фестивали|Репертуар|Изменения в афише|Выбрать сцену|Все площадки|Все спектакли|Архив афиши|Полная программа)$",
    re.I,
)
FOOTER_RE = re.compile(
    r"^(Для обращений|Справочная служба|По вопросам реализации билетов|Скачать мобильное приложение|Любое использование|Закрыть|Вход в личный кабинет|Официальные билеты|Поделиться)$",
    re.I,
)
MARIINSKY_STOP_RE = re.compile(
    r"^(Возрастная категория(\s*\d+\+?)?|XXXIV\s+Музыкальный фестиваль.*Зв[её]зды белых ночей|Музыкальный фестиваль.*Зв[её]зды белых ночей|Зв[её]зды белых ночей|Краткое содержание|Содержание)$",
    re.I,
)
NOISE_RE = re.compile(
    r"(@@|купить|заказать|продажа|стоимость|цена|билет|билетов|билеты|касс[аеы]|авторизация|войти|регистрация|личный кабинет|cookie|cookies|согласие на использование|подписаться|поиск|версия для слабовидящих|опрос|для обращений|справочная служба|скачать мобильное приложение|mariinsky\.tv|mariinsky\.fm|правообладател|зв[её]здный состав|блестящий состав|история постановки|описание спектакля)",
    re.I,
)

PHILHARMONIA_HOSTS = {"www.philharmonia.spb.ru", "philharmonia.spb.ru"}
PHILHARMONIA_EVENT_KEYS = {"id", "event", "event_id", "ev_id", "ev_z", "concert", "concert_id", "ELEMENT_ID", "ID"}
PHILHARMONIA_LIST_KEYS = {"year", "month", "date", "page", "p", "tag", "tags", "search", "q", "hall", "type", "genre", "series", "abonement"}
PHILHARMONIA_BAD_PATH_PARTS = {"pc", "print", "calendar", "rss", "ical", "ics"}

PERFORMER_WORDS = [
    "дириж", "солист", "солистка", "исполн", "состав", "партию", "партия",
    "сопрано", "тенор", "баритон", "бас", "скрипка", "альт", "виолончель",
    "фортепиано", "орган", "кларнет", "флейта", "хор", "оркестр", "ансамбль",
    "артист", "артисты", "концертмейстер", "режиссер", "режиссёр", "хормейстер",
]
ROLE_WORDS = [
    "дирижер", "дирижёр", "солист", "солистка", "солисты", "исполнитель",
    "исполнительница", "исполнители", "сопрано", "тенор", "баритон", "бас",
    "скрипка", "альт", "виолончель", "фортепиано", "орган", "кларнет", "флейта",
    "хор", "оркестр", "ансамбль", "артист", "артисты", "концертмейстер",
    "режиссер", "режиссёр", "хормейстер",
]
ENSEMBLE_WORDS = ["оркестр", "хор", "ансамбль"]
PROGRAM_WORDS = [
    "симфони", "концерт", "сюита", "увертюр", "сонат", "ноктюрн", "реквием",
    "оратори", "кантат", "рапсод", "адажио", "танц", "прелюди", "фуга",
    "квартет", "квинтет", "месса",
]
COMPOSERS = [
    "Бах", "Бетховен", "Брамс", "Верди", "Вагнер", "Моцарт", "Шопен", "Шуберт",
    "Шуман", "Рахманинов", "Прокофьев", "Стравинский", "Римский-Корсаков",
    "Чайковский", "Дебюсси", "Пуленк", "Дворжак", "Гершвин", "Барбер",
    "Бернстайн", "Копленд", "Пьяццолла", "Респиги", "Глинка", "Мусоргский",
    "Бородин", "Масканьи", "Пуччини", "Россини", "Доницетти", "Беллини",
    "Бизе", "Гуно", "Массне", "Равель", "Малер", "Брукнер", "Шостакович",
]

NON_REPERTOIRE_PATTERNS = [
    "антракт", "без антракта", "с антрактом", "концерт идет", "спектакль идет",
    "опера идет", "балет идет", "представление идет", "продолжительность",
    "одно отделение", "два отделения", "в одном отделении", "в двух отделениях",
    "без перерыва",
]
CAST_PLACEHOLDER_PATTERNS = [
    "состав исполнителей будет объявлен позднее", "состав будет объявлен позднее",
    "исполнители будут объявлены позднее", "исполнители будут объявлены дополнительно",
    "состав исполнителей будет объявлен дополнительно", "состав исполнителей уточняется",
    "состав будет уточнен", "состав будет уточнён", "будет объявлен позднее",
    "будут объявлены позднее", "будет объявлен дополнительно", "будут объявлены дополнительно",
]

BALLET_TITLES = {
    "адажио хаммерклавир", "анна каренина", "арлекинада", "бахчисарайский фонтан",
    "баядерка", "видение розы", "вечер балетов", "времена года", "дон кихот",
    "жар птица", "жар-птица", "жизель", "золушка", "кармен-сюита",
    "карнавал шехеразада", "конек горбунок", "конёк горбунок", "корсар",
    "лебединое озеро", "легенда о любви", "манон", "марко спада",
    "медный всадник", "пахита", "петрушка", "пламя парижа", "раймонда",
    "ромео и джульетта", "сильфида", "спартак", "спящая красавица",
    "тысяча и одна ночь", "шехеразада", "шопениана", "щелкунчик",
    "виктория терешкина 25 лет на сцене", "виктория терёшкина 25 лет на сцене",
}
OPERA_TITLE_MARKERS = {
    "аида", "набукко", "травиата", "тоска", "богема", "кармен", "фауст",
    "риголетто", "отелло", "турандот", "евгений онегин", "пиковая дама",
    "царская невеста", "садко", "борис годунов", "хованщина", "князь игорь",
    "золото рейна", "валькирия", "зигфрид", "гибель богов", "летучий голландец",
    "лоэнгрин", "тристан и изольда", "леди макбет мценского уезда", "нос",
    "сказание о невидимом граде китеже и деве февронии",
}
LIST_BALLET_MARKERS = ["балет", "балета", "балеты", "гала-концерт балета", "артисты балета", "театр балета", "хореография", "хореограф", "па-де-де", "вариация", "исполняется под фонограмму"]
LIST_OPERA_MARKERS = ["опера", "опера-буффа", "драма в музыке", "музыкальная драма"]
LIST_CONCERT_MARKERS = ["концерт", "концерты", "кантата", "оратория", "реквием", "месса", "симфонический оркестр"]

LOCATION_LINES = {
    "санкт петербург", "санкт-петербург", "санкт — петербург", "санкт – петербург",
    "мариинский театр", "мариинский 2", "мариинский-2", "концертный зал", "зал стравинского",
    "камерные залы", "зал щедрина", "зал мусоргского", "концертный зал мариинского театра",
}


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
    s = key(s)
    s = s.replace("cостав", "состав")
    return s


def title_key(s):
    s = canonical_low(s)
    s = re.sub(r"[«»\"'()\[\]{}.,:;!?]+", " ", s)
    s = s.replace("—", " ").replace("–", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_moscow():
    return datetime.now(TZ).date()


def normalize_url(url):
    return urldefrag(url)[0]


def canonical_url(url):
    url = normalize_url(url)
    parsed = urlparse(url)
    if parsed.netloc == "philharmonia.spb.ru":
        return parsed._replace(netloc="www.philharmonia.spb.ru").geturl()
    return url


def digest_obj(obj):
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def fetch(url):
    candidates = [url]
    parsed = urlparse(url)
    if parsed.netloc == "www.philharmonia.spb.ru":
        candidates.append(parsed._replace(netloc="philharmonia.spb.ru").geturl())
    elif parsed.netloc == "philharmonia.spb.ru":
        candidates.append(parsed._replace(netloc="www.philharmonia.spb.ru").geturl())
    last_exc = None
    for attempt in range(1, 4):
        for candidate in dict.fromkeys(candidates):
            try:
                r = SESSION.get(candidate, timeout=30)
                r.raise_for_status()
                if not r.encoding or r.encoding.lower() in {"iso-8859-1", "ascii"}:
                    r.encoding = r.apparent_encoding or "utf-8"
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


def philharmonia_list_urls(months_ahead):
    today = today_moscow()
    urls = []
    for root in PHILHARMONIA_ROOTS:
        urls.append(root)
        y, m = today.year, today.month
        for offset in range(months_ahead + 1):
            yy = y + (m - 1 + offset) // 12
            mm = (m - 1 + offset) % 12 + 1
            urls.extend([
                urljoin(root, f"{yy}/{mm}/"),
                urljoin(root, f"{yy}/{mm:02d}/"),
                root + "?" + urlencode({"year": yy, "month": mm}),
                root + "?" + urlencode({"month": mm, "year": yy}),
            ])
    return list(dict.fromkeys(urls))


def marker_in_text(text, marker):
    low = canonical_low(text)
    marker = canonical_low(marker)
    if not marker:
        return False
    if len(marker) <= 3:
        return bool(re.search(rf"(?<![а-яёa-z]){re.escape(marker)}(?![а-яёa-z])", low, re.I))
    return marker in low


def contains_word(text, words):
    return any(marker_in_text(text, w) for w in words)


def has_composer(text):
    low = canonical_low(text)
    return any(canonical_low(c) in low for c in COMPOSERS)


def is_subscription_line(line):
    low = canonical_low(line)
    return "абонемент" in low or "абонементы" in low


def is_non_repertoire_info(line):
    low = canonical_low(line)
    return any(p in low for p in NON_REPERTOIRE_PATTERNS)


def is_cast_placeholder_line(line):
    low = canonical_low(line)
    return any(p in low for p in CAST_PLACEHOLDER_PATTERNS)


def is_location_line(line):
    low = title_key(line)
    return low in LOCATION_LINES or clean(line) in MARIINSKY_VENUES


def is_genre_description(line):
    low = canonical_low(line)
    genre_starts = [
        "опера ", "оперы ", "балет ", "балеты ", "концерт ", "концерты ",
        "гала-концерт", "симфонический концерт", "камерный концерт",
    ]
    if any(low.startswith(x) for x in genre_starts):
        return True
    if re.fullmatch(r"опера(\s+.+)?", low):
        return True
    return False


def is_explanatory_line(line):
    low = canonical_low(line)
    bad_starts = [
        "к ", "ко ", "посвящается", "к юбилею", "к 120", "к 100", "к 150",
        "в рамках", "при поддержке", "фестиваль", "звезды белых ночей", "звёзды белых ночей",
    ]
    return any(low.startswith(x) for x in bad_starts)


def is_noise(line):
    line = clean(line)
    if not line:
        return True
    if MENU_RE.fullmatch(line) or NOISE_RE.search(line):
        return True
    if is_subscription_line(line) or is_non_repertoire_info(line) or is_cast_placeholder_line(line):
        return True
    return False


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
    return bool(re.search(r"\b\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", canonical_low(line)))


def is_time_line(line):
    return bool(re.fullmatch(r"\d{1,2}[:.]\d{2}", clean(line)))


def parse_ru_date(line):
    m = re.search(r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})\b", canonical_low(line))
    if not m:
        return None, ""
    d, month_word, y = int(m.group(1)), m.group(2), int(m.group(3))
    month = MONTH_NUM[month_word]
    return date(y, month, d), f"{d} {MONTHS[month]} {y}"


def parse_time(line):
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", clean(line))
    if not m:
        return ""
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def first_page_time(lines):
    for line in lines[:120]:
        low = canonical_low(line)
        if low.startswith(("в программе", "программа", "исполнители", "исполнитель")):
            continue
        value = parse_time(line)
        if value:
            return value
    return ""


def is_valid_title(title):
    title = clean(title)
    low = title_key(title)
    if not title or len(title) < 3:
        return False
    if low in BAD_TITLES or "cookie" in low:
        return False
    if is_noise(title) or is_location_line(title):
        return False
    if re.fullmatch(r"[\d\W_]+", title) or re.fullmatch(r"\d{1,2}\s+[а-яё]+", low):
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
        if is_valid_title(line) and not is_date_line(line) and not is_time_line(line):
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


def parse_philharmonia_date_from_url(url):
    m = re.search(r"/afisha/grand/(20\d{2})/(\d{1,2})/(\d{1,2})/", urlparse(url).path)
    if not m:
        return None, ""
    return date_text_from_parts(m.group(1), m.group(2), m.group(3))


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


def infer_mariinsky_list_type(text):
    low = canonical_low(text)
    if any(x in low for x in LIST_BALLET_MARKERS):
        return "ballet"
    if any(x in low for x in LIST_OPERA_MARKERS):
        return "opera"
    if any(x in low for x in LIST_CONCERT_MARKERS):
        return "concert"
    return ""


def mariinsky_card_text_for_link(a):
    link_text = clean(a.get_text(" ", strip=True))
    for parent in a.parents:
        name = getattr(parent, "name", "")
        if name in {"body", "html", "[document]"}:
            break
        if not hasattr(parent, "get_text"):
            continue
        text = clean(parent.get_text(" ", strip=True))
        if not text or len(text) > 2500:
            continue
        if link_text and link_text in text and infer_mariinsky_list_type(text):
            return text
    return link_text


def is_mariinsky_list_ballet_meta(meta):
    if not isinstance(meta, dict):
        return False
    if meta.get("list_type") == "ballet":
        return True
    return infer_mariinsky_list_type(meta.get("list_text", "")) == "ballet"


def fallback_title_from_meta(fallback):
    if isinstance(fallback, dict):
        return clean(fallback.get("title", ""))
    return clean(fallback)


def is_ballet_genre_line(line):
    low = title_key(line)
    if low in {"балет", "балеты", "одноактный балет", "одноактные балеты", "вечер балетов", "хореографическая миниатюра", "хореографические миниатюры"}:
        return True
    return bool(re.fullmatch(r"балет(ы)?(\s+в\s+.+\s+действиях?)?", low))


def is_opera_genre_line(line):
    low = title_key(line)
    if low in {"опера", "оперы", "опера-буффа", "драма в музыке", "музыкальная драма"}:
        return True
    return bool(re.fullmatch(r"опера(\s+в\s+.+\s+действиях?)?", low))


def is_ballet_event(title, lines):
    t = title_key(title)
    if t in BALLET_TITLES:
        return True, "ballet_title"
    for ballet_title in BALLET_TITLES:
        if t.startswith(ballet_title + " ") or t.endswith(" " + ballet_title):
            return True, "ballet_title_partial"
    if any(is_ballet_genre_line(line) for line in lines):
        return True, "ballet_genre"
    text = canonical_low(" ".join([title] + list(lines[:120])))
    hard = ["гала-концерт балета", "артисты балета", "театр балета", "хореография", "хореограф", "па-де-де", "вариация", "исполняется под фонограмму"]
    if any(x in text for x in hard):
        return True, "ballet_content_marker"
    return False, ""


def classify_event(title, lines, list_type=""):
    if list_type == "ballet":
        return "ballet", "list_ballet"
    if list_type == "opera":
        return "opera", "list_opera"
    if list_type == "concert":
        return "concert", "list_concert"
    is_ballet, reason = is_ballet_event(title, lines)
    if is_ballet:
        return "ballet", reason
    t = title_key(title)
    if t in OPERA_TITLE_MARKERS or any(is_opera_genre_line(line) for line in lines):
        return "opera", "opera_marker"
    if has_composer(title) or contains_word(title, PROGRAM_WORDS) or contains_word(title, ["концерт", "симфонический вечер", "камерный вечер", "реквием", "месса", "оратория", "кантата"]):
        return "concert", "title_music_marker"
    if any(has_composer(line) or contains_word(line, PROGRAM_WORDS) for line in lines[:100]):
        return "concert", "content_music_marker"
    return "unknown", "no_strong_marker"


def looks_like_person_name_single(line):
    line = clean(line).strip("()[]")
    if not line or is_noise(line) or is_date_line(line) or is_time_line(line):
        return False
    if is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False
    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False
    words = [w for w in re.split(r"\s+", line.replace(".", " ")) if w]
    if not (1 <= len(words) <= 5):
        return False
    return all(re.match(r"^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+$", w) for w in words)


def looks_like_person_list(line):
    parts = [p for p in re.split(r"\s*,\s*|\s*;\s*", clean(line)) if clean(p)]
    return bool(parts) and all(looks_like_person_name_single(p) for p in parts)


def looks_like_ensemble_phrase(line):
    if is_noise(line) or is_date_line(line) or is_time_line(line) or is_location_line(line):
        return False
    low = canonical_low(line)
    return contains_word(line, ENSEMBLE_WORDS) and not re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low)


def role_only_prefix(line):
    m = re.match(r"^(.+?)\s*[-–—:]\s*$", clean(line))
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
        if role and i + 1 < len(lines):
            nxt = clean(lines[i + 1])
            if looks_like_person_list(nxt) or looks_like_ensemble_phrase(nxt):
                merged.append(f"{role} — {nxt}")
                i += 2
                continue
        if not role:
            merged.append(line)
        i += 1
    return merged


def is_production_credit_label(label):
    low = canonical_low(label)
    prefixes = [
        "хореография", "хореограф", "исполняется под фонограмму", "постановка",
        "сценография", "костюмы", "свет", "видео", "либретто", "автор",
        "режиссер-постановщик", "режиссёр-постановщик",
    ]
    return any(low.startswith(x) for x in prefixes)


def looks_like_opera_role_assignment(label, rest):
    label = clean(label)
    rest = clean(rest)
    low_label = canonical_low(label)
    if not label or not rest:
        return False
    if is_location_line(label) or is_location_line(rest):
        return False
    if is_production_credit_label(label) or is_genre_description(label) or is_genre_description(rest):
        return False
    if low_label.startswith(("опера", "балет", "концерт", "гала-концерт")):
        return False
    if len(label) > 90 or len(rest) > 220:
        return False
    if has_composer(label) or contains_word(label, PROGRAM_WORDS):
        return False
    return looks_like_person_list(rest) or looks_like_person_name_single(rest)


def is_labeled_performer_line(line):
    m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", clean(line))
    if not m:
        return False
    label, rest = clean(m.group(1)), clean(m.group(2))
    if not rest or is_noise(rest):
        return False
    if is_location_line(line) or is_location_line(label) or is_location_line(rest):
        return False
    if is_production_credit_label(label) or is_genre_description(label) or is_genre_description(line):
        return False
    if contains_word(label, ROLE_WORDS) or contains_word(label, PERFORMER_WORDS):
        return looks_like_person_list(rest) or looks_like_ensemble_phrase(rest) or bool(clean(rest))
    return looks_like_opera_role_assignment(label, rest)


def is_ensemble_performer_line(line):
    if is_location_line(line) or is_genre_description(line):
        return False
    if not contains_word(line, ENSEMBLE_WORDS):
        return False
    low = canonical_low(line)
    if re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low):
        return False
    if re.match(r"^(симфонический|камерный|струнный|духовой|детский|женский|мужской|смешанный)?\s*(оркестр|хор|ансамбль)\b", low):
        return True
    return "мариинск" in low or "филармони" in low or "театра" in low


def is_performer_line(line):
    line = clean(line)
    if is_noise(line) or is_location_line(line) or is_cast_placeholder_line(line):
        return False
    if is_production_credit_label(line) or is_genre_description(line) or is_explanatory_line(line):
        return False
    if is_labeled_performer_line(line) or is_ensemble_performer_line(line):
        return True
    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False
    return contains_word(line, PERFORMER_WORDS) or (line.startswith(":") and "," in line)


def is_program_line(line, title):
    line = clean(line)
    if is_noise(line) or is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False
    if is_date_line(line) or is_time_line(line) or title_key(line) == title_key(title):
        return False
    if is_ballet_genre_line(line) or is_opera_genre_line(line) or is_performer_line(line):
        return False
    if has_composer(line):
        words = [w for w in re.split(r"\s+", line) if w]
        if len(words) <= 3 and not any(p in canonical_low(line) for p in PROGRAM_WORDS):
            return False
        return True
    return contains_word(line, PROGRAM_WORDS) or "«" in line or "»" in line


def split_people(text):
    text = clean(text).strip(" :;,-–—")
    return [clean(x) for x in re.split(r"\s*,\s*|\s*;\s*", text) if clean(x)]


def performer_items_from_line(line):
    line = clean(line)
    if not line or not is_performer_line(line):
        return []
    if line.startswith(":"):
        return split_people(line[1:])
    m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", line)
    if m:
        label, rest = clean(m.group(1)), clean(m.group(2))
        if looks_like_opera_role_assignment(label, rest):
            return [f"{label} — {rest}"]
        people = split_people(rest)
        if contains_word(label, PERFORMER_WORDS) and people:
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
        k = normalize_compare_key(item)
        if item and k not in seen:
            out.append(item)
            seen.add(k)
    return out


def filter_items(items):
    return uniq([
        x for x in items
        if clean(x)
        and not is_noise(x)
        and not is_location_line(x)
        and not is_genre_description(x)
        and not is_explanatory_line(x)
        and not is_production_credit_label(x)
    ])


def extract_performers(lines):
    items = []
    for line in lines:
        if is_performer_line(line):
            items.extend(performer_items_from_line(line))
    return filter_items(items)


def extract_program(lines, title):
    return filter_items([line for line in lines if is_program_line(line, title)])


def strip_section_prefix(s):
    s = clean(s).replace("–", "—").replace("-", "—")
    s = re.sub(r"^(исполнители|исполнитель|солисты|состав исполнителей|в программе|программа|полная программа)\s*[—:]\s*", "", s, flags=re.I)
    return clean(s)


def normalize_compare_key(s):
    s = title_key(strip_section_prefix(s))
    return re.sub(r"\s+", " ", s).strip()


def split_performer_for_compare(item):
    item = strip_section_prefix(item)
    if not item or not is_performer_line(item):
        return []
    if "," in item and not has_composer(item):
        parts = [clean(x) for x in item.split(",") if clean(x)]
        if len(parts) > 1:
            return parts
    return [item]


def split_program_for_compare(item):
    item = strip_section_prefix(item)
    if not item or len(item) > 220 or not is_program_line(item, ""):
        return []
    return [item]


def normalized_item_map(items, kind):
    result = {}
    for raw in items or []:
        pieces = split_performer_for_compare(raw) if kind == "performers" else split_program_for_compare(raw)
        for piece in pieces:
            k = normalize_compare_key(piece)
            if k and len(k) >= 3:
                result.setdefault(k, clean(piece))
    return result


def normalized_set_diff(old_items, new_items, kind):
    old_map = normalized_item_map(old_items, kind)
    new_map = normalized_item_map(new_items, kind)
    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]
    return added, removed


def build_event_record(source, url, title, venue, event_date, date_text, time_text, lines, event_type):
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
        url=canonical_url(url),
        title=core["title"] or "Без названия",
        venue=core["venue"],
        date_text=core["date_text"],
        time_text=core["time_text"],
        event_date=event_date.isoformat() if isinstance(event_date, date) else "",
        event_type=event_type,
        performers=performers,
        program=program,
        digest=digest_obj(core),
    )


def audit_item(url, source, status, reason, title="", venue="", date_text="", time_text="", event_type="", performers_count=0, program_count=0, error=""):
    return {
        "url": canonical_url(url),
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
    fallback_title = fallback_title_from_meta(fallback)
    list_type = fallback.get("list_type", "") if isinstance(fallback, dict) else ""
    if is_mariinsky_list_ballet_meta(fallback):
        return None, audit_item(url, "mariinsky", "skipped", "list_ballet", title=fallback_title, venue=venue, date_text=date_text, time_text=time_text, event_type="ballet")
    soup = BeautifulSoup(fetch(url), "lxml")
    lines = html_lines(soup, stop_re=MARIINSKY_STOP_RE)
    page_time = first_page_time(lines)
    if page_time:
        time_text = page_time
    title = title_from_soup(soup, fallback_title)
    if not is_valid_title(title):
        return None, audit_item(url, "mariinsky", "skipped", "bad_title", title=title, venue=venue, date_text=date_text, time_text=time_text)
    for v in MARIINSKY_VENUES:
        if any(v.lower() == line.lower() for line in lines):
            venue = v
            break
    if any(canonical_low(marker) in canonical_low(line) for marker in EXTERNAL_STAGE_MARKERS for line in [venue, title] + list(lines[:20])):
        return None, audit_item(url, "mariinsky", "skipped", "external_stage", title=title, venue=venue, date_text=date_text, time_text=time_text)
    event_type, class_reason = classify_event(title, lines, list_type=list_type)
    if event_type == "ballet":
        return None, audit_item(url, "mariinsky", "skipped", class_reason, title=title, venue=venue, date_text=date_text, time_text=time_text, event_type=event_type)
    rec = build_event_record("mariinsky", url, title, venue, event_date, date_text, time_text, lines, event_type)
    return rec, audit_item(url, "mariinsky", "included", class_reason, title=rec.title, venue=rec.venue, date_text=rec.date_text, time_text=rec.time_text, event_type=rec.event_type, performers_count=len(rec.performers), program_count=len(rec.program))


def has_nonempty_query_value(query, names):
    for name in names:
        for value in query.get(name, []):
            if clean(value):
                return True
    return False


def is_philharmonia_event_url(url):
    parsed = urlparse(canonical_url(url))
    path = parsed.path or ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    keys = set(query.keys())
    if parsed.netloc not in PHILHARMONIA_HOSTS or not path.startswith("/afisha/"):
        return False
    if any(key(part) in PHILHARMONIA_BAD_PATH_PARTS for part in path.strip("/").split("/")):
        return False
    if keys & PHILHARMONIA_LIST_KEYS and not has_nonempty_query_value(query, PHILHARMONIA_EVENT_KEYS):
        return False
    if keys & PHILHARMONIA_EVENT_KEYS:
        return has_nonempty_query_value(query, PHILHARMONIA_EVENT_KEYS)
    if parsed.query or not path.startswith("/afisha/grand/"):
        return False
    tail = path[len("/afisha/grand/"):].strip("/")
    if not tail:
        return False
    parts = [p for p in tail.split("/") if p]
    if len(parts) == 1 and re.fullmatch(r"\d{4,}", parts[0]):
        return True
    if len(parts) >= 4 and re.fullmatch(r"20\d{2}", parts[0]) and re.fullmatch(r"\d{1,2}", parts[1]) and re.fullmatch(r"\d{1,2}", parts[2]):
        return any(re.search(r"\d{3,}", p) for p in parts[3:])
    return False


def parse_philharmonia_event(url, fallback=""):
    url = canonical_url(url)
    if not is_philharmonia_event_url(url):
        return None, audit_item(url, "philharmonia_grand", "skipped", "not_event_url")
    soup = BeautifulSoup(fetch(url), "lxml")
    lines = html_lines(soup)
    fallback_title = fallback_title_from_meta(fallback)
    title = title_from_soup(soup, fallback_title)
    if not is_valid_title(title) or title_key(title) in {"афиша", "афиша и билеты", "большой зал"}:
        return None, audit_item(url, "philharmonia_grand", "skipped", "bad_or_list_title", title=title)
    event_date = None
    date_text = ""
    time_text = ""
    url_date, url_date_text = parse_philharmonia_date_from_url(url)
    if url_date:
        event_date, date_text = url_date, url_date_text
    for line in lines[:160]:
        if not date_text:
            event_date, date_text = parse_ru_date(line)
        if not time_text:
            time_text = parse_time(line)
        if date_text and time_text:
            break
    if not date_text or not time_text:
        return None, audit_item(url, "philharmonia_grand", "skipped", "missing_date_or_time", title=title, date_text=date_text, time_text=time_text)
    event_type, class_reason = classify_event(title, lines)
    if event_type == "ballet":
        event_type = "concert"
        class_reason = "philharmonia_treat_ballet_reference_as_concert"
    rec = build_event_record("philharmonia_grand", url, title, SOURCES["philharmonia_grand"], event_date, date_text, time_text, lines, event_type)
    return rec, audit_item(url, "philharmonia_grand", "included", class_reason, title=rec.title, venue=rec.venue, date_text=rec.date_text, time_text=rec.time_text, event_type=rec.event_type, performers_count=len(rec.performers), program_count=len(rec.program))


def extract_mariinsky_links_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    pat = re.compile(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_\d{4}/")
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if not pat.search(href):
            continue
        url = normalize_url(urljoin(base_url, href))
        title = clean(a.get_text(" ", strip=True))
        card_text = mariinsky_card_text_for_link(a)
        list_type = infer_mariinsky_list_type(card_text)
        out.setdefault(url, {"title": title if is_valid_title(title) else "", "list_type": list_type, "list_text": card_text[:1200]})
    return out


def philharmonia_candidate_urls_from_raw_html(html, base_url):
    out = set()
    patterns = [
        r"(?:https?:)?//(?:www\.)?philharmonia\.spb\.ru/afisha/[^\"'<>\s)]+",
        r"/afisha/grand/[^\"'<>\s)]+",
        r"/afisha/\?[^\"'<>\s)]+",
    ]
    for pat in patterns:
        for m in re.finditer(pat, html):
            raw = m.group(0).replace("&amp;", "&").rstrip(".,;]")
            if raw.startswith("//"):
                raw = "https:" + raw
            out.add(canonical_url(urljoin(base_url, raw)))
    return out


def extract_philharmonia_links_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = set()
    link_text = {}
    for a in soup.find_all("a", href=True):
        url = canonical_url(urljoin(base_url, a.get("href") or ""))
        candidates.add(url)
        text = clean(a.get_text(" ", strip=True))
        if text:
            link_text.setdefault(url, text)
    candidates.update(philharmonia_candidate_urls_from_raw_html(html, base_url))
    out = {}
    for url in sorted(candidates):
        if not is_philharmonia_event_url(url):
            continue
        text = clean(link_text.get(url, ""))
        out.setdefault(url, {"title": text if is_valid_title(text) else "", "list_type": "", "list_text": text[:1200]})
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
    links = {}
    for url in philharmonia_list_urls(MONTHS_AHEAD):
        try:
            links.update(extract_philharmonia_links_from_html(fetch(url), url))
        except Exception as exc:
            audit["source_errors"].append({"source": "philharmonia_grand", "url": url, "error": f"{type(exc).__name__}: {exc}"})
    return links


def read_source(source, links, parser, audit):
    events = {}
    seen_urls = set(links.keys())
    failed_urls = set()
    for url, fallback in sorted(links.items()):
        try:
            rec, item = parser(url, fallback)
            audit["items"].append(item)
            if rec:
                events[rec.url] = rec.to_state_record()
            time.sleep(0.2)
        except Exception as exc:
            failed_urls.add(url)
            audit["items"].append(audit_item(url, source, "failed", "fetch_or_parse_failed", error=f"{type(exc).__name__}: {exc}"))
    return events, seen_urls, failed_urls


def scan_all():
    audit = {"app": APP_NAME, "engine_version": "V2", "schema_version": SCHEMA_VERSION, "filter_version": FILTER_VERSION, "run_mode": RUN_MODE, "run_at": now_utc(), "source_errors": [], "items": [], "summary": {}}
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
    return True if event_date is None else event_date > today_moscow()


def is_bogus_philharmonia_record(record):
    if not isinstance(record, dict) or record.get("source") != "philharmonia_grand":
        return False
    title = title_key(record.get("title", ""))
    url = record.get("url", "")
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if title in {"афиша", "афиша и билеты", "большой зал", "без названия"}:
        return True
    if "ev_z" in query and not has_nonempty_query_value(query, {"ev_z"}):
        return True
    if re.search(r"/afisha/grand/20\d{2}/\d{1,2}/?$", parsed.path):
        return True
    return "/pc/" in parsed.path or parsed.path.endswith("/pc/")


def is_mariinsky_ballet_record(record):
    if not isinstance(record, dict) or record.get("source") != "mariinsky":
        return False
    title = title_key(record.get("title", ""))
    if title in BALLET_TITLES:
        return True
    text = " ".join([record.get("title", ""), record.get("event_type", ""), " ".join(record.get("performers", []) or []), " ".join(record.get("program", []) or [])])
    low = canonical_low(text)
    hard = ["гала-концерт балета", "артисты балета", "театр балета", "хореография", "хореограф", "па-де-де", "вариация", "исполняется под фонограмму"]
    return any(x in low for x in hard)


def sanitize_events(source, events):
    events = dict(events or {})
    out = {}
    for url, rec in events.items():
        if source == "philharmonia_grand" and is_bogus_philharmonia_record(rec):
            continue
        if source == "mariinsky" and is_mariinsky_ballet_record(rec):
            continue
        rec = dict(rec)
        rec["performers"] = extract_performers(rec.get("performers", []) or [])
        rec["program"] = extract_program(rec.get("program", []) or [], rec.get("title", ""))
        out[url] = rec
    return out


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


def is_mariinsky_url_time_guess(record):
    if not isinstance(record, dict) or record.get("source") != "mariinsky":
        return False
    m = re.search(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_(\d{4})/", record.get("url", ""))
    if not m:
        return False
    raw = m.group(1)
    return clean(record.get("time_text", "")) == f"{raw[:2]}:{raw[2:]}"


def is_parser_time_correction(old, new):
    if old.get("source") != "mariinsky" or new.get("source") != "mariinsky":
        return False
    if clean(old.get("title", "")) != clean(new.get("title", "")):
        return False
    if clean(old.get("venue", "")) != clean(new.get("venue", "")):
        return False
    if clean(old.get("date_text", "")) != clean(new.get("date_text", "")):
        return False
    if clean(old.get("time_text", "")) == clean(new.get("time_text", "")):
        return False
    return is_mariinsky_url_time_guess(old)


def change_sections(old, new):
    sections = []
    title_change = before_after("Изменение названия:", old.get("title", ""), new.get("title", ""))
    if title_change:
        sections.append(title_change)
    if not is_parser_time_correction(old, new):
        date_time_change = before_after("Изменение даты / времени:", date_line(old), date_line(new))
        if date_time_change:
            sections.append(date_time_change)
    venue_change = before_after("Изменение площадки:", source_line(old), source_line(new))
    if venue_change:
        sections.append(venue_change)
    perf_added, perf_removed = normalized_set_diff(old.get("performers", []), new.get("performers", []), "performers")
    prog_added, prog_removed = normalized_set_diff(old.get("program", []), new.get("program", []), "program")
    perf_section = section_added_removed("Изменение в составе:", perf_added, perf_removed)
    if perf_section:
        sections.append(perf_section)
    prog_section = section_added_removed("Изменение в программе:", prog_added, prog_removed)
    if prog_section:
        sections.append(prog_section)
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
    return {"app": APP_NAME, "engine_version": "V2", "schema_version": SCHEMA_VERSION, "filter_version": FILTER_VERSION, "updated_at": now_utc(), "sources": {s: {"events": {}} for s in SOURCES}, "pending_messages": []}


def sanitize_pending_messages(messages):
    out = []
    for msg in messages or []:
        text = str(msg or "")
        low = canonical_low(text)
        if "название: афиша" in low:
            continue
        if "ev_z=" in text and re.search(r"ev_z=(?:\s|$|&)", text):
            continue
        if "/afisha/grand/" in text and "/pc/" in text:
            continue
        out.append(text)
    return out


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
        state["sources"][source]["events"] = sanitize_events(source, state["sources"][source].get("events", {}))
    state["pending_messages"] = sanitize_pending_messages(state.get("pending_messages", []))
    return state


def is_uninitialized_state(state):
    if not isinstance(state, dict):
        return True
    if state.get("app") or state.get("engine_version") or state.get("updated_at"):
        return False
    sources = state.get("sources", {})
    return not any(source_data.get("events") for source_data in sources.values() if isinstance(source_data, dict))


def save_state(state):
    state["app"] = APP_NAME
    state["engine_version"] = "V2"
    state["schema_version"] = SCHEMA_VERSION
    state["filter_version"] = FILTER_VERSION
    state["updated_at"] = now_utc()
    state["pending_messages"] = sanitize_pending_messages(state.get("pending_messages", []))
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def save_audit(audit):
    AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def build_messages_for_source(source, old_events, new_events, seen_urls, failed_urls):
    old_events = sanitize_events(source, old_events)
    new_events = sanitize_events(source, new_events)
    messages = []
    if not old_events and new_events:
        return messages, "initial_source_baseline_no_messages"
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
    return messages, ""


def add_pending(state, messages):
    state.setdefault("pending_messages", [])
    state["pending_messages"] = sanitize_pending_messages(state["pending_messages"] + list(messages or []))


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
    pending[:] = sanitize_pending_messages(pending)
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
        rec, item = parse_philharmonia_event(canonical_url(url), "")
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
    suppressed = {}
    for source in SOURCES:
        old_events = old_state.get("sources", {}).get(source, {}).get("events", {})
        source_messages, reason = build_messages_for_source(source, old_events, scanned[source], seen_urls[source], failed_urls[source])
        if reason:
            suppressed[source] = reason
        messages.extend(source_messages)
    messages = sanitize_pending_messages(messages)
    audit["would_notify_count"] = len(messages)
    audit["would_notify_preview"] = messages[:20]
    audit["suppressed"] = suppressed
    save_audit(audit)
    if RUN_MODE == "dry_run":
        print(f"DRY_RUN: would queue {len(messages)} messages. State was not changed.")
        if suppressed:
            print("Suppressed:", json.dumps(suppressed, ensure_ascii=False, sort_keys=True))
        for msg in messages[:20]:
            print("--- WOULD NOTIFY ---")
            print(msg)
        return
    for source in SOURCES:
        old_state.setdefault("sources", {}).setdefault(source, {})["events"] = scanned[source]
    if RUN_MODE == "bootstrap":
        old_state["pending_messages"] = []
        save_state(old_state)
        print(f"BOOTSTRAP: state refreshed. Pending cleared. {len(messages)} possible messages were not queued or sent.")
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
    assert FILTER_VERSION == "V2.7.1-meaningful-diff-only"
    assert parse_time("20:00") == "20:00"
    assert parse_time("25:99") == ""
    assert not contains_word("Хореография Ильи Живого", ["хор"])
    assert contains_word("Хор и Симфонический оркестр Мариинского театра", ["хор"])
    assert infer_mariinsky_list_type("Виктория Терёшкина. 25 лет на сцене гала-концерт балета") == "ballet"
    assert infer_mariinsky_list_type("Леди Макбет Мценского уезда опера Дмитрия Шостаковича") == "opera"
    assert infer_mariinsky_list_type("Тоска опера Джакомо Пуччини") == "opera"
    assert is_labeled_performer_line("Флория Тоска — Хибла Герзмава")
    assert is_labeled_performer_line("Леди Макбет — Анжелика Минасова")
    assert not is_labeled_performer_line("Хореография — Илья Живой")
    assert not is_labeled_performer_line("Санкт — Петербург")
    assert not is_labeled_performer_line("опера Николая Римского — Корсакова")
    assert not is_program_line("опера Дмитрия Шостаковича", "Леди Макбет Мценского уезда")
    assert not is_program_line("опера Николая Римского — Корсакова", "Царская невеста")
    assert not is_program_line("К 120—летию со дня рождения Дмитрия Шостаковича", "Шостакович. Четвертая симфония")
    assert not is_program_line("Дмитрий Шостакович", "Шостакович. Четвертая симфония")
    assert is_program_line("Бетховен. Месса до мажор", "Бетховен. Торжественная месса")
    old = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/22/2_2001/",
        "title": "Бетховен. Торжественная месса",
        "venue": "Мариинский-2",
        "date_text": "22 июля 2026",
        "time_text": "20:01",
    }
    new = dict(old)
    new["time_text"] = "20:00"
    assert is_parser_time_correction(old, new)
    assert change_sections(old, new) == []
    old_cast = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/22/2_2001/",
        "title": "Бетховен. Торжественная месса",
        "venue": "Мариинский-2",
        "date_text": "22 июля 2026",
        "time_text": "20:00",
        "performers": ["Солисты оперы, Хор и Симфонический оркестр Мариинского театра"],
        "program": [],
    }
    new_cast = dict(old_cast)
    new_cast["performers"] = ["ИСПОЛНИТЕЛИ — Солисты оперы", "ИСПОЛНИТЕЛИ — Хор и Симфонический оркестр Мариинского театра", "Хор и Симфонический оркестр Мариинского театра"]
    assert change_sections(old_cast, new_cast) == []
    assert format_changed(old_cast, new_cast) == ""
    old_conductor = dict(old_cast)
    new_conductor = dict(old_cast)
    old_conductor["performers"] = ["Дирижер — Иван Петров"]
    new_conductor["performers"] = ["Дирижер — Валерий Гергиев"]
    msg = format_changed(old_conductor, new_conductor)
    assert "Изменение в составе" in msg and "Валерий Гергиев" in msg and "Иван Петров" in msg
    old_role = dict(old_cast)
    new_role = dict(old_cast)
    old_role["performers"] = ["Флория Тоска — Мария Иванова"]
    new_role["performers"] = ["Флория Тоска — Хибла Герзмава"]
    msg = format_changed(old_role, new_role)
    assert "Хибла Герзмава" in msg and "Мария Иванова" in msg
    noisy_old = dict(old_cast)
    noisy_new = dict(old_cast)
    noisy_old["performers"] = []
    noisy_new["performers"] = ["Санкт — Петербург", "Зал Стравинского", "опера Николая Римского — Корсакова"]
    noisy_new["program"] = ["опера Дмитрия Шостаковича", "К 120—летию со дня рождения Дмитрия Шостаковича", "Дмитрий Шостакович"]
    assert format_changed(noisy_old, noisy_new) == ""
    assert is_mariinsky_ballet_record({"source": "mariinsky", "title": "Виктория Терёшкина. 25 лет на сцене", "event_type": "unknown", "performers": ["Хореография Ильи Живого"], "program": ["«Шехеразада»"]})
    assert is_mariinsky_list_ballet_meta({"title": "Виктория Терёшкина. 25 лет на сцене", "list_type": "ballet", "list_text": "гала-концерт балета"})
    assert is_philharmonia_event_url("https://www.philharmonia.spb.ru/afisha/grand/12345/")
    assert is_philharmonia_event_url("https://www.philharmonia.spb.ru/afisha/grand/?ev_y=2026&ev_z=12345")
    assert not is_philharmonia_event_url("https://www.philharmonia.spb.ru/afisha/grand/2027/2/pc/")
    assert not is_philharmonia_event_url("https://www.philharmonia.spb.ru/afisha/grand/?year=2026&month=7")
    assert not is_philharmonia_event_url("https://www.philharmonia.spb.ru/afisha/grand/2026/06/?ev_y=2025&ev_m=6&ev_d=12&ev_z=")
    pending = sanitize_pending_messages(["СПб филармония\nНазвание: Афиша\nhttps://www.philharmonia.spb.ru/afisha/grand/2026/06/?ev_z=", "normal"])
    assert pending == ["normal"]
    print("SELF_TEST_OK")


if __name__ == "__main__":
    if SELF_TEST:
        run_self_tests()
    else:
        main()
