import json
import unittest
from synthesize_seed_voice import classify_http_failure

class SeedFailureTests(unittest.TestCase):
    def test_resource_permission_is_not_retried_or_exposed(self):
        body=json.dumps({'header':{'code':45000030,'message':'resource not granted; secret=DO_NOT_ECHO'}}).encode()
        result=classify_http_failure(403,body)
        self.assertEqual(result['reason'],'resource_not_granted')
        self.assertFalse(result['retryable'])
        self.assertNotIn('DO_NOT_ECHO',json.dumps(result))
    def test_transient_and_permanent_errors_are_distinct(self):
        for status in [429,500,502,503]:
            self.assertTrue(classify_http_failure(status,b'private raw response')['retryable'])
        for status in [400,401,403,404]:
            self.assertFalse(classify_http_failure(status,b'private raw response')['retryable'])
    def test_malformed_response_does_not_break_safe_receipt(self):
        self.assertEqual(classify_http_failure(403,b'bad json')['http_status'],403)
        self.assertIsNone(classify_http_failure(403,b'bad json')['provider_code'])

if __name__=='__main__':unittest.main()
