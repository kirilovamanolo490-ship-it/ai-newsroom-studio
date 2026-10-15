import asyncio
import unittest

import uploader.xiaohongshu_uploader.main as xhs_main


class BlankPreview:
    async def inner_text(self):
        return ""

    async def query_selector_all(self, selector):
        return []


class UploadInput:
    def __init__(self, preview):
        self.preview = preview

    async def query_selector(self, selector):
        return self.preview


class VisibleTitle:
    async def count(self):
        return 1

    async def is_visible(self):
        return True


class PreviewAndTitlePage:
    def __init__(self):
        self.preview = BlankPreview()
        self.upload_input = UploadInput(self.preview)

    async def wait_for_selector(self, selector, **kwargs):
        return self.upload_input

    def locator(self, selector):
        if selector == 'input[placeholder*="填写标题"]':
            return VisibleTitle()
        raise AssertionError(f"Unexpected locator: {selector}")


class XiaohongshuReadinessTests(unittest.TestCase):
    def test_readiness_wait_has_a_deadline_before_metadata_or_publish(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题内容", file_path="demo.mp4", tags=[],
            publish_date=0, account_file="account.json", thumbnail_path="cover.png",
        )
        with self.assertRaisesRegex(RuntimeError, "timeout_before_metadata"):
            asyncio.run(app._wait_for_video_upload(PreviewAndTitlePage(), timeout_seconds=0))

    def test_visible_title_is_ready_even_when_preview_exists_without_text(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题内容",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            thumbnail_path="cover.png",
        )

        # The empty preview represents the 10:00 failure mode: the preview DOM
        # exists, but its status text never contains one of the success markers.
        asyncio.run(app._wait_for_video_upload(PreviewAndTitlePage()))


if __name__ == "__main__":
    unittest.main()
