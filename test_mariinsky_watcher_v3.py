import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
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
    def setUp(self):
        # All tests are offline. Dedicated Telegram contract tests override this mock.
        for method in ("get", "post"):
            network = patch.object(watcher.SESSION, method, side_effect=AssertionError("Unexpected network call in offline test"))
            network.start()
            self.addCleanup(network.stop)

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

    def test_main_dry_run_writes_no_files_or_telegram(self):
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
                    {"items": [], "summary": {}, "scan_complete": True},
                ),
            ), patch.object(watcher, "save_state", side_effect=AssertionError("dry_run must not save state")), patch.object(
                watcher, "send_message", side_effect=AssertionError("dry_run must not send Telegram")
            ):
                watcher.main()
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)
            self.assertFalse(audit_path.exists())

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
            ), patch.object(watcher, "flush_pending", side_effect=AssertionError("Incomplete scan must not deliver")):
                with self.assertRaisesRegex(RuntimeError, "Scan failed quality"):
                    watcher.main()

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            saved_events = saved["sources"]["mariinsky"]["events"]
            self.assertIn(old["url"], saved_events)
            self.assertNotIn(new["url"], saved_events)
            self.assertEqual(saved, state)

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

    def test_new_event_with_initial_cast_sends_separate_cast_message(self):
        record = sample_record(
            "/playbill/playbill/2026/10/19/3_1900/",
            "Свиридов. «Поэма памяти Сергея Есенина», «Метель»",
            performers=[
                "Солист — Егор Семенков",
                "Чтец — Владимир Рылов",
                "Дирижер — Константин Рылов",
            ],
        )
        messages = watcher.build_messages({}, {record["url"]: record})
        self.assertEqual(len(messages), 2)
        self.assertIn("🐣𝄞 Свиридов. «Поэма памяти Сергея Есенина», «Метель»", messages[0])
        self.assertNotIn("Егор Семенков", messages[0])
        self.assertIn("Изменение в составе:", messages[1])
        self.assertIn("🟢 Добавлено:", messages[1])
        self.assertIn("Солист — Егор Семенков", messages[1])
        self.assertIn("Чтец — Владимир Рылов", messages[1])
        self.assertIn("Дирижер — Константин Рылов", messages[1])

    def test_new_event_without_initial_cast_keeps_single_compact_message(self):
        record = sample_record(title="Фауст")
        messages = watcher.build_messages({}, {record["url"]: record})
        self.assertEqual(messages, [watcher.format_new(record)])

    def test_initial_cast_dedupes_person_between_performers_and_main_roles(self):
        record = sample_record(
            title="Идиот",
            performers=["Рогожин — Владислав Сулимский"],
        )
        record["main_roles"] = ["Владислава Сулимского"]
        record["main_roles_source"] = "list_main_roles"
        record = watcher.with_digest(record)
        cast = watcher.initial_cast_lines(record)
        self.assertEqual(cast, ["Рогожин — Владислав Сулимский"])

    def test_sviridov_name_is_not_stored_as_performer(self):
        self.assertTrue(watcher.looks_like_composer_name_line("Георгий Свиридов"))
        self.assertEqual(watcher.normalize_stored_performer_item("Георгий Свиридов"), "")
        self.assertEqual(
            watcher.extract_performers_from_lines(
                [
                    "Солист — Егор Семенков",
                    "Чтец — Владимир Рылов",
                    "Дирижер — Константин Рылов",
                    "Георгий Свиридов",
                ]
            ),
            [
                "Солист — Егор Семенков",
                "Чтец — Владимир Рылов",
                "Дирижер — Константин Рылов",
            ],
        )


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


