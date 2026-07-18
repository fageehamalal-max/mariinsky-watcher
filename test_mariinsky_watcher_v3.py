import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mariinsky_watcher_v3 as watcher


def sample_record(url="/playbill/playbill/2026/7/31/2_1900/", title="Турандот", performers=None, program=None):
    dt, date_text, time_text, venue, venue_source = watcher.parse_mariinsky_url_parts("https://www.mariinsky.ru" + url)
    record = {
        "source": "mariinsky",
        "url": "https://www.mariinsky.ru" + url,
        "title": title,
        "venue": venue,
        "venue_source": venue_source,
        "date_text": date_text,
        "time_text": time_text,
        "event_date": dt.isoformat(),
        "event_type": "opera",
        "classification_source": "known_opera_title",
        "classification_confidence": "high",
        "performers": performers or [],
        "performers_source": "detail_section" if performers else "none",
        "main_roles": [],
        "main_roles_source": "none",
        "program": program or [],
        "program_source": "detail_program_section" if program else "none",
    }
    return watcher.with_digest(record)


class MariinskyWatcherV3Tests(unittest.TestCase):
    def test_opera_titles_are_not_ballet_due_to_description_words(self):
        for title in ["Джоконда", "Пиковая дама"]:
            cls = watcher.classify_event(title, "opera", ["описание содержит балет и хореография"])
            self.assertEqual(cls.status, "included")
            self.assertEqual(cls.event_type, "opera")
            self.assertTrue(cls.included_despite_ballet_words)

    def test_same_url_title_change_is_replacement(self):
        old = sample_record("/playbill/playbill/2026/7/17/2_1900/", "Пиковая дама")
        new = sample_record("/playbill/playbill/2026/7/17/2_1900/", "Джоконда")
        messages = watcher.build_messages({old["url"]: old}, {new["url"]: new})
        self.assertEqual(len(messages), 1)
        self.assertIn("𝄞 Пиковая дама → Джоконда", messages[0])
        self.assertIn("Замена спектакля", messages[0])

    def test_venue_code_two_is_mariinsky_two(self):
        _, _, time_text, venue, venue_source = watcher.parse_mariinsky_url_parts("https://www.mariinsky.ru/playbill/playbill/2026/9/5/2_1700/")
        self.assertEqual(venue, "Мариинский-2")
        self.assertEqual(time_text, "17:00")
        self.assertEqual(venue_source, "url_code")

    def test_turandot_role_lines_parse(self):
        lines = [
            "Дирижер — Валерий Гергиев",
            "Принцесса Турандот — Екатерина Семенчук",
            "Лиу — Марина Шахдинарова",
        ]
        performers = watcher.extract_performers_from_lines(lines)
        self.assertEqual(performers, lines)

    def test_participation_splits_participants(self):
        self.assertEqual(
            watcher.split_participation("При участии Екатерины Семенчук и Марины Шахдинаровой"),
            ["Екатерина Семенчук", "Марина Шахдинарова"],
        )
        self.assertEqual(
            watcher.split_participation("При участии Екатерины Семенчук, Марины Шахдинаровой и Ольги Пудовой"),
            ["Екатерина Семенчук", "Марина Шахдинарова", "Ольга Пудова"],
        )

    def test_role_lines_override_participation_duplicates(self):
        performers = watcher.extract_performers_from_lines(
            [
                "Принцесса Турандот — Екатерина Семенчук",
                "Лиу — Марина Шахдинарова",
                "При участии Екатерины Семенчук и Марины Шахдинаровой",
            ]
        )
        self.assertEqual(
            performers,
            ["Принцесса Турандот — Екатерина Семенчук", "Лиу — Марина Шахдинарова"],
        )

    def test_mass_program_and_cast_are_separated(self):
        program, performers = watcher.extract_program_and_performers(
            [
                "Торжественная месса, соч. 123",
                "Солисты оперы, Хор и Симфонический оркестр Мариинского театра",
                "Ответственный концертмейстер — Лоренц Настурика-Гершовичи",
                "Дирижер — Валерий Гергиев",
            ],
            "Бетховен. Торжественная месса",
        )
        self.assertEqual(program, ["Торжественная месса, соч. 123"])
        self.assertIn("Солисты оперы, Хор и Симфонический оркестр Мариинского театра", performers)
        self.assertIn("Ответственный концертмейстер — Лоренц Настурика-Гершовичи", performers)
        self.assertIn("Дирижер — Валерий Гергиев", performers)

    def test_responsible_concertmaster_is_not_program(self):
        line = "Ответственный концертмейстер — Лоренц Настурика-Гершовичи"
        self.assertTrue(watcher.is_role_line(line))
        self.assertFalse(watcher.is_program_line(line, "Концерт"))

    def test_historical_description_does_not_become_performer(self):
        performers = watcher.extract_performers_from_lines(
            [
                "Первое исполнение — 9 февраля 1886 года",
                "смешанный хор и четыре солиста — при этом в ней нет ни одного отдельного сольного номера",
            ]
        )
        self.assertEqual(performers, [])

    def test_telegram_format_contract(self):
        record = sample_record()
        message = watcher.format_new(record)
        self.assertNotIn("Название:", message)
        self.assertNotIn("Новое событие", message)
        lines = message.splitlines()
        self.assertEqual(lines[0], "Мариинский-2")
        self.assertEqual(lines[1], "🐣𝄞 Турандот")
        self.assertEqual(lines[2], "31 июля▫️19:00")
        self.assertIn("ℹ️ https://www.mariinsky.ru/", message)
        self.assertNotIn("Ссылка:", message)

    def test_operetta_is_classified_as_opera(self):
        cls = watcher.classify_event(
            "Летучая мышь",
            "",
            ["оперетта Иоганна Штрауса"],
        )
        self.assertEqual(cls.status, "included")
        self.assertEqual(cls.event_type, "opera")

    def test_stravinsky_new_event_format(self):
        record = sample_record(
            "/playbill/playbill/2026/7/22/10_1900/",
            "Песни рек: звуки Янцзы и Невы",
        )
        message = watcher.format_new(record)
        lines = message.splitlines()
        self.assertEqual(lines[0], "Зал Стравинского")
        self.assertEqual(lines[1], "🐣𝄞 Песни рек: звуки Янцзы и Невы")
        self.assertEqual(lines[2], "22 июля▫️19:00")
        self.assertIn("ℹ️ https://www.mariinsky.ru/", message)
        self.assertNotIn("Ссылка:", message)

    def test_removed_event_format_uses_red_markers(self):
        record = sample_record()
        message = watcher.format_removed(record)
        lines = message.splitlines()
        self.assertEqual(lines[0], "Мариинский-2")
        self.assertEqual(lines[1], "𝄞 Турандот")
        self.assertEqual(lines[2], "31 июля▫️19:00")
        self.assertNotIn("Событие исчезло", message)

    def test_cross_section_transfer_is_not_reported_as_removal(self):
        old = sample_record(
            "/playbill/playbill/2026/7/18/3_1900/",
            "Травиата",
            performers=["Виолетта Валери — Инара Козловская"],
        )
        old["main_roles"] = ["Екатерина Гончарова"]
        old["main_roles_source"] = "list_main_roles"
        old = watcher.with_digest(old)

        new = sample_record(
            "/playbill/playbill/2026/7/18/3_1900/",
            "Травиата",
            performers=["Виолетта Валери — Екатерина Гончарова"],
        )

        message = watcher.build_messages({old["url"]: old}, {new["url"]: new})[0]
        self.assertIn("Виолетта Валери — Екатерина Гончарова", message)
        self.assertIn("Виолетта Валери — Инара Козловская", message)
        self.assertNotIn("Изменение в главных партиях", message)
        self.assertNotIn("🔴 Удалено:\nЕкатерина Гончарова", message)

    def test_person_identity_matches_nominative_and_genitive(self):
        self.assertEqual(
            watcher.person_compare_key("Рогожин — Владислав Сулимский"),
            watcher.person_compare_key("Владислава Сулимского"),
        )
        self.assertEqual(
            watcher.person_compare_key("Амелия — Инара Козловская"),
            watcher.person_compare_key("Инары Козловской"),
        )
        self.assertEqual(
            watcher.person_compare_key("Виолетта Валери — Екатерина Гончарова"),
            watcher.person_compare_key("Екатерины Гончаровой"),
        )

    def test_existing_performer_is_not_removed_when_main_role_disappears(self):
        url = "/playbill/playbill/2026/7/26/3_1900/"
        old = sample_record(
            url,
            "Идиот",
            performers=[
                "Дирижер — Заурбек Гугкаев",
                "Рогожин — Владислав Сулимский",
            ],
        )
        old["main_roles"] = ["Владислава Сулимского"]
        old["main_roles_source"] = "list_main_roles"
        old = watcher.with_digest(old)

        new = sample_record(
            url,
            "Идиот",
            performers=[
                "Дирижер — Заурбек Гугкаев",
                "Князь Мышкин — Илья Селиванов",
                "Настасья Филипповна — Мария Баянкина",
                "Аглая — Екатерина Сергеева",
                "Рогожин — Владислав Сулимский",
                "Ганя — Александр Трофимов",
                "Лебедев — Дмитрий Колеушко",
            ],
        )

        message = watcher.build_messages({old["url"]: old}, {new["url"]: new})[0]
        self.assertIn("Князь Мышкин — Илья Селиванов", message)
        self.assertNotIn("Владислава Сулимского", message)
        self.assertNotIn("Владислав Сулимский", message.split("🔴 Удалено:")[-1] if "🔴 Удалено:" in message else "")
        self.assertNotIn("Изменение в главных партиях", message)

    def test_new_faust_and_parsifal_messages_keep_chick_and_treble_clef(self):
        for url, title in [
            ("/playbill/playbill/2026/9/17/1_1900/", "Фауст"),
            ("/playbill/playbill/2026/9/12/2_1700/", "Парсифаль"),
        ]:
            with self.subTest(title=title):
                record = sample_record(url, title)
                message = watcher.format_new(record)
                self.assertIn(f"🐣𝄞 {title}", message)
                self.assertIn(f"𝄞 {title}", message)

    def test_change_markers_and_personal_performer_emojis(self):
        old = sample_record(
            "/playbill/playbill/2026/7/18/3_1900/",
            "Травиата",
            performers=[
                "Виолетта Валери — Инара Козловская",
                "Маддалена — Юлия Маточкина",
            ],
        )
        new = sample_record(
            "/playbill/playbill/2026/7/18/3_1900/",
            "Травиата",
            performers=[
                "Виолетта Валери — Михаил Векуа",
                "Любаша — Екатерина Семенчук",
            ],
        )

        message = watcher.build_messages({old["url"]: old}, {new["url"]: new})[0]
        self.assertIn("🟢 Добавлено:", message)
        self.assertIn("🔴 Удалено:", message)
        self.assertIn("Виолетта Валери — 👰‍♂Михаил Векуа", message)
        self.assertIn("Любаша — 🧝🏼‍♀Екатерина Семенчук", message)
        self.assertIn("Маддалена — 🦹🏻‍♀Юлия Маточкина", message)
        self.assertNotIn("✅ Добавлено:", message)
        self.assertNotIn("⛔ Удалено:", message)

    def test_personal_emoji_matches_surname_first_order(self):
        self.assertEqual(watcher.decorate_performer_line("Векуа Михаил"), "👰‍♂Векуа Михаил")
        self.assertEqual(watcher.decorate_performer_line("Маточкина Юлия"), "🦹🏻‍♀Маточкина Юлия")
        self.assertEqual(watcher.decorate_performer_line("Семенчук Екатерина"), "🧝🏼‍♀Семенчук Екатерина")

    def test_cancelled_event_is_detected_and_formatted(self):
        cancelled, source = watcher.detect_cancellation(
            "Турандот",
            "Турандот. Спектакль отменён",
            [],
        )
        self.assertTrue(cancelled)
        self.assertEqual(source, "list_card")

        old = sample_record()
        new = dict(old)
        new["cancelled"] = True
        new["cancellation_source"] = "list_card"
        new = watcher.with_digest(new)
        messages = watcher.build_messages({old["url"]: old}, {new["url"]: new})
        self.assertEqual(len(messages), 1)
        self.assertIn("𝄞 Турандот", messages[0])
        self.assertIn("31 июля▫️19:00", messages[0])

    def test_dry_run_does_not_mutate_state_or_send_telegram(self):
        old = sample_record(title="Турандот")
        new = sample_record(title="Джоконда")
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {old["url"]: old}
        original = copy.deepcopy(state)
        messages = watcher.build_messages(state["sources"]["mariinsky"]["events"], {new["url"]: new})
        self.assertEqual(state, original)
        self.assertTrue(messages)

    def test_main_dry_run_writes_audit_but_not_state_or_telegram(self):
        old = sample_record(title="Турандот")
        new = sample_record(title="Джоконда")
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {old["url"]: old}
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            audit_path = Path(tmp) / "scan_audit.json"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            with patch.object(watcher, "RUN_MODE", "dry_run"), patch.object(watcher, "STATE_FILE", state_path), patch.object(watcher, "AUDIT_FILE", audit_path), patch.object(
                watcher,
                "scan_all",
                return_value=(
                    {"mariinsky": {new["url"]: new}},
                    {"mariinsky": {new["url"]}},
                    {"mariinsky": set()},
                    {"items": [], "summary": {}},
                ),
            ), patch.object(watcher, "save_state", side_effect=AssertionError("dry_run must not save state")), patch.object(
                watcher, "send_message", side_effect=AssertionError("dry_run must not send Telegram")
            ):
                watcher.main()
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)
            self.assertTrue(audit_path.exists())

    def test_live_preserves_pending_messages_on_telegram_failure(self):
        state = watcher.default_state()
        watcher.add_pending(state, ["message one", "message two"])
        with patch.object(watcher, "send_message", side_effect=RuntimeError("telegram down")):
            with self.assertRaises(RuntimeError):
                watcher.flush_pending(state)
        self.assertEqual(state["pending_messages"], ["message one", "message two"])

    def test_parse_synthetic_detail_page(self):
        html = """
        <html><body>
        <h1>Турандот</h1>
        <h2>Исполнители</h2>
        <p>Дирижер — Валерий Гергиев</p>
        <p>Принцесса Турандот — Екатерина Семенчук</p>
        <p>Лиу — Марина Шахдинарова</p>
        <h2>Краткое содержание</h2>
        <p>Описание содержит слово балет.</p>
        </body></html>
        """
        record, audit = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/31/2_1900/",
            "Турандот опера В главных партиях Екатерина Семенчук, Марина Шахдинарова",
            "opera",
            html=html,
        )
        self.assertEqual(audit["status"], "included")
        self.assertEqual(record.venue, "Мариинский-2")
        self.assertIn("Лиу — Марина Шахдинарова", record.performers)


    def test_page_time_overrides_url_time(self):
        html = """
        <html><body>
        <div>18 июля 2026</div>
        <div>13:00</div>
        <h1>Джоконда</h1>
        <h2>Исполнители</h2>
        <p>Джоконда — Мария Баянкина</p>
        <p>Лаура Адорно — Ирина Шишкова</p>
        <h2>Краткое содержание</h2>
        </body></html>
        """
        record, audit = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/18/2_1301/",
            "Джоконда опера",
            "opera",
            html=html,
        )
        self.assertEqual(record.time_text, "13:00")
        self.assertEqual(audit["time_source"], "detail_page")
        self.assertIn("Джоконда — Мария Баянкина", record.performers)

    def test_url_time_is_fallback_when_page_has_no_time(self):
        html = """
        <html><body>
        <h1>Джоконда</h1>
        <h2>Исполнители</h2>
        <p>Джоконда — Мария Баянкина</p>
        <h2>Краткое содержание</h2>
        </body></html>
        """
        record, audit = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/18/2_1301/",
            "Джоконда опера",
            "opera",
            html=html,
        )
        self.assertEqual(record.time_text, "13:01")
        self.assertEqual(audit["time_source"], "url_code")

    def test_incomplete_scan_suppresses_removed_notifications(self):
        old = sample_record("/playbill/playbill/2026/7/31/2_1900/", "Турандот")
        messages = watcher.build_messages(
            {old["url"]: old},
            {},
            seen_urls=set(),
            failed_urls=set(),
            allow_removals=False,
        )
        self.assertEqual(messages, [])

    def test_live_incomplete_scan_preserves_missing_state(self):
        old = sample_record("/playbill/playbill/2026/7/31/2_1900/", "Турандот")
        new = sample_record("/playbill/playbill/2026/8/1/2_1900/", "Джоконда")
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {old["url"]: old}

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            audit_path = Path(tmp) / "scan_audit.json"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

            audit = {
                "items": [],
                "summary": {},
                "source_errors": [{"url": "month", "error": "timeout"}],
                "scan_complete": False,
            }

            with patch.object(watcher, "RUN_MODE", "live"), patch.object(
                watcher, "STATE_FILE", state_path
            ), patch.object(watcher, "AUDIT_FILE", audit_path), patch.object(
                watcher,
                "scan_all",
                return_value=(
                    {"mariinsky": {new["url"]: new}},
                    {"mariinsky": {new["url"]}},
                    {"mariinsky": set()},
                    audit,
                ),
            ), patch.object(watcher, "flush_pending", return_value=1):
                watcher.main()

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            saved_events = saved["sources"]["mariinsky"]["events"]
            self.assertIn(old["url"], saved_events)
            self.assertIn(new["url"], saved_events)

    def test_telegram_response_is_verified_and_logged(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "ok": True,
            "result": {"message_id": 321, "chat": {"id": 654}},
        }

        with patch.object(watcher, "TELEGRAM_BOT_TOKEN", "token"), patch.object(
            watcher, "TELEGRAM_CHAT_ID", "654"
        ), patch.object(watcher.SESSION, "post", return_value=response), patch("builtins.print") as print_mock:
            receipts = watcher.send_message("test")

        self.assertEqual(receipts, [{"message_id": 321, "chat_id": 654}])
        print_mock.assert_called_once()

    def test_telegram_ok_false_raises(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": False, "description": "Bad Request"}

        with patch.object(watcher, "TELEGRAM_BOT_TOKEN", "token"), patch.object(
            watcher, "TELEGRAM_CHAT_ID", "654"
        ), patch.object(watcher.SESSION, "post", return_value=response):
            with self.assertRaises(RuntimeError):
                watcher.send_message("test")



    def test_voice_and_role_require_a_real_person_name(self):
        valid = [
            "Сопрано — Мария Пайманова",
            "Мария Пайманова — сопрано",
            "Меццо-сопрано — Юлия Маточкина",
            "Тенор — Михаил Векуа",
            "Виолетта Валери — Екатерина Гончарова",
            "Дирижер — Валерий Гергиев",
        ]
        invalid = [
            "– сопрано, лауреат международных конкурсов. Родилась в Ленинграде.",
            "сопрано — лауреат международных конкурсов",
            "меццо-сопрано — в настоящее время студентка консерватории",
            "тенор — выступал в Большом зале филармонии",
            "баритон — удостоен первой премии конкурса",
        ]
        for line in valid:
            with self.subTest(line=line):
                self.assertTrue(watcher.is_role_line(line))
        for line in invalid:
            with self.subTest(line=line):
                self.assertFalse(watcher.is_role_line(line))

    def test_named_voice_line_is_trimmed_before_biography(self):
        line = "Мария Пайманова — сопрано, лауреат международных конкурсов. Родилась в Орле."
        self.assertEqual(watcher.sanitize_performer_line(line), "Мария Пайманова — сопрано")
        self.assertEqual(watcher.extract_performers_from_lines([line]), ["Мария Пайманова — сопрано"])

    def test_exact_user_beard_is_rejected_from_cast_and_program(self):
        beard = [
            "– сопрано, лауреат международных конкурсов. Родилась в Ленинграде. Окончила музыкальную школу по классу виолончели, а в 2003 году — с отличием — Санкт-Петербургскую государственную академию театрального искусства по специальности «артист музыкального театра».",
            "– сопрано, лауреат международных конкурсов. Родилась в Орле. Обучалась в московском Музыкальном училище им. Гнесиных. В настоящее время — студентка Санкт-Петербургской государственной консерватории.",
            "– меццо-сопрано, лауреат международных конкурсов. Родилась в Китае. В 2026 году окончила ассистентуру-стажировку Санкт-Петербургской государственной консерватории.",
            "– пианистка, лауреат международных и всероссийских конкурсов. Ведущий концертмейстер Санкт-Петербургской государственной консерватории. Доцент кафедры концертмейстерского мастерства.",
        ]
        self.assertEqual(watcher.extract_performers_from_lines(beard), [])
        program, performers = watcher.extract_program_and_performers(beard, "Песни рек: звуки Янцзы и Невы")
        self.assertEqual(program, [])
        self.assertEqual(performers, [])

    def test_cold_annotation_corpus_never_becomes_cast_or_program(self):
        openings = [
            "Родилась в Санкт-Петербурге",
            "Окончил Московскую государственную консерваторию",
            "Лауреат международных конкурсов",
            "В настоящее время студентка консерватории",
            "Удостоена первой премии международного конкурса",
            "В репертуаре концертных программ произведения русских композиторов",
            "Выступала в Большом зале Санкт-Петербургской филармонии",
            "Член Союза концертных деятелей Санкт-Петербурга",
        ]
        tails = [
            "С 2020 года — солистка театра.",
            "В 2026 году окончила ассистентуру-стажировку.",
            "Обучалась в классе профессора Ольги Кондиной.",
            "Принимала участие в фестивалях и конкурсах.",
        ]
        corpus = [f"{opening}. {tail}" for opening in openings for tail in tails]
        for line in corpus:
            with self.subTest(line=line):
                self.assertFalse(watcher.is_role_line(line))
                self.assertFalse(watcher.is_program_line(line, "Тестовый концерт"))
        self.assertEqual(watcher.extract_performers_from_lines(corpus), [])
        program, performers = watcher.extract_program_and_performers(corpus, "Тестовый концерт")
        self.assertEqual(program, [])
        self.assertEqual(performers, [])

    def test_program_keeps_only_composers_and_work_titles(self):
        lines = [
            "Вольфганг Амадей Моцарт",
            "Концерт № 2 для фортепиано с оркестром",
            "Петр Чайковский",
            "Сюита из балета «Щелкунчик»",
            "В репертуаре концертных программ Марии Паймановой — произведения зарубежных и русских композиторов.",
            "Лауреат международного конкурса выступала в Большом зале филармонии.",
        ]
        program, performers = watcher.extract_program_and_performers(lines, "Гала-концерт")
        self.assertEqual(
            program,
            [
                "Вольфганг Амадей Моцарт",
                "Концерт № 2 для фортепиано с оркестром",
                "Петр Чайковский",
                "Сюита из балета «Щелкунчик»",
            ],
        )
        self.assertEqual(performers, [])

    def test_full_parser_filters_biographies_but_keeps_named_cast(self):
        html = """
        <html><body>
        <div>22 июля 2026</div>
        <div>19:00</div>
        <h1>Песни рек: звуки Янцзы и Невы</h1>
        <h2>Исполнители</h2>
        <p>Мария Пайманова — сопрано, лауреат международных конкурсов. Родилась в Орле.</p>
        <p>– сопрано, лауреат международных конкурсов. Родилась в Ленинграде. Окончила консерваторию.</p>
        <p>Дирижер — Иван Рудин</p>
        <h2>В программе</h2>
        <p>Вольфганг Амадей Моцарт</p>
        <p>Концерт № 2 для фортепиано с оркестром</p>
        <p>– меццо-сопрано, лауреат международных конкурсов. Родилась в Китае. В 2026 году окончила консерваторию.</p>
        <p>В репертуаре концертных программ Марии Паймановой — произведения зарубежных композиторов.</p>
        <h2>Аннотация</h2>
        <p>Большой текст о концерте.</p>
        </body></html>
        """
        record, audit = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/22/8_1900/",
            "Песни рек: звуки Янцзы и Невы концерт",
            "concert",
            html=html,
        )
        self.assertEqual(record.performers, ["Мария Пайманова — сопрано", "Дирижер — Иван Рудин"])
        self.assertEqual(record.program, ["Вольфганг Амадей Моцарт", "Концерт № 2 для фортепиано с оркестром"])
        combined = "\n".join(record.performers + record.program)
        for forbidden in ["лауреат", "родилась", "консерватори", "в репертуаре"]:
            self.assertNotIn(forbidden, combined.lower())
        self.assertEqual(audit["performers_preview"], record.performers)
        self.assertEqual(audit["program_preview"], record.program)

    def test_long_program_annotation_with_composer_name_is_rejected(self):
        line = (
            "Бетховен создавал Торжественную мессу несколько лет. Композитор стремился "
            "соединить симфонический размах, хор и четыре сольных голоса в едином произведении."
        )
        self.assertFalse(watcher.is_program_line(line, "Бетховен. Торжественная месса"))



    def test_performer_section_accepts_bare_names_and_compact_voice_notation(self):
        lines = [
            "Мария Пайманова",
            "Лю Цзысюань, меццо-сопрано",
            "Анна Смирнова (сопрано)",
            "Дирижер",
            "Сопрано",
        ]
        self.assertCountEqual(
            watcher.extract_performers_from_lines(lines),
            [
                "Мария Пайманова",
                "Лю Цзысюань — меццо-сопрано",
                "Анна Смирнова — сопрано",
            ],
        )

    def test_generated_voice_annotation_matrix_is_fully_blocked(self):
        voices = ["сопрано", "меццо-сопрано", "тенор", "баритон", "бас", "контратенор"]
        biographies = [
            "лауреат международных конкурсов",
            "родилась в Ленинграде",
            "окончил государственную консерваторию",
            "в настоящее время студентка академии",
            "выступала в Большом зале филармонии",
            "удостоен первой премии конкурса",
            "в репертуаре концертные произведения",
            "обучалась в классе профессора",
        ]
        corpus = []
        for voice in voices:
            for biography in biographies:
                corpus.extend(
                    [
                        f"– {voice}, {biography}. В 2026 году — с отличием — завершила обучение.",
                        f"{voice} — {biography}",
                        f"{biography} — {voice}",
                    ]
                )
        self.assertEqual(len(corpus), 144)
        for line in corpus:
            with self.subTest(line=line):
                self.assertEqual(watcher.sanitize_performer_line(line), "")
                self.assertFalse(watcher.is_role_line(line))
                self.assertFalse(watcher.is_program_line(line, "Оперный концерт"))
        self.assertEqual(watcher.extract_performers_from_lines(corpus), [])
        program, performers = watcher.extract_program_and_performers(corpus, "Оперный концерт")
        self.assertEqual(program, [])
        self.assertEqual(performers, [])



    def test_old_beard_cleanup_does_not_generate_removal_message(self):
        old = sample_record(
            "/playbill/playbill/2026/7/22/8_1900/",
            "Песни рек: звуки Янцзы и Невы",
            performers=[
                "– сопрано, лауреат международных конкурсов. Родилась в Ленинграде. Окончила консерваторию.",
                "– пианистка, лауреат всероссийских конкурсов. Доцент кафедры концертмейстерского мастерства.",
            ],
            program=[
                "– меццо-сопрано, лауреат международных конкурсов. Родилась в Китае.",
                "В репертуаре концертных программ представлены произведения русских композиторов.",
            ],
        )
        new = sample_record(
            "/playbill/playbill/2026/7/22/8_1900/",
            "Песни рек: звуки Янцзы и Невы",
            performers=[],
            program=[],
        )
        self.assertEqual(watcher.build_messages({old["url"]: old}, {new["url"]: new}), [])

    def test_valid_role_with_trailing_biography_is_trimmed_not_lost(self):
        lines = [
            "Дирижер — Иван Рудин, лауреат международных конкурсов. Окончил консерваторию.",
            "Виолетта Валери — Екатерина Гончарова, лауреат международных конкурсов. Родилась в Москве.",
        ]
        self.assertEqual(
            watcher.extract_performers_from_lines(lines),
            ["Дирижер — Иван Рудин", "Виолетта Валери — Екатерина Гончарова"],
        )

    def test_short_program_prose_is_rejected_even_with_composer_and_work_word(self):
        prose = [
            "Бетховен написал эту симфонию в 1808 году.",
            "Чайковский создал концерт для скрипки за несколько недель.",
            "Торжественная месса длится около девяноста минут.",
            "Сюита состоит из пяти контрастных частей.",
            "Рахманинов посвятил концерт известному пианисту.",
        ]
        for line in prose:
            with self.subTest(line=line):
                self.assertFalse(watcher.is_program_line(line, "Концерт"))

    def test_exact_without_intermission_notice_is_not_program(self):
        self.assertFalse(watcher.is_program_line("Концерт идет без антракта", "Симфонический концерт"))

    def test_service_notices_never_enter_program(self):
        notices = [
            "Концерт идёт без антракта",
            "Концерт пройдет без антракта",
            "Спектакль идет с одним антрактом",
            "Опера состоится с антрактом",
            "Мероприятие начнется в 19:00",
            "Программа завершится около 21:30",
            "Продолжительность концерта — 1 час 20 минут",
            "Длительность спектакля 3 часа",
            "Начало концерта в 19:00",
            "Окончание спектакля ориентировочно в 22:00",
            "Двери открываются за 45 минут до начала",
            "Вход в зал после третьего звонка запрещен",
            "Опоздавшие зрители в зал не допускаются",
            "Возрастное ограничение 12+",
            "Рекомендуемый возраст — от 12 лет",
            "Программа может быть изменена",
            "В программе возможны изменения",
            "Обращаем внимание: концерт идет без антракта",
            "Просим обратить внимание на время начала",
        ]
        for line in notices:
            with self.subTest(line=line):
                self.assertTrue(watcher.is_program_service_note(line))
                self.assertFalse(watcher.is_program_line(line, "Тестовый концерт"))

    def test_valid_concert_titles_survive_service_filter(self):
        valid = [
            "Скрипичный концерт",
            "Концерт № 2 для фортепиано с оркестром",
            "Концерт для скрипки с оркестром ре мажор, соч. 35",
            "Двойной концерт для скрипки и виолончели",
        ]
        for line in valid:
            with self.subTest(line=line):
                self.assertFalse(watcher.is_program_service_note(line))
                self.assertTrue(watcher.is_program_line(line, "Тестовый концерт"))

    def test_service_notice_is_removed_end_to_end(self):
        html = """
        <html><body>
        <div>18 июля 2026</div>
        <div>11:00</div>
        <h1>Дебюсси. Прелюдия к отдыху фавна</h1>
        <h2>В программе</h2>
        <p>Клод Дебюсси</p>
        <p>Прелюдия к «Послеполуденному отдыху фавна»</p>
        <p>Концерт идет без антракта</p>
        <h2>Аннотация</h2>
        </body></html>
        """
        record, audit = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/18/3_1100/",
            "Симфонический концерт",
            "concert",
            html=html,
        )
        self.assertEqual(record.program, ["Клод Дебюсси", "Прелюдия к «Послеполуденному отдыху фавна»"])
        self.assertNotIn("Концерт идет без антракта", audit["program_preview"])

    def test_old_service_notice_does_not_create_removed_notification(self):
        old = sample_record(program=["Концерт идет без антракта"])
        new = sample_record(program=[])
        self.assertEqual(watcher.change_sections(old, new), [])

    def test_bare_role_labels_never_enter_program(self):
        for line in ["Сопрано", "Меццо-сопрано", "Дирижер", "Ведущий концертмейстер", "Баритон"]:
            with self.subTest(line=line):
                self.assertFalse(watcher.is_program_line(line, "Гала-концерт"))



    def test_polluted_list_card_conductor_line_is_rejected(self):
        list_text = (
            "Дирижер — Иван Рудин Концертный зал Купить билет 19:00 19:00 Дебюсси "
            "Мариинский театр"
        )
        self.assertEqual(watcher.extract_list_performers(list_text), [])

    def test_program_adjacent_pollution_is_rejected_end_to_end(self):
        html = """
        <html><body>
        <div>23 июля 2026</div>
        <div>19:00</div>
        <h1>Симфонический концерт</h1>
        <h2>В программе</h2>
        <p>Дирижер — Иван Рудин Концертный зал Купить билет 19:00 19:00 Дебюсси</p>
        <p>Клод Дебюсси</p>
        <p>Симфоническая сюита</p>
        <p>Дебюсси написал это произведение в период творческого расцвета.</p>
        <h2>Аннотация</h2>
        </body></html>
        """
        record, _ = watcher.parse_mariinsky_event(
            "https://www.mariinsky.ru/playbill/playbill/2026/7/23/3_1900/",
            "Симфонический концерт",
            "concert",
            html=html,
        )
        self.assertEqual(record.performers, [])
        self.assertEqual(record.program, ["Клод Дебюсси", "Симфоническая сюита"])



    def test_all_russian_cases_normalize_to_nominative(self):
        cases = {
            "Владислава Сулимского": "Владислав Сулимский",
            "Владиславу Сулимскому": "Владислав Сулимский",
            "Владиславом Сулимским": "Владислав Сулимский",
            "Владиславе Сулимском": "Владислав Сулимский",
            "Екатерины Гончаровой": "Екатерина Гончарова",
            "Екатерине Гончаровой": "Екатерина Гончарова",
            "Екатериной Гончаровой": "Екатерина Гончарова",
            "Юлии Маточкиной": "Юлия Маточкина",
            "Юлией Маточкиной": "Юлия Маточкина",
            "Михаила Векуа": "Михаил Векуа",
            "Михаилу Векуа": "Михаил Векуа",
            "Ильи Селиванова": "Илья Селиванов",
            "Марии Баянкиной": "Мария Баянкина",
            "Александра Трофимова": "Александр Трофимов",
            "Дмитрия Колеушко": "Дмитрий Колеушко",
            "Инары Козловской": "Инара Козловская",
            "Марины Шахдинаровой": "Марина Шахдинарова",
            "Ольги Пудовой": "Ольга Пудова",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(watcher.normalize_person_name(source), expected)

    def test_role_lines_are_always_emitted_with_nominative_names(self):
        lines = [
            "Рогожин — Владислава Сулимского",
            "Виолетта Валери — Екатерины Гончаровой",
            "Сопрано — Марии Паймановой",
            "Юлии Маточкиной — меццо-сопрано",
        ]
        self.assertEqual(
            watcher.extract_performers_from_lines(lines),
            [
                "Рогожин — Владислав Сулимский",
                "Виолетта Валери — Екатерина Гончарова",
                "Сопрано — Мария Пайманова",
                "Юлия Маточкина — меццо-сопрано",
            ],
        )

    def test_case_matrix_has_one_identity_key_for_every_artist(self):
        groups = [
            [
                "Владислав Сулимский",
                "Владислава Сулимского",
                "Владиславу Сулимскому",
                "Владиславом Сулимским",
                "Владиславе Сулимском",
            ],
            [
                "Екатерина Гончарова",
                "Екатерины Гончаровой",
                "Екатерине Гончаровой",
                "Екатериной Гончаровой",
            ],
            [
                "Инара Козловская",
                "Инары Козловской",
                "Инаре Козловской",
                "Инарой Козловской",
            ],
        ]
        for forms in groups:
            keys = {watcher.person_compare_key(form) for form in forms}
            self.assertEqual(len(keys), 1, forms)

    def test_old_inflected_state_never_generates_false_removal(self):
        old = sample_record(
            "/playbill/playbill/2026/7/26/3_1900/",
            "Идиот",
            performers=["Дирижер — Заурбек Гугкаев"],
        )
        old["main_roles"] = ["Владислава Сулимского"]
        old["main_roles_source"] = "list_main_roles"
        old = watcher.with_digest(old)
        new = sample_record(
            "/playbill/playbill/2026/7/26/3_1900/",
            "Идиот",
            performers=[
                "Дирижер — Заурбек Гугкаев",
                "Рогожин — Владислав Сулимский",
            ],
        )
        messages = watcher.build_messages({old["url"]: old}, {new["url"]: new})
        self.assertEqual(len(messages), 1)
        self.assertNotIn("🔴 Удалено", messages[0])
        self.assertNotIn("Владислава Сулимского", messages[0])

    def test_unknown_foreign_nominative_name_is_not_distorted(self):
        self.assertEqual(watcher.normalize_person_name("Лю Цзысюань", "nomn"), "Лю Цзысюань")
        self.assertEqual(
            watcher.sanitize_performer_line("Лю Цзысюань, меццо-сопрано"),
            "Лю Цзысюань — меццо-сопрано",
        )

    def test_new_event_uses_only_chick_before_treble_clef(self):
        message = watcher.format_new(sample_record(title="Фауст"))
        self.assertIn("🐣𝄞 Фауст", message)
        self.assertNotIn("Новый спектакль", message)
        self.assertNotIn("Новое событие", message)

    def test_feminine_nominative_is_not_masculinized(self):
        self.assertEqual(watcher.normalize_person_name("Евгения Муравьёва", "nomn"), "Евгения Муравьёва")
        self.assertEqual(
            watcher.extract_list_main_roles(
                "В главных партиях: Евгения Муравьёва Дирижер — Валерий Гергиев Мариинский-2"
            ),
            ["Евгения Муравьёва"],
        )

    def test_gotterdammerung_main_role_duplicate_is_suppressed(self):
        old = sample_record(
            "/playbill/playbill/2026/7/26/2_1700/",
            "Гибель богов",
            performers=[
                "Дирижер — Валерий Гергиев",
                "Гутруна — Евгения Муравьёва",
            ],
        )
        new = copy.deepcopy(old)
        new["main_roles"] = watcher.extract_list_main_roles(
            "В главных партиях: Евгения Муравьёва Дирижер — Валерий Гергиев Мариинский-2"
        )
        performer_keys = {watcher.person_compare_key(item) for item in new["performers"]}
        new["main_roles"] = [
            item for item in new["main_roles"]
            if watcher.person_compare_key(item) not in performer_keys
        ]
        new = watcher.with_digest(new)
        self.assertEqual(new["main_roles"], [])
        self.assertEqual(watcher.build_messages({old["url"]: old}, {new["url"]: new}), [])

    def test_flattened_person_plus_role_fragment_is_rejected(self):
        bad = "Екатерины Семенчук Дирижер — Валерий Гергиев"
        self.assertTrue(watcher.has_person_role_collision("Екатерины Семенчук Дирижер"))
        self.assertEqual(watcher.sanitize_performer_line(bad), "")
        self.assertEqual(watcher.normalize_stored_performer_item(bad), "")

    def test_old_hovanshchina_garbage_is_silently_purged(self):
        old = sample_record(
            "/playbill/playbill/2026/8/2/2_1700/",
            "Хованщина",
            performers=[
                "Марфа — Екатерина Семенчук",
                "Екатерины Семенчук Дирижер — Валерий Гергиев",
            ],
        )
        new = sample_record(
            "/playbill/playbill/2026/8/2/2_1700/",
            "Хованщина",
            performers=["Марфа — Екатерина Семенчук"],
        )
        self.assertEqual(watcher.build_messages({old["url"]: old}, {new["url"]: new}), [])

    def test_reverse_person_voice_form_still_works(self):
        self.assertEqual(
            watcher.sanitize_performer_line("Юлия Маточкина — меццо-сопрано"),
            "Юлия Маточкина — меццо-сопрано",
        )


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MariinskyWatcherV3Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    run_all_tests()
