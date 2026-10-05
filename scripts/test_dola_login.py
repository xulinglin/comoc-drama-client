"""人工登录进程、profile 交接和账号锁；只使用本地测试页面。"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import sync_playwright

from constants import BUNDLED_CHROME
from dola_login import DolaLoginBrowser, launch_dola_login, resolve_dola_browser
from launcher import DesktopApi
from original_doubao_base import BaseAccountBrowserWorker


class DolaLoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = patch.multiple("launcher", ACCOUNTS_DIR=self.root / "accounts",
                                    ACCOUNTS_FILE=self.root / "accounts.json", DATA_DIR=self.root)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.api = DesktopApi.__new__(DesktopApi)
        self.api._lock = threading.Lock()
        self.api._workers, self.api._tasks, self.api._account_usage = {}, {}, {}
        self.api._login_browsers, self.api._finishing_logins = {}, set()
        self.api._session_probe_cache, self.api._login_expired = {}, {}
        self.api._accounts_read_cache = (0.0, [])
        self.api._storage_available = lambda: False
        self.api._ensure_cloud_accounts_synced = Mock()
        self.api._push_cloud_account_state = Mock()
        self.api._pull_cloud_account_quota = Mock()
        self.api.get_settings = lambda: {"dailyVideoQuota": 3, "dolaDailyVideoQuota": 4}
        self.api._write_accounts([{"id": "global", "name": "国际", "accountType": "dola"},
                                  {"id": "cn", "name": "国内"}])

    def test_dola_launch_does_not_start_worker_and_duplicate_open_reuses_window(self):
        with patch("launcher.launch_dola_login") as launch, patch.object(self.api, "_ensure_worker") as worker:
            self.assertEqual(self.api.open_account_login("global")["status"], "manual")
            self.assertEqual(self.api.open_account_login("global")["status"], "manual")
            launch.assert_called_once_with(self.root / "accounts/global/profile", "https://www.dola.com/chat")
            worker.assert_not_called()
        self.api._has_saved_original_doubao_session = Mock(return_value=True)
        pending = self.api.list_accounts()[0]
        self.assertTrue(pending["manualLoginPending"])
        self.assertFalse(pending["authenticated"])
        self.assertFalse(pending.get("hasLoggedIn", False))

    def test_generation_check_and_delete_cannot_touch_pending_profile(self):
        self.api._login_browsers["global"] = Mock()
        for operation in (lambda: self.api._acquire_account_usage("global", "task", "video"),
                          lambda: self.api._ensure_worker("global", False),
                          lambda: self.api.check_account_login("global"),
                          lambda: self.api.delete_account("global")):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "完成.*登录"):
                operation()
        with self.assertRaisesRegex(ValueError, "运行中"):
            self.api._acquire_available_generation_account("global", "task", "dola")
        self.assertEqual(self.api._acquire_available_generation_account("", "task")["id"], "cn")

    def test_busy_or_slow_worker_prevents_manual_launch(self):
        with patch("launcher.launch_dola_login") as launch:
            self.api._account_usage["global"] = {"ownerId": "task"}
            with self.assertRaisesRegex(ValueError, "运行中"):
                self.api.open_account_login("global")
            self.api._account_usage.clear()
            worker = Mock()
            worker.thread.is_alive.return_value = True
            self.api._workers["global"] = worker
            with self.assertRaisesRegex(RuntimeError, "正在关闭"):
                self.api.open_account_login("global")
            launch.assert_not_called()
        self.assertEqual(self.api._login_browsers, {})

    def test_startup_failure_releases_login_reservation(self):
        with patch("launcher.launch_dola_login", side_effect=RuntimeError("Chrome 未能启动")):
            with self.assertRaisesRegex(RuntimeError, "未能启动"):
                self.api.open_account_login("global")
        self.assertEqual(self.api._login_browsers, {})

    def test_completion_closes_before_checking_clears_stale_cache_and_persists_success(self):
        browser = Mock()
        self.api._login_browsers["global"] = browser
        cache = self.api._account_cookie_cache_path("global")
        cache.parent.mkdir(parents=True)
        cache.write_text('"stale"')

        def verify(account_id, token, *, completing_login):
            browser.close.assert_called_once()
            self.assertFalse(cache.exists())
            self.assertTrue(completing_login)
            with self.assertRaisesRegex(ValueError, "正在确认"):
                self.api.complete_account_login(account_id)
            with self.assertRaisesRegex(ValueError, "完成.*登录"):
                self.api._acquire_account_usage(account_id, "task", "video")
            return {"loggedIn": True, "method": "browser"}

        with patch.object(self.api, "_check_account_login", side_effect=verify):
            result = self.api.complete_account_login("global")
        self.assertTrue(result["loggedIn"])
        self.assertTrue(self.api._find_account("global")["hasLoggedIn"])
        self.assertEqual(self.api._login_browsers, {})
        self.assertEqual(self.api._finishing_logins, set())

    def test_failed_login_never_marks_account_authenticated(self):
        self.api._login_browsers["global"] = Mock()
        with patch.object(self.api, "_check_account_login", return_value={"loggedIn": False}):
            result = self.api.complete_account_login("global")
        self.assertFalse(result["loggedIn"])
        self.assertFalse(self.api._find_account("global").get("hasLoggedIn", False))
        self.assertEqual(self.api._login_browsers, {})

    def test_close_timeout_retains_window_for_retry_without_starting_automation(self):
        browser = Mock()
        browser.close.side_effect = RuntimeError("请手动关闭")
        self.api._login_browsers["global"] = browser
        with patch.object(self.api, "_check_account_login") as check:
            with self.assertRaisesRegex(RuntimeError, "手动关闭"):
                self.api.complete_account_login("global")
            check.assert_not_called()
        self.assertIs(self.api._login_browsers["global"], browser)
        self.assertEqual(self.api._finishing_logins, set())

    def test_completion_uses_browser_check_and_retires_temporary_worker(self):
        browser = Mock()
        browser.process.poll.return_value = 0
        self.api._login_browsers["global"] = browser
        worker = Mock(start_error="")
        worker.ready.wait.return_value = True
        worker.thread.is_alive.return_value = False
        worker.submit_check_login.side_effect = lambda reply: reply.put({"success": True, "data": {
            "loggedIn": True, "hasSessionCookie": True, "url": "https://www.dola.com/chat"}})
        with patch.object(self.api, "_ensure_worker", return_value=worker), \
             patch.object(self.api, "_http_check_login") as http:
            result = self.api.complete_account_login("global")
        self.assertEqual(result["method"], "browser")
        http.assert_not_called()
        worker.stop.assert_called_once()
        worker.thread.join.assert_called_once()

    def test_domestic_login_keeps_existing_worker_flow(self):
        self.api._workers["cn"] = Mock(visible=True)
        self.api._bring_main_window_to_foreground = Mock()
        self.api._set_login_expired = Mock()
        with patch("launcher.launch_dola_login") as launch:
            self.assertEqual(self.api.open_account_login("cn")["status"], "running")
            launch.assert_not_called()
        with self.assertRaisesRegex(ValueError, "仅适用于 Dola"):
            self.api.complete_account_login("cn")


class BrowserHandoffTests(unittest.TestCase):
    def test_worker_uses_the_executable_saved_by_manual_login(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "local-chrome.exe"
            executable.write_bytes(b"fixture")
            profile = root / "global/profile"
            profile.mkdir(parents=True)
            (profile / "login_browser.json").write_text(json.dumps({"executablePath": str(executable)}))
            api = Mock()
            api._find_account.return_value = {"accountType": "dola"}
            worker = BaseAccountBrowserWorker(api, "global", False)
            page = Mock(url="https://www.dola.com/chat")
            page.evaluate.return_value = "login"
            context = Mock(pages=[page])
            context.cookies.return_value = []
            worker.stop()
            with patch("original_doubao_base.ACCOUNTS_DIR", root), \
                 patch("original_doubao_base.sync_playwright") as factory:
                browser = factory.return_value.start.return_value
                browser.chromium.launch_persistent_context.return_value = context
                worker._run()
            options = browser.chromium.launch_persistent_context.call_args.kwargs
            self.assertEqual(options["executable_path"], str(executable.resolve()))
            self.assertEqual(options["user_data_dir"], str(profile.resolve()))

    def test_launch_has_no_automation_or_debugging_flags_and_records_executable(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch("dola_login.resolve_dola_browser", return_value=BUNDLED_CHROME.resolve()), \
             patch("dola_login.subprocess.Popen") as popen:
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired("chrome", 1)
            profile = Path(temp) / "profile"
            launch_dola_login(profile, "https://www.dola.com/chat")
            args = popen.call_args.args[0]
            self.assertFalse(any("automation" in arg or "remote-debugging" in arg for arg in args))
            self.assertNotIn("--no-sandbox", args)
            self.assertIn(f"--user-data-dir={profile.resolve()}", args)
            self.assertEqual(resolve_dola_browser(profile), BUNDLED_CHROME.resolve())
            saved = profile / "login_browser.json"
            saved.write_text(json.dumps({"executablePath": str(profile / "missing.exe")}))
            with self.assertRaisesRegex(RuntimeError, "重新打开登录"):
                resolve_dola_browser(profile)

    @unittest.skipUnless(BUNDLED_CHROME.is_file(), "requires bundled Chrome")
    def test_manual_browser_flushes_http_only_cookie_and_playwright_reuses_profile(self):
        loaded = threading.Event()

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Set-Cookie", "sessionid=dola-fixture; Max-Age=3600; HttpOnly; Path=/")
                self.end_headers()
                self.wfile.write(b"<html><title>Local login fixture</title>Login fixture</html>")
                loaded.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
                profile = Path(temp) / "profile"
                executable = resolve_dola_browser(profile, for_login=True)
                url = f"http://127.0.0.1:{server.server_port}/"
                popen = subprocess.Popen
                log_path = Path(temp) / "chrome.log"

                def launch_offscreen(args, **kwargs):
                    # 内置测试内核在此 runner 中需要与 Playwright 相同的沙箱设置。
                    # 本机正式 Chrome 和产品的人工登录启动均不添加此参数。
                    flags = ["--no-sandbox"] if executable == BUNDLED_CHROME.resolve() else []
                    with log_path.open("w", encoding="utf-8") as log:
                        return popen([*args, "--window-position=-32000,-32000", "--enable-logging=stderr", *flags],
                                     stdout=log, stderr=log)

                with patch("dola_login.subprocess.Popen", side_effect=launch_offscreen):
                    login = launch_dola_login(profile, url)
                try:
                    self.assertTrue(loaded.wait(20), f"manual Chrome exit={login.process.poll()}: "
                                    + log_path.read_text(encoding="utf-8", errors="replace")[-3000:])
                    time.sleep(1)
                    login.close()
                    self.assertIsNotNone(login.process.poll())
                    with sync_playwright() as playwright:
                        context = playwright.chromium.launch_persistent_context(
                            str(profile), executable_path=str(resolve_dola_browser(profile)), headless=False,
                            args=["--window-position=-32000,-32000"],
                        )
                        try:
                            cookies = context.cookies([url])
                            self.assertTrue(any(c["name"] == "sessionid" and c["value"] == "dola-fixture"
                                                and c["httpOnly"] for c in cookies))
                        finally:
                            context.close()
                finally:
                    login.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