class SafeScanTests(unittest.TestCase):
    ROOT = watcher.MARIINSKY_ROOT
    MONTH = ROOT + "2026/10/"
    DAY = MONTH + "25/"
    EVENT = DAY + "2_1900/"
    FAR = ROOT + "2027/6/"
    DETAIL = "<html><body><h1>Турандот</h1><h2>Исполнители</h2><p>Дирижер — Валерий Гергиев</p></body></html>"
    CARD = '<html><body><h1>Афиша</h1><a href="/playbill/playbill/2026/10/25/2_1900/">Турандот опера</a></body></html>'

    def setUp(self):
        for method in ("get", "post"):
            mocker = patch.object(watcher.SESSION, method, side_effect=AssertionError("Offline tests cannot access network"))
            mocker.start()
            self.addCleanup(mocker.stop)
        clock = patch.object(watcher, "today_moscow", return_value=date(2026, 10, 24))
        clock.start()
        self.addCleanup(clock.stop)

    def record(self, day=25):
        return sample_record(f"/playbill/playbill/2026/10/{day}/2_1900/")

    def snapshot(self, records=None):
        events = {r["url"]: r for r in (records if records is not None else [self.record()])}
        return ({"mariinsky": events}, {"mariinsky": set(events)}, {"mariinsky": set()},
                {"items": [], "summary": {}, "source_errors": [], "scan_complete": True})

    def run_main(self, mode, state, snapshot, expected_error=None):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            audit_path = Path(folder) / "audit.json"
            if state is not None:
                state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            before = state_path.read_bytes() if state_path.exists() else None
            with patch.object(watcher, "STATE_FILE", state_path), patch.object(watcher, "AUDIT_FILE", audit_path), patch.object(watcher, "RUN_MODE", mode), patch.object(watcher, "DEBUG_URL", ""), patch.object(watcher, "scan_all", return_value=snapshot), contextlib.redirect_stdout(io.StringIO()):
                if expected_error:
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        watcher.main()
                else:
                    watcher.main()
            after = state_path.read_bytes() if state_path.exists() else None
            return before, after, json.loads(after) if after else None, json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None

    def test_http_200_security_fixture_is_rejected_without_retry(self):
        raw = (Path(__file__).parent / "tests/fixtures/security_check.html").read_text(encoding="utf-8")
        response = Mock(status_code=200, headers={"Content-Type": "text/html"}, encoding="utf-8", text=raw)
        with patch.object(watcher.SESSION, "get", return_value=response) as get:
            with self.assertRaisesRegex(watcher.PageValidationError, "Security challenge"):
                watcher.fetch_page(self.ROOT)
            self.assertEqual(get.call_count, 1)

    def test_http_200_blank_and_non_html_are_rejected(self):
        for raw, content_type in [("", "text/html"), ("<html><body></body></html>", "text/html"), (self.CARD, "application/json")]:
            response = Mock(status_code=200, headers={"Content-Type": content_type}, encoding="utf-8", text=raw)
            with self.subTest(raw=raw), patch.object(watcher.SESSION, "get", return_value=response):
                with self.assertRaises(watcher.PageValidationError):
                    watcher.fetch_page(self.ROOT)

    def test_unexpected_redirect_is_not_followed(self):
        response = Mock(status_code=302)
        with patch.object(watcher.SESSION, "get", return_value=response) as get:
            with self.assertRaisesRegex(watcher.PageValidationError, "redirect"):
                watcher.fetch_page(self.ROOT)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_error_page_and_detail_without_heading_are_rejected(self):
        for raw in ['<html><title>Service unavailable</title><p>try again</p></html>', '<html><p>Турандот опера</p></html>', '<title>Ошибка</title><h1>Сервис временно недоступен</h1><p>Попробуйте позже</p>', '<h1>Please try again later</h1><p>Something happened</p>']:
            with self.subTest(raw=raw), self.assertRaises(watcher.PageValidationError):
                watcher.parse_mariinsky_event(self.EVENT, "Турандот опера", "opera", html=raw)

    def test_scan_traverses_month_days_and_deduplicates(self):
        pages = {self.ROOT: self.CARD, self.MONTH: '<h1>Афиша</h1><a href="25/">25</a><a href="25/">25</a>', self.DAY: self.CARD, self.EVENT: self.DETAIL}
        with patch.object(watcher, "month_urls", return_value=[self.ROOT, self.MONTH]), patch.object(watcher, "fetch_page", side_effect=pages.__getitem__) as fetch:
            events, seen, failed, audit = watcher.scan_all()
        self.assertTrue(audit["scan_complete"])
        self.assertEqual(set(events["mariinsky"]), {self.EVENT})
        self.assertEqual(seen["mariinsky"], {self.EVENT})
        self.assertFalse(failed["mariinsky"])
        self.assertEqual(sum(call.args == (self.DAY,) for call in fetch.call_args_list), 1)
        self.assertEqual(sum(call.args == (self.EVENT,) for call in fetch.call_args_list), 1)

    def test_external_urls_and_days_outside_month_are_ignored(self):
        raw = '<a href="https://evil.example/playbill/playbill/2026/10/25/2_1900/">Турандот</a><a href="https://evil.example/playbill/playbill/2026/10/25/">25</a><a href="../11/1/">1</a><a href="32/">32</a><a href="25/">25</a>'
        self.assertFalse(watcher.extract_playbill_links(raw, self.MONTH))
        self.assertEqual(watcher.extract_day_links(raw, self.MONTH), [self.DAY])

    def test_explicit_empty_far_month_does_not_break_nonempty_scan(self):
        pages = {self.ROOT: self.CARD, self.FAR: '<html><h1>Афиша</h1><p>Событий не найдено</p></html>', self.EVENT: self.DETAIL}
        with patch.object(watcher, "month_urls", return_value=[self.ROOT, self.FAR]), patch.object(watcher, "fetch_page", side_effect=pages.__getitem__):
            _, _, _, audit = watcher.scan_all()
        self.assertTrue(audit["scan_complete"])
        self.assertTrue(audit["pages"][1]["explicit_empty"])

    def test_unexplained_empty_month_and_empty_current_month_are_errors(self):
        for url, raw in [(self.FAR, '<h1>Афиша</h1>'), (self.MONTH, '<h1>Афиша</h1><p>Событий не найдено</p>')]:
            with self.subTest(url=url), patch.object(watcher, "month_urls", return_value=[url]), patch.object(watcher, "fetch_page", return_value=raw):
                _, _, _, audit = watcher.scan_all()
            self.assertFalse(audit["scan_complete"])

    def test_failed_day_or_detail_makes_whole_scan_incomplete(self):
        for failing in [self.DAY, self.EVENT]:
            pages = {self.MONTH: '<h1>Афиша</h1><a href="25/">25</a>', self.DAY: self.CARD, self.EVENT: self.DETAIL}
            def fetch(url):
                if url == failing:
                    raise watcher.PageValidationError("bad page")
                return pages[url]
            with self.subTest(failing=failing), patch.object(watcher, "month_urls", return_value=[self.MONTH]), patch.object(watcher, "fetch_page", side_effect=fetch):
                _, _, failed, audit = watcher.scan_all()
            self.assertFalse(audit["scan_complete"])
            if failing == self.EVENT:
                self.assertEqual(failed["mariinsky"], {self.EVENT})

    def test_zero_links_preserves_nonempty_state_and_pending(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {self.EVENT: self.record()}
        state["pending_messages"] = ["unsent queue entry"]
        before, after, _, audit = self.run_main("live", state, self.snapshot([]), "Scan failed quality")
        self.assertEqual(before, after)
        self.assertEqual(audit["would_notify_count"], 0)
        self.assertEqual(audit["state_update_strategy"], "preserve_all")

    def test_sharp_drop_of_future_events_is_rejected(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {r["url"]: r for r in [self.record(d) for d in range(25, 31)]}
        before, after, _, audit = self.run_main("live", state, self.snapshot([self.record()]), "Scan failed quality")
        self.assertEqual(before, after)
        self.assertTrue(any("sharp_drop_included" in reason for reason in audit["quality_errors"]))

    def test_month_drop_cannot_hide_behind_other_month(self):
        state = watcher.default_state()
        old = [self.record(d) for d in range(25, 31)] + [sample_record(f"/playbill/playbill/2026/11/{d}/2_1900/") for d in range(1, 25)]
        state["sources"]["mariinsky"]["events"] = {r["url"]: r for r in old}
        before, after, _, audit = self.run_main("live", state, self.snapshot(old[6:]), "Scan failed quality")
        self.assertEqual(before, after)
        self.assertTrue(any("2026-10" in reason for reason in audit["quality_errors"]))

    def test_past_events_roll_out_without_false_anomaly(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {r["url"]: r for r in [self.record(d) for d in range(1, 15)]}
        audit = self.snapshot()[-1]
        self.assertTrue(watcher.assess_scan(state, self.snapshot()[0]["mariinsky"], {self.EVENT}, set(), audit))

    def test_last_successful_link_coverage_also_detects_drop(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["last_successful_scan"] = {"seen_urls": [self.record(d)["url"] for d in range(25, 31)]}
        audit = self.snapshot()[-1]
        self.assertFalse(watcher.assess_scan(state, self.snapshot()[0]["mariinsky"], {self.EVENT}, set(), audit))

    def test_initial_empty_live_state_requires_reviewed_bootstrap(self):
        for state in [None, watcher.default_state()]:
            with self.subTest(state=state):
                before, after, _, _ = self.run_main("live", state, self.snapshot(), "No nonempty baseline")
                self.assertEqual(before, after)

    def test_bootstrap_preserves_unknown_fields_and_is_idempotent(self):
        state = watcher.default_state()
        state["operator_metadata"] = {"retain": 17}
        state["sources"]["other"] = {"retain": True}
        state["sources"]["mariinsky"]["unknown"] = "retain"
        state["sources"]["mariinsky"]["last_successful_scan"] = {"seen_urls": [], "operator_field": {"retain": True}}
        _, _, saved, _ = self.run_main("bootstrap", state, self.snapshot())
        self.assertEqual(saved["operator_metadata"], state["operator_metadata"])
        self.assertEqual(saved["sources"]["other"], state["sources"]["other"])
        self.assertEqual(saved["sources"]["mariinsky"]["unknown"], "retain")
        self.assertEqual(saved["sources"]["mariinsky"]["last_successful_scan"]["operator_field"], {"retain": True})
        self.assertEqual(saved["pending_messages"], [])
        before, after, _, _ = self.run_main("bootstrap", saved, self.snapshot())
        self.assertEqual(before, after)
        self.assertEqual(watcher.build_messages(saved["sources"]["mariinsky"]["events"], self.snapshot()[0]["mariinsky"]), [])

    def test_bootstrap_refuses_pending_or_uncertain_delivery(self):
        for extra in [{"pending_messages": ["fresh queue"]}, {"delivery_uncertain": {"reason": "timeout"}}]:
            state = watcher.default_state()
            state.update(extra)
            before, after, _, _ = self.run_main("bootstrap", state, self.snapshot(), "pending or uncertain|delivery is uncertain")
            self.assertEqual(before, after)

    def test_bootstrap_refuses_incomplete_scan(self):
        snapshot = self.snapshot()
        snapshot[-1]["scan_complete"] = False
        before, after, _, _ = self.run_main("bootstrap", watcher.default_state(), snapshot, "Scan failed quality")
        self.assertEqual(before, after)

    def test_dry_run_never_writes_existing_audit_or_any_state(self):
        state = watcher.default_state()
        for snapshot in [self.snapshot(), self.snapshot([])]:
            with self.subTest(empty=not snapshot[0]["mariinsky"]):
                before, after, _, audit = self.run_main("dry_run", state, snapshot, "quality checks" if not snapshot[0]["mariinsky"] else None)
                self.assertEqual(before, after)
                self.assertIsNone(audit)

    def test_repeated_scan_and_queue_append_do_not_duplicate_messages(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {self.EVENT: self.record()}
        with patch.object(watcher, "flush_pending", return_value=0):
            _, _, first, _ = self.run_main("live", state, self.snapshot([self.record(), self.record(26)]))
            _, _, second, _ = self.run_main("live", first, self.snapshot([self.record(), self.record(26)]))
        self.assertTrue(first["pending_messages"])
        self.assertEqual(first["pending_messages"], second["pending_messages"])
        watcher.add_pending(second, first["pending_messages"] * 2)
        self.assertEqual(first["pending_messages"], second["pending_messages"])

    def test_corrupt_state_is_not_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            for raw in ["{", "[]", '{"sources":{}}', '{"sources":{"mariinsky":{"events":{}}},"pending_messages":"bad"}']:
                path.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw), patch.object(watcher, "STATE_FILE", path), self.assertRaises(RuntimeError):
                    watcher.load_state()
                self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_delivery_exception_persists_uncertainty_and_stops_auto_retry(self):
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {self.EVENT: self.record()}
        state["pending_messages"] = ["message"]
        with patch.object(watcher, "send_message", side_effect=TimeoutError("uncertain")):
            _, _, saved, _ = self.run_main("live", state, self.snapshot(), "delivery status requires review")
        self.assertEqual(saved["pending_messages"], ["message"])
        self.assertTrue(saved["delivery_uncertain"])
        before, after, _, _ = self.run_main("live", saved, self.snapshot(), "delivery is uncertain")
        self.assertEqual(before, after)

    def test_single_missing_link_keeps_trusted_record_without_cancellation(self):
        old, other = self.record(), self.record(26)
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {r["url"]: r for r in [old, other]}
        _, _, saved, audit = self.run_main("live", state, self.snapshot([other]))
        self.assertEqual(saved["sources"]["mariinsky"]["events"][old["url"]], old)
        self.assertEqual(saved["pending_messages"], [])
        self.assertEqual(audit["would_notify_count"], 0)
        self.assertEqual(audit["unconfirmed_missing_preserved"], 1)
        self.assertFalse(audit["inferred_removal_notifications"])

    def test_empty_failure_does_not_freeze_later_verified_cast_change(self):
        old = self.record()
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {old["url"]: old}
        _, _, preserved, _ = self.run_main("live", state, self.snapshot([]), "Scan failed quality")
        changed = copy.deepcopy(old)
        changed["performers"] = ["Дирижер — Валерий Гергиев"]
        changed = watcher.with_digest(changed)
        with patch.object(watcher, "flush_pending", return_value=0):
            _, _, updated, audit = self.run_main("live", preserved, self.snapshot([changed]))
        self.assertEqual(updated["sources"]["mariinsky"]["events"][old["url"]], changed)
        self.assertEqual(audit["would_notify_count"], 1)
        self.assertIn("Валерий Гергиев", updated["pending_messages"][0])

    def test_explicit_cancellation_is_still_reported(self):
        old = self.record()
        state = watcher.default_state()
        state["sources"]["mariinsky"]["events"] = {old["url"]: old}
        cancelled = copy.deepcopy(old)
        cancelled["cancelled"] = True
        cancelled["cancellation_source"] = "detail_page"
        cancelled = watcher.with_digest(cancelled)
        with patch.object(watcher, "flush_pending", return_value=0):
            _, _, saved, audit = self.run_main("live", state, self.snapshot([cancelled]))
        self.assertEqual(audit["would_notify_count"], 1)
        self.assertTrue(saved["sources"]["mariinsky"]["events"][old["url"]]["cancelled"])
        self.assertEqual(saved["pending_messages"], [watcher.format_cancelled(cancelled)])


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MariinskyWatcherV3Tests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(SafeScanTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    run_all_tests()
