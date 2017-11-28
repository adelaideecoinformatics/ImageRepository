import unittest
import logging
import json
from base64 import b64decode
from flask import Flask
from src.Restful import Image, build_api
from src.ImageType import ImageInstance, ImageHandle, ImageName

repo_logger = logging.getLogger("test_image_repository")

def accept_header(value):
    return Flask(__name__).test_request_context(path='/', headers={'Accept': value})

class TestRestful(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_mime01(self):
        """Can we determine when we have JSON?"""
        with accept_header('application/json'):
            objectundertest = Image(repo_logger=repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'application/json')

    def test_get_mime02(self):
        """Can we determine when we have JPEG?"""
        with accept_header('image/jpeg'):
            objectundertest = Image(repo_logger=repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime03(self):
        """Can we select the default type when anything is acceptable?"""
        with accept_header('*/*'):
            objectundertest = Image(repo_logger=repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime04(self):
        """Can we handle a specified type that we don't support?"""
        with accept_header('test/alwaysfail'):
            objectundertest = Image(repo_logger=repo_logger)
            result = objectundertest.get_mime()
            self.assertEqual(result, 'test/alwaysfail')

    def test_get_application_json01(self):
        """Can we call the correct handler when we request JSON?"""
        app = build_api('images', {'repo_logger': repo_logger})
        the_path = '/images/some_image'
        app.testing = True
        result = app.test_client().get(path=the_path, headers={'Accept': 'application/json'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['filename'], 'some_image.json')

    def test_get_image_jpeg01(self):
        """Can we call the correct handler when we request JPEG?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_jpeg = '/9j/4AAQSkZJRgABAQIAHAAcAAD//gATQ3JlYXRlZCB3aXRoIEdJTVD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=='
                handle = ImageHandle.from_bytes(the_bytes = b64decode(onepixel_jpeg))
                return ImageInstance(image_name = the_name, image_handle = handle)
        app = build_api('images', {'repo_logger': repo_logger, 'master': StubMaster()})
        the_path = '/images/some_image'
        app.testing = True
        result = app.test_client().get(path=the_path, headers={'Accept': 'image/jpeg'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/jpeg')
        data_has_jpeg_magic_bytes = result.get_data()[:2] == '\xff\xd8' and result.get_data()[-2:] == '\xff\xd9'
        self.assertTrue(data_has_jpeg_magic_bytes, msg="Body doesn't look like a JPEG")

    def test_get01(self):
        """Can we return a 406 when we request a unhandled type?"""
        app = build_api('images', {'repo_logger': repo_logger})
        the_path = '/images/some_image'
        app.testing = True
        result = app.test_client().get(path=the_path, headers={'Accept': 'test/alwaysfail'})
        self.assertEqual(result.status_code, 406)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['message'], u"Cannot handle the requested type 'test/alwaysfail'")
        self.assertEqual(len(body['accepted_mimes']), 6)

if __name__ == '__main__':
    unittest.main()
