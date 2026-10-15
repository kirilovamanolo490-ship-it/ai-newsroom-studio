import unittest

from build_source_library import merge_entries, reconcile_registry
from connect_library_watch import usable_feeds


class SourceLibraryTests(unittest.TestCase):
    def test_new_unreviewed_article_cannot_inherit_verification_from_same_homepage(self):
        known=dict(id='known',kind='web',entry_url='https://example.com/',verification='verified_index',
                   recommended=True,name='Known index',covered_urls=['https://example.com/old'],origin_hosts=['example.com'])
        pending=dict(known,id='pending-new',verification='unresolved',recommended=False,
                     pending_resolution=True,covered_urls=['https://example.com/new-section/new'])
        result=merge_entries([known,pending])
        self.assertEqual(len(result),2)
        self.assertEqual(next(e for e in result if e['id']=='pending-new')['verification'],'unresolved')

    def test_duplicate_directory_preserves_strongest_evidence(self):
        a = dict(id='candidate', kind='web', entry_url='https://example.com/news/',
                 verification='unresolved', recommended=False, name='Candidate',
                 covered_urls=['https://example.com/a'], origin_hosts=['example.com'])
        b = dict(a, id='checked', verification='verified_index', recommended=True,
                 name='Example News', covered_urls=['https://example.com/b'],
                 index_samples=[{'url': 'https://example.com/b'}])
        result = merge_entries([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['verification'], 'verified_index')
        self.assertEqual(result[0]['name'], 'Example News')
        self.assertEqual(len(result[0]['covered_urls']), 2)

    def test_remapped_article_does_not_return_to_old_source_next_month(self):
        old = [dict(id='old', covered_urls=['article-now', 'article-archived'])]
        current = [dict(id='new', covered_urls=['article-now'])]
        result = {e['id']: e for e in reconcile_registry(old, current, {'article-now'})}
        self.assertEqual(result['old']['covered_urls'], ['article-archived'])
        self.assertEqual(result['new']['covered_urls'], ['article-now'])

    def test_sitemap_is_not_misconfigured_as_rss(self):
        self.assertEqual(usable_feeds(['https://example.com/sitemap.xml',
                                       'https://example.com/news/rss.xml']),
                         ['https://example.com/news/rss.xml'])


if __name__ == '__main__':
    unittest.main()
