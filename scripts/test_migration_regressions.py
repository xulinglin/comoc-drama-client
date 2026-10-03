"""Python migration contracts. All providers and user storage are isolated fixtures."""
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from local_storage import LocalStorageServer


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, body, content_type="application/json", status=200):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.requests.append((self.path, dict(self.headers),
                                     json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        if self.path.endswith("/voice_design"):
            self.respond(self.server.audio)
        elif self.path.endswith("/tasks"):
            self.respond({"id": "task-1", "status": "queued"})
        elif self.path.endswith("/messages"):
            self.respond({"content": [{"type": "text", "text": "测试回复"}]})
        else:
            self.respond({"choices": [{"message": {"content": "测试回复"}}]})

    def do_GET(self):
        self.server.downloads.append((self.path, self.headers.get("Authorization")))
        if self.path.endswith("/task-1"):
            self.respond(self.server.video)
        elif self.path.endswith(".png"):
            self.respond(self.server.png, "image/png")
        else:
            self.respond(b"\x00\x00\x00\x18ftypmp42fixture\r\n", "video/mp4")


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.provider.server_port}"
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(image, "PNG")
        cls.provider.png = image.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.provider.shutdown()
        cls.provider.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = LocalStorageServer(self.root / "storage", port=0)
        self.server.start()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.server._server.server_port}", trust_env=False)
        self.provider.requests = []
        self.provider.downloads = []
        self.provider.audio = {"voice_id": "voice-1", "trial_audio": b"ID3test-audio\r\n".hex(),
                               "base_resp": {"status_code": 0}}
        self.provider.video = {"id": "task-1", "status": "running"}

    def tearDown(self):
        self.client.close()
        self.server.stop()
        self.temp.cleanup()

    def model(self, model_type, provider, suffix):
        return self.server.storage.create_document("ai_models", {
            "name": "测试模型", "modelType": model_type, "provider": provider, "modelName": "real-api-model",
            "apiUrl": self.url + suffix, "apiKey": "fixture-private-key", "enabled": True,
        })

    def post(self, path, body):
        return self.client.post(path, json=body).json()

    def test_account_document_envelope_and_revision_conflicts(self):
        path = "/api/storage/data/account/account-1"
        created = self.client.put(path, json={"data": {"id": "account-1", "name": "账号"},
                                             "expectedRevision": 0}).json()
        self.assertEqual(created["data"]["name"], "账号")
        self.assertEqual(created["revision"], 1)
        self.assertEqual(self.client.get("/api/storage/data/account").json()[0]["id"], "account-1")
        self.assertEqual(self.client.get(path).json()["namespace"], "account")
        self.assertEqual(self.client.put(path, json={"data": {}, "expectedRevision": 0}).status_code, 409)
        self.assertEqual(self.client.delete(path + "?expectedRevision=0").status_code, 409)
        self.assertEqual(self.client.delete(path + "?expectedRevision=1").status_code, 204)
        self.assertEqual(self.client.get("/api/storage/data/account").json(), [])

    def test_desktop_account_cache_restores_from_database(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._storage_available = lambda: True
        api._storage_request = self.client.request
        with patch.multiple("launcher", DATA_DIR=self.root, ACCOUNTS_FILE=self.root / "accounts.json",
                            SETTINGS_FILE=self.root / "settings.json"):
            api._write_accounts([{"id": "first", "name": "第一"}, {"id": "second", "name": "第二"}])
            (self.root / "accounts.json").unlink()
            self.assertEqual([item["id"] for item in api._read_accounts()], ["first", "second"])
            api._write_accounts([{"id": "second", "name": "改名"}])
            records = self.client.get("/api/storage/data/account").json()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["data"]["name"], "改名")

    def test_sqlite_connections_close_after_reads_and_writes(self):
        storage = self.server.storage
        connect = storage._connect
        connections = []
        def tracked():
            connection = connect()
            connections.append(connection)
            return connection
        with patch.object(storage, "_connect", side_effect=tracked):
            storage.create_document("projects", {"name": "测试"})
            storage.list_documents("projects")
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_file_upload_preserves_binary_crlf_and_custom_bucket(self):
        content = b"\r\n\x00binary\r\n--not-boundary\r\n"
        result = self.client.post("/file/upload", files={"file": ("test.mp4", content, "video/mp4")},
                                  data={"bucket": "custom"}).json()["data"]
        self.assertEqual(result["bucket"], "custom")
        response = self.client.get(result["url"])
        self.assertEqual(response.content, content)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_asset_upload_persists_fields_and_project_bindings(self):
        result = self.client.post("/asset/upload", files={"file": ("orig.png", self.provider.png, "image/png")},
                                  data={"name": "人物一", "description": "描述", "tags": "主角", "type": "role",
                                        "duration": "5", "boundProjectIds": ["project-1", "project-2"]}).json()["data"]
        saved = self.server.storage.get_document("assets", result["id"])
        self.assertEqual(saved["name"], "人物一")
        self.assertEqual(saved["description"], "描述")
        self.assertEqual(saved["tags"], "主角")
        self.assertEqual(saved["type"], "role")
        self.assertEqual(saved["duration"], "5")
        self.assertEqual(saved["boundProjectIds"], ["project-1", "project-2"])

    def test_batch_upload_saves_every_file(self):
        result = self.client.post("/asset/upload/batch", files=[
            ("files", ("a.png", self.provider.png, "image/png")),
            ("files", ("b.mp3", b"ID3audio\r\n", "audio/mpeg")),
        ], data={"tags": "批量"}).json()["data"]
        self.assertEqual(len(result), 2)
        self.assertEqual({item["name"] for item in result}, {"a", "b"})
        self.assertEqual(len(self.server.storage.list_documents("assets")), 2)
        self.assertEqual({item["type"] for item in result}, {"image", "audio"})

    def test_empty_batch_reports_error(self):
        self.assertNotEqual(self.post("/asset/upload/batch", {})["code"], 200)

    def test_file_head_ranges_and_unsatisfiable_range(self):
        content = b"0123456789"
        file = self.server.storage.save_file("files", content, "video.mp4", "video/mp4")
        url = f"/file/{file['id']}/download"
        head = self.client.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(head.headers["Content-Length"], "10")
        for header, expected in [("bytes=2-5", b"2345"), ("bytes=7-", b"789"), ("bytes=-3", b"789")]:
            response = self.client.get(url, headers={"Range": header})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, expected)
        invalid = self.client.get(url, headers={"Range": "bytes=20-"})
        self.assertEqual(invalid.status_code, 416)
        self.assertEqual(invalid.headers["Content-Range"], "bytes */10")

    def test_quota_consumes_and_resets_on_new_day(self):
        first = self.post("/desktop/account-quota/consume", {"accountId": "a", "dailyLimit": 5})["data"]
        self.assertEqual(first["generatedCount"], 1)
        self.assertEqual(first["dailyLimit"], 5)
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 1)
        self.server.storage.update_document("desktop_account_quota", "a", {"date": "2000-01-01"})
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 0)
        next_day = self.post("/desktop/account-quota/consume", {"accountId": "a"})["data"]
        self.assertEqual(next_day["generatedCount"], 1)
        self.assertEqual(next_day["dailyLimit"], 5)

    def test_concurrent_quota_consumption_is_not_lost(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.post("/desktop/account-quota/consume", {"accountId": "a"}), range(4)))
        self.assertTrue(all(result["code"] == 200 for result in results))
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 4)

    def test_shared_prompt_filter_and_limit(self):
        self.server.storage.create_document("prompts", {"title": "私有", "shared": False})
        self.server.storage.create_document("prompts", {"title": "共享", "shared": True})
        shared = self.client.get("/prompt/list?scope=shared").json()["data"]
        self.assertEqual([item["title"] for item in shared], ["共享"])
        self.assertEqual(len(self.client.get("/prompt/list?scope=mine").json()["data"]), 2)
        self.assertEqual(len(self.client.get("/prompt/list?limit=1").json()["data"]), 1)

    def test_minimax_audio_decoded_saved_and_previewed(self):
        self.model("audio", "MiniMax", "/v1/voice_design")
        result = self.post("/ai/audio", {"prompt": "温柔女声", "preview_text": "你好"})
        self.assertEqual(result["code"], 200, result)
        data = result["data"]
        self.assertEqual(data["voice_id"], "voice-1")
        response = self.client.get(data["content"])
        self.assertEqual(response.content, b"ID3test-audio\r\n")
        self.assertEqual(response.headers["Content-Type"], "audio/mpeg")
        self.assertEqual(self.provider.requests[0][2], {"prompt": "温柔女声", "preview_text": "你好"})

    def test_audio_error_does_not_save_fake_file(self):
        self.model("audio", "MiniMax", "/v1/voice_design")
        self.provider.audio = {"base_resp": {"status_code": 1004, "status_msg": "余额不足"}}
        result = self.post("/ai/audio", {"prompt": "女声", "preview_text": "你好"})
        self.assertIn("余额不足", result["message"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(list((self.server.storage.root / "files").glob("**/content.bin")), [])

    def test_audio_invalid_hex_and_preview_length(self):
        self.model("audio", "MiniMax", "/v1")
        self.provider.audio = {"trial_audio": "invalid"}
        self.assertIn("十六进制", self.post("/ai/audio", {"prompt": "女声", "preview_text": "你好"})["message"])
        self.provider.requests = []
        self.assertIn("500", self.post("/ai/audio", {"prompt": "女声", "preview_text": "a" * 501})["message"])
        self.assertEqual(self.provider.requests, [])

    def test_seedance_submit_and_running_status(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        result = self.post("/ai/video", {"model": model["id"], "content": [{"type": "text", "text": "描述"}],
                                         "duration": 5, "generate_audio": False})
        self.assertEqual(result["data"]["taskId"], "task-1")
        self.assertEqual(self.provider.requests[0][2]["model"], "real-api-model")
        self.assertFalse(self.provider.requests[0][2]["generate_audio"])
        status = self.client.get(f"/ai/video/task-1?model={model['id']}").json()["data"]
        self.assertEqual(status["status"], "running")

    def test_seedance_completion_downloads_and_cache_survives_storage_reload(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        self.provider.video = {"id": "task-1", "status": "succeeded",
                               "content": {"video_url": self.url + "/video.mp4", "last_frame_url": self.url + "/frame.png"}}
        path = f"/ai/video/task-1?model={model['id']}"
        result = self.client.get(path).json()["data"]
        self.assertTrue(result["video_url"].startswith("/file/local_"))
        self.assertTrue(result["last_frame_url"].startswith("/file/local_"))
        self.assertEqual(result["content"]["video_url"], result["video_url"])
        self.assertEqual(self.client.get(result["last_frame_url"]).content, self.provider.png)
        self.assertIsNone(self.provider.downloads[1][1])
        self.assertIsNone(self.provider.downloads[2][1])
        from local_storage import LocalStorage
        self.server.storage = LocalStorage(self.server.storage.root)
        self.server._server.RequestHandlerClass.storage = self.server.storage
        self.assertEqual(self.client.get(path).json()["data"], result)
        self.assertEqual(len(self.provider.downloads), 3)

    def test_terminal_video_error_returns_task_not_transport_failure(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        for status in ["failed", "expired"]:
            self.provider.video = {"status": status, "error": {"message": "任务已失败"}}
            result = self.client.get(f"/ai/video/task-1?model={model['id']}").json()
            self.assertEqual(result["code"], 200)
            self.assertEqual(result["data"]["status"], status)

    def test_chat_forwards_selected_model_without_streaming(self):
        model = self.model("text", "DeepSeek", "")
        result = self.post("/ai/chat", {"model": model["id"], "messages": [{"role": "user", "content": "你好"}], "stream": True})
        self.assertEqual(result["data"]["choices"][0]["message"]["content"], "测试回复")
        request = self.provider.requests[0]
        self.assertEqual(request[0], "/v1/chat/completions")
        self.assertEqual(request[2]["model"], "real-api-model")
        self.assertFalse(request[2]["stream"])

    def test_claude_message_endpoint_and_headers(self):
        model = self.model("text", "teamorouter-claude", "/v1/messages")
        result = self.post("/ai/chat", {"model": model["id"], "messages": [{"role": "user", "content": "你好"}]})
        self.assertEqual(result["data"]["content"][0]["text"], "测试回复")
        request = self.provider.requests[0]
        self.assertEqual(request[0], "/v1/messages")
        self.assertEqual(request[1]["anthropic-version"], "2023-06-01")
        self.assertEqual(request[1]["x-api-key"], "fixture-private-key")
        self.assertEqual(request[2]["max_tokens"], 4096)

    def test_manual_doubao_account_does_not_use_undefined_account(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._lock = threading.Lock()
        api._tasks, api._workers = {}, {}
        api.get_settings = lambda: {"defaultAccountId": "a"}
        api._find_account = lambda _: {"id": "a", "name": "手动账号"}
        api._acquire_account_usage = Mock()
        worker = Mock(visible=True, start_error=None)
        worker.ready = threading.Event()
        worker.ready.set()
        api._ensure_worker = Mock(return_value=worker)
        file = self.root / "reference.png"
        file.write_bytes(self.provider.png)
        with patch("launcher.DATA_DIR", self.root):
            result = api.start_generation({"attachments": [{"path": str(file), "type": "image"}],
                                           "prompt": "测试", "accountId": "a", "autoAssignAccount": False})
        self.assertEqual(api._tasks[result["taskId"]]["accountName"], "手动账号")
        worker.submit_generation.assert_called_once()

    def test_text_bridge_timeout_allows_provider_processing(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._storage_request = Mock(return_value=httpx.Response(200, json={"code": 200, "data": {}}))
        api.backend_request("POST", "/ai/chat", body={"messages": []})
        self.assertEqual(api._storage_request.call_args.kwargs["timeout"], 330)

    def test_storage_settings_report_restart_without_moving_user_data(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        old_root = self.server.storage.root
        api._local_storage_server = self.server
        api.get_settings = lambda: {"defaultAccountId": "", "storageDir": str(old_root),
                                   "outputDir": str(self.root / "output"), "dailyVideoQuota": 3}
        api._write_settings = Mock()
        api._push_cloud_account_state = Mock()
        self.assertFalse(api.save_settings({"storageDir": str(old_root)})["storageRestartRequired"])
        new_root = self.root / "new-storage"
        self.assertTrue(api.save_settings({"storageDir": str(new_root)})["storageRestartRequired"])
        self.assertEqual(api._local_storage_server.storage.root, old_root)
        self.assertFalse((new_root / "storage.db").exists())


if __name__ == "__main__":
    unittest.main()
