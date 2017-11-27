import unittest
import logging
from flask import Flask
from Restful import Image

repo_logger = logging.getLogger("test_image_repository")

def accept_header(value):
    return Flask(__name__).test_request_context(path='/', headers={'Accept': value})

class TestRestful(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_mime01(self):
        """Can we determine when we have JSON?"""
        with accept_header('application/json'):
            objectundertest = Image(repo_logger = repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'application/json')

    def test_get_mime02(self):
        """Can we determine when we have JPEG?"""
        with accept_header('image/jpeg'):
            objectundertest = Image(repo_logger = repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime03(self):
        """Can we default when nothing is supplied?"""
        with accept_header('*/*'):
            objectundertest = Image(repo_logger = repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

if __name__ == '__main__':
    unittest.main()
