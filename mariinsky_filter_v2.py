import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


APP_NAME = "Mariinsky Filter V2"
SCHEMA_VERSION = 2
FILTER_VERSION = "V2.8.2-mariinsky-no-ballet-with-list-cast"

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
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 MariinskyWatcherV2/2.8.2 (+https://github.com/fageehamalal-max/mariinsky-watcher)",
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

MARIINSKY_VENUES = set(VENUE_BY_CODE.values()) | {
    "Концертный зал Мариинского театра",
    "Японский павильон",
    "Ораниенбаум",
    "Меншиковский дворец",
}

SOURCES = {
    "mariinsky": "Мариинский театр",
}

BAD_TITLES = {
    "афиша", "афиша и билеты", "главная", "репертуар",
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    "cookie", "cookies", "использование cookies",
    "согласие на использование cookie", "согласие на использование cookies",
}

EXTERNAL_STAGE_MARKERS = [
    "Приморская сцена",
    "Владивосток",
    "Владикавказ",
    "РСО-Алания",
]

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

PERFORMER_WORDS = [
    "дириж", "солист", "солистка", "исполн", "состав",
    "партию", "партия", "партии", "главные партии", "главных партиях",
    "сопрано", "тенор", "баритон", "бас", "скрипка", "альт", "виолончель",
    "фортепиано", "орган", "кларнет", "флейта", "хор", "оркестр", "ансамбль",
    "артист", "артисты", "концертмейстер", "режиссер", "режиссёр", "хормейстер",
]

ROLE_WORDS = [
    "дирижер", "дирижёр", "солист", "солистка", "солисты", "исполнитель",
    "исполнительница", "исполнители", "главные партии", "главных партиях",
    "партия", "партии", "партию",
    "сопрано", "тенор", "баритон", "бас",
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
    "антракт", "без антракта", "с антрактом",
    "концерт идет", "спектакль идет", "опера идет", "балет идет",
    "представление идет", "продолжительность",
    "одно отделение", "два отделения", "в одном отделении", "в двух отделениях",
    "без перерыва", "программа концерта будет опубликована позднее",
]

CAST_PLACEHOLDER_PATTERNS = [
    "состав исполнителей будет объявлен позднее",
    "состав будет объявлен позднее",
    "исполнители будут объявлены позднее",
    "исполнители будут объявлены дополнительно",
    "состав исполнителей будет объявлен дополнительно",
    "состав исполнителей уточняется",
    "состав будет уточнен",
    "состав будет уточнён",
    "будет объявлен позднее",
    "будут объявлены позднее",
    "будет объявлен дополнительно",
    "будут объявлены дополнительно",
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
    "золото рейна", "валькирия", "зигфрид", "гибель богов",
    "летучий голландец", "лоэнгрин", "тристан и изольда",
    "леди макбет мценского уезда", "нос",
    "сказание о невидимом граде китеже и деве февронии", "джоконда",
    "обручение в монастыре", "троянцы", "лакме", "бенвенуто челлини",
    "свадьба фигаро", "итальянка в алжире", "чародейка", "аттила",
    "парсифаль",
}

LIST_BALLET_MARKERS = [
    "балет", "балета", "балеты", "гала-концерт балета", "артисты балета",
    "театр балета", "хореография", "хореограф", "па-де-де", "вариация",
    "исполняется под фонограмму",
]

LIST_OPERA_MARKERS = [
    "опера", "опера-буффа", "драма в музыке", "музыкальная драма",
]

LIST_CONCERT_MARKERS = [
    "концерт", "концерты", "кантата", "оратория", "реквием", "месса",
    "симфонический оркестр",
]

LOCATION_LINES = {
    "санкт петербург", "санкт-петербург", "санкт — петербург", "санкт – петербург",
    "санкт петербург концертный зал", "санкт петербург мариинский театр",
    "мариинский театр", "мариинский 2", "мариинский-2", "концертный зал",
    "зал стравинского", "камерные залы", "зал щедрина", "зал мусоргского",
    "концертный зал мариинского театра",
}

MEANINGLESS_PERFORMER_LINES = {
    "орган",
    "исполнители",
    "исполнитель",
    "солисты",
    "солист",
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
    return key(s).replace("cостав", "состав")


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
    return normalize_url(url)


def digest_obj(obj):
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def record_core(record):
    return {
        "title": clean(record.get("title", "")),
        "venue": clean(record.get("venue", "")),
        "date_text": clean(record.get("date_text", "")),
        "time_text": clean(record.get("time_text", "")),
        "event_type": clean(record.get("event_type", "")),
        "performers": list(record.get("performers", []) or []),
        "program": list(record.get("program", []) or []),
    }


def refresh_record_digest(record):
    record["digest"] = digest_obj(record_core(record))
    return record


def event_move_key(record):
    return "|".join([
        title_key(record.get("title", "")),
        title_key(record.get("venue", "")),
    ])


def fetch(url):
    last_exc = None

    for attempt in range(1, 4):
        try:
            r = SESSION.get(url, timeout=30)
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

    if low in LOCATION_LINES or clean(line) in MARIINSKY_VENUES:
        return True

    if "санкт петербург" in low and any(x in low for x in ["концертный зал", "мариинский театр", "мариинский 2"]):
        return True

    return False


def is_genre_description(line):
    low = canonical_low(line)
    genre_starts = [
        "опера ", "оперы ", "балет ", "балеты ",
        "гала-концерт", "симфонический концерт", "камерный концерт",
    ]

    if any(low.startswith(x) for x in genre_starts):
        return True

    return bool(re.fullmatch(r"опера(\s+.+)?", low))


def is_explanatory_line(line):
    low = canonical_low(line)
    bad_starts = [
        "к ", "ко ", "посвящается", "к юбилею", "к 120", "к 100", "к 150",
        "в рамках", "при поддержке", "фестиваль", "звезды белых ночей",
        "звёзды белых ночей", "виртуальная выставка",
    ]
    return any(low.startswith(x) for x in bad_starts)


def is_meaningless_performer_line(line):
    low = title_key(line)

    if low in MEANINGLESS_PERFORMER_LINES:
        return True

    raw_low = canonical_low(line)

    if raw_low.startswith("исполняется на "):
        return True

    if "сопровождается синхронными титрами" in raw_low:
        return True

    if raw_low.startswith("mariinsky.tv") or raw_low.startswith("mariinsky.fm"):
        return True

    return False


def is_noise(line):
    line = clean(line)

    if not line:
        return True

    if MENU_RE.fullmatch(line) or NOISE_RE.search(line):
        return True

    return is_subscription_line(line) or is_non_repertoire_info(line) or is_cast_placeholder_line(line)


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
    return bool(re.search(rf"\b\d{{1,2}}\s+{MONTH_WORD_RE}\b", canonical_low(line)))


def is_time_line(line):
    return bool(re.fullmatch(r"\d{1,2}[:.]\d{2}", clean(line)))


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
    venue = clean(record.get("venue", ""))
    return f"{MARIINSKY_MARK} {venue or 'Мариинский театр'}"


def infer_mariinsky_list_type(text):
    low = canonical_low(text)

    if any(x in low for x in LIST_BALLET_MARKERS):
        return "ballet"

    if any(x in low for x in LIST_OPERA_MARKERS):
        return "opera"

    if title_key(text) in OPERA_TITLE_MARKERS:
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


def fallback_list_text(fallback):
    if isinstance(fallback, dict):
        return clean(fallback.get("list_text", ""))
    return ""


def is_ballet_genre_line(line):
    low = title_key(line)

    if low in {
        "балет", "балеты", "одноактный балет", "одноактные балеты",
        "вечер балетов", "хореографическая миниатюра", "хореографические миниатюры",
    }:
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
    hard = [
        "гала-концерт балета", "артисты балета", "театр балета",
        "хореография", "хореограф", "па-де-де", "вариация",
        "исполняется под фонограмму",
    ]

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

    if is_meaningless_performer_line(line):
        return False

    if is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False

    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False

    words = [w for w in re.split(r"\s+", line.replace(".", " ")) if w]

    if not (1 <= len(words) <= 5):
        return False

    return all(re.match(r"^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+$", w) for w in words)


def split_people(text):
    text = clean(text).strip(" :;,-–—")
    return [clean(x) for x in re.split(r"\s*,\s*|\s*;\s*", text) if clean(x)]


def looks_like_person_list(line):
    parts = split_people(line)
    return bool(parts) and all(looks_like_person_name_single(p) for p in parts)


def looks_like_ensemble_phrase(line):
    if is_noise(line) or is_date_line(line) or is_time_line(line) or is_location_line(line):
        return False

    if is_meaningless_performer_line(line):
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
        "хореография", "хореограф", "исполняется под фонограмму",
        "постановка", "сценография", "костюмы", "свет", "видео",
        "либретто", "автор", "режиссер-постановщик", "режиссёр-постановщик",
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

    if is_meaningless_performer_line(label) or is_meaningless_performer_line(rest):
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

    if is_meaningless_performer_line(line) or is_meaningless_performer_line(rest):
        return False

    if is_production_credit_label(label) or is_genre_description(label) or is_genre_description(line):
        return False

    if contains_word(label, ROLE_WORDS) or contains_word(label, PERFORMER_WORDS):
        return looks_like_person_list(rest) or looks_like_person_name_single(rest) or looks_like_ensemble_phrase(rest)

    return looks_like_opera_role_assignment(label, rest)


def is_ensemble_performer_line(line):
    if is_location_line(line) or is_genre_description(line):
        return False

    if is_meaningless_performer_line(line):
        return False

    if not contains_word(line, ENSEMBLE_WORDS):
        return False

    low = canonical_low(line)

    if re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low):
        return False

    if re.match(r"^(симфонический|камерный|струнный|духовой|детский|женский|мужской|смешанный)?\s*(оркестр|хор|ансамбль)\b", low):
        return True

    return "мариинск" in low or "театра" in low


def is_loose_performer_phrase(line):
    line = clean(line)

    if not line or is_meaningless_performer_line(line):
        return False

    if is_noise(line) or is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False

    if is_production_credit_label(line) or contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False

    return contains_word(line, PERFORMER_WORDS)


def is_performer_line(line):
    line = clean(line)

    if is_noise(line) or is_location_line(line) or is_cast_placeholder_line(line):
        return False

    if is_meaningless_performer_line(line):
        return False

    if is_production_credit_label(line) or is_genre_description(line) or is_explanatory_line(line):
        return False

    if is_labeled_performer_line(line) or is_ensemble_performer_line(line):
        return True

    if contains_word(line, PROGRAM_WORDS) or has_composer(line):
        return False

    return is_loose_performer_phrase(line) or (line.startswith(":") and "," in line)


def is_program_line(line, title):
    line = clean(line)

    if len(line) > 220:
        return False

    if is_noise(line) or is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False

    if is_meaningless_performer_line(line):
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
                return [f"{label} — {p}" for p in people if looks_like_person_name_single(p)]

            return [f"{label} — {people[0]}"]

        return [line]

    if "," in line and not contains_word(line, PROGRAM_WORDS):
        return split_people(line)

    return [line]


def strip_section_prefix(s):
    s = clean(s).replace("–", "—").replace("-", "—")
    s = re.sub(
        r"^(исполнители|исполнитель|солисты|состав исполнителей|в программе|программа|полная программа)\s*[—:]\s*",
        "",
        s,
        flags=re.I,
    )
    return clean(s)


def normalize_compare_key(s):
    s = title_key(strip_section_prefix(s))
    return re.sub(r"\s+", " ", s).strip()


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
        and not is_meaningless_performer_line(x)
    ])


