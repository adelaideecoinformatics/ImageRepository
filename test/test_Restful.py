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
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_jpeg))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = build_api('images', {'repo_logger': repo_logger, 'master': StubMaster()})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/jpeg'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/jpeg')
        data_has_jpeg_magic_bytes = result.get_data()[:2] == '\xff\xd8' and result.get_data()[-2:] == '\xff\xd9'
        self.assertTrue(data_has_jpeg_magic_bytes, msg="Body doesn't look like a JPEG")

    def test_get_image_png01(self):
        """Can we call the correct handler when we request PNG?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQAAAAA3bvkkAAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAAAmJLR0QAAKqNIzIAAAAJcEhZcwAACxMAAAsTAQCanBgAAAAHdElNRQfhCxwGHyMXY7jvAAAACklEQVQI12NoAAAAggCB3UNq9AAAABl0RVh0Q29tbWVudABDcmVhdGVkIHdpdGggR0lNUFeBDhcAAAAldEVYdGRhdGU6Y3JlYXRlADIwMTctMTEtMjhUMTY6MDk6NDIrMTE6MDBd/JF+AAAAJXRFWHRkYXRlOm1vZGlmeQAyMDE3LTExLTI4VDE1OjE2OjI1KzExOjAwoib2SAAAAABJRU5ErkJggg=='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_png))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = build_api('images', {'repo_logger': repo_logger, 'master': StubMaster()})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/png'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/png')
        self.assertEqual(result.get_data()[:8], '\x89\x50\x4e\x47\x0d\x0a\x1a\x0a', msg="Body doesn't look like a PNG")

    def test_get_image_tiff01(self):
        """Can we call the correct handler when we request TIFF?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_tiff = 'SUkqABIAAAB42msAAACBAIEAEgAAAQMAAQAAAAEAAAABAQMAAQAAAAEAAAACAQMAAQAAAAEAAAADAQMAAQAAAAgAAAAGAQMAAQAAAAEAAAAKAQMAAQAAAAEAAAARAQQAAQAAAAgAAAASAQMAAQAAAAEAAAAVAQMAAQAAAAEAAAAWAQMAAQAAAAEAAAAXAQQAAQAAAAkAAAAaAQUAAQAAAPAAAAAbAQUAAQAAAPgAAAAcAQMAAQAAAAEAAAAoAQMAAQAAAAMAAAApAQMAAgAAAAAAAQA+AQUAAgAAADABAAA/AQUABgAAAAABAAAAAAAA/////+qsBwn/////6qwHCQAK16P/////gOF6VP////8AzcxM/////wCamZn/////gGZmJv/////wKFwP/////4AbDVD/////AFg5VP////8='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_tiff))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = build_api('images', {'repo_logger': repo_logger, 'master': StubMaster()})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/tiff'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/tiff')
        self.assertEqual(result.get_data()[:4], '\x49\x49\x2a\x00', msg="Body doesn't look like a TIFF")

    def test_get_image_bmp01(self):
        """Can we call the correct handler when we request BMP?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_bmp = 'Qk2OAAAAAAAAAIoAAAB8AAAAAQAAAAEAAAABABgAAAAAAAQAAAATCwAAEwsAAAAAAAAAAAAAAAD/AAD/AAD/AAAAAAAA/0JHUnOAwvUoYLgeFSCF6wFAMzMTgGZmJkBmZgagmZkJPArXAyRcjzIAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAA////AA=='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_bmp))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = build_api('images', {'repo_logger': repo_logger, 'master': StubMaster()})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/bmp'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/bmp')
        self.assertEqual(result.get_data()[:2], '\x42\x4d', msg="Body doesn't look like a BMP")

    def test_get01(self):
        """Can we return a 406 when we request a unhandled type?"""
        app = build_api('images', {'repo_logger': repo_logger})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'test/alwaysfail'})
        self.assertEqual(result.status_code, 406)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['message'], u"Cannot handle the requested type 'test/alwaysfail'")
        self.assertEqual(len(body['accepted_mimes']), 6)

    def test_get02(self):
        """Assert that BPG isn't supported. Not that we have anything against it,
        we just can support it and the original code had minimal support for it."""
        app = build_api('images', {'repo_logger': repo_logger})
        app.testing = True
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/bpg'})
        self.assertEqual(result.status_code, 406)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['message'], u"Cannot handle the requested type 'image/bpg'")

if __name__ == '__main__':
    unittest.main()
