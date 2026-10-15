"""Behavior checks: duplication, failed/partial watermarks, future dates and blockers."""
import unittest
import requests
from unittest.mock import Mock, patch
from source_watch import reconcile, parse_html, source_due, parse_sitemap, fetch_source

NOW='2026-10-10T06:00:00+00:00'
OLD='2026-10-10T04:00:00+00:00'
def item(key,content='first',date='2026-10-10T05:00:00+00:00'):
    return {'key':key,'title':key,'url':'https://example.com/'+key,'content':content,'published_at':date}

class WatchBehavior(unittest.TestCase):
    def x_response(self, payload):
        response=Mock()
        response.content=b'public fixture'
        response.encoding='utf-8'
        response.url='https://api.twitterapi.io/twitter/tweet/advanced_search'
        response.status_code=200
        response.headers={'Content-Type':'application/json'}
        response.text='{}'
        response.json.return_value=payload
        return response

    def github_pages(self, fail_second=False):
        recent=[{'full_name':f'example/recent-{i}','html_url':f'https://github.com/example/recent-{i}',
                 'description':'Recent project','created_at':'2026-10-10T01:00:00Z',
                 'pushed_at':'2026-10-10T05:00:00Z','updated_at':'2026-10-10T05:00:00Z'} for i in range(100)]
        older=[{'full_name':'example/older','html_url':'https://github.com/example/older',
                'description':'Older project','created_at':'2026-10-09T01:00:00Z',
                'pushed_at':'2026-10-10T03:00:00Z','updated_at':'2026-10-10T03:00:00Z'}]
        def provider(url,params,**kwargs):
            page=params.get('page',1)
            if page==2 and fail_second:raise requests.HTTPError('Second page unavailable')
            return self.x_response(recent if page==1 else older)
        session=Mock();session.headers={};session.proxies={};session.get.side_effect=provider
        return session

    def test_github_org_reaches_previous_success_after_the_first_hundred_repositories(self):
        source={'id':'gh','name':'Example','url':'https://github.com/example','kind':'github_org','owner':'example'}
        before={'baseline_at':OLD,'last_success_at':OLD,'seen':{}}
        with patch('source_watch.requests.Session',return_value=self.github_pages()):
            result=fetch_source(source,before,NOW,'')
        self.assertTrue(result.get('complete'))
        self.assertEqual(len(result.get('items',[])),101)
        self.assertEqual(result['items'][-1]['key'],'example/older')

    def test_github_org_resumes_the_next_page_without_advancing_the_fixed_window_early(self):
        source={'id':'gh','name':'Example','url':'https://github.com/example','kind':'github_org','owner':'example','max_pages':1}
        before={'baseline_at':OLD,'last_success_at':OLD,'seen':{'saved':'old-digest'}}
        with patch('source_watch.requests.Session',return_value=self.github_pages()):
            partial=fetch_source(source,before,NOW,'')
        middle,_=reconcile(before,partial,NOW)
        self.assertEqual(middle['last_success_at'],OLD)
        self.assertEqual(middle.get('resume',{}).get('next_page'),2)
        self.assertEqual(middle['seen']['saved'],'old-digest')
        later='2026-10-10T07:00:00+00:00'
        with patch('source_watch.requests.Session',return_value=self.github_pages()):
            finished=fetch_source(source,middle,later,'')
        self.assertEqual([x['key'] for x in finished.get('items',[])],['example/older'])
        after,_=reconcile(middle,finished,later)
        self.assertEqual(after['last_success_at'],NOW)
        self.assertNotIn('resume',after)

    def test_github_org_failed_later_page_retains_completed_items_and_retry_cursor(self):
        source={'id':'gh','name':'Example','url':'https://github.com/example','kind':'github_org','owner':'example'}
        before={'baseline_at':OLD,'last_success_at':OLD,'seen':{}}
        with patch('source_watch.requests.Session',return_value=self.github_pages(fail_second=True)):
            result=fetch_source(source,before,NOW,'')
        self.assertFalse(result.get('complete'))
        self.assertIn('page_read_failed',result.get('coverage_warning',''))
        after,_=reconcile(before,result,NOW)
        self.assertEqual(after['last_success_at'],OLD)
        self.assertEqual(after.get('resume',{}).get('next_page'),2)
        self.assertEqual(len(after['seen']),100)

    def test_expanded_feed_parameters_recover_the_missing_success_window(self):
        source={'id':'feed','name':'Feed','url':'https://example.com/feed','kind':'rss','feed_params':{'limit':100}}
        session=Mock();session.headers={};session.proxies={}
        def provider(url,params=None,**kwargs):
            older='<item><guid>older</guid><link>https://example.com/older</link><title>Older</title><pubDate>Sat, 10 Oct 2026 03:00:00 GMT</pubDate></item>' if params=={'limit':100} else ''
            response=self.x_response({});response.content=('<rss version="2.0"><channel><title>Feed</title><item><guid>new</guid><link>https://example.com/new</link><title>New</title><pubDate>Sat, 10 Oct 2026 05:00:00 GMT</pubDate></item>'+older+'</channel></rss>').encode()
            return response
        session.get.side_effect=provider
        with patch('source_watch.requests.Session',return_value=session):
            result=fetch_source(source,{'last_success_at':OLD},NOW,'')
        self.assertTrue(result.get('complete'))
        self.assertEqual([x['key'] for x in result.get('items',[])],['new','older'])
        self.assertEqual(result.get('oldest_item_at'),'2026-10-10T03:00:00+00:00')

    def test_same_utc_day_x_poll_recovers_known_post_with_supported_time_operators(self):
        source={'id':'x-qoder','name':'Qoder','url':'https://x.com/qoder_ai_ide','kind':'x','handle':'qoder_ai_ide','bootstrap_hours':4,'max_pages':1}
        post={'id':'2108806953141162235','text':'Performance is now Fast','createdAt':'Sat Oct 10 06:28:52 +0000 2026','author':{'userName':'qoder_ai_ide'}}
        session=Mock();session.headers={};session.proxies={}
        def provider(url,params,**kwargs):
            # Reproduction from live controls: date-time strings returned empty;
            # since_time/until_time returned the known announcement in this window.
            supported='since_time:' in params['query'] and 'until_time:' in params['query']
            return self.x_response({'tweets':[post] if supported else [],'has_next_page':False})
        session.get.side_effect=provider
        before={'baseline_at':'2026-10-10T06:24:27+00:00','last_success_at':'2026-10-10T09:08:06+00:00','seen':{}}
        with patch('source_watch.requests.Session',return_value=session):
            result=fetch_source(source,before,'2026-10-10T09:30:00+00:00','fake-test-key')
        self.assertEqual([x['key'] for x in result.get('items',[])],['2108806953141162235'])
        self.assertTrue(result.get('coverage_recovery'))
        self.assertLess(result.get('query_start_at'),'2026-10-10T06:28:52+00:00')

    def test_x_provider_outside_time_window_is_failure_not_empty_success(self):
        source={'id':'x-qoder','name':'Qoder','url':'https://x.com/qoder_ai_ide','kind':'x','handle':'qoder_ai_ide','max_pages':1}
        session=Mock();session.headers={};session.proxies={};session.get.return_value=self.x_response({'tweets':[{'id':'future','text':'future','createdAt':'Sun Oct 11 06:00:00 +0000 2026','author':{'userName':'qoder_ai_ide'}}],'has_next_page':False})
        with patch('source_watch.requests.Session',return_value=session):result=fetch_source(source,{},NOW,'fake-test-key')
        self.assertIn('error',result)
        self.assertFalse(result['complete'])

    def test_recovery_retains_seen_items_and_clears_pending_only_after_complete_window(self):
        before={'baseline_at':OLD,'last_success_at':OLD,'seen':{'old':'digest'}}
        result={'complete':False,'items':[item('b')],'query_format':'epoch_seconds_v1','coverage_recovery':True,'resume':{'query':'since_time:1 until_time:2','cursor':'next','until':NOW,'since':OLD,'query_format':'epoch_seconds_v1','coverage_recovery':True}}
        partial,events=reconcile(before,result,NOW)
        self.assertEqual(partial['last_success_at'],OLD)
        self.assertEqual(partial['seen']['old'],'digest')
        self.assertTrue(partial.get('x_coverage_recovery_pending'))
        self.assertEqual(partial.get('x_query_format'),'epoch_seconds_v1')
        complete,repeated=reconcile(partial,{**result,'complete':True,'window_end':NOW},NOW)
        self.assertFalse(complete.get('x_coverage_recovery_pending'))
        self.assertEqual(complete['last_success_at'],NOW)
        self.assertEqual(repeated,[])

    def test_sitemap_finds_new_help_articles_without_inventing_publication_dates(self):
        source={'url':'https://example.com/sitemap.xml','url_pattern':'/en/articles/'}
        body='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/en/articles/design-migration</loc><lastmod>2026-10-10T03:00:00Z</lastmod></url><url><loc>https://example.com/zh/articles/design-migration</loc></url></urlset>'
        parsed=parse_sitemap(source,body)
        self.assertTrue(parsed['complete'])
        self.assertEqual(len(parsed['items']),1)
        self.assertIsNone(parsed['items'][0]['published_at'])
        self.assertEqual(parsed['items'][0]['modified_at'],'2026-10-10T03:00:00Z')

    def test_child_sitemap_index_requires_traversal_and_is_not_empty_success(self):
        parsed=parse_sitemap({'url':'https://example.com/sitemap.xml'},'<sitemapindex><sitemap><loc>https://example.com/child.xml</loc></sitemap></sitemapindex>')
        self.assertFalse(parsed['complete'])
        self.assertIn('error',parsed)

    def test_new_source_is_due_and_healthy_source_respects_its_interval(self):
        self.assertTrue(source_due({'interval_hours':24},{},NOW))
        self.assertFalse(source_due({'interval_hours':24},{'checked_at':OLD,'status':'ok'},NOW))
        self.assertTrue(source_due({'interval_hours':1},{'checked_at':OLD,'status':'ok'},NOW))

    def test_failed_daily_source_is_retried_soon_instead_of_waiting_another_day(self):
        self.assertTrue(source_due({'interval_hours':24},{'checked_at':OLD,'status':'failed'},NOW))
        self.assertTrue(source_due({'interval_hours':24},{'checked_at':OLD,'status':'partial'},NOW))

    def test_first_read_creates_baseline_without_announcing_old_news(self):
        state,events=reconcile({}, {'complete':True,'items':[item('a')]}, NOW)
        self.assertEqual(events,[])
        self.assertEqual(state.get('last_success_at'),NOW)
        self.assertIn('a',state.get('seen',{}))

    def test_second_read_deduplicates_but_finds_new_and_edited_items(self):
        state,_=reconcile({}, {'complete':True,'items':[item('a')]},OLD)
        # Initial item must already be in the baseline; use a known older timestamp.
        state,_=reconcile({}, {'complete':True,'items':[item('a',date='2026-10-10T03:00:00+00:00')]},OLD)
        state,events=reconcile(state, {'complete':True,'items':[item('a','edited',date='2026-10-10T03:00:00+00:00'),item('b')]},NOW)
        self.assertEqual([(e['key'],e['change']) for e in events],[('a','content_updated'),('b','new_item')])
        _,events=reconcile(state, {'complete':True,'items':[item('a','edited',date='2026-10-10T03:00:00+00:00'),item('b')]},NOW)
        self.assertEqual(events,[])

    def test_failed_read_cannot_advance_or_erase_success(self):
        before={'last_success_at':OLD,'seen':{'a':'saved'}}
        after,events=reconcile(before,{'error':'HTTP 403','items':[]},NOW)
        self.assertEqual(after,before)
        self.assertEqual(events,[])

    def test_partial_pages_preserve_watermark_and_resume_cursor(self):
        previous={'last_success_at':OLD,'seen':{},'baseline_at':OLD}
        pending={'query':'fixed time window','cursor':'page-4','until':NOW}
        after,events=reconcile(previous,{'complete':False,'items':[item('b')],'resume':pending},NOW)
        self.assertEqual(after['last_success_at'],OLD)
        self.assertEqual(after.get('resume'),pending)
        self.assertIn('b',after.get('seen',{}))
        self.assertEqual(len(events),1)
        final,repeated=reconcile(after,{'complete':True,'items':[item('b')],'window_end':NOW},NOW)
        self.assertEqual(repeated,[])
        self.assertNotIn('resume',final)
        self.assertEqual(final['last_success_at'],NOW)

    def test_future_post_is_not_announced_or_permanently_deduplicated(self):
        previous={'last_success_at':OLD,'seen':{},'baseline_at':OLD}
        future=item('future',date='2026-10-11T01:00:00+00:00')
        state,events=reconcile(previous,{'complete':True,'items':[future]},NOW)
        self.assertNotIn('future',state.get('seen',{}))
        self.assertEqual(events,[])
        _,events=reconcile(state,{'complete':True,'items':[future]},'2026-10-11T02:00:00+00:00')
        self.assertEqual(len(events),1)

    def test_undated_new_page_remains_discovery_not_dated_news(self):
        previous={'last_success_at':OLD,'seen':{},'baseline_at':OLD}
        _,events=reconcile(previous,{'complete':True,'items':[item('undated',date=None)]},NOW)
        self.assertEqual(events[0]['change'] if events else None,'discovered_undated')

    def test_http_200_challenge_page_is_not_valid_source_content(self):
        source={'url':'https://example.com','kind':'html','expect':['News'],'min_chars':30}
        parsed=parse_html(source,'<html><title>Security Verification</title><body>Please enable JavaScript to continue. News</body></html>')
        self.assertIn('error',parsed)
        self.assertFalse(parsed.get('complete',False))

    def test_html_discovers_article_links_and_page_edits(self):
        source={'url':'https://example.com/news','kind':'html','expect':['News'],'min_chars':20,'link_pattern':'/news/'}
        parsed=parse_html(source,'<html><title>News</title><main><h1>News: the release</h1><a href="/news/release">Official release</a><p>New model available today</p></main></html>')
        self.assertEqual([x['url'] for x in parsed['items']],['https://example.com/news','https://example.com/news/release'])

if __name__=='__main__':unittest.main()
