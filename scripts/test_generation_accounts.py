"""豆包 / Dola 账号路由与本地网页自动化回归；不访问真实服务或使用用户账号。"""
import sqlite3
from datetime import date, timedelta
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from playwright.sync_api import sync_playwright

from constants import BUNDLED_CHROME
from generation_accounts import is_platform_url
from launcher import DesktopApi
from original_doubao_base import BaseAccountBrowserWorker
from original_doubao_image_worker import OriginalDoubaoImageWorker
from original_doubao_nomark import OriginalDoubaoVideoEvidence
from original_doubao_video_worker import ORIGINAL_DOUBAO_MATERIAL_PLEDGE, OriginalDoubaoVideoWorker


class AccountTypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = patch.multiple("launcher", DATA_DIR=self.root, ACCOUNTS_DIR=self.root / "accounts",
                                    ACCOUNTS_FILE=self.root / "accounts.json", SETTINGS_FILE=self.root / "settings.json",
                                    GENERATION_TASKS_FILE=self.root / "generation_tasks.json")
        self.paths.start()
        self.api = DesktopApi.__new__(DesktopApi)
        self.api._storage_available = lambda: False
        self.api._ensure_cloud_accounts_synced = Mock()
        self.api._push_cloud_account_state = Mock()
        self.api.get_settings = lambda: {"dailyVideoQuota": 3, "defaultAccountId": ""}
        self.api._accounts_read_cache = (0.0, [])
        self.api._session_probe_cache = {}
        self.api._login_expired = {}
        self.api._lock = threading.Lock()
        self.api._account_usage = {}

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def test_legacy_default_and_type_survive_reload_rename_and_reorder(self):
        self.api._write_accounts([{"id": "old", "name": "历史账号"}])
        created = self.api.create_generation_account("国际账号", "dola")
        self.api.rename_account(created["id"], "国际主账号")
        self.api.reorder_accounts([created["id"], "old"])
        self.api._accounts_read_cache = (0.0, [])
        accounts = self.api._read_accounts()
        self.assertEqual([(item["name"], item["accountType"]) for item in accounts],
                         [("国际主账号", "dola"), ("历史账号", "doubao")])
        self.assertTrue((self.root / "accounts" / created["id"] / "profile").is_dir())
        with self.assertRaisesRegex(ValueError, "不支持的账号类型"):
            self.api.create_account("错误账号", "", "unknown")
        self.assertEqual(len(self.api._read_accounts()), 2)

    def test_auto_assignment_stays_on_selected_platform(self):
        self.api._write_accounts([
            {"id": "cn", "name": "国内"},
            {"id": "global1", "name": "国际一", "accountType": "dola"},
            {"id": "global2", "name": "国际二", "accountType": "dola"},
        ])
        self.api._account_usage["global1"] = {"ownerId": "previous"}
        self.assertEqual(self.api._acquire_available_generation_account("global1", "next")["id"], "global2")
        with self.assertRaisesRegex(ValueError, "都在运行中"):
            self.api._acquire_available_generation_account("global1", "third")
        self.assertNotIn("cn", self.api._account_usage)
        self.assertEqual(self.api._acquire_available_generation_account("cn", "domestic")["id"], "cn")

    def test_dola_accounts_default_to_four_and_legacy_domestic_to_three(self):
        self.api._write_accounts([{"id": "cn", "name": "旧国内账号"},
                                  {"id": "global", "name": "旧国际账号", "accountType": "dola", "dailyQuota": 3,
                                   "quotaUsageDate": date.today().isoformat(), "generatedToday": 1, "hasLoggedIn": True}])
        self.api._workers = {}
        self.api._pull_cloud_account_quota = Mock()
        listed = {item["id"]: item for item in self.api.list_accounts()}
        self.assertEqual((listed["cn"]["dailyQuota"], listed["cn"]["quotaRemainingToday"]), (3, 3))
        self.assertEqual((listed["global"]["dailyQuota"], listed["global"]["quotaRemainingToday"]), (4, 3))
        self.assertEqual(self.api.create_generation_account("新国际账号", "dola")["dailyQuota"], 4)
        self.assertEqual(self.api.create_generation_account("新国内账号", "doubao")["dailyQuota"], 3)

    def test_dola_fourth_generation_is_available_and_fifth_is_blocked(self):
        today = date.today().isoformat()
        self.api._write_accounts([{"id": "cn", "name": "国内", "hasLoggedIn": True,
                                   "quotaUsageDate": today, "generatedToday": 3},
                                  {"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": True,
                                   "quotaUsageDate": today, "generatedToday": 3}])
        self.api._active_account_token = lambda token="": ""
        self.assertEqual(self.api._acquire_available_generation_account("", "fourth", "auto")["id"], "global")
        self.api._record_account_generation_success("global")
        self.api._release_account_usage("global", "fourth")
        account = self.api._find_account("global")
        self.assertEqual((account["generatedToday"], account["dailyQuota"]), (4, 4))
        self.assertEqual(account["quotaExhaustedOn"], today)
        with self.assertRaisesRegex(ValueError, "没有可用"):
            self.api._acquire_available_generation_account("", "fifth", "auto")

    def test_quota_edits_only_affect_accounts_of_the_selected_platform(self):
        today = date.today().isoformat()
        settings = {"dailyVideoQuota": 3, "dolaDailyVideoQuota": 4, "defaultAccountId": ""}
        self.api.get_settings = lambda: dict(settings)
        self.api._write_settings = lambda values: settings.update(values)
        self.api._write_accounts([{"id": "cn", "name": "国内", "dailyQuota": 3,
                                   "quotaUsageDate": today, "generatedToday": 2},
                                  {"id": "global", "name": "国际", "accountType": "dola",
                                   "quotaUsageDate": today, "generatedToday": 1}])
        self.assertEqual(self.api.set_account_daily_quota("global", 4)["quotaRemainingToday"], 3)
        self.assertEqual(settings["dailyVideoQuota"], 3)
        domestic = self.api._find_account("cn")
        self.assertEqual((domestic["dailyQuota"], domestic["generatedToday"]), (3, 2))
        self.api.set_account_daily_quota("cn", 5)
        self.assertEqual(settings["dolaDailyVideoQuota"], 4)
        self.assertEqual(self.api._account_daily_quota(self.api._find_account("global")), 4)

    def test_dola_reported_zero_is_applied_at_completion_before_reassignment(self):
        today = date.today()
        self.api._active_account_token = lambda token="": ""
        self.api._set_cloud_account_quota_status = Mock(return_value=True)
        self.api._persist_tasks_locked = Mock()
        self.api._apply_task_result = Mock()
        for terminal_status in ("succeeded", "failed"):
            with self.subTest(status=terminal_status):
                self.api._write_accounts([
                    {"id": "cn", "name": "国内", "hasLoggedIn": True},
                    {"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": True,
                     "quotaUsageDate": today.isoformat(), "generatedToday": 1},
                ])
                self.api._tasks = {"task": {"accountId": "global", "accountType": "dola", "status": "generating"}}
                self.api._account_usage = {"global": {"ownerId": "task"}}
                self.api._update_task("task", status="downloading", quotaExhaustedAfterGeneration=True)
                self.assertEqual(self.api._find_account("global")["generatedToday"], 1)
                self.assertFalse(self.api.is_account_quota_exhausted_today("global"))

                release = self.api._release_account_usage
                def release_after_zero(account_id, task_id):
                    self.assertTrue(self.api.is_account_quota_exhausted_today(account_id))
                    self.assertEqual(self.api._find_account(account_id)["generatedToday"], 4)
                    return release(account_id, task_id)
                with patch.object(self.api, "_release_account_usage", side_effect=release_after_zero):
                    self.api._update_task("task", status=terminal_status)
                self.assertEqual(self.api._acquire_available_generation_account("", "next", "auto")["id"], "cn")
                self.assertEqual(self.api._account_daily_quota(self.api._find_account("cn")), 3)
                with patch("launcher.date") as clock:
                    clock.today.return_value = today + timedelta(days=1)
                    self.assertFalse(self.api.is_account_quota_exhausted_today("global"))

    def test_zero_after_generation_does_not_affect_unfinished_cancelled_or_domestic_tasks(self):
        self.api._active_account_token = lambda token="": ""
        self.api._set_cloud_account_quota_status = Mock(return_value=True)
        self.api._persist_tasks_locked = Mock()
        self.api._apply_task_result = Mock()
        for platform, cancelled, completed, expected_used in [
            ("dola", False, False, 0), ("dola", True, True, 0), ("doubao", False, True, 1),
        ]:
            with self.subTest(platform=platform, cancelled=cancelled, completed=completed):
                self.api._write_accounts([{"id": "account", "name": "测试", "accountType": platform}])
                self.api._tasks = {"task": {"accountId": "account", "accountType": platform,
                                           "status": "generating", "cancelled": cancelled}}
                self.api._account_usage = {"account": {"ownerId": "task"}}
                self.api._update_task("task", status="succeeded" if completed else "failed",
                                      quotaExhaustedAfterGeneration=completed)
                account = self.api._find_account("account")
                self.assertEqual(account.get("generatedToday", 0), expected_used)
                self.assertFalse(self.api.is_account_quota_exhausted_today("account"))

    def test_settings_save_preserves_dola_quota_when_legacy_payload_omits_it(self):
        self.api.get_settings = DesktopApi.get_settings.__get__(self.api)
        settings = self.api.save_settings({"storageDir": str(self.root / "storage"), "outputDir": str(self.root / "output"),
                                          "dailyVideoQuota": 3, "dolaDailyVideoQuota": 4})
        self.assertEqual(settings["dolaDailyVideoQuota"], 4)
        settings = self.api.save_settings({"dailyVideoQuota": 5})
        self.assertEqual((settings["dailyVideoQuota"], settings["dolaDailyVideoQuota"]), (5, 4))

    def test_explicit_video_platform_overrides_foreign_preferred_account(self):
        self.api._write_accounts([{"id": "cn", "name": "国内"}, {"id": "global", "name": "国际", "accountType": "dola"}])
        self.api._tasks, self.api._workers = {}, {}
        worker = Mock(visible=True, start_error="")
        worker.ready = threading.Event()
        worker.ready.set()
        self.api._ensure_worker = Mock(return_value=worker)
        image = self.root / "fixture.png"
        image.write_bytes(b"fixture")
        for platform, preferred, expected in [("dola", "cn", "global"), ("doubao", "global", "cn")]:
            result = self.api.start_generation({"imagePath": str(image), "prompt": "A landscape", "accountType": platform,
                                                "accountId": preferred, "generationEngine": platform})
            self.assertEqual(result["accountId"], expected)
            self.assertEqual(self.api._tasks[result["taskId"]]["accountType"], platform)
            self.api._release_account_usage(expected, result["taskId"])
        with self.assertRaisesRegex(ValueError, "生成平台不一致"):
            self.api.start_generation({"imagePath": str(image), "prompt": "A landscape", "accountType": "dola",
                                       "accountId": "cn", "autoAssignAccount": False})

    def test_explicit_dola_platform_never_falls_back_to_domestic_account(self):
        self.api._write_accounts([{"id": "cn", "name": "国内"}])
        with self.assertRaisesRegex(ValueError, "Dola"):
            self.api._acquire_available_generation_account("cn", "task", "dola")
        self.assertEqual(self.api._account_usage, {})

    def test_do_auto_uses_both_platforms_and_skips_unavailable_accounts(self):
        today = date.today().isoformat()
        self.api._write_accounts([
            {"id": "new", "name": "未登录", "hasLoggedIn": False},
            {"id": "expired", "name": "过期", "hasLoggedIn": True, "loginExpiredAt": today},
            {"id": "quota", "name": "额度用完", "hasLoggedIn": True, "quotaUsageDate": today, "generatedToday": 3},
            {"id": "busy", "name": "占用", "hasLoggedIn": True},
            {"id": "cn", "name": "国内", "hasLoggedIn": True},
            {"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": True},
        ])
        self.api._account_usage["busy"] = {"ownerId": "previous"}
        picked = {self.api._acquire_available_generation_account("busy", owner, "auto")["id"] for owner in ["one", "two"]}
        self.assertEqual(picked, {"cn", "global"})
        with self.assertRaisesRegex(ValueError, "都在运行中"):
            self.api._acquire_available_generation_account("busy", "three", "auto")

    def test_do_auto_respects_live_login_state_and_reports_empty_pool(self):
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": True}])
        self.api._workers = {"global": Mock(authenticated=False)}
        with self.assertRaisesRegex(ValueError, "没有可用"):
            self.api._acquire_available_generation_account("global", "task", "auto")
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": False}])
        self.api._workers["global"].authenticated = True
        self.assertEqual(self.api._acquire_available_generation_account("", "task", "auto")["id"], "global")

    def test_do_auto_submission_opens_allocated_platform_instead_of_default(self):
        self.api._write_accounts([{"id": "cn", "name": "国内", "hasLoggedIn": True},
                                 {"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": True}])
        self.api._account_usage["cn"] = {"ownerId": "previous"}
        self.api._tasks, self.api._workers = {}, {}
        worker = Mock(visible=True, start_error="")
        worker.ready = threading.Event()
        worker.ready.set()
        self.api._ensure_worker = Mock(return_value=worker)
        image = self.root / "fixture.png"
        image.write_bytes(b"fixture")
        payload = {"imagePath": str(image), "prompt": "A landscape", "accountId": "cn", "accountType": "auto", "generationEngine": "do"}
        result = self.api.start_generation(payload)
        self.assertEqual(result["accountId"], "global")
        self.assertEqual(self.api._tasks[result["taskId"]]["accountType"], "dola")
        self.assertEqual(self.api._tasks[result["taskId"]]["generationEngine"], "do")
        self.api._ensure_worker.assert_called_once_with("global", visible=True)
        with self.assertRaisesRegex(ValueError, "自动分配"):
            self.api.start_generation({**payload, "autoAssignAccount": False})

    def test_dola_session_probe_only_accepts_its_domain(self):
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola"}])
        database = self.root / "accounts/global/profile/Default/Network/Cookies"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, expires_utc INTEGER)")
            connection.execute("INSERT INTO cookies VALUES ('.doubao.com','sessionid','fixture',X'',0)")
            connection.commit()
        finally:
            connection.close()
        self.assertFalse(self.api._has_saved_original_doubao_session("global"))
        connection = sqlite3.connect(database)
        try:
            connection.execute("UPDATE cookies SET host_key = '.dola.com'")
            connection.commit()
        finally:
            connection.close()
        self.api._session_probe_cache.clear()
        self.assertTrue(self.api._has_saved_original_doubao_session("global"))
        with patch("launcher.httpx.get") as request:
            self.assertIsNone(self.api._http_check_login("global"))
            request.assert_not_called()

    def test_detected_dola_login_is_shown_and_saved_by_account_polling(self):
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola", "hasLoggedIn": False}])
        worker = Mock(authenticated=None)
        self.api._workers = {"global": worker}
        self.api._pull_cloud_account_quota = Mock()
        waiting = self.api.list_accounts()[0]
        self.assertEqual(waiting["status"], "登录窗口已打开 · 等待登录")
        worker.authenticated = True
        logged_in = self.api.list_accounts()[0]
        self.assertTrue(logged_in["authenticated"])
        self.assertTrue(logged_in["hasLoggedIn"])
        self.assertEqual(logged_in["status"], "已登录 · 状态已保存")
        self.api._accounts_read_cache = (0.0, [])
        self.assertTrue(self.api._read_accounts()[0]["hasLoggedIn"])

    def test_login_browser_opens_platform_home_with_independent_profile(self):
        for account_type, home in [("doubao", "https://www.doubao.com/"), ("dola", "https://www.dola.com/chat")]:
            api = Mock()
            api._find_account.return_value = {"accountType": account_type}
            worker = BaseAccountBrowserWorker(api, account_type, False)
            page = Mock(url="about:blank")
            page.evaluate.return_value = "login"
            context = Mock(pages=[page])
            context.cookies.return_value = []
            playwright = Mock()
            playwright.chromium.launch_persistent_context.return_value = context
            worker.stop()
            with patch("original_doubao_base.sync_playwright") as factory, patch("original_doubao_base.ACCOUNTS_DIR", self.root):
                factory.return_value.start.return_value = playwright
                worker._run()
            page.goto.assert_called_once_with(home, wait_until="domcontentloaded", timeout=60_000)
            kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
            self.assertEqual(kwargs["user_data_dir"], str((self.root / account_type / "profile").resolve()))
        self.assertFalse(is_platform_url("https://www.dola.com.evil.test/chat", "dola.com"))

    def test_dola_never_uses_domestic_share_parser(self):
        api = Mock()
        api._find_account.return_value = {"accountType": "dola"}
        api.get_settings.return_value = {"autoDownload": True}
        worker = OriginalDoubaoVideoWorker(api, "global", False)
        with patch("original_doubao_video_worker.original_doubao_video_parse") as parser:
            path, message = worker._download_nomark_video(Mock(), OriginalDoubaoVideoEvidence(), "task")
        self.assertEqual(path, "")
        self.assertIn("Dola", message)
        parser.assert_not_called()
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola"}])
        with self.assertRaisesRegex(ValueError, "此链接需要 OriginaDoubao 账号"):
            self.api.convert_original_doubao_link("https://www.doubao.com/video-sharing?video_id=test", "global")
        self.assertEqual(self.api._account_usage, {})

    def test_switching_image_browser_to_video_keeps_new_task_reserved(self):
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola"}])
        self.api._tasks = {}
        previous = OriginalDoubaoImageWorker.__new__(OriginalDoubaoImageWorker)
        previous.visible = True
        previous.thread = Mock()
        previous.stop = lambda: self.api._worker_stopped("global", previous)
        self.api._workers = {"global": previous}
        replacement = Mock(visible=True, start_error="")
        replacement.ready = threading.Event()
        replacement.ready.set()
        self.api._ensure_worker = Mock(return_value=replacement)
        image = self.root / "fixture.png"
        image.write_bytes(b"fixture")
        result = self.api.start_generation({"accountId": "global", "imagePath": str(image), "prompt": "A landscape"})
        task = self.api._tasks[result["taskId"]]
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["accountType"], "dola")
        self.assertEqual(self.api._account_usage["global"]["ownerId"], result["taskId"])
        replacement.submit_generation.assert_called_once()

    def test_dola_link_conversion_uses_selected_account_worker_and_releases_it(self):
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola"}])
        worker = Mock(visible=True, start_error="")
        worker.ready = threading.Event()
        worker.ready.set()
        worker.submit_link_conversion.side_effect = lambda link, reply: reply.put({"success": True, "data": {"path": "original.mp4"}})
        self.api._workers = {"global": worker}
        self.assertEqual(self.api.convert_original_doubao_link("https://v16-dola.dola.com/file/video/tos/mya/video/?download=true", "global"), {"path": "original.mp4"})
        worker.submit_link_conversion.assert_called_once()
        self.assertEqual(self.api._account_usage, {})