def is_valid_performer_piece(item):
    item = strip_section_prefix(item)

    if not item:
        return False

    if is_noise(item) or is_location_line(item) or is_genre_description(item) or is_explanatory_line(item):
        return False

    if is_production_credit_label(item) or is_meaningless_performer_line(item):
        return False

    return (
        is_labeled_performer_line(item)
        or is_ensemble_performer_line(item)
        or looks_like_person_name_single(item)
        or looks_like_person_list(item)
        or is_loose_performer_phrase(item)
    )


def sanitize_parsed_performers(items):
    cleaned = []

    for item in items or []:
        item = strip_section_prefix(clean(item))

        if not item:
            continue

        if "," in item and not has_composer(item) and not is_labeled_performer_line(item):
            parts = split_people(item)

            if len(parts) > 1:
                for part in parts:
                    if is_valid_performer_piece(part):
                        cleaned.append(part)
                continue

        if is_valid_performer_piece(item):
            cleaned.append(item)

    return uniq(cleaned)


def sanitize_parsed_program(items, title):
    cleaned = []

    for item in items or []:
        item = strip_section_prefix(clean(item))

        if item and is_program_line(item, title):
            cleaned.append(item)

    return uniq(cleaned)


def extract_performers(lines):
    items = []

    for line in lines:
        if is_performer_line(line):
            items.extend(performer_items_from_line(line))

    return sanitize_parsed_performers(items)


