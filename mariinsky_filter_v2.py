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
FILTER_VERSION = "V2.9.3-participation-cast-title-mark"

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
    "User-Agent": "Mozilla/5.0 MariinskyWatcherV2/2.9.3 (+https://github.com/fageehamalal-max/mariinsky-watcher)",
    "Accept-Language": "ru,en;q=0.9",
})

EMOJI_NEW = "🐣"
EMOJI_ADDED = "✅"
EMOJI_REMOVED = "⛔"
EMOJI_DATE = "🔸"
MARIINSKY_MARK = "𝄞"

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
MONTH_WORD_RE = r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября)"

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

PERFORMERS_HEADERS = {"исполнители", "исполнитель", "состав исполнителей", "солисты"}
PROGRAM_HEADERS = {"в программе", "программа", "полная программа"}
STOP_DETAIL_SECTIONS = {
    "краткое содержание",
    "содержание",
    "либретто",
    "история",
    "история создания",
    "первое исполнение",
    "о спектакле",
    "об опере",
    "о произведении",
    "аннотация",
    "возрастная категория",
    "фотогалерея",
    "медиа",
    "рецензии",
}
EXTERNAL_STAGE_MARKERS = ["Приморская сцена", "Владивосток", "Владикавказ", "РСО-Алания"]

MENU_RE = re.compile(
    r"^(Афиша и билеты|Подарочные карты|Детям|Визит в театр|Труппа|О театре|Новости|Для прессы|Афиша|Абонементы|Фестивали|Репертуар|Изменения в афише|Выбрать сцену|Все площадки|Все спектакли|Архив афиши|Полная программа|Показать спектакли.*)$",
    re.I,
)
FOOTER_RE = re.compile(
    r"^(Для обращений|Справочная служба|По вопросам реализации билетов|Скачать мобильное приложение|Любое использование|Закрыть|Вход в личный кабинет|Официальные билеты|Поделиться)$",
    re.I,
)
NOISE_RE = re.compile(
    r"(@@|купить|заказать|продажа|стоимость|цена|билет|билетов|билеты|касс[аеы]|авторизация|войти|регистрация|личный кабинет|cookie|cookies|согласие на использование|подписаться|поиск|версия для слабовидящих|опрос|для обращений|справочная служба|скачать мобильное приложение|mariinsky\.tv|mariinsky\.fm|правообладател|зв[её]здный состав|блестящий состав|история постановки|описание спектакля)",
    re.I,
)

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

BALLET_TITLES = {
    "адажио хаммерклавир",
    "анна каренина",
    "арлекинада",
    "бахчисарайский фонтан",
    "баядерка",
    "видение розы",
    "вечер балетов",
    "времена года",
    "дон кихот",
    "жар птица",
    "жар-птица",
    "жизель",
    "золушка",
    "кармен-сюита",
    "карнавал шехеразада",
    "карнавал. шехеразада",
    "конек горбунок",
    "конёк горбунок",
    "корсар",
    "лебединое озеро",
    "легенда о любви",
    "манон",
    "марко спада",
    "медный всадник",
    "пахита",
    "петрушка",
    "пламя парижа",
    "раймонда",
    "ромео и джульетта",
    "сильфида",
    "спартак",
    "спящая красавица",
    "тысяча и одна ночь",
    "шехеразада",
    "шопениана",
    "щелкунчик",
    "виктория терешкина 25 лет на сцене",
    "виктория терёшкина 25 лет на сцене",
}

OPERA_TITLES = {
    "аида",
    "аттила",
    "бал маскарад",
    "бал-маскарад",
    "богема",
    "борис годунов",
    "валькирия",
    "вильгельм телль",
    "война и мир",
    "волшебная флейта",
    "гибель богов",
    "девушка с запада",
    "директор театра",
    "дон карлос",
    "дон жуан",
    "джоконда",
    "евгений онегин",
    "женитьба фигаро",
    "зигфрид",
    "золото рейна",
    "золотой петушок",
    "идиот",
    "иоланта",
    "итальянка в алжире",
    "кармен",
    "князь игорь",
    "кощей бессмертный",
    "леди макбет мценского уезда",
    "летучая мышь",
    "лоэнгрин",
    "лючия ди ламмермур",
    "мазепа",
    "макбет",
    "мефистофель",
    "млада",
    "моцарт и сальери",
    "набукко",
    "нос",
    "обручение в монастыре",
    "отелло",
    "паяцы",
    "парсифаль",
    "пиковая дама",
    "псковитянка",
    "риголетто",
    "русалка",
    "садко",
    "самсон и далила",
    "свадьба фигаро",
    "севильский цирюльник",
    "сестра анжелика",
    "сестра анжелика джанни скикки",
    "симон бокканегра",
    "сказание о невидимом граде китеже и деве февронии",
    "сказка о царе салтане",
    "скупой рыцарь",
    "снегурочка",
    "сельская честь",
    "тоска",
    "травиата",
    "троянцы",
    "трубадур",
    "турандот",
    "турок в италии",
    "фауст",
    "фальстаф",
    "хованщина",
    "царская невеста",
    "чародейка",
    "человеческий голос",
}

LIST_BALLET_MARKERS = [
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
    "исполняется под фонограмму",
]
LIST_OPERA_MARKERS = ["опера", "опера-буффа", "драма в музыке", "музыкальная драма", "моноопера"]
LIST_CONCERT_MARKERS = [
    "концерт",
    "концерты",
    "кантата",
    "оратория",
    "реквием",
    "месса",
    "симфонический оркестр",
    "вокальные циклы",
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
    "танц",
    "прелюди",
    "фуга",
    "квартет",
    "квинтет",
    "месса",
    "вариаци",
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
    "Барбер",
    "Бернстайн",
    "Копленд",
    "Пьяццолла",
    "Респиги",
    "Глинка",
    "Мусоргский",
    "Бородин",
    "Масканьи",
    "Пуччини",
    "Россини",
    "Доницетти",
    "Беллини",
    "Бизе",
    "Гуно",
    "Массне",
    "Равель",
    "Малер",
    "Брукнер",
    "Шостакович",
    "Понкьелли",
    "Берлиоз",
    "Делиб",
    "Римский",
    "Корсаков",
]
ROLE_WORDS = [
    "дирижер",
    "дирижёр",
    "солист",
    "солистка",
    "солисты",
    "исполнитель",
    "исполнительница",
    "исполнители",
    "сопрано",
    "тенор",
    "баритон",
    "бас",
    "скрипка",
    "альт",
    "виолончель",
    "фортепиано",
    "кларнет",
    "флейта",
    "хор",
    "оркестр",
    "ансамбль",
    "концертмейстер",
    "хормейстер",
]
PRODUCTION_CREDIT_PREFIXES = [
    "хореография",
    "хореограф",
    "исполняется под фонограмму",
    "постановка",
    "сценография",
    "костюмы",
    "свет",
    "видео",
    "либретто",
    "автор",
    "режиссер-постановщик",
    "режиссёр-постановщик",
    "режиссер",
    "режиссёр",
]
MEANINGLESS_PERFORMER_LINES = {
    "орган",
    "исполнители",
    "исполнитель",
    "солисты",
    "солист",
    "солистка",
    "в главных партиях",
}
LOCATION_LINES = {
    "санкт петербург",
    "санкт-петербург",
    "санкт — петербург",
    "санкт – петербург",
    "мариинский театр",
    "мариинский 2",
    "мариинский-2",
    "концертный зал",
    "зал стравинского",
    "камерные залы",
    "зал щедрина",
    "зал мусоргского",
    "концертный зал мариинского театра",
}
CAST_PLACEHOLDER_PATTERNS = [
    "состав исполнителей будет объявлен позднее",
    "состав будет объявлен позднее",
    "исполнители будут объявлены позднее",
    "исполнители будут объявлены дополнительно",
    "состав исполнителей уточняется",
    "будет объявлен позднее",
    "будут объявлены позднее",
]


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
    performers_source: str = "none"
    main_roles: list[str] = field(default_factory=list)
    main_roles_source: str = "none"
    program: list[str] = field(default_factory=list)
    program_source: str = "none"
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
        "main_roles": list(record.get("main_roles", []) or []),
        "program": list(record.get("program", []) or []),
    }