FIXTURE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<button data-testid="user-menu">Profile</button>
<button onclick="document.querySelector('h1').hidden=false;document.querySelector('#creation').hidden=true">New Chat</button>
<h1>How can I assist you today?</h1>
<button onclick="openCreation('video')">Create Videos</button>
<button onclick="openCreation('image')">Create Images</button>
<section id="creation" hidden>
  <button>Seedance 2.0 Fast</button>
  <button onclick="document.querySelector('#settings').hidden=false">Auto · 10s</button>
  <div id="settings" hidden><button onclick="document.body.dataset.ratio='16:9'">16:9</button><input type="range" min="4" max="15" value="4"></div>
  <input type="file" accept="image/*" hidden>
  <textarea placeholder="Message Dola"></textarea>
  <button onclick="document.body.dataset.submitted=document.querySelector('textarea').value;history.replaceState({},'', '/chat/fixture-result')">Send</button>
</section>
<script>function openCreation(kind){document.body.dataset.kind=kind;document.querySelector('#creation').hidden=false;document.querySelector('h1').hidden=true}</script>
</body></html>"""


class DolaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(BUNDLED_CHROME), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.debug_path = patch("original_doubao_base.DATA_DIR", Path(self.temp.name))
        self.debug_path.start()
        self.context = self.browser.new_context()
        self.context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=FIXTURE))
        self.page = self.context.new_page()
        self.page.goto("https://www.dola.com/chat/old")
        self.api = Mock()
        self.api._find_account.return_value = {"accountType": "dola"}
        self.api.is_account_quota_exhausted_today.return_value = False

    def tearDown(self):
        self.context.close()
        self.debug_path.stop()
        self.temp.cleanup()

    def test_dola_original_parser_uses_current_browser_login_cookie(self):
        video_id = "v186a3gm000cdb1lgrvog65sait4etb0"
        self.context.add_cookies([{"name": "sessionid", "value": "fixture-only", "url": "https://www.dola.com", "httpOnly": True}])
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        evidence = OriginalDoubaoVideoEvidence()
        evidence.add(video_id)
        parser = AsyncMock(return_value=[{"url": "https://cdn.test/original.mp4"}])
        with patch("original_doubao_video_worker.dola_video_parse", parser), \
             patch("original_doubao_video_worker.original_doubao_fplay_parse") as domestic:
            videos = worker._resolve_nomark_in_logged_in_page(self.page, evidence)
        self.assertEqual(videos[0]["url"], "https://cdn.test/original.mp4")
        self.assertEqual(parser.call_args.args, ([video_id], {"sessionid": "fixture-only"}))
        domestic.assert_not_called()

    def test_video_preparation_and_submission_in_english_page(self):
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "fixture.png"
            image.write_bytes(b"fixture-image")
            with patch.object(self.page, "wait_for_timeout"), patch.object(worker, "_monitor_result") as monitor:
                worker._generate(self.page, "task", {"prompt": "A moving landscape", "imagePath": str(image), "ratio": "16:9", "duration": 10})
            self.assertTrue(monitor.called, self.api._update_task.call_args_list)
            self.assertEqual(self.page.locator("body").get_attribute("data-submitted"),
                             f"A moving landscape\n\n{ORIGINAL_DOUBAO_MATERIAL_PLEDGE}")
            self.assertEqual(self.page.locator("body").get_attribute("data-ratio"), "16:9")
            self.assertEqual(self.page.locator('input[type="range"]').input_value(), "10")
            self.assertEqual(self.page.locator('input[type="file"]').evaluate("el => el.files.length"), 1)
            self.assertEqual(self.page.url, "https://www.dola.com/chat/fixture-result")

    def test_image_preparation_and_submission_in_english_page(self):
        worker = OriginalDoubaoImageWorker(self.api, "global", False)
        with patch.object(self.page, "wait_for_timeout"), patch.object(worker, "_monitor_image_result") as monitor:
            worker._generate_image(self.page, "task", {"prompt": "A landscape"})
        monitor.assert_called_once()
        self.assertEqual(self.page.locator("body").get_attribute("data-kind"), "image")
        self.assertEqual(self.page.locator("body").get_attribute("data-submitted"), "A landscape")

    def test_video_submission_with_chinese_and_english_separate_dropdowns(self):
        for language, new_chat, welcome, creation, video, model, ratio in [
            ("zh", "新对话", "有什么我能帮你的吗？", "AI 创作", "视频生成", "模型", "比例"),
            ("en", "New Chat", "How can I help you today?", "AI Creation", "Create Videos", "Model", "Ratio"),
        ]:
            with self.subTest(language=language):
                self.page.set_content(f'''<img data-testid="chat_header_avatar_button" style="width:36px;height:36px">
                <button onclick="document.querySelector('h1').hidden=false">{new_chat}</button><h1>{welcome}</h1>
                <button onclick="document.querySelector('#video-entry').hidden=false">{creation}</button>
                <button id="video-entry" hidden onclick="document.querySelector('#editor').hidden=false;document.querySelector('h1').hidden=true">{video}</button>
                <section id="editor" hidden>
                  <div onclick="document.querySelector('#models').hidden=false">{model} 2.5</div>
                  <div id="models" hidden><button onclick="document.body.dataset.model='fast';this.parentElement.hidden=true">Dreamina Seedance 2.0 Fast</button></div>
                  <button onclick="document.querySelector('#ratios').hidden=false">{ratio}</button>
                  <div id="ratios" hidden><button onclick="document.body.dataset.ratio='16:9';this.parentElement.hidden=true">16:9</button></div>
                  <button onclick="document.querySelector('#durations').hidden=false">5s</button>
                  <div id="durations" hidden><button onclick="document.body.dataset.duration='10';this.parentElement.hidden=true">10s</button></div>
                  <input type="file" accept="image/*" hidden><textarea placeholder="描述你想要的视频"></textarea>
                  <button id="flow-end-msg-send" onclick="document.body.dataset.submitted=document.querySelector('textarea').value;history.replaceState({{}},'', '/chat/result-{language}')"></button>
                </section>''')
                worker = OriginalDoubaoVideoWorker(self.api, "global", False)
                image = Path(self.temp.name) / "fixture.png"
                image.write_bytes(b"fixture")
                with patch.object(self.page, "wait_for_timeout"), patch.object(worker, "_monitor_result") as monitor:
                    worker._generate(self.page, "task", {"prompt": "A landscape", "imagePath": str(image), "ratio": "16:9", "duration": 10})
                self.assertTrue(monitor.called, self.api._update_task.call_args_list)
                for key, expected in [("model", "fast"), ("ratio", "16:9"), ("duration", "10"),
                                      ("submitted", f"A landscape\n\n{ORIGINAL_DOUBAO_MATERIAL_PLEDGE}")]:
                    self.assertEqual(self.page.locator('body').get_attribute(f'data-{key}'), expected)

    def test_dola_separate_duration_slider_uses_its_actual_minimum(self):
        self.page.set_content('''<button onclick="document.querySelector('#ratios').hidden=false">Ratio</button>
          <div id="ratios" hidden><button onclick="this.parentElement.hidden=true">16:9</button></div>
          <button onclick="document.querySelector('input').hidden=false">5s</button>
          <input type="range" min="5" max="10" value="5" hidden>''')
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        with patch.object(self.page, "wait_for_timeout"):
            worker._configure_video(self.page, "16:9", 10)
        self.assertEqual(self.page.locator('input').input_value(), "10")

    def test_video_result_is_saved_without_calling_domestic_parser(self):
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        self.api.get_settings.return_value = {"autoDownload": True}
        self.api._webview_preview_path.side_effect = lambda path: path
        self.api._media_url_for.return_value = "http://127.0.0.1/fixture.mp4"
        self.page.evaluate("() => {const video = document.createElement('video'); video.src = 'https://www.dola.com/video/tos/fixture.mp4'; document.body.append(video)}")
        result_path = Path(self.temp.name) / "fixture.mp4"
        result_path.write_bytes(b"fixture-video")
        with patch.object(self.page, "wait_for_timeout"), patch.object(worker, "_video_id_from_media_url", return_value=""), \
             patch.object(worker, "_save_media_url", return_value=result_path), \
             patch.object(worker, "_resolve_nomark_in_logged_in_page", return_value=[]), \
             patch("original_doubao_video_worker.original_doubao_video_parse") as parser:
            worker._monitor_result(self.page, "task", 0, set(), OriginalDoubaoVideoEvidence(),
                                   OriginalDoubaoVideoEvidence(), (lambda _: None, lambda _: None), {}, {})
        parser.assert_not_called()
        result = self.api._update_task.call_args.kwargs
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["resultPath"], str(result_path))
        self.assertTrue(result["resultWatermarked"])

    def test_dola_submitted_zero_balance_recognizes_both_languages(self):
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        chinese = ('Dola 本次使用 **Seedance 2.0 Fast** 生成，将消耗 2 个视频生成额度，预计等待 5 分钟。'
                   '视频生成好后，我会主动发送给你，今日剩余 0 个视频生成额度。')
        english = ("Video generation has been submitted using Seedance 2.0 Fast. Estimated wait: 5 minutes. "
                   "I'll send you the video when it's ready. You have 0 video generation credits remaining today.")
        for text, expected in [(chinese, True), (english, True),
                               ("Video generation has been submitted. Today's remaining video generation credits: 0.", True),
                               (chinese.replace("剩余 0", "剩余 2"), False),
                               (english.replace("0 video", "10 video"), False),
                               ("今日剩余 0 个视频生成额度，无法提交视频", False),
                               ("0 video generation credits remaining today. Cannot submit video.", False)]:
            with self.subTest(text=text):
                self.page.set_content(f'<div data-message-author-role="assistant">{text}</div>')
                self.assertEqual(worker._dola_generation_reports_zero_quota(self.page), expected)
        self.page.set_content(f'<p>{chinese}</p>')
        self.assertTrue(worker._dola_generation_reports_zero_quota(self.page))
        self.page.set_content(f'<div data-message-author-role="user">{chinese}</div>')
        self.assertFalse(worker._dola_generation_reports_zero_quota(self.page))
        self.page.set_content(f'<div data-message-author-role="assistant">{chinese}</div>'
                              f'<div data-message-author-role="assistant">{chinese.replace("剩余 0", "剩余 2")}</div>')
        self.assertFalse(worker._dola_generation_reports_zero_quota(self.page))
        self.api._find_account.return_value = {"accountType": "doubao"}
        domestic = OriginalDoubaoVideoWorker(self.api, "cn", False)
        self.page.set_content(f'<p>{chinese}</p>')
        self.assertFalse(domestic._dola_generation_reports_zero_quota(self.page))

    def test_dola_zero_balance_waits_for_video_and_download_instead_of_aborting(self):
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        self.page.set_content('<div data-message-author-role="assistant">视频生成好后，我会主动发送给你，'
                              '今日剩余 0 个视频生成额度。</div>')
        self.api.get_settings.return_value = {"autoDownload": True}
        self.api._webview_preview_path.side_effect = lambda path: path
        result_path = Path(self.temp.name) / "fixture.mp4"
        result_path.write_bytes(b"fixture-video")
        ticks = 0
        def advance(_):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                self.api.mark_account_quota_exhausted.assert_not_called()
                self.assertFalse(any(call.kwargs.get("quotaExhaustedAfterGeneration")
                                     for call in self.api._update_task.call_args_list))
                # The acknowledgement may disappear; keep its balance latched.
                self.page.set_content('<video src="https://www.dola.com/video/tos/fixture.mp4"></video>')
        def download(*args, **kwargs):
            self.api.mark_account_quota_exhausted.assert_not_called()
            self.assertNotIn("succeeded", [call.kwargs.get("status") for call in self.api._update_task.call_args_list])
            return result_path, "视频已保存"
        with patch.object(self.page, "wait_for_timeout", side_effect=advance), \
             patch.object(worker, "_video_id_from_media_url", return_value=""), \
             patch.object(worker, "_download_nomark_video", side_effect=download):
            worker._monitor_result(self.page, "task", 0, set(), OriginalDoubaoVideoEvidence(),
                                   OriginalDoubaoVideoEvidence(), (lambda _: None, lambda _: None), {}, {})
        self.assertGreaterEqual(ticks, 2)
        zero_update = next(call.kwargs for call in self.api._update_task.call_args_list
                           if call.kwargs.get("quotaExhaustedAfterGeneration"))
        self.assertEqual(zero_update["status"], "sharing")
        self.assertEqual(self.api._update_task.call_args.kwargs["status"], "succeeded")
        self.assertEqual(self.api._update_task.call_args.kwargs["resultPath"], str(result_path))

    def test_dola_zero_acknowledgement_without_video_does_not_commit_exhaustion(self):
        worker = OriginalDoubaoVideoWorker(self.api, "global", False)
        self.page.set_content('<p>视频生成好后，我会主动发送给你，今日剩余 0 个视频生成额度。</p>')
        with patch.object(self.page, "wait_for_timeout", side_effect=[None, RuntimeError("浏览器中断")]):
            with self.assertRaisesRegex(RuntimeError, "浏览器中断"):
                worker._monitor_result(self.page, "task", 0, set(), OriginalDoubaoVideoEvidence(),
                                       OriginalDoubaoVideoEvidence(), (lambda _: None, lambda _: None), {}, {})
        self.api.mark_account_quota_exhausted.assert_not_called()
        self.assertFalse(any(call.kwargs.get("quotaExhaustedAfterGeneration")
                             for call in self.api._update_task.call_args_list))

    def test_text_generation_confirmation_variants_and_latest_reply(self):
        for account_type in ("doubao", "dola"):
            self.api._find_account.return_value = {"accountType": account_type}
            worker = OriginalDoubaoVideoWorker(self.api, "fixture", False)
            for text in (
                "确认后我再开始生成视频",
                "你确认后，我再开始生成视频。",
                "**确认后**\n我再开始生成视频。",
                "请回复“确认”，我将开始生成视频。",
                "Please reply to confirm video generation.",
            ):
                with self.subTest(account_type=account_type, text=text):
                    self.page.set_content('<div data-message-author-role="assistant"></div>')
                    self.page.locator('[data-message-author-role="assistant"]').evaluate(
                        '(element, text) => element.textContent = text', text,
                    )
                    self.assertTrue(worker._generation_confirmation_requested(self.page))
            self.page.set_content('<div data-message-author-role="user">确认后我再开始生成视频</div>')
            self.assertFalse(worker._generation_confirmation_requested(self.page))
            self.page.set_content('<div data-message-author-role="assistant">确认后我再开始生成视频</div>'
                                  '<div data-message-author-role="assistant">视频已开始生成，无需确认。</div>')
            self.assertFalse(worker._generation_confirmation_requested(self.page))

    def test_doubao_text_confirmation_is_sent_once_then_waits_for_video(self):
        self.api._find_account.return_value = {"accountType": "doubao"}
        worker = OriginalDoubaoVideoWorker(self.api, "fixture", False)
        self.page.goto("https://www.doubao.com/chat/fixture")
        self.page.set_content('<div data-message-author-role="assistant">确认后我再开始生成视频</div>'
                              '<textarea></textarea><button onclick="document.body.dataset.reply = '
                              'document.querySelector(\'textarea\').value; '
                              'document.body.dataset.sends = Number(document.body.dataset.sends || 0) + 1">发送</button>')
        self.api.get_settings.return_value = {"autoDownload": False}
        evidence = OriginalDoubaoVideoEvidence()
        evidence.add('{"video_id":"fixture-video"}')
        ticks = 0

        def advance(_):
            nonlocal ticks
            ticks += 1
            if ticks == 3:
                self.page.evaluate("() => {const video = document.createElement('video'); document.body.append(video)}")

        with patch.object(self.page, "wait_for_timeout", side_effect=advance), \
             patch.object(worker, "_download_nomark_video", return_value=("", "视频已生成")):
            worker._monitor_result(self.page, "task", 0, set(), evidence,
                                   OriginalDoubaoVideoEvidence(), (lambda _: None, lambda _: None), {}, {})
        self.assertEqual(self.page.evaluate("document.body.dataset.reply"), "我确认开始生成视频")
        self.assertEqual(self.page.evaluate("document.body.dataset.sends"), "1")
        self.assertEqual(self.api._update_task.call_args.kwargs["status"], "succeeded")

    def test_confirmation_and_quota_messages_are_detected(self):
        worker = BaseAccountBrowserWorker(self.api, "global", False)
        self.page.set_content('<button data-testid="user-menu">Profile</button><div role="dialog">Confirm video generation<button>Confirm</button></div>')
        self.assertTrue(worker._has_visible_generation_confirmation_dialog(self.page))
        self.page.set_content('<button data-testid="user-menu">Profile</button><p>Not enough credits</p>')
        reason, manual = worker._generation_block_reason(self.page)
        self.assertTrue(worker._is_quota_exhausted_reason(reason))
        self.assertFalse(manual)

    def test_dola_sidebar_avatar_updates_login_status_without_session_cookie(self):
        worker = BaseAccountBrowserWorker(self.api, "global", False)
        self.page.set_content('<aside style="position:fixed;bottom:0;left:0">'
                              '<img data-testid="chat_header_avatar_button" class="rounded-full object-cover" '
                              'style="width:36px;height:36px"><span>Apple User453763697</span></aside>')
        worker._refresh_authentication(self.context)
        self.assertTrue(worker.authenticated)
        result = worker._check_login(self.context, self.page)
        self.assertTrue(result["loggedIn"])
        self.assertEqual(result["pageState"], "avatar")
        self.assertFalse(result["hasSessionCookie"])

    def test_dola_sidebar_avatar_is_ignored_when_hidden_or_on_domestic_account(self):
        worker = BaseAccountBrowserWorker(self.api, "global", False)
        self.page.set_content('<img data-testid="chat_header_avatar_button" '
                              'style="width:36px;height:36px;visibility:hidden">')
        self.assertIsNone(worker._detect_login_state(self.page))
        self.page.locator('img').evaluate("el => el.style.visibility = 'visible'")
        self.api._find_account.return_value = {"accountType": "doubao"}
        domestic = BaseAccountBrowserWorker(self.api, "cn", False)
        self.assertIsNone(domestic._detect_login_state(self.page))

    def test_login_entry_overrides_stale_cookie_and_unknown_state_is_not_success(self):
        worker = BaseAccountBrowserWorker(self.api, "global", False)
        self.context.add_cookies([{"name": "sessionid", "value": "stale-fixture", "url": "https://www.dola.com"}])
        self.page.set_content('<button>Log In</button><span class="avatar">Avatar</span>'
                              '<img data-testid="chat_header_avatar_button" style="width:36px;height:36px">')
        result = worker._check_login(self.context, self.page)
        self.assertFalse(result["loggedIn"])
        self.assertTrue(result["hasSessionCookie"])
        with patch.object(worker, "_detect_login_state", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "尚未确认登录状态"):
                worker._check_login(self.context, self.page)


if __name__ == "__main__":
    unittest.main()