def extract_program(lines, title):
    return sanitize_parsed_program([line for line in lines if is_program_line(line, title)], title)


def extract_list_cast_lines(list_text):
    text = clean(list_text)

    if not text:
        return []

    out = []

    marker_pattern = re.compile(
        rf"(?:в\s+главных\s+партиях|главные\s+партии)\s*[:—-]\s*(.+?)(?=\s+(?:дириж[её]р|режисс[её]р|хор|оркестр)\s*[:—-]|\s+\d{{1,2}}\s+{MONTH_WORD_RE}\b|\s+(?:Мариинский театр|Мариинский-2|Концертный зал|Зал Стравинского|Зал Щедрина|Зал Мусоргского|Камерные залы)\b|$)",
        re.I,
    )

    for match in marker_pattern.finditer(text):
        people_block = clean(match.group(1))
        people = split_people(people_block)

        for person in people:
            if looks_like_person_name_single(person):
                out.append(f"Главные партии — {person}")

    explicit_role_pattern = re.compile(
        r"\b(Дириж[её]р|Хормейстер|Концертмейстер|Режисс[её]р)\s*[—–-]\s*([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z .'\-]{2,80})(?=\s+(?:Мариинский театр|Мариинский-2|Концертный зал|Зал Стравинского|Зал Щедрина|Зал Мусоргского|Камерные залы)\b|\s+\d{1,2}\s+" + MONTH_WORD_RE + r"\b|$)",
        re.I,
    )

    for match in explicit_role_pattern.finditer(text):
        label = clean(match.group(1))
        rest = clean(match.group(2))
        candidate = f"{label} — {rest}"

        if is_labeled_performer_line(candidate):
            out.append(candidate)

    return uniq(out)


