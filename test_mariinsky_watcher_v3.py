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
        self.assertIn("🎵Пиковая дама → Джоконда", messages[0])
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
            ["Екатерины Семенчук", "Марины Шахдинаровой"],
        )
        self.assertEqual(
            watcher.split_participation("При участии Екатерины Семенчук, Марины Шахдинаровой и Ольги Пудовой"),
            ["Екатерины Семенчук", "Марины Шахдинаровой", "Ольги Пудовой"],
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
        self.assertEqual(lines[0], "🔱Мариинский-2🔱")
        self.assertEqual(lines[1], "🐣Турандот")
        self.assertEqual(lines[2], "🔷31 июля🔹19:00")
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
        self.assertEqual(lines[1], "🐣Песни рек: звуки Янцзы и Невы")
        self.assertEqual(lines[2], "🔷22 июля🔹19:00")
        self.assertIn("ℹ️ https://www.mariinsky.ru/", message)
        self.assertNotIn("Ссылка:", message)

    def test_removed_event_format_uses_red_markers(self):
        record = sample_record()
        message = watcher.format_removed(record)
        lines = message.splitlines()
        self.assertEqual(lines[0], "🔱Мариинский-2🔱")
        self.assertEqual(lines[1], "❌Турандот")
        self.assertEqual(lines[2], "🔻31 июля🔻19:00")
        self.assertNotIn("Событие исчезло", message)

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
        self.assertIn("❌Турандот", messages[0])
        self.assertIn("🔻31 июля🔻19:00", messages[0])

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



def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MariinskyWatcherV3Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    run_all_tests()