def refresh_record_digest(record):
    record["digest"] = digest_obj(record_core(record))
    return record


def event_move_key(record):
    return "|".join([title_key(record.get("title", "")), title_key(record.get("venue", ""))])


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


def is_noise(line):
    line = clean(line)
    if not line:
        return True
    low = canonical_low(line)
    if MENU_RE.fullmatch(line) or FOOTER_RE.fullmatch(line) or NOISE_RE.search(line):
        return True
    if "абонемент" in low or any(p in low for p in CAST_PLACEHOLDER_PATTERNS):
        return True
    return False


def is_location_line(line):
    low = title_key(line)
    if low in LOCATION_LINES or clean(line) in MARIINSKY_VENUES:
        return True
    if "санкт петербург" in low and any(x in low for x in ["концертный зал", "мариинский театр", "мариинский 2"]):
        return True
    return False


def is_genre_description(line):
    low = canonical_low(line)
    if low.startswith(("опера ", "оперы ", "балет ", "балеты ", "гала-концерт")):
        return True
    return bool(re.fullmatch(r"опера(\s+.+)?", low))


def is_explanatory_line(line):
    low = canonical_low(line)
    bad_starts = [
        "к ",
        "ко ",
        "посвящается",
        "к юбилею",
        "в рамках",
        "при поддержке",
        "фестиваль",
        "звезды белых ночей",
        "звёзды белых ночей",
        "виртуальная выставка",
        "первое исполнение",
        "мировая премьера",
        "премьера состоялась",
        "впервые исполнено",
    ]
    return any(low.startswith(x) for x in bad_starts)


def html_lines(html_or_soup):
    soup = BeautifulSoup(html_or_soup, "lxml") if isinstance(html_or_soup, str) else html_or_soup
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
    return out


def find_section(lines, header_keys, stop_keys=None, max_lines=80):
    stop_keys = set(stop_keys or [])
    for i, line in enumerate(lines):
        low = title_key(line)
        if low in header_keys:
            section = []
            for nxt in lines[i + 1:i + 1 + max_lines]:
                nlow = title_key(nxt)
                if nlow in header_keys or nlow in stop_keys or nlow in PERFORMERS_HEADERS or nlow in PROGRAM_HEADERS:
                    break
                if any(nlow.startswith(x) for x in STOP_DETAIL_SECTIONS):
                    break
                section.append(nxt)
            return section
    return []


def is_valid_title(title):
    title = clean(title)
    low = title_key(title)
    if not title or len(title) < 3:
        return False
    if low in BAD_TITLES or "cookie" in low:
        return False
    if is_noise(title) or is_location_line(title) or is_date_line(title) or is_time_line(title):
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


def date_text_from_parts(year, month, day):
    y, m, d = int(year), int(month), int(day)
    return date(y, m, d), f"{d} {MONTHS[m]} {y}"


def parse_mariinsky_date(url):
    m = re.search(r"/playbill/playbill/(\d{4})/(\d{1,2})/(\d{1,2})/(\d+)_(\d{4})/", str(url or ""))
    if not m:
        return None, "", "", "Мариинский театр"
    event_date, date_text = date_text_from_parts(m.group(1), m.group(2), m.group(3))
    time_raw = m.group(5)
    venue = VENUE_BY_CODE.get(m.group(4), "Мариинский театр")
    return event_date, date_text, f"{time_raw[:2]}:{time_raw[2:]}", venue


def venue_from_mariinsky_url(url):
    m = re.search(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/(\d+)_\d{4}/", str(url or ""))
    if not m:
        return ""
    return VENUE_BY_CODE.get(m.group(1), "")


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
    return venue or "Мариинский театр"


def display_title(record):
    return clean(record.get("title", "")) or "Без названия"


def title_line(record):
    return f"{MARIINSKY_MARK} {display_title(record)}"


def infer_mariinsky_list_type(text):
    low = canonical_low(text)
    if any(x in low for x in LIST_OPERA_MARKERS):
        return "opera"
    if any(x in low for x in LIST_CONCERT_MARKERS):
        return "concert"
    if any(x in low for x in LIST_BALLET_MARKERS):
        return "ballet"
    return ""


def is_opera_title(title):
    t = title_key(title)
    if t in OPERA_TITLES:
        return True
    return any(t == x or t.startswith(x + " ") for x in OPERA_TITLES)


def is_ballet_genre_line(line):
    low = title_key(line)
    if low in {"балет", "балеты", "одноактный балет", "вечер балетов"}:
        return True
    return bool(re.fullmatch(r"балет(ы)?(\s+в\s+.+\s+действиях?)?", low))


def is_ballet_event(title, lines, list_type="", allow_content_markers=False):
    if list_type in {"opera", "concert"}:
        return False, "explicit_non_ballet"
    if is_opera_title(title):
        return False, "opera_title"
    if list_type == "ballet":
        return True, "list_ballet"

    t = title_key(title)
    if t in BALLET_TITLES:
        return True, "ballet_title"

    if any(is_ballet_genre_line(x) for x in lines[:30]):
        return True, "ballet_genre"

    if allow_content_markers:
        text = canonical_low(" ".join([title] + list(lines[:60])))
        hard = [
            "гала-концерт балета",
            "артисты балета",
            "театр балета",
            "па-де-де",
            "исполняется под фонограмму",
        ]
        if any(x in text for x in hard):
            return True, "ballet_content_marker"

    return False, ""


def has_opera_marker(lines):
    for line in lines[:80]:
        low = title_key(line)
        if low == "опера" or low.startswith("опера "):
            return True
        if marker_in_text(line, "опера") or marker_in_text(line, "моноопера") or marker_in_text(line, "опера-буффа"):
            return True
    return False


def classify_event(title, lines, list_type=""):
    if list_type == "opera":
        return "opera", "list_opera"
    if list_type == "concert":
        return "concert", "list_concert"
    if is_opera_title(title):
        return "opera", "opera_title"
    if has_opera_marker(lines):
        return "opera", "opera_marker"

    is_ballet, reason = is_ballet_event(title, lines, list_type=list_type, allow_content_markers=False)
    if is_ballet:
        return "ballet", reason

    if has_composer(title) or contains_word(title, PROGRAM_WORDS) or any(has_composer(x) for x in lines[:30]):
        return "concert", "music_marker"

    return "concert", "ambiguous_included"


def mariinsky_card_text_for_link(a):
    link_text = clean(a.get_text(" ", strip=True))
    best = link_text
    for parent in a.parents:
        name = getattr(parent, "name", "")
        if name in {"body", "html", "[document]"}:
            break
        if not hasattr(parent, "get_text"):
            continue
        text = clean(parent.get_text(" ", strip=True))
        if not text or len(text) > 2600:
            continue
        if link_text and link_text in text:
            best = text
            if infer_mariinsky_list_type(text):
                return text
    return best


def fallback_title_from_meta(fallback):
    return clean(fallback.get("title", "")) if isinstance(fallback, dict) else clean(fallback)


def fallback_list_text(fallback):
    return clean(fallback.get("list_text", "")) if isinstance(fallback, dict) else ""


def split_people(text):
    text = clean(text).strip(" :;,-–—")
    return [clean(x) for x in re.split(r"\s*,\s*|\s*;\s*", text) if clean(x)]


def split_participation_people(text):
    text = clean(text).strip(" :;,-–—")
    text = re.sub(r"\s+и\s+", ", ", text, flags=re.I)
    text = re.sub(r"\s*;\s*", ", ", text)
    return [clean(x) for x in re.split(r"\s*,\s*", text) if clean(x)]


def strip_voice_note(s):
    return clean(re.sub(r"\s*\([^)]{1,80}\)\s*", " ", s))


def looks_like_person_name_single(line):
    line = strip_voice_note(line).strip("()[]")
    if not line or is_noise(line) or is_date_line(line) or is_time_line(line):
        return False
    if is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False
    if has_composer(line) or contains_word(line, PROGRAM_WORDS):
        return False
    words = [w for w in re.split(r"\s+", line.replace(".", " ")) if w]
    if not (1 <= len(words) <= 5):
        return False
    return all(re.match(r"^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+$", w) for w in words)


def looks_like_person_list(line):
    parts = split_people(line)
    return bool(parts) and all(looks_like_person_name_single(p) for p in parts)


def looks_like_ensemble_phrase(line):
    if is_noise(line) or is_date_line(line) or is_time_line(line) or is_location_line(line):
        return False
    low = canonical_low(line)
    if re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low):
        return False
    return any(marker_in_text(line, x) for x in ["оркестр", "хор", "ансамбль"])


