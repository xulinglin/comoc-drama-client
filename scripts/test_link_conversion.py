"""Link conversion fixtures: no user credentials or live platform requests."""
import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from original_doubao_nomark import (
    OriginalDoubaoVideoEvidence, conversion_account_type, is_supported_conversion_url,
    dola_video_parse, original_doubao_fplay_parse, platform_media_proxy,
)
from original_doubao_video_worker import OriginalDoubaoVideoWorker


DOLA_LINK = "https://v16-dola.dola.com/hash/video/tos/mya/file/?lr=cici_ai&download=true"
VIDEO_ID = "v186a3gm000cdb1lgrvog65sait4etb0"


class LinkConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "original.mp4"
        self.api = Mock()
        self.api._find_account.return_value = {"accountType": "dola"}
        self.api.get_settings.return_value = {"autoDownload": True, "outputDir": self.temp.name}
        self.api._media_url_for.return_value = "http://localhost/fixture.mp4"
        self.worker = OriginalDoubaoVideoWorker(self.api, "fixture", False)
        self.page = Mock(url="https://www.dola.com/chat")
        self.evidence = OriginalDoubaoVideoEvidence()
        self.evidence.add(VIDEO_ID)

    def tearDown(self):
        self.temp.cleanup()

    def test_platform_domains_are_strict_and_do_not_rewrite_download_query(self):
        self.assertTrue(is_supported_conversion_url(DOLA_LINK))
        self.assertEqual(conversion_account_type(DOLA_LINK), "dola")
        self.assertEqual(conversion_account_type("https://www.dola.com/chat/123"), "dola")
        self.assertEqual(conversion_account_type("https://www.doubao.com/video-sharing?video_id=x"), "doubao")
        for url in [DOLA_LINK.replace("dola.com", "dola.com.evil.test"), "https://evil.dola.com/video/tos/file", "file:///video/tos/file"]:
            self.assertFalse(is_supported_conversion_url(url))

    def test_direct_link_reads_mp4_id_and_saves_resolved_original(self):
        parser = AsyncMock(return_value=[{"url": "https://v16-dola.dola.com/original.mp4"}])
        with patch.object(self.worker, "_detect_login_state", return_value="logged_in"), \
             patch.object(self.worker, "_video_id_from_media_url", return_value=VIDEO_ID) as read_id, \
             patch.object(self.worker, "_save_media_url", return_value=self.output) as save, \
             patch("original_doubao_video_worker.dola_video_parse", parser), \
             patch("original_doubao_video_worker.original_doubao_video_parse") as domestic:
            result = self.worker._convert_link(self.page, DOLA_LINK)
        read_id.assert_called_once_with(DOLA_LINK)
        self.page.goto.assert_not_called()
        self.page.evaluate.assert_not_called()
        self.assertEqual(parser.call_args.args[0], [VIDEO_ID])
        self.assertEqual(save.call_args.args[0], "https://v16-dola.dola.com/original.mp4")
        self.assertEqual(result["watermarkStatus"], "official_unwatermarked")
        domestic.assert_not_called()

    def test_failed_resolution_never_downloads_watermarked_source_or_calls_domestic_parser(self):
        with patch.object(self.worker, "_detect_login_state", return_value="logged_in"), \
             patch.object(self.worker, "_video_id_from_media_url", return_value=VIDEO_ID), \
             patch.object(self.worker, "_save_media_url") as save, \
             patch("original_doubao_video_worker.dola_video_parse", AsyncMock(side_effect=ValueError("Dola 当前网络受地区限制"))), \
             patch("original_doubao_video_worker.original_doubao_video_parse") as domestic:
            with self.assertRaisesRegex(ValueError, "地区限制"):
                self.worker._convert_link(self.page, DOLA_LINK)
        save.assert_not_called()
        domestic.assert_not_called()

    def test_foreign_page_is_rejected_before_authenticated_fetch(self):
        self.page.url = "https://www.doubao.com/chat"
        with self.assertRaisesRegex(ValueError, "账号平台不一致"):
            self.worker._resolve_nomark_in_logged_in_page(self.page, self.evidence)
        self.page.evaluate.assert_not_called()

    def test_mp4_comment_contains_id_even_when_direct_url_does_not(self):
        response = Mock()
        response.iter_bytes.return_value = [b"ftypmp42\x00comment vid:" + VIDEO_ID.encode() + b"\x00"]
        with patch("original_doubao_video_worker.httpx.stream") as stream:
            stream.return_value.__enter__.return_value = response
            self.assertEqual(self.worker._video_id_from_media_url(DOLA_LINK), VIDEO_ID)

    def test_dola_media_uses_system_proxy_and_domestic_keeps_default(self):
        with patch("original_doubao_nomark.getproxies", return_value={"https": "http://127.0.0.1:7897"}):
            self.assertEqual(platform_media_proxy("https://www.dola.com/chat"), "http://127.0.0.1:7897")
            self.assertIsNone(platform_media_proxy("https://www.doubao.com/"))

    def test_fplay_retains_platform_referer_and_excludes_logo_rendition(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"data": {"key_seed": base64.b64encode(b"x" * 32).decode(), "video_list": {
                "marked": {"logo_type": "dola", "main_url": "https://cdn.test/marked.mp4", "width": 1920, "height": 1080},
                "original": {"main_url": "https://cdn.test/original.mp4", "width": 1280, "height": 720},
            }}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("original_doubao_nomark.httpx.AsyncClient", return_value=client):
            videos = asyncio.run(original_doubao_fplay_parse("https://vod.test/video/fplay/?key_seed=x&logo_type=dola&force_fids=x", VIDEO_ID, referer="https://www.dola.com/chat"))
        self.assertEqual([v["url"] for v in videos], ["https://cdn.test/original.mp4"])
        self.assertEqual(requests[0].headers["referer"], "https://www.dola.com/chat")
        self.assertNotIn("logo_type", requests[0].url.params)
        self.assertNotIn("force_fids", requests[0].url.params)


class DolaOfficialApiTests(unittest.TestCase):
    def parse(self, replies):
        requests = []
        def handle(request):
            requests.append(request)
            if not replies:
                raise AssertionError("Unexpected extra Dola API request")
            return httpx.Response(200, json=replies.pop(0))
        client_type = httpx.AsyncClient
        def client(**kwargs):
            return client_type(**kwargs, transport=httpx.MockTransport(handle))
        with patch("original_doubao_nomark.httpx.AsyncClient", side_effect=client):
            try:
                videos = asyncio.run(dola_video_parse([VIDEO_ID], {"sessionid": "fixture-only"}))
            finally:
                self.requests = requests
        self.assertEqual(replies, [])
        return videos

    def resource(self, enabled=True):
        return {"code": 0, "data": {"without_watermark": enabled, "download_video": {
            VIDEO_ID: {"vid": VIDEO_ID, "download_url": "https://v16-dola.dola.com/original.mp4", "duration": 10.08}
        }}}

    def test_enabled_account_gets_official_original_without_changing_setting(self):
        videos = self.parse([self.resource()])
        self.assertEqual(videos[0]["url"], "https://v16-dola.dola.com/original.mp4")
        self.assertEqual(videos[0]["source"], "dola_official_without_watermark")
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.url.host, "www.dola.com")
        self.assertEqual(request.url.path, "/creativity/resource/get_without_watermark")
        self.assertEqual(request.url.params["aid"], "495671")
        self.assertIn("sessionid=fixture-only", request.headers["cookie"])

    def test_disabled_account_enables_official_switch_then_retries_same_vid(self):
        self.parse([{"code": 0, "data": {"without_watermark": False}},
                    {"code": 0, "data": {"config_map": {"2": {"portrait_auth": {"status": 0}}}}},
                    {"code": 0}, self.resource()])
        self.assertEqual([r.url.path for r in self.requests], [
            "/creativity/resource/get_without_watermark", "/creativity/user_config/get",
            "/creativity/user_config/set", "/creativity/resource/get_without_watermark",
        ])
        self.assertEqual(json.loads(self.requests[2].content), {"config_type": 1, "config_value": {"watermark_option": {"is_on": True}}})
        self.assertEqual(json.loads(self.requests[3].content), {"vid": [VIDEO_ID]})

    def test_upgrade_requirement_stops_before_setting_or_downloading(self):
        with self.assertRaisesRegex(ValueError, "需升级"):
            self.parse([{"code": 0, "data": {"without_watermark": False}}, {"code": 0, "data": {
                "config_map": {"1": {"watermark_option": {"subscribe_config": {"need_upgrade": True}}}}
            }}])
        self.assertEqual(len(self.requests), 2)

    def test_unsuccessful_enable_restores_setting_and_returns_no_marked_video(self):
        with self.assertRaisesRegex(ValueError, "未提供"):
            self.parse([{"code": 0, "data": {"without_watermark": False}}, {"code": 0, "data": {}},
                        {"code": 0}, {"code": 0, "data": {"without_watermark": False}}, {"code": 0}])
        self.assertFalse(json.loads(self.requests[-1].content)["config_value"]["watermark_option"]["is_on"])

    def test_missing_video_does_not_use_preview_or_unrelated_download(self):
        response = self.resource()
        response["data"]["download_video"] = {"unrelated": {"download_url": "https://cdn.test/other.mp4"}}
        response["data"]["preview_video"] = {VIDEO_ID: {"download_url": "https://cdn.test/marked.mp4"}}
        with self.assertRaisesRegex(ValueError, "未返回.*下载地址"):
            self.parse([response])

    def test_api_reports_actual_expired_login_or_region_restriction(self):
        for code, message in [(710012001, "登录已过期"), (710022003, "地区限制")]:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, message):
                self.parse([{"code": code, "msg": "fixture-only"}])


if __name__ == "__main__":
    unittest.main()
