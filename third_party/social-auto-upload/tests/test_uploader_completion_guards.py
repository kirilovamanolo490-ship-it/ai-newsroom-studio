import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, MagicMock, patch

from uploader.xiaohongshu_uploader.main import XiaoHongShuBaseUploader
from uploader.youtube_uploader.main import (
    _require_publish_confirmation,
    _require_upload_complete,
    _submit_publish_and_confirm,
    cookie_auth,
    _confirm_from_channel_list,
)


class UploaderCompletionGuardTests(unittest.TestCase):
    def test_youtube_channel_list_confirms_exact_public_published_video(self):
        async def scenario():
            page=Mock();page.url='https://studio.youtube.com/channel/UCexample/videos/upload'
            page.goto=AsyncMock()
            row=Mock();row.first=row;row.wait_for=AsyncMock();row.count=AsyncMock(return_value=1)
            row.inner_text=AsyncMock(return_value='Example title\nPublic\nPublished\n0:53')
            link=Mock();link.first=link
            link.get_attribute=AsyncMock(return_value='https://studio.youtube.com/video/W2BBGfbS7gE/edit')
            row.get_by_role.return_value=link
            page.get_by_role.return_value.filter.return_value=row
            self.assertEqual(await _confirm_from_channel_list(page,'Example title'),'https://www.youtube.com/watch?v=W2BBGfbS7gE')
            row.inner_text=AsyncMock(return_value='Example title\nPrivate\nPublished')
            with self.assertRaisesRegex(RuntimeError,'not confirmed'):
                await _confirm_from_channel_list(page,'Example title')
            row.count=AsyncMock(return_value=2)
            with self.assertRaisesRegex(RuntimeError,'exactly one'):
                await _confirm_from_channel_list(page,'Example title')
        asyncio.run(scenario())

    def test_youtube_auth_waits_for_channel_redirect_in_visible_chrome(self):
        async def scenario():
            page=Mock();page.url='https://studio.youtube.com/'
            page.goto=AsyncMock()
            async def channel_loaded(*args,**kwargs):
                page.url='https://studio.youtube.com/channel/UCexample/dashboard'
            page.wait_for_url=AsyncMock(side_effect=channel_loaded)
            context=Mock();context.new_page=AsyncMock(return_value=page)
            browser=Mock();browser.new_context=AsyncMock(return_value=context);browser.close=AsyncMock()
            playwright=Mock();playwright.chromium.launch=AsyncMock(return_value=browser)
            manager=MagicMock();manager.__aenter__=AsyncMock(return_value=playwright);manager.__aexit__=AsyncMock(return_value=False)
            with patch('uploader.youtube_uploader.main.async_playwright',return_value=manager), patch('uploader.youtube_uploader.main.set_init_script',new=AsyncMock(return_value=context)):
                self.assertTrue(await cookie_auth('saved.json'))
            self.assertFalse(playwright.chromium.launch.call_args.kwargs['headless'])
            page.wait_for_url.assert_awaited_once()
            browser.close.assert_awaited_once()
        asyncio.run(scenario())

    def test_xhs_skips_repost_declaration_when_source_is_blank(self):
        async def scenario():
            uploader = object.__new__(XiaoHongShuBaseUploader)
            uploader.repost_source = "  \n"
            page = Mock()

            await uploader.check_original_declaration(page)

            page.get_by_text.assert_not_called()
            page.locator.assert_not_called()

        asyncio.run(scenario())

    def test_xhs_fills_explicit_repost_source_unchanged(self):
        async def scenario():
            uploader = object.__new__(XiaoHongShuBaseUploader)
            uploader.repost_source = "公开视频素材"
            page = Mock()
            trigger = Mock()
            trigger.scroll_into_view_if_needed = AsyncMock()
            trigger.click = AsyncMock()
            page.get_by_text.return_value.first = trigger
            page.wait_for_timeout = AsyncMock()

            option = Mock()
            option.count = AsyncMock(return_value=1)
            option.click = AsyncMock()
            page.locator.return_value.filter.return_value.last = option

            source_input = Mock()
            source_input.wait_for = AsyncMock()
            source_input.click = AsyncMock()
            source_input.fill = AsyncMock()
            page.get_by_placeholder.return_value.first = source_input

            confirm = Mock()
            confirm.wait_for = AsyncMock()
            confirm.click = AsyncMock()
            page.get_by_role.return_value.first = confirm

            await uploader.check_original_declaration(page)

            source_input.fill.assert_awaited_once_with("公开视频素材")

        asyncio.run(scenario())

    def test_youtube_upload_timeout_prevents_publish(self):
        async def scenario():
            page = Mock()
            with self.assertRaisesRegex(RuntimeError, "publish was not submitted"):
                await _require_upload_complete(page, max_polls=0)
            page.locator.assert_not_called()

        asyncio.run(scenario())

    def test_youtube_missing_publish_confirmation_raises(self):
        async def scenario():
            page = Mock()
            dialog = Mock()
            dialog.first = dialog
            dialog.count = AsyncMock(return_value=0)
            page.locator.return_value = dialog

            with self.assertRaisesRegex(RuntimeError, "share dialog did not confirm publication"):
                await _require_publish_confirmation(page, timeout_ms=0)

        asyncio.run(scenario())

    def test_youtube_publish_confirmation_accepts_concrete_link(self):
        async def scenario():
            page = Mock()
            dialog = Mock()
            dialog.first = dialog
            dialog.count = AsyncMock(return_value=1)
            dialog.inner_text = AsyncMock(return_value="Video published")
            links = Mock()
            links.count = AsyncMock(return_value=1)
            link = Mock()
            link.get_attribute = AsyncMock(return_value="https://youtu.be/abcdefghijk")
            links.nth.return_value = link
            dialog.locator.return_value = links
            page.locator.return_value = dialog

            self.assertEqual(await _require_publish_confirmation(page, timeout_ms=100), "https://youtu.be/abcdefghijk")

        asyncio.run(scenario())

    def test_youtube_global_link_without_share_dialog_does_not_confirm(self):
        async def scenario():
            page = Mock()
            dialog = Mock()
            dialog.first = dialog
            dialog.count = AsyncMock(return_value=0)
            page.locator.return_value = dialog
            page.wait_for_timeout = AsyncMock()

            with self.assertRaisesRegex(RuntimeError, "share dialog did not confirm publication"):
                await _require_publish_confirmation(page, timeout_ms=5)
            page.locator.assert_called_with("ytcp-video-share-dialog")

        asyncio.run(scenario())

    def test_youtube_missing_done_button_prevents_submit(self):
        async def scenario():
            page = Mock()
            button = Mock()
            button.wait_for = AsyncMock(side_effect=TimeoutError("missing"))
            button.click = AsyncMock()
            page.locator.return_value.first = button

            with self.assertRaisesRegex(RuntimeError, "publish button was not available"):
                await _submit_publish_and_confirm(page)
            button.click.assert_not_awaited()

        asyncio.run(scenario())