def is_production_credit_label(label):
    low = canonical_low(label)
    return any(low.startswith(x) for x in PRODUCTION_CREDIT_PREFIXES)


def is_role_label(label):
    low = canonical_low(label)
    if is_production_credit_label(label):
        return False
    if contains_word(label, ROLE_WORDS):
        return True
    if 1 <= len(label.split()) <= 8 and not has_composer(label) and not contains_word(label, PROGRAM_WORDS):
        return True
    return False


def is_labeled_performer_line(line):
    line = clean(line)
    m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", line)
    if not m:
        return False
    label, rest = clean(m.group(1)), clean(m.group(2))
    if not label or not rest or is_noise(rest):
        return False
    if is_location_line(line) or is_location_line(label) or is_location_line(rest):
        return False
    if title_key(rest) in MEANINGLESS_PERFORMER_LINES:
        return False
    if is_genre_description(label) or is_explanatory_line(label) or is_explanatory_line(line):
        return False
    if is_production_credit_label(label):
        return False
    if not is_role_label(label):
        return False
    return looks_like_person_list(rest) or looks_like_person_name_single(rest) or looks_like_ensemble_phrase(rest)


def is_ensemble_performer_line(line):
    if is_location_line(line) or is_genre_description(line) or is_explanatory_line(line):
        return False
    low = canonical_low(line)
    if re.search(r"\bдля\b.*\b(оркестр|хор|ансамбль)", low):
        return False
    return looks_like_ensemble_phrase(line) and (
        "мариинск" in low
        or "театра" in low
        or low.startswith(("симфонический", "камерный", "хор", "оркестр", "ансамбль"))
    )


def is_valid_performer_piece(item):
    item = clean(item)
    if not item:
        return False
    if is_noise(item) or is_location_line(item) or is_genre_description(item) or is_explanatory_line(item):
        return False
    if title_key(item) in MEANINGLESS_PERFORMER_LINES:
        return False
    return is_labeled_performer_line(item) or is_ensemble_performer_line(item) or looks_like_person_name_single(item)


def normalize_performer_line(line):
    line = clean(line).replace("–", "—")
    m = re.match(r"^(.+?)\s+[—-]\s+(.+)$", line)
    if not m:
        m = re.match(r"^(.+?)\s*:\s*(.+)$", line)
    if not m:
        return line
    label, rest = clean(m.group(1)), clean(m.group(2))
    return f"{label} — {rest}"


def performer_compare_key(item):
    item = normalize_performer_line(item)
    m = re.match(r"^(.+?)\s*—\s*(.+)$", item)
    if m:
        label = title_key(m.group(1))
        rest = title_key(strip_voice_note(m.group(2)))
        return f"{label}|{rest}"
    return title_key(strip_voice_note(item))


def performer_names(items):
    names = set()
    for item in items or []:
        m = re.match(r"^(.+?)\s*[-–—:]\s*(.+)$", clean(item))
        if m:
            rest = clean(m.group(2))
            for part in split_people(rest):
                if looks_like_person_name_single(part):
                    names.add(title_key(strip_voice_note(part)))
        elif looks_like_person_name_single(item):
            names.add(title_key(strip_voice_note(item)))
    return names


def performer_last_names(items):
    out = set()
    for name in performer_names(items):
        parts = [p for p in name.split() if p]
        if parts:
            out.add(parts[-1])
    return out


def uniq_text(items, key_func=None):
    out = []
    seen = set()
    key_func = key_func or (lambda x: title_key(x))
    for item in items or []:
        item = clean(item)
        k = key_func(item)
        if item and k and k not in seen:
            out.append(item)
            seen.add(k)
    return out


def sanitize_parsed_performers(items):
    out = []
    seen = set()
    for item in items or []:
        item = normalize_performer_line(item)
        if not is_valid_performer_piece(item):
            continue
        k = performer_compare_key(item)
        if k and k not in seen:
            out.append(item)
            seen.add(k)
    return out


def extract_participation_performers(text):
    text = clean(text)
    if not text:
        return []

    out = []
    pattern = re.compile(
        rf"\bпри\s+участии\s+(.+?)(?=\s+(?:дириж[её]р|хормейстер|концертмейстер|режисс[её]р|хор|оркестр)\s*[—–\-:]|\s+(?:Мариинский театр|Мариинский-2|Концертный зал|Зал Стравинского|Зал Щедрина|Зал Мусоргского|Камерные залы)\b|\s+\d{{1,2}}\s+{MONTH_WORD_RE}\b|$)",
        re.I,
    )

    for match in pattern.finditer(text):
        raw_people = clean(match.group(1))
        for person in split_participation_people(raw_people):
            person = strip_voice_note(person)
            if looks_like_person_name_single(person):
                out.append(person)

    return uniq_text(out, key_func=lambda x: title_key(strip_voice_note(x)))


