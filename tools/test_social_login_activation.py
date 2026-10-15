import unittest
from unittest.mock import patch
import social_login as login


class ActivationTests(unittest.TestCase):
    def test_douyin_only_can_activate(self):
        config={'enabled':False,'platforms':{'douyin':{'account':'news','confirmed':True},
                                           'bilibili':{'account':'news','confirmed':False,'tid':None}}}
        with patch.object(login,'config',return_value=config), patch.object(login,'account_check',return_value=(True,'')) as check, patch.object(login,'atomic_json') as save:
            self.assertTrue(login.activate())
        check.assert_called_once_with('douyin','news')
        self.assertTrue(save.call_args.args[1]['enabled'])

    def test_bound_bilibili_without_category_does_not_block_douyin(self):
        config={'enabled':False,'platforms':{'douyin':{'account':'news','confirmed':True},
                                           'bilibili':{'account':'news','confirmed':True,'tid':None}}}
        with patch.object(login,'config',return_value=config), patch.object(login,'account_check',return_value=(True,'')), patch.object(login,'atomic_json'):
            self.assertTrue(login.activate())

    def test_no_bound_account_does_not_activate(self):
        config={'enabled':False,'platforms':{'douyin':{'account':'news','confirmed':False}}}
        with patch.object(login,'config',return_value=config), patch.object(login,'account_check') as check, patch.object(login,'atomic_json') as save:
            self.assertFalse(login.activate())
        check.assert_not_called();save.assert_not_called()


if __name__=='__main__':unittest.main()
