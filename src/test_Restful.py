import unittest
from flask import Flask
from Restful import Image, TestOnly

class TestRestful(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_mime01(self):
        """Can we determine when we have JSON?"""
        with Flask(__name__).test_request_context(path='/', headers={'Accept': 'application/json'}):
            TestOnly.initlogger()
            objectundertest = Image()
            result = objectundertest.get_mime()
            self.assertEqual(result, 'application/json')

    def test_get_mime02(self):
        """Can we determine when we have JPEG?"""
        with Flask(__name__).test_request_context(path='/', headers={'Accept': 'image/jpeg'}):
            TestOnly.initlogger()
            objectundertest = Image()
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime03(self):
        """Can we default when nothing is supplied?"""
        with Flask(__name__).test_request_context(path='/', headers={'Accept': '*/*'}):
            TestOnly.initlogger()
            objectundertest = Image()
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

if __name__ == '__main__':
    unittest.main()