def extract_detail_performers(lines):
    section = find_section(lines, PERFORMERS_HEADERS, STOP_DETAIL_SECTIONS | PROGRAM_HEADERS, max_lines=90)
    out = []
    for line in section:
        line = clean(line).replace("–", "—")
        if title_key(line) in MEANINGLESS_PERFORMER_LINES:
            continue

        out.extend(extract_participation_performers(line))

        if is_labeled_performer_line(line) or is_ensemble_performer_line(line):
            out.append(line)

    return sanitize_parsed_performers(out)


def is_program_line(line, title):
    line = clean(line)
    if not line or len(line) > 220:
        return False
    if is_noise(line) or is_location_line(line) or is_explanatory_line(line) or is_date_line(line) or is_time_line(line):
        return False
    if title_key(line) == title_key(title) or is_labeled_performer_line(line) or is_ensemble_performer_line(line):
        return False
    if is_genre_description(line) or is_ballet_genre_line(line):
        return False
    if has_composer(line):
        words = [w for w in re.split(r"\s+", line) if w]
        if len(words) <= 3 and not contains_word(line, PROGRAM_WORDS):
            return False
        return True
    return contains_word(line, PROGRAM_WORDS) or "«" in line or "»" in line


def extract_program_section(lines, title):
    section = find_section(lines, PROGRAM_HEADERS, STOP_DETAIL_SECTIONS | PERFORMERS_HEADERS, max_lines=120)
    out = []
    for line in section:
        if is_program_line(line, title):
            out.append(line)
    return uniq_text(out, key_func=lambda x: title_key(x))


def extract_list_main_roles(list_text):
    text = clean(list_text)
    if not text:
        return []
    out = []
    pattern = re.compile(
        rf"(?:в\s+главных\s+партиях|главные\s+партии)\s*[:—-]\s*(.+?)(?=\s+(?:дириж[её]р|режисс[её]р|хор|оркестр)\s*[:—–-]|\s+\d{{1,2}}\s+{MONTH_WORD_RE}\b|\s+(?:Мариинский театр|Мариинский-2|Концертный зал|Зал Стравинского|Зал Щедрина|Зал Мусоргского|Камерные залы)\b|$)",
        re.I,
    )
    for match in pattern.finditer(text):
        for person in split_people(match.group(1)):
            if looks_like_person_name_single(person):
                out.append(strip_voice_note(person))
    return uniq_text(out, key_func=lambda x: title_key(strip_voice_note(x)))


def extract_list_performers(list_text):
    text = clean(list_text)
    out = []

    out.extend(extract_participation_performers(text))

    role_pattern = re.compile(
        rf"\b(Дириж[её]р|Хормейстер|Концертмейстер)\s*[—–-]\s*([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z .'-]{{2,80}})(?=\s+(?:Мариинский театр|Мариинский-2|Концертный зал|Зал Стравинского|Зал Щедрина|Зал Мусоргского|Камерные залы)\b|\s+\d{{1,2}}\s+{MONTH_WORD_RE}\b|$)",
        re.I,
    )
    for m in role_pattern.finditer(text):
        candidate = f"{clean(m.group(1))} — {clean(m.group(2))}"
        if is_labeled_performer_line(candidate):
            out.append(candidate)

    if "Симфонический оркестр Мариинского театра" in text:
        out.insert(0, "Симфонический оркестр Мариинского театра")

    return sanitize_parsed_performers(out)


def sanitize_main_roles(items):
    out = []
    for item in items or []:
        item = strip_voice_note(item)
        if looks_like_person_name_single(item):
            out.append(item)
    return uniq_text(out, key_func=lambda x: title_key(strip_voice_note(x)))


def sanitize_parsed_program(items, title):
    return uniq_text([x for x in (items or []) if is_program_line(x, title)], key_func=lambda x: title_key(x))


def merge_detail_and_list_performers(detail_performers, list_performers):
    detail_performers = sanitize_parsed_performers(detail_performers)
    list_performers = sanitize_parsed_performers(list_performers)

    if not detail_performers:
        return list_performers, "list_card" if list_performers else "none"

    out = list(detail_performers)
    seen = {performer_compare_key(x) for x in out}
    detail_last_names = performer_last_names(out)

    for item in list_performers:
        k = performer_compare_key(item)
        if not k or k in seen:
            continue

        item_names = performer_names([item])
        item_last_names = set()
        for name in item_names:
            parts = [p for p in name.split() if p]
            if parts:
                item_last_names.add(parts[-1])

        if item_last_names and item_last_names <= detail_last_names:
            continue

        out.append(item)
        seen.add(k)

    source = "detail_plus_list_card" if len(out) > len(detail_performers) else "detail_section"
    return out, source


def build_event_record(
    source,
    url,
    title,
    venue,
    event_date,
    date_text,
    time_text,
    event_type,
    detail_performers,
    list_performers,
    list_main_roles,
    program,
):
    detail_performers = sanitize_parsed_performers(detail_performers)
    list_performers = sanitize_parsed_performers(list_performers)
    performers, performers_source = merge_detail_and_list_performers(detail_performers, list_performers)

    list_main_roles = sanitize_main_roles(list_main_roles)
    program = sanitize_parsed_program(program, title)

    detail_names = performer_names(performers)
    if detail_names:
        main_roles = [p for p in list_main_roles if title_key(strip_voice_note(p)) not in detail_names]
    else:
        main_roles = list_main_roles

    main_roles_source = "list_main_roles" if main_roles else "none"
    program_source = "program_section" if program else "none"

    rec = ParsedEvent(
        source=source,
        url=canonical_url(url),
        title=clean(title) or "Без названия",
        venue=clean(venue),
        date_text=clean(date_text),
        time_text=clean(time_text),
        event_date=event_date.isoformat() if isinstance(event_date, date) else "",
        event_type=clean(event_type),
        performers=performers,
        performers_source=performers_source,
        main_roles=main_roles,
        main_roles_source=main_roles_source,
        program=program,
        program_source=program_source,
    )
    data = rec.to_state_record()
    rec.digest = digest_obj(record_core(data))
    return rec


def audit_item(
    url,
    source,
    status,
    reason,
    title="",
    venue="",
    date_text="",
    time_text="",
    event_type="",
    performers=None,
    performers_source="none",
    main_roles=None,
    program=None,
    program_source="none",
    error="",
):
    performers = performers or []
    main_roles = main_roles or []
    program = program or []
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
        "performers_count": len(performers),
        "performers_source": performers_source,
        "performers_preview": performers[:8],
        "main_roles_count": len(main_roles),
        "main_roles_preview": main_roles[:8],
        "program_count": len(program),
        "program_source": program_source,
        "program_preview": program[:8],
        "error": clean(error),
    }


def first_safe_time(lines):
    for line in lines[:80]:
        low = canonical_low(line)
        if low.startswith(("в программе", "программа", "исполнители", "исполнитель")):
            continue
        value = parse_time(line)
        if value:
            return value
    return ""


