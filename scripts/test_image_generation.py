"""图片生成迁移回归：使用本机模拟模型服务，不调用付费接口。"""
import base64
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from PIL import Image

from local_storage import LocalStorageServer, _Handler


def image_bytes(image_format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buffer, format=image_format)
    return buffer.getvalue()


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.requests.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "contentType": self.headers.get("Content-Type"),
            "body": self.rfile.read(int(self.headers["Content-Length"])),
        })
        payload = self.server.payload
        if payload is None:
            payload = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
        content = json.dumps(payload).encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        self.server.download_auth = self.headers.get("Authorization")
        content = image_bytes("JPEG")
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class ImageGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.provider = f"http://127.0.0.1:{cls.upstream.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.thread.join()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = LocalStorageServer(Path(self.directory.name), port=0)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server._server.server_port}"
        self.upstream.requests = []
        self.upstream.payload = None
        self.upstream.status = 200
        self.upstream.download_auth = None
        self.model = self.server.storage.create_document("ai_models", {
            "name": "测试图片模型", "modelType": "image", "modelName": "gpt-image-test",
            "apiUrl": self.provider, "apiKey": "test-key-private", "enabled": True,
        })

    def tearDown(self):
        self.server.stop()
        self.directory.cleanup()

    def call(self, body, route="/ai/image"):
        request = urllib.request.Request(self.base + route, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return json.loads(response.read())

    def generate(self, **overrides):
        return self.call({"model": self.model["id"], "prompt": "测试角色图", "n": 1,
                          "size": "1024x1024", **overrides})

    def test_configured_model_generation_and_local_preview(self):
        result = self.generate()
        self.assertEqual(result["code"], 200, result)
        request = self.upstream.requests[0]
        self.assertEqual(request["path"], "/v1/images/generations")
        self.assertEqual(request["auth"], "Bearer test-key-private")
        self.assertEqual(json.loads(request["body"])["model"], "gpt-image-test")
        self.assertEqual(json.loads(request["body"])["size"], "1024x1024")
        self.assertTrue(result["data"]["fileId"].startswith("local_"))
        with urllib.request.urlopen(self.base + result["data"]["content"]) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(), image_bytes())

    def test_desktop_bridge_returns_preview_and_provider_error(self):
        from launcher import DesktopApi

        # Skip DesktopApi startup so tests cannot touch the user's storage or UI.
        api = DesktopApi.__new__(DesktopApi)
        with httpx.Client(base_url=self.base, trust_env=False) as client:
            api._storage_request = client.request
            body = {"model": self.model["id"], "prompt": "测试角色图"}
            result = api.backend_request("POST", "/ai/image", body=body)
            self.assertTrue(result["content"].startswith("/file/local_"))
            self.upstream.status = 401
            self.upstream.payload = {"error": {"message": "Invalid key"}}
            with self.assertRaisesRegex(ValueError, "HTTP 401"):
                api.backend_request("POST", "/ai/image", body=body)

    def test_multiple_reference_images_use_edit_endpoint(self):
        original = image_bytes()
        source = "data:image/png;base64," + base64.b64encode(original).decode()
        self.assertEqual(self.generate(image=[source, source])["code"], 200)
        request = self.upstream.requests[0]
        self.assertEqual(request["path"], "/v1/images/edits")
        fields, files = _Handler._parse_multipart(request["body"], request["contentType"])
        self.assertEqual(fields["model"], "gpt-image-test")
        self.assertEqual(fields["prompt"], "测试角色图")
        self.assertEqual([file[0] for file in files], ["image[]", "image[]"])
        self.assertEqual([file[2] for file in files], [original, original])

    def test_single_reference_file(self):
        source = "data:image/png;base64," + base64.b64encode(image_bytes()).decode()
        self.assertEqual(self.generate(image=source)["code"], 200)
        request = self.upstream.requests[0]
        _, files = _Handler._parse_multipart(request["body"], request["contentType"])
        self.assertEqual(files[0][0], "image")

    def test_url_result_is_saved_without_forwarding_key(self):
        self.upstream.payload = {"data": [{"url": self.provider + "/result.jpg"}]}
        result = self.generate()
        self.assertEqual(result["code"], 200)
        self.assertIsNone(self.upstream.download_auth)
        with urllib.request.urlopen(self.base + result["data"]["content"]) as response:
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
            self.assertEqual(response.read(), image_bytes("JPEG"))

    def test_disabled_model_does_not_call_provider(self):
        self.server.storage.update_document("ai_models", self.model["id"], {"enabled": False})
        result = self.generate()
        self.assertIn("未找到已启用", result["message"])
        self.assertEqual(self.upstream.requests, [])

    def test_missing_key_reports_real_configuration_problem(self):
        self.server.storage.update_document("ai_models", self.model["id"], {"apiKey": ""})
        self.assertIn("API Key", self.generate()["message"])
        self.assertEqual(self.upstream.requests, [])

    def test_unknown_model_does_not_silently_use_another(self):
        self.assertNotEqual(self.generate(model="missing")["code"], 200)
        self.assertEqual(self.upstream.requests, [])

    def test_model_name_compatibility(self):
        self.assertEqual(self.generate(model="gpt-image-test")["code"], 200)

    def test_empty_prompt_does_not_call_provider(self):
        self.assertIn("描述", self.generate(prompt=" ")["message"])
        self.assertEqual(self.upstream.requests, [])

    def test_invalid_reference_does_not_call_provider(self):
        self.assertNotEqual(self.generate(image="data:image/png;base64,invalid!")["code"], 200)
        self.assertEqual(self.upstream.requests, [])

    def test_provider_error_is_visible_and_key_is_redacted(self):
        self.upstream.status = 401
        self.upstream.payload = {"error": {"message": "Invalid key test-key-private"}}
        result = self.generate()
        self.assertNotEqual(result["code"], 200)
        self.assertIn("HTTP 401", result["message"])
        self.assertNotIn("test-key-private", result["message"])
        self.assertEqual(len(self.upstream.requests), 1)

    def test_empty_provider_result_is_not_success(self):
        self.upstream.payload = {"data": []}
        self.assertIn("没有返回图片", self.generate()["message"])

    def test_invalid_image_result_is_not_saved(self):
        self.upstream.payload = {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}
        self.assertNotEqual(self.generate()["code"], 200)
        with closing(self.server.storage._connect()) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM storage_file").fetchone()[0], 0)

    def test_non_image_routes_report_not_implemented(self):
        self.assertIn("尚未接入", self.call({}, "/ai/unsupported")["message"])
        self.assertEqual(self.upstream.requests, [])

    def test_endpoint_accepts_base_versioned_and_full_urls(self):
        for address in [self.provider, self.provider + "/v1/", self.provider + "/v1/images/generations"]:
            with self.subTest(address=address):
                self.server.storage.update_document("ai_models", self.model["id"], {"apiUrl": address})
                self.assertEqual(self.generate()["code"], 200)
                self.assertEqual(self.upstream.requests[-1]["path"], "/v1/images/generations")


if __name__ == "__main__":
    unittest.main()