def split_performer_for_compare(item):
    item = strip_section_prefix(item)

    if not item:
        return []

    if not is_valid_performer_piece(item):
        return []

    if "," in item and not has_composer(item):
        parts = split_people(item)

        if len(parts) > 1:
            return [p for p in parts if is_valid_performer_piece(p)]

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
        "event_type": clean(event_type),
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
        event_type=core["event_type"],
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
    list_text = fallback_list_text(fallback)
    list_type = fallback.get("list_type", "") if isinstance(fallback, dict) else ""

    if is_mariinsky_list_ballet_meta(fallback):
        return None, audit_item(
            url, "mariinsky", "skipped", "list_ballet",
            title=fallback_title, venue=venue, date_text=date_text,
            time_text=time_text, event_type="ballet",
        )

    soup = BeautifulSoup(fetch(url), "lxml")
    detail_lines = html_lines(soup, stop_re=MARIINSKY_STOP_RE)
    list_cast_lines = extract_list_cast_lines(list_text)
    lines = uniq(list_cast_lines + detail_lines)

    page_time = first_page_time(detail_lines)
    if page_time:
        time_text = page_time

    title = title_from_soup(soup, fallback_title)

    if not is_valid_title(title):
        return None, audit_item(
            url, "mariinsky", "skipped", "bad_title",
            title=title, venue=venue, date_text=date_text, time_text=time_text,
        )

    for v in MARIINSKY_VENUES:
        if any(v.lower() == line.lower() for line in detail_lines):
            venue = v
            break

    if any(canonical_low(marker) in canonical_low(line) for marker in EXTERNAL_STAGE_MARKERS for line in [venue, title] + list(detail_lines[:20])):
        return None, audit_item(
            url, "mariinsky", "skipped", "external_stage",
            title=title, venue=venue, date_text=date_text, time_text=time_text,
        )

    event_type, class_reason = classify_event(title, lines, list_type=list_type)

    if event_type == "ballet":
        return None, audit_item(
            url, "mariinsky", "skipped", class_reason,
            title=title, venue=venue, date_text=date_text,
            time_text=time_text, event_type=event_type,
        )

    if event_type == "unknown":
        return None, audit_item(
            url, "mariinsky", "skipped", "unknown_event_type",
            title=title, venue=venue, date_text=date_text,
            time_text=time_text, event_type=event_type,
        )

    rec = build_event_record("mariinsky", url, title, venue, event_date, date_text, time_text, lines, event_type)

    return rec, audit_item(
        url, "mariinsky", "included", class_reason,
        title=rec.title, venue=rec.venue, date_text=rec.date_text,
        time_text=rec.time_text, event_type=rec.event_type,
        performers_count=len(rec.performers), program_count=len(rec.program),
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
        title = clean(a.get_text(" ", strip=True))
        card_text = mariinsky_card_text_for_link(a)
        list_type = infer_mariinsky_list_type(card_text)

        out.setdefault(url, {
            "title": title if is_valid_title(title) else "",
            "list_type": list_type,
            "list_text": card_text[:2000],
        })

    return out


def collect_mariinsky_links(audit):
    links = {}

    for url in month_urls(MARIINSKY_ROOT, MONTHS_AHEAD):
        try:
            links.update(extract_mariinsky_links_from_html(fetch(url), url))
        except Exception as exc:
            audit["source_errors"].append({
                "source": "mariinsky",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })

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
            failed_urls.add(canonical_url(url))
            audit["items"].append(audit_item(
                url, source, "failed", "fetch_or_parse_failed",
                error=f"{type(exc).__name__}: {exc}",
            ))

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
    scanned = {}
    seen_urls = {}
    failed_urls = {}

    scanned["mariinsky"], seen_urls["mariinsky"], failed_urls["mariinsky"] = read_source(
        "mariinsky", mariinsky_links, parse_mariinsky_event, audit
    )

    source_items = [x for x in audit["items"] if x["source"] == "mariinsky"]
    audit["summary"]["mariinsky"] = {
        "links_found": len(mariinsky_links),
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


def is_mariinsky_ballet_record(record):
    if not isinstance(record, dict) or record.get("source") != "mariinsky":
        return False

    title = title_key(record.get("title", ""))

    if title in BALLET_TITLES:
        return True

    text = " ".join([
        record.get("title", ""),
        record.get("event_type", ""),
        " ".join(record.get("performers", []) or []),
        " ".join(record.get("program", []) or []),
    ])
    low = canonical_low(text)
    hard = [
        "гала-концерт балета", "артисты балета", "театр балета",
        "хореография", "хореограф", "па-де-де", "вариация",
        "исполняется под фонограмму",
    ]

    return any(x in low for x in hard)


def sanitize_events(source, events):
    events = dict(events or {})
    out = {}

    for url, rec in events.items():
        if not isinstance(rec, dict):
            continue

        rec = dict(rec)
        rec["source"] = "mariinsky"
        rec["url"] = canonical_url(rec.get("url") or url)

        if is_mariinsky_ballet_record(rec):
            continue

        if rec.get("event_type") not in {"opera", "concert"}:
            continue

        rec["performers"] = sanitize_parsed_performers(rec.get("performers", []) or [])
        rec["program"] = sanitize_parsed_program(rec.get("program", []) or [], rec.get("title", ""))

        refresh_record_digest(rec)
        out[rec["url"]] = rec

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

    return "\n".join([
        title,
        "",
        f"{EMOJI_REMOVED} Было:",
        old or "—",
        "",
        f"{EMOJI_ADDED} Стало:",
        new or "—",
    ])


def format_new(record):
    parts = [
        source_line(record),
        f"{EMOJI_NEW} Новое событие",
        "",
        f"Название: {record.get('title', 'Без названия')}",
    ]

    dt = date_line(record)

    if dt:
        parts.append(dt)

    parts += ["", f"Ссылка: {record.get('url', '')}"]

    return "\n".join(parts).strip()


def format_removed(record):
    parts = [
        source_line(record),
        f"{EMOJI_REMOVED} Событие исчезло",
        "",
        f"Название: {record.get('title', 'Без названия')}",
    ]

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

    parts = [
        source_line(new),
        "",
        f"Название: {new.get('title', 'Без названия')}",
    ]

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
        "sources": {"mariinsky": {"events": {}}},
        "pending_messages": [],
    }


def sanitize_pending_messages(messages):
    out = []
    seen = set()

    for msg in messages or []:
        text = str(msg or "")

        if MARIINSKY_MARK not in text:
            continue

        if "philharmonia" in canonical_low(text) or "филармони" in canonical_low(text):
            continue

        dedup_key = title_key(text)

        if dedup_key in seen:
            continue

        seen.add(dedup_key)
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

    state["sources"].setdefault("mariinsky", {}).setdefault("events", {})
    state["sources"]["mariinsky"]["events"] = sanitize_events(
        "mariinsky",
        state["sources"]["mariinsky"].get("events", {}),
    )
    state["pending_messages"] = sanitize_pending_messages(state.get("pending_messages", []))

    return state


def is_uninitialized_state(state):
    if not isinstance(state, dict):
        return True

    if state.get("app") or state.get("engine_version") or state.get("updated_at"):
        return False

    sources = state.get("sources", {})
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

    mariinsky_events = state.get("sources", {}).get("mariinsky", {}).get("events", {})
    state["sources"] = {
        "mariinsky": {
            "events": sanitize_events("mariinsky", mariinsky_events)
        }
    }
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

    matched_old = set()
    matched_new = set()

    for url, new in sorted(new_events.items()):
        old = old_events.get(url)

        if old is None:
            continue

        matched_old.add(url)
        matched_new.add(url)

        msg = format_changed(old, new)
        if msg:
            messages.append(msg)

    old_unmatched = {
        url: rec
        for url, rec in old_events.items()
        if url not in matched_old and url not in failed_urls and url not in seen_urls and is_future_removed(rec)
    }
    new_unmatched = {
        url: rec
        for url, rec in new_events.items()
        if url not in matched_new
    }

    old_by_move_key = {}
    new_by_move_key = {}

    for url, rec in old_unmatched.items():
        old_by_move_key.setdefault(event_move_key(rec), []).append((url, rec))

    for url, rec in new_unmatched.items():
        new_by_move_key.setdefault(event_move_key(rec), []).append((url, rec))

    for move_key in sorted(set(old_by_move_key) & set(new_by_move_key)):
        old_group = old_by_move_key[move_key]
        new_group = new_by_move_key[move_key]

        if len(old_group) != 1 or len(new_group) != 1:
            continue

        old_url, old_rec = old_group[0]
        new_url, new_rec = new_group[0]

        matched_old.add(old_url)
        matched_new.add(new_url)

        msg = format_changed(old_rec, new_rec)
        if msg:
            messages.append(msg)

    for url, new in sorted(new_events.items()):
        if url in matched_new:
            continue
        messages.append(format_new(new))

    for url, old in sorted(old_events.items()):
        if url in matched_old or url in failed_urls or url in seen_urls:
            continue
        if is_future_removed(old):
            messages.append(format_removed(old))

    return messages, ""


def add_pending(state, messages):
    state.setdefault("pending_messages", [])
    state["pending_messages"] = sanitize_pending_messages(state["pending_messages"] + list(messages or []))

    if len(state["pending_messages"]) > PENDING_WARNING_THRESHOLD:
        print(f"WARNING: pending_messages is {len(state['pending_messages'])}, above threshold {PENDING_WARNING_THRESHOLD}.")


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
            response = SESSION.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True},
                timeout=30,
            )

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
    if "mariinsky.ru" not in url:
        raise ValueError("Only Mariinsky event URLs are supported in this script.")

    rec, item = parse_mariinsky_event(normalize_url(url), "")
    payload = {
        "audit": item,
        "record": rec.to_state_record() if rec else None,
    }
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
        new_state["sources"]["mariinsky"]["events"] = scanned["mariinsky"]

        if RUN_MODE == "dry_run":
            print("DRY_RUN: no state exists. Current scan was audited but state was not created.")
            return

        save_state(new_state)
        print("No previous V2 state. Baseline created without Telegram messages.")
        return

    old_events = old_state.get("sources", {}).get("mariinsky", {}).get("events", {})
    messages, reason = build_messages_for_source(
        "mariinsky",
        old_events,
        scanned["mariinsky"],
        seen_urls["mariinsky"],
        failed_urls["mariinsky"],
    )

    suppressed = {}
    if reason:
        suppressed["mariinsky"] = reason

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

    old_state.setdefault("sources", {}).setdefault("mariinsky", {})["events"] = scanned["mariinsky"]

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
    assert FILTER_VERSION == "V2.8.2-mariinsky-no-ballet-with-list-cast"

    assert parse_time("20:00") == "20:00"
    assert parse_time("25:99") == ""

    assert not contains_word("Хореография Ильи Живого", ["хор"])
    assert contains_word("Хор и Симфонический оркестр Мариинского театра", ["хор"])

    assert infer_mariinsky_list_type("Виктория Терёшкина. 25 лет на сцене гала-концерт балета") == "ballet"
    assert infer_mariinsky_list_type("Леди Макбет Мценского уезда опера Дмитрия Шостаковича") == "opera"
    assert infer_mariinsky_list_type("Тоска опера Джакомо Пуччини") == "opera"
    assert infer_mariinsky_list_type("Шостакович. Четвертая симфония концерт") == "concert"

    assert is_labeled_performer_line("Флория Тоска — Хибла Герзмава")
    assert is_labeled_performer_line("Леди Макбет — Анжелика Минасова")
    assert is_labeled_performer_line("Главные партии — Татьяна Сержан")
    assert not is_labeled_performer_line("Хореография — Илья Живой")
    assert not is_labeled_performer_line("Санкт — Петербург")
    assert not is_labeled_performer_line("опера Николая Римского — Корсакова")

    assert not is_performer_line("Орган")
    assert not is_performer_line("Исполнители")
    assert not is_performer_line("Исполняется на итальянском языке (сопровождается синхронными титрами на русском языке)")
    assert is_labeled_performer_line("Дирижер — Валерий Гергиев")
    assert is_labeled_performer_line("Джоконда — Татьяна Сержан")

    assert not is_program_line("опера Дмитрия Шостаковича", "Леди Макбет Мценского уезда")
    assert not is_program_line("опера Николая Римского — Корсакова", "Царская невеста")
    assert not is_program_line("К 120—летию со дня рождения Дмитрия Шостаковича", "Шостакович. Четвертая симфония")
    assert not is_program_line("Дмитрий Шостакович", "Шостакович. Четвертая симфония")
    assert not is_program_line("Виртуальная выставка «Однажды в Венеции»", "Джоконда")
    assert is_program_line("Бетховен. Месса до мажор", "Бетховен. Торжественная месса")

    list_cast = extract_list_cast_lines(
        "Джоконда опера Амилькаре Понкьелли В главных партиях: Татьяна Сержан, Зинаида Царенко, Нажмиддин Мавлянов Дирижер — Валерий Гергиев Мариинский-2"
    )
    assert "Главные партии — Татьяна Сержан" in list_cast
    assert "Главные партии — Зинаида Царенко" in list_cast
    assert "Главные партии — Нажмиддин Мавлянов" in list_cast
    assert "Дирижер — Валерий Гергиев" in list_cast

    old = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/22/2_2001/",
        "title": "Бетховен. Торжественная месса",
        "venue": "Мариинский-2",
        "date_text": "22 июля 2026",
        "time_text": "20:01",
        "event_type": "concert",
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
        "event_type": "concert",
        "performers": ["Солисты оперы, Хор и Симфонический оркестр Мариинского театра"],
        "program": [],
    }
    new_cast = dict(old_cast)
    new_cast["performers"] = [
        "ИСПОЛНИТЕЛИ — Солисты оперы",
        "ИСПОЛНИТЕЛИ — Хор и Симфонический оркестр Мариинского театра",
        "Хор и Симфонический оркестр Мариинского театра",
    ]
    assert change_sections(old_cast, new_cast) == []
    assert format_changed(old_cast, new_cast) == ""

    old_conductor = dict(old_cast)
    new_conductor = dict(old_cast)
    old_conductor["performers"] = ["Дирижер — Иван Петров"]
    new_conductor["performers"] = ["Дирижер — Валерий Гергиев"]
    msg = format_changed(old_conductor, new_conductor)
    assert "Изменение в составе" in msg
    assert "Валерий Гергиев" in msg
    assert "Иван Петров" in msg

    old_role = dict(old_cast)
    new_role = dict(old_cast)
    old_role["performers"] = ["Флория Тоска — Мария Иванова"]
    new_role["performers"] = ["Флория Тоска — Хибла Герзмава"]
    msg = format_changed(old_role, new_role)
    assert "Хибла Герзмава" in msg
    assert "Мария Иванова" in msg

    old_joconda = dict(old_cast)
    new_joconda = dict(old_cast)
    old_joconda["title"] = "Джоконда"
    new_joconda["title"] = "Джоконда"
    old_joconda["event_type"] = "opera"
    new_joconda["event_type"] = "opera"
    old_joconda["performers"] = ["Дирижер — Валерий Гергиев"]
    new_joconda["performers"] = [
        "Дирижер — Валерий Гергиев",
        "Главные партии — Татьяна Сержан",
        "Главные партии — Зинаида Царенко",
        "Главные партии — Нажмиддин Мавлянов",
    ]
    old_joconda["digest"] = "same-as-new-by-bug"
    new_joconda["digest"] = "same-as-new-by-bug"
    msg = format_changed(old_joconda, new_joconda)
    assert "Главные партии — Татьяна Сержан" in msg
    assert "Главные партии — Зинаида Царенко" in msg

    noisy_old = dict(old_cast)
    noisy_new = dict(old_cast)
    noisy_old["performers"] = []
    noisy_new["performers"] = [
        "Санкт — Петербург",
        "Зал Стравинского",
        "опера Николая Римского — Корсакова",
        "Орган",
        "Исполнители",
    ]
    noisy_new["program"] = [
        "опера Дмитрия Шостаковича",
        "К 120—летию со дня рождения Дмитрия Шостаковича",
        "Дмитрий Шостакович",
    ]
    assert format_changed(noisy_old, noisy_new) == ""

    dirty_state_record = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/4/2_1900/",
        "title": "Джоконда",
        "venue": "Мариинский-2",
        "date_text": "4 июля 2026",
        "time_text": "19:00",
        "event_type": "opera",
        "performers": [
            "Орган",
            "Исполняется на итальянском языке (сопровождается синхронными титрами на русском языке)",
            "Исполнители",
            "Дирижер — Валерий Гергиев",
        ],
        "program": ["Виртуальная выставка «Однажды в Венеции»"],
        "digest": "wrong-old-digest",
    }
    clean_state = sanitize_events("mariinsky", {dirty_state_record["url"]: dirty_state_record})
    rec = list(clean_state.values())[0]
    assert rec["performers"] == ["Дирижер — Валерий Гергиев"]
    assert rec["program"] == []
    assert rec["digest"] != "wrong-old-digest"

    concert_state_record = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/6/2_2000/",
        "title": "Шостакович. Четвертая симфония",
        "venue": "Мариинский-2",
        "date_text": "6 июля 2026",
        "time_text": "20:00",
        "event_type": "concert",
        "performers": ["Симфонический оркестр Мариинского театра", "Дирижер — Валерий Гергиев"],
        "program": ["Симфония № 4 до минор, соч. 43"],
    }
    assert sanitize_events("mariinsky", {concert_state_record["url"]: concert_state_record})

    assert is_mariinsky_ballet_record({
        "source": "mariinsky",
        "title": "Виктория Терёшкина. 25 лет на сцене",
        "event_type": "opera",
        "performers": ["Хореография Ильи Живого"],
        "program": ["«Шехеразада»"],
    })

    assert is_mariinsky_list_ballet_meta({
        "title": "Виктория Терёшкина. 25 лет на сцене",
        "list_type": "ballet",
        "list_text": "гала-концерт балета",
    })

    pending = sanitize_pending_messages([
        "СПб филармония, Большой зал\n🐣 Новое событие\n\nНазвание: С помощью:",
        "𝄞 Мариинский-2\n🐣 Новое событие\n\nНазвание: Тоска",
    ])
    assert pending == ["𝄞 Мариинский-2\n🐣 Новое событие\n\nНазвание: Тоска"]

    old_move = {
        "source": "mariinsky",
        "url": "old-url",
        "title": "Тоска",
        "venue": "Мариинский-2",
        "date_text": "1 августа 2026",
        "time_text": "19:00",
        "event_date": "2026-08-01",
        "event_type": "opera",
        "performers": [],
        "program": [],
    }
    new_move = dict(old_move)
    new_move["url"] = "new-url"
    new_move["date_text"] = "2 августа 2026"
    new_move["event_date"] = "2026-08-02"
    move_messages, _ = build_messages_for_source(
        "mariinsky",
        {"old-url": old_move},
        {"new-url": new_move},
        seen_urls=set(),
        failed_urls=set(),
    )
    assert len(move_messages) == 1
    assert "Изменение даты / времени" in move_messages[0]

    print("SELF_TEST_OK")


if __name__ == "__main__":
    if SELF_TEST:
        run_self_tests()
    else:
        main()