def parse_mariinsky_event(url, fallback=""):
    event_date, date_text, time_text, venue = parse_mariinsky_date(url)
    fallback_title = fallback_title_from_meta(fallback)
    list_text = fallback_list_text(fallback)
    list_type = fallback.get("list_type", "") if isinstance(fallback, dict) else ""
    list_lines = html_lines(list_text)

    if list_type == "ballet":
        return None, audit_item(
            url,
            "mariinsky",
            "skipped",
            "list_ballet",
            title=fallback_title,
            venue=venue,
            date_text=date_text,
            time_text=time_text,
            event_type="ballet",
        )

    if list_type not in {"opera", "concert"}:
        is_ballet, ballet_reason = is_ballet_event(
            fallback_title,
            list_lines,
            list_type=list_type,
            allow_content_markers=True,
        )
        if is_ballet:
            return None, audit_item(
                url,
                "mariinsky",
                "skipped",
                ballet_reason,
                title=fallback_title,
                venue=venue,
                date_text=date_text,
                time_text=time_text,
                event_type="ballet",
            )

    soup = BeautifulSoup(fetch(url), "lxml")
    lines = html_lines(soup)
    title = title_from_soup(soup, fallback_title)

    if not is_valid_title(title):
        return None, audit_item(
            url,
            "mariinsky",
            "skipped",
            "bad_title",
            title=title,
            venue=venue,
            date_text=date_text,
            time_text=time_text,
        )

    page_time = first_safe_time(lines)
    if page_time:
        time_text = page_time

    url_venue = venue_from_mariinsky_url(url)
    if url_venue:
        venue = url_venue

    if any(canonical_low(marker) in canonical_low(line) for marker in EXTERNAL_STAGE_MARKERS for line in [venue, title] + lines[:30]):
        return None, audit_item(
            url,
            "mariinsky",
            "skipped",
            "external_stage",
            title=title,
            venue=venue,
            date_text=date_text,
            time_text=time_text,
        )

    combined_for_class = list_lines + lines[:100]
    event_type, class_reason = classify_event(title, combined_for_class, list_type=list_type)

    if event_type == "ballet":
        return None, audit_item(
            url,
            "mariinsky",
            "skipped",
            class_reason,
            title=title,
            venue=venue,
            date_text=date_text,
            time_text=time_text,
            event_type=event_type,
        )

    detail_performers = extract_detail_performers(lines)
    list_performers = extract_list_performers(list_text)
    list_main_roles = extract_list_main_roles(list_text)
    program = extract_program_section(lines, title)

    rec = build_event_record(
        "mariinsky",
        url,
        title,
        venue,
        event_date,
        date_text,
        time_text,
        event_type,
        detail_performers,
        list_performers,
        list_main_roles,
        program,
    )

    return rec, audit_item(
        url,
        "mariinsky",
        "included",
        class_reason,
        title=rec.title,
        venue=rec.venue,
        date_text=rec.date_text,
        time_text=rec.time_text,
        event_type=rec.event_type,
        performers=rec.performers,
        performers_source=rec.performers_source,
        main_roles=rec.main_roles,
        program=rec.program,
        program_source=rec.program_source,
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

        out.setdefault(
            url,
            {
                "title": title if is_valid_title(title) else "",
                "list_type": list_type,
                "list_text": card_text[:2400],
            },
        )

    return out


def collect_mariinsky_links(audit):
    links = {}
    for url in month_urls(MARIINSKY_ROOT, MONTHS_AHEAD):
        try:
            links.update(extract_mariinsky_links_from_html(fetch(url), url))
        except Exception as exc:
            audit["source_errors"].append(
                {"source": "mariinsky", "url": url, "error": f"{type(exc).__name__}: {exc}"}
            )
    return links


def read_source(source, links, parser, audit):
    events = {}
    seen_urls = set()
    failed_urls = set()

    for url, fallback in sorted(links.items()):
        try:
            rec, item = parser(url, fallback)
            audit["items"].append(item)

            if rec:
                events[rec.url] = rec.to_state_record()
                seen_urls.add(rec.url)

            time.sleep(0.2)
        except Exception as exc:
            failed_urls.add(canonical_url(url))
            audit["items"].append(
                audit_item(url, source, "failed", "fetch_or_parse_failed", error=f"{type(exc).__name__}: {exc}")
            )

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

    links = collect_mariinsky_links(audit)
    scanned, seen_urls, failed_urls = {}, {}, {}

    scanned["mariinsky"], seen_urls["mariinsky"], failed_urls["mariinsky"] = read_source(
        "mariinsky",
        links,
        parse_mariinsky_event,
        audit,
    )

    source_items = [x for x in audit["items"] if x["source"] == "mariinsky"]
    audit["summary"]["mariinsky"] = {
        "links_found": len(links),
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

    event_type = clean(record.get("event_type", ""))
    if event_type == "ballet":
        return True

    is_ballet, _ = is_ballet_event(
        record.get("title", ""),
        [record.get("title", ""), event_type] + list(record.get("performers", []) or []),
        list_type=event_type,
        allow_content_markers=False,
    )
    return is_ballet


def normalize_source(src):
    src = clean(src)
    return src if src in {"detail_section", "list_card", "detail_plus_list_card", "list_main_roles", "none"} else "none"


def sanitize_events(source, events):
    events = dict(events or {})
    out = {}

    for url, rec in events.items():
        if not isinstance(rec, dict):
            continue

        rec = dict(rec)

        if rec.get("source") and rec.get("source") != "mariinsky":
            continue

        rec["source"] = "mariinsky"
        rec["url"] = canonical_url(rec.get("url") or url)

        url_venue = venue_from_mariinsky_url(rec["url"])
        if url_venue:
            rec["venue"] = url_venue

        if is_mariinsky_ballet_record(rec):
            continue

        if rec.get("event_type") not in {"opera", "concert"}:
            inferred, _ = classify_event(
                rec.get("title", ""),
                [rec.get("title", "")] + list(rec.get("program", []) or []),
                list_type="",
            )
            if inferred == "ballet":
                continue
            rec["event_type"] = inferred

        rec["performers"] = sanitize_parsed_performers(rec.get("performers", []) or [])
        rec["performers_source"] = normalize_source(
            rec.get("performers_source", "detail_section" if rec["performers"] else "none")
        )
        rec["main_roles"] = sanitize_main_roles(rec.get("main_roles", []) or [])
        rec["main_roles_source"] = "list_main_roles" if rec["main_roles"] else "none"
        rec["program"] = sanitize_parsed_program(rec.get("program", []) or [], rec.get("title", ""))
        rec["program_source"] = "program_section" if rec["program"] else "none"

        refresh_record_digest(rec)
        out[rec["url"]] = rec

    return out


def source_rank(src):
    return {
        "none": 0,
        "list_main_roles": 1,
        "list_card": 1,
        "detail_section": 2,
        "detail_plus_list_card": 3,
    }.get(clean(src), 0)


def merge_safe_record(old, new):
    if not isinstance(old, dict):
        return dict(new)

    merged = dict(new)

    old_performers = sanitize_parsed_performers(old.get("performers", []) or [])
    new_performers = sanitize_parsed_performers(new.get("performers", []) or [])
    old_src = normalize_source(old.get("performers_source", "detail_section" if old_performers else "none"))
    new_src = normalize_source(new.get("performers_source", "detail_section" if new_performers else "none"))

    title_changed = title_key(old.get("title", "")) != title_key(new.get("title", ""))

    if not title_changed:
        if old_performers and (
            source_rank(new_src) < source_rank(old_src)
            or (len(new_performers) < max(1, len(old_performers) // 2) and old_src in {"detail_section", "detail_plus_list_card"})
        ):
            merged["performers"] = old_performers
            merged["performers_source"] = old_src

        old_roles = sanitize_main_roles(old.get("main_roles", []) or [])
        new_roles = sanitize_main_roles(new.get("main_roles", []) or [])

        if old_roles and not new_roles and not performer_names(merged.get("performers", [])):
            merged["main_roles"] = old_roles
            merged["main_roles_source"] = "list_main_roles"

    refresh_record_digest(merged)
    return merged


def normalized_set_diff(old_items, new_items, key_func):
    old_map = {key_func(x): x for x in old_items or [] if key_func(x)}
    new_map = {key_func(x): x for x in new_items or [] if key_func(x)}
    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]
    return added, removed


def section_added_removed(title, added, removed):
    added = uniq_text(added, key_func=lambda x: title_key(x))
    removed = uniq_text(removed, key_func=lambda x: title_key(x))

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
    parts = [
        source_line(record),
        title_line(record),
        f"{EMOJI_NEW} Новое событие",
    ]

    dt = date_line(record)
    if dt:
        parts.append(dt)

    if record.get("main_roles"):
        parts += ["", "В главных партиях:"] + list(record.get("main_roles", []))

    if record.get("performers"):
        parts += ["", "Исполнители:"] + list(record.get("performers", [])[:12])

    parts += ["", f"Ссылка: {record.get('url', '')}"]
    return "\n".join(parts).strip()


def format_removed(record):
    parts = [
        source_line(record),
        title_line(record),
        f"{EMOJI_REMOVED} Событие исчезло",
    ]

    dt = date_line(record)
    if dt:
        parts.append(dt)

    parts += ["", f"Ссылка: {record.get('url', '')}"]
    return "\n".join(parts).strip()


def is_mariinsky_url_time_guess(record):
    m = re.search(r"/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_(\d{4})/", record.get("url", ""))
    if not m:
        return False

    raw = m.group(1)
    return clean(record.get("time_text", "")) == f"{raw[:2]}:{raw[2:]}"


def is_parser_time_correction(old, new):
    return (
        old.get("source") == "mariinsky"
        and new.get("source") == "mariinsky"
        and clean(old.get("title", "")) == clean(new.get("title", ""))
        and clean(old.get("venue", "")) == clean(new.get("venue", ""))
        and clean(old.get("date_text", "")) == clean(new.get("date_text", ""))
        and clean(old.get("time_text", "")) != clean(new.get("time_text", ""))
        and is_mariinsky_url_time_guess(old)
    )


def allow_performer_removals(old, new):
    old_src = normalize_source(old.get("performers_source", "detail_section" if old.get("performers") else "none"))
    new_src = normalize_source(new.get("performers_source", "detail_section" if new.get("performers") else "none"))
    old_count = len(old.get("performers", []) or [])
    new_count = len(new.get("performers", []) or [])

    if old_src in {"detail_section", "detail_plus_list_card"} and new_src in {"detail_section", "detail_plus_list_card"} and new_count >= max(1, old_count // 2):
        return True

    return False


def allow_main_role_removals(old, new):
    old_roles = old.get("main_roles", []) or []
    new_roles = new.get("main_roles", []) or []

    if not old_roles:
        return False

    if new_roles:
        return True

    if performer_names(new.get("performers", []) or []):
        return False

    return False


def is_title_replacement(old, new):
    return title_key(old.get("title", "")) != title_key(new.get("title", ""))


def format_replacement(old, new):
    old_title = display_title(old)
    new_title = display_title(new)

    parts = [
        source_line(new),
        f"{MARIINSKY_MARK} {old_title} → {new_title}",
    ]

    dt = date_line(new)
    if dt:
        parts.append(dt)

    parts += [
        "",
        "Замена спектакля:",
        "",
        f"{EMOJI_REMOVED} Было:",
        old_title,
        "",
        f"{EMOJI_ADDED} Стало:",
        new_title,
        "",
        f"Ссылка: {new.get('url', '')}",
    ]

    return "\n".join(parts).strip()


def change_sections(old, new):
    sections = []

    if not is_parser_time_correction(old, new):
        date_time_change = before_after("Изменение даты / времени:", date_line(old), date_line(new))
        if date_time_change:
            sections.append(date_time_change)

    venue_change = before_after("Изменение площадки:", source_line(old), source_line(new))
    if venue_change:
        sections.append(venue_change)

    perf_added, perf_removed = normalized_set_diff(
        old.get("performers", []),
        new.get("performers", []),
        performer_compare_key,
    )

    if perf_removed and not allow_performer_removals(old, new):
        perf_removed = []

    perf_section = section_added_removed("Изменение в составе:", perf_added, perf_removed)
    if perf_section:
        sections.append(perf_section)

    old_names = performer_names(old.get("performers", []) or [])
    new_names = performer_names(new.get("performers", []) or [])

    old_roles = [x for x in old.get("main_roles", []) or [] if title_key(strip_voice_note(x)) not in new_names]
    new_roles = [x for x in new.get("main_roles", []) or [] if title_key(strip_voice_note(x)) not in old_names]

    role_added, role_removed = normalized_set_diff(
        old_roles,
        new_roles,
        lambda x: title_key(strip_voice_note(x)),
    )

    if role_removed and not allow_main_role_removals(old, new):
        role_removed = []

    role_section = section_added_removed("Изменение в главных партиях:", role_added, role_removed)
    if role_section:
        sections.append(role_section)

    prog_added, prog_removed = normalized_set_diff(
        old.get("program", []),
        new.get("program", []),
        lambda x: title_key(x),
    )

    prog_section = section_added_removed("Изменение в программе:", prog_added, prog_removed)
    if prog_section:
        sections.append(prog_section)

    return sections


def format_changed(old, new):
    if is_title_replacement(old, new):
        return format_replacement(old, new)

    sections = change_sections(old, new)
    if not sections:
        return ""

    parts = [
        source_line(new),
        title_line(new),
    ]

    dt = date_line(new)
    if dt:
        parts.append(dt)

    parts.append("")
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


def is_false_venue_pending_message(text):
    text = str(text or "")

    if "Изменение площадки:" not in text:
        return False

    other_sections = [
        "Изменение в составе:",
        "Изменение в главных партиях:",
        "Изменение даты / времени:",
        "Изменение названия:",
        "Изменение в программе:",
        "Событие исчезло",
        "Новое событие",
        "Замена спектакля",
    ]

    if any(section in text for section in other_sections):
        return False

    url_match = re.search(
        r"https?://(?:www\.)?mariinsky\.ru/playbill/playbill/\d{4}/\d{1,2}/\d{1,2}/\d+_\d{4}/",
        text,
    )

    if not url_match:
        return False

    expected_venue = venue_from_mariinsky_url(url_match.group(0))
    if not expected_venue:
        return False

    new_match = re.search(r"✅ Стало:\s*\n\s*𝄞\s*([^\n\r]+)", text)
    if not new_match:
        return False

    new_venue = clean(new_match.group(1))
    return title_key(new_venue) != title_key(expected_venue)


def sanitize_pending_messages(messages):
    out = []
    seen = set()

    for msg in messages or []:
        text = str(msg or "")

        if MARIINSKY_MARK not in text:
            continue

        if is_false_venue_pending_message(text):
            continue

        k = title_key(text)
        if k not in seen:
            out.append(text)
            seen.add(k)

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
    return not any(source_data.get("events") for source_data in sources.values() if isinstance(source_data, dict))


def save_state(state):
    state["app"] = APP_NAME
    state["engine_version"] = "V2"
    state["schema_version"] = SCHEMA_VERSION
    state["filter_version"] = FILTER_VERSION
    state["updated_at"] = now_utc()

    mariinsky_events = state.get("sources", {}).get("mariinsky", {}).get("events", {})
    state["sources"] = {"mariinsky": {"events": sanitize_events("mariinsky", mariinsky_events)}}
    state["pending_messages"] = sanitize_pending_messages(state.get("pending_messages", []))

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def save_audit(audit):
    AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def build_effective_new_events(old_events, new_events):
    old_events = sanitize_events("mariinsky", old_events)
    new_events = sanitize_events("mariinsky", new_events)

    out = {}
    for url, new in new_events.items():
        out[url] = merge_safe_record(old_events.get(url), new) if url in old_events else new

    return out


def build_messages_for_source(source, old_events, new_events, seen_urls, failed_urls):
    old_events = sanitize_events(source, old_events)
    new_events = build_effective_new_events(old_events, new_events)

    messages = []

    if not old_events and new_events:
        return messages, "initial_source_baseline_no_messages", new_events

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
    new_unmatched = {url: rec for url, rec in new_events.items() if url not in matched_new}

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
        if url not in matched_new:
            messages.append(format_new(new))

    for url, old in sorted(old_events.items()):
        if url in matched_old or url in failed_urls or url in seen_urls:
            continue
        if is_future_removed(old):
            messages.append(format_removed(old))

    return messages, "", new_events


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
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )

            if response.status_code == 429:
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after") or 30)
                except Exception:
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

    messages, reason, effective_new_events = build_messages_for_source(
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

    old_state.setdefault("sources", {}).setdefault("mariinsky", {})["events"] = effective_new_events

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
    assert FILTER_VERSION == "V2.9.3-participation-cast-title-mark"
    assert parse_time("20:00") == "20:00"
    assert parse_time("25:99") == ""

    assert infer_mariinsky_list_type("Джоконда опера Амилькаре Понкьелли") == "opera"
    assert infer_mariinsky_list_type("Шостакович. Четвертая симфония Симфонический оркестр Мариинского театра") == "concert"
    assert infer_mariinsky_list_type("Бахчисарайский фонтан балет Бориса Асафьева") == "ballet"

    assert classify_event("Джоконда", ["хореография", "балет в третьем акте"], list_type="opera") == ("opera", "list_opera")
    assert classify_event("Пиковая дама", ["хореография", "балет"], list_type="") == ("opera", "opera_title")
    assert classify_event("Турандот", ["При участии Екатерины Семенчук и Марины Шахдинаровой"], list_type="opera") == ("opera", "list_opera")
    assert classify_event("Неизвестный вечер", ["что-то непонятное"], list_type="") == ("concert", "ambiguous_included")

    assert is_ballet_event("Джоконда", ["хореография", "балет"], list_type="opera")[0] is False
    assert is_ballet_event("Спящая красавица", ["балет"], list_type="ballet")[0] is True

    assert extract_participation_performers("При участии Екатерины Семенчук и Марины Шахдинаровой") == [
        "Екатерины Семенчук",
        "Марины Шахдинаровой",
    ]
    assert extract_participation_performers("При участии Екатерины Семенчук, Марины Шахдинаровой и Ольги Пудовой") == [
        "Екатерины Семенчук",
        "Марины Шахдинаровой",
        "Ольги Пудовой",
    ]
    assert extract_participation_performers("При участии Семенчук, Шевцовой-Назаровой") == [
        "Семенчук",
        "Шевцовой-Назаровой",
    ]

    bad_section = [
        "Первое исполнение — 9 февраля 1886 года",
        "Первое исполнение — Санкт-Петербург",
        "смешанный хор и четыре солиста — при этом в ней нет ни одного отдельного сольного номера",
    ]
    assert extract_detail_performers(["Исполнители"] + bad_section + ["Краткое содержание"]) == []

    lines = [
        "Исполнители",
        "Дирижер - Кристиан Кнапп",
        "Фальстаф - Магеррам Гусейнов",
        "Наннетта – Изабелла Андриасян",
        "Алиса Форд - Оксана Шилова",
        "Миссис Мэг Пейдж – Варвара Соловьёва",
        "Миссис Квикли – Виктория Ястребова",
        "Фентон - Кирилл Белов",
        "Форд - Владимир Мороз",
        "Краткое содержание",
    ]
    perfs = extract_detail_performers(lines)
    assert "Фальстаф — Магеррам Гусейнов" in perfs
    assert "Наннетта — Изабелла Андриасян" in perfs
    assert not any(x.startswith("Главные партии") for x in perfs)

    turandot_lines = [
        "Исполнители",
        "Дирижер – Валерий Гергиев",
        "Принцесса Турандот – Екатерина Семенчук",
        "Лиу – Марина Шахдинарова",
        "Полный список солистов будет объявлен позднее",
        "Краткое содержание",
    ]
    turandot_perfs = extract_detail_performers(turandot_lines)
    assert "Дирижер — Валерий Гергиев" in turandot_perfs
    assert "Принцесса Турандот — Екатерина Семенчук" in turandot_perfs
    assert "Лиу — Марина Шахдинарова" in turandot_perfs

    pulenk = [
        "Исполнители",
        "Солистка – Юлия Маточкина (меццо-сопрано)",
        "Симфонический оркестр Мариинского театра",
        "Дирижер – Кристиан Кнапп",
    ]
    perfs = extract_detail_performers(pulenk)
    assert "Солистка — Юлия Маточкина (меццо-сопрано)" in perfs
    assert "Солистка" not in perfs
    assert "Дирижер — Кристиан Кнапп" in perfs

    list_roles = extract_list_main_roles(
        "Джоконда опера Амилькаре Понкьелли В главных партиях: Ирина Чурилова, Зинаида Царенко, Ахмед Агади Дирижер – Валерий Гергиев Мариинский-2"
    )
    assert list_roles == ["Ирина Чурилова", "Зинаида Царенко", "Ахмед Агади"]

    list_perfs = extract_list_performers(
        "Турандот опера Джакомо Пуччини При участии Екатерины Семенчук и Марины Шахдинаровой Дирижер – Валерий Гергиев Мариинский-2"
    )
    assert "Екатерины Семенчук" in list_perfs
    assert "Марины Шахдинаровой" in list_perfs
    assert "Дирижер — Валерий Гергиев" in list_perfs

    merged, src = merge_detail_and_list_performers(
        ["Дирижер — Валерий Гергиев"],
        ["Екатерины Семенчук", "Марины Шахдинаровой", "Дирижер — Валерий Гергиев"],
    )
    assert src == "detail_plus_list_card"
    assert "Дирижер — Валерий Гергиев" in merged
    assert "Екатерины Семенчук" in merged
    assert "Марины Шахдинаровой" in merged

    merged_roles, src_roles = merge_detail_and_list_performers(
        ["Дирижер — Валерий Гергиев", "Принцесса Турандот — Екатерина Семенчук", "Лиу — Марина Шахдинарова"],
        ["Екатерины Семенчук", "Марины Шахдинаровой", "Дирижер — Валерий Гергиев"],
    )
    assert src_roles == "detail_section"
    assert "Принцесса Турандот — Екатерина Семенчук" in merged_roles
    assert "Лиу — Марина Шахдинарова" in merged_roles
    assert "Екатерины Семенчук" not in merged_roles
    assert "Марины Шахдинаровой" not in merged_roles

    old_j = {
        "source": "mariinsky",
        "url": "u",
        "title": "Джоконда",
        "venue": "Мариинский-2",
        "date_text": "4 июля 2026",
        "time_text": "19:00",
        "event_date": "2026-07-04",
        "event_type": "opera",
        "performers": ["Дирижер — Валерий Гергиев"],
        "performers_source": "detail_section",
        "main_roles": [],
        "program": [],
    }
    new_j = dict(old_j)
    new_j["main_roles"] = ["Ирина Чурилова", "Зинаида Царенко"]
    new_j["main_roles_source"] = "list_main_roles"
    msg = format_changed(old_j, new_j)
    assert "Изменение в главных партиях" in msg
    assert "Ирина Чурилова" in msg
    assert "Название:" not in msg
    assert "𝄞 Джоконда" in msg
    assert not msg.startswith("𝄞 Мариинский-2")

    old_repl = dict(old_j)
    old_repl["title"] = "Пиковая дама"
    old_repl["url"] = "https://www.mariinsky.ru/playbill/playbill/2026/7/17/2_1900/"
    new_repl = dict(old_repl)
    new_repl["title"] = "Джоконда"
    repl_msg = format_changed(old_repl, new_repl)
    assert "𝄞 Пиковая дама → Джоконда" in repl_msg
    assert "Замена спектакля" in repl_msg
    assert "Название:" not in repl_msg

    old_t = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/31/2_1900/",
        "title": "Турандот",
        "venue": "Мариинский-2",
        "date_text": "31 июля 2026",
        "time_text": "19:00",
        "event_date": "2026-07-31",
        "event_type": "opera",
        "performers": ["Дирижер — Валерий Гергиев"],
        "performers_source": "detail_section",
        "main_roles": [],
        "program": [],
    }
    new_t = dict(old_t)
    new_t["performers"] = [
        "Дирижер — Валерий Гергиев",
        "Екатерины Семенчук",
        "Марины Шахдинаровой",
    ]
    new_t["performers_source"] = "detail_plus_list_card"
    t_msg = format_changed(old_t, new_t)
    assert "Изменение в составе" in t_msg
    assert "Екатерины Семенчук" in t_msg
    assert "Марины Шахдинаровой" in t_msg
    assert "При участии —" not in t_msg

    old_p = {
        "source": "mariinsky",
        "url": "u",
        "title": "Пуленк. Моноопера «Человеческий голос»",
        "venue": "Концертный зал",
        "date_text": "15 июля 2026",
        "time_text": "19:00",
        "event_date": "2026-07-15",
        "event_type": "concert",
        "performers": ["Солистка — Юлия Маточкина"],
        "performers_source": "detail_section",
        "main_roles": [],
        "program": [],
    }
    new_p = dict(old_p)
    new_p["performers"] = []
    new_p["performers_source"] = "none"
    assert format_changed(old_p, merge_safe_record(old_p, new_p)) == ""

    concert = {
        "source": "mariinsky",
        "url": "u",
        "title": "Шостакович. Четвертая симфония",
        "venue": "Мариинский-2",
        "date_text": "6 июля 2026",
        "time_text": "20:00",
        "event_date": "2026-07-06",
        "event_type": "concert",
        "performers": ["Симфонический оркестр Мариинского театра", "Дирижер — Валерий Гергиев"],
        "program": ["Симфония № 4 до минор, соч. 43"],
    }
    assert sanitize_events("mariinsky", {"u": concert})

    ballet = dict(concert)
    ballet["title"] = "Жизель"
    ballet["event_type"] = "ballet"
    assert sanitize_events("mariinsky", {"u": ballet}) == {}

    assert venue_from_mariinsky_url("https://www.mariinsky.ru/playbill/playbill/2026/9/5/2_1700/") == "Мариинский-2"
    assert venue_from_mariinsky_url("https://www.mariinsky.ru/playbill/playbill/2026/9/5/1_1700/") == "Мариинский театр"

    false_venue_message = (
        "𝄞 Мариинский театр\n\n"
        "Парсифаль\n"
        "🔸 5 сентября 2026. 17:00\n"
        "Изменение площадки:\n\n"
        "⛔ Было:\n"
        "𝄞 Мариинский-2\n\n"
        "✅ Стало:\n"
        "𝄞 Мариинский театр\n\n"
        "Ссылка: https://www.mariinsky.ru/playbill/playbill/2026/9/5/2_1700/"
    )
    assert sanitize_pending_messages([false_venue_message]) == []

    pending = sanitize_pending_messages([
        "Сторонняя площадка\n🐣 Новое событие",
        "Мариинский-2\n𝄞 Тоска\n🐣 Новое событие",
    ])
    assert pending == ["Мариинский-2\n𝄞 Тоска\n🐣 Новое событие"]

    old_move = dict(concert)
    old_move.update({
        "url": "old",
        "title": "Тоска",
        "event_type": "opera",
        "date_text": "1 августа 2026",
        "event_date": "2026-08-01",
    })
    new_move = dict(old_move)
    new_move.update({
        "url": "new",
        "date_text": "2 августа 2026",
        "event_date": "2026-08-02",
    })
    move_messages, _, _ = build_messages_for_source(
        "mariinsky",
        {"old": old_move},
        {"new": new_move},
        seen_urls=set(),
        failed_urls=set(),
    )
    assert len(move_messages) == 1
    assert "Изменение даты / времени" in move_messages[0]

    old_removed = dict(concert)
    old_removed.update({
        "url": "https://www.mariinsky.ru/playbill/playbill/2026/7/17/2_1900/",
        "title": "Пиковая дама",
        "event_type": "opera",
        "date_text": "17 июля 2026",
        "event_date": "2026-07-17",
    })
    removed_messages, _, _ = build_messages_for_source(
        "mariinsky",
        {old_removed["url"]: old_removed},
        {},
        seen_urls=set(),
        failed_urls=set(),
    )
    assert len(removed_messages) == 1
    assert "𝄞 Пиковая дама" in removed_messages[0]
    assert "Событие исчезло" in removed_messages[0]

    print("SELF_TEST_OK")


if __name__ == "__main__":
    if SELF_TEST:
        run_self_tests()
    else:
        main()
