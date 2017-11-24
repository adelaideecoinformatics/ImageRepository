import unittest
from Restful import Image, TestOnly

class TestRestful(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_mime01(self):
        """Can we determine when we have JSON?"""
        TestOnly.initlogger()
        objectundertest = Image()
        result = objectundertest.get_mime('application/json')
        self.assertEqual(result, 'application/json')

    def test_get_mime02(self):
        """Can we determine when we have JPEG?"""
        TestOnly.initlogger()
        objectundertest = Image()
        result = objectundertest.get_mime('image/jpeg')
        self.assertEqual(result, 'image/jpeg')

    def test_get_mime03(self):
        """Can we default when nothing is supplied?"""
        TestOnly.initlogger()
        objectundertest = Image()
        result = objectundertest.get_mime('*/*')
        self.assertEqual(result, 'image/jpeg')

if __name__ == '__main__':
    unittest.main()
