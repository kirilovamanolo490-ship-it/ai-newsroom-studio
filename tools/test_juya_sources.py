import unittest
from juya_sources import normalize_url, extract_issue, x_account

class JuyaSourceTests(unittest.TestCase):
    def test_extracts_related_links_without_counting_overview_or_media(self):
        body='''<main><section class="issue-overview"><a href="https://x.com/Test/status/42">copy</a></section><h2>产品</h2><section class="news-item"><h3 id="n1"><a href="https://x.com/Test/status/42">测试标题</a><a class="article-ref" href="#overview">#1</a></h3><p>相关链接：</p><a href="https://x.com/Test/status/42?s=20">post</a><a href="https://example.com/blog/post">related</a><a href="https://assets.juya.uk/a.png"><img src="x"></a></section></main>'''
        result=extract_issue(body,'2026-10-10')
        self.assertEqual(len(result['links']),2)
        self.assertEqual(len(result['excluded']),1)
        self.assertEqual(result['links'][0]['news_title'],'测试标题')
        self.assertEqual(result['links'][1]['category'],'产品')
    def test_urls_preserve_semantic_parameters_and_drop_tracking(self):
        self.assertEqual(normalize_url('https://github.com/a/b?ref=explainx&utm_source=x#readme'),'https://github.com/a/b')
        self.assertEqual(normalize_url('https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1'),'https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1')
    def test_x_accounts_are_not_status_or_generic_route(self):
        self.assertEqual(x_account('https://twitter.com/OpenAI/status/42'),'OpenAI')
        self.assertIsNone(x_account('https://x.com/i/status/42'))
        self.assertIsNone(x_account('https://x.com/search?q=ai'))
    def test_empty_shell_is_a_failure(self):
        with self.assertRaises(ValueError):extract_issue('<main>Just a moment</main>','2026-10-10')

if __name__=='__main__':unittest.main()
