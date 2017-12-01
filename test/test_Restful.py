"""Unit tests for Restful.py"""
import unittest
import logging
import mongomock
from base64 import b64decode
from flask import Flask, json
from src.Restful import build_app, build_api, SingleImageRouter, MetadataRecord
from src.ImageType import ImageInstance, ImageHandle

repo_logger = logging.getLogger("test_image_repository")

def get_app(path_base, master):
    """Builds a test-ready app without a mongo client"""
    def app_callback(app):
        app.config['REPO_LOGGER'] = repo_logger
        app.config['MASTER'] = master
        app.config['PARATOO_DB'] = None
    app = build_app(app_callback)
    build_api(app, path_base)
    return app

def accept_header(value):
    return Flask(__name__).test_request_context(path='/', headers={'Accept': value})

SingleImageRouterDeps = {
    'image_delegate': None,
    'metadata_record_delegate': None,
    'repo_logger': repo_logger
}
class TestSingleImageRouter(unittest.TestCase):

    def test_get_mime01(self):
        """Can we determine when we have JSON?"""
        with accept_header('application/json'):
            objectundertest = SingleImageRouter(**SingleImageRouterDeps)
            result = objectundertest._get_mime()
            self.assertEqual(result, 'application/json')

    def test_get_mime02(self):
        """Can we determine when we have JPEG?"""
        with accept_header('image/jpeg'):
            objectundertest = SingleImageRouter(**SingleImageRouterDeps)
            result = objectundertest._get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime03(self):
        """Can we select the default type when anything is acceptable?"""
        with accept_header('*/*'):
            objectundertest = SingleImageRouter(**SingleImageRouterDeps)
            result = objectundertest._get_mime()
            self.assertEqual(result, 'image/jpeg')

    def test_get_mime04(self):
        """Can we handle a specified type that we don't support?"""
        with accept_header('test/alwaysfail'):
            objectundertest = SingleImageRouter(**SingleImageRouterDeps)
            result = objectundertest._get_mime()
            self.assertEqual(result, 'test/alwaysfail')

class TestImage(unittest.TestCase):
    def test_get01(self):
        """Can we call the correct handler when we request JPEG?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_jpeg = '/9j/4AAQSkZJRgABAQIAHAAcAAD//gATQ3JlYXRlZCB3aXRoIEdJTVD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_jpeg))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = get_app('images', StubMaster())
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/jpeg'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/jpeg')
        data_has_jpeg_magic_bytes = result.get_data()[:2] == '\xff\xd8' and result.get_data()[-2:] == '\xff\xd9'
        self.assertTrue(data_has_jpeg_magic_bytes, msg="Body doesn't look like a JPEG")

    def test_get02(self):
        """Can we call the correct handler when we request PNG?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQAAAAA3bvkkAAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAAAmJLR0QAAKqNIzIAAAAJcEhZcwAACxMAAAsTAQCanBgAAAAHdElNRQfhCxwGHyMXY7jvAAAACklEQVQI12NoAAAAggCB3UNq9AAAABl0RVh0Q29tbWVudABDcmVhdGVkIHdpdGggR0lNUFeBDhcAAAAldEVYdGRhdGU6Y3JlYXRlADIwMTctMTEtMjhUMTY6MDk6NDIrMTE6MDBd/JF+AAAAJXRFWHRkYXRlOm1vZGlmeQAyMDE3LTExLTI4VDE1OjE2OjI1KzExOjAwoib2SAAAAABJRU5ErkJggg=='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_png))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = get_app('images', StubMaster())
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/png'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/png')
        self.assertEqual(result.get_data()[:8], '\x89\x50\x4e\x47\x0d\x0a\x1a\x0a', msg="Body doesn't look like a PNG")

    def test_get03(self):
        """Can we call the correct handler when we request TIFF?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_tiff = 'SUkqABIAAAB42msAAACBAIEAEgAAAQMAAQAAAAEAAAABAQMAAQAAAAEAAAACAQMAAQAAAAEAAAADAQMAAQAAAAgAAAAGAQMAAQAAAAEAAAAKAQMAAQAAAAEAAAARAQQAAQAAAAgAAAASAQMAAQAAAAEAAAAVAQMAAQAAAAEAAAAWAQMAAQAAAAEAAAAXAQQAAQAAAAkAAAAaAQUAAQAAAPAAAAAbAQUAAQAAAPgAAAAcAQMAAQAAAAEAAAAoAQMAAQAAAAMAAAApAQMAAgAAAAAAAQA+AQUAAgAAADABAAA/AQUABgAAAAABAAAAAAAA/////+qsBwn/////6qwHCQAK16P/////gOF6VP////8AzcxM/////wCamZn/////gGZmJv/////wKFwP/////4AbDVD/////AFg5VP////8='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_tiff))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = get_app('images', StubMaster())
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/tiff'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/tiff')
        self.assertEqual(result.get_data()[:4], '\x49\x49\x2a\x00', msg="Body doesn't look like a TIFF")

    def test_get04(self):
        """Can we call the correct handler when we request BMP?"""
        class StubMaster:
            def contains_original(self, image_name, regexp):
                return True

            def get_as_defined(self, the_name):
                onepixel_bmp = 'Qk2OAAAAAAAAAIoAAAB8AAAAAQAAAAEAAAABABgAAAAAAAQAAAATCwAAEwsAAAAAAAAAAAAAAAD/AAD/AAD/AAAAAAAA/0JHUnOAwvUoYLgeFSCF6wFAMzMTgGZmJkBmZgagmZkJPArXAyRcjzIAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAA////AA=='
                handle = ImageHandle.from_bytes(the_bytes=b64decode(onepixel_bmp))
                return ImageInstance(image_name=the_name, image_handle=handle)
        app = get_app('images', StubMaster())
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/bmp'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'image/bmp')
        self.assertEqual(result.get_data()[:2], '\x42\x4d', msg="Body doesn't look like a BMP")

    def test_get05(self):
        """Can we return a 406 when we request a unhandled type?"""
        app = get_app('images', None)
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'test/alwaysfail'})
        self.assertEqual(result.status_code, 406)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['message'], u"Cannot handle the requested type 'test/alwaysfail'")
        self.assertEqual(len(body['accepted_mimes']), 5)

    def test_get06(self):
        """Assert that BPG isn't supported. Not that we have anything against it,
        we just can support it and the original code had minimal support for it."""
        app = get_app('images', None)
        result = app.test_client().get(path='/images/some_image', headers={'Accept': 'image/bpg'})
        self.assertEqual(result.status_code, 406)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['message'], u"Cannot handle the requested type 'image/bpg'")

class TestMetadata(unittest.TestCase):
    def setUp(self):
        def conf(app):
            app.config['REPO_LOGGER'] = logging.getLogger('test_image_repository')
            app.config['MASTER'] = None
            app.config['PARATOO_DB'] = mongomock.MongoClient().db
        self.app = build_app(conf)
        self.db = self.app.config['PARATOO_DB']
        build_api(self.app, 'images')

    def test_get01(self):
        """Can we get something that we've uploaded?"""
        self.app.test_client().post(
            path='/images/some_image',
            headers={'Accept': 'application/json'},
            data=json.dumps({
                "field1": 123,
                "field2": "foo",
                "field3": ["bar1", "bar2"]
            }))
        result = self.app.test_client().get(
            path='/images/some_image',
            headers={'Accept': 'application/json'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['field1'], 123)
        self.assertEqual(body['field2'], 'foo')
        self.assertEqual(body['field3'], ['bar1', 'bar2'])

    def test_get02(self):
        """Do we get a 404 when we request something that doesn't exist?"""
        result = self.app.test_client().get(
            path='/images/some_image',
            headers={'Accept': 'application/json'})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.headers['Content-type'], 'application/json')

    def test_get03(self):
        """Can we verify a mongo document has the expected fields?"""
        collection = MetadataRecord._get_collection(self.db)
        collection.insert_one({'_id': 'explode'})
        result = self.app.test_client().get(
            path='/images/explode',
            headers={'Accept': 'application/json'})
        self.assertEqual(result.status_code, 500)

    def test_post01(self):
        """Do we get a 500 when we post invalid JSON in the body?"""
        # FIXME stop the InternalServerError message from showing in the logs, it's expected
        result = self.app.test_client().post(
            path='/images/some_image',
            headers={'Accept': 'application/json'},
            data='{"invalidJSON":...')
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.headers['Content-type'], 'application/json')

    def test_post02(self):
        """Can we overwrite an existing metadata record?"""
        firstpost = self.app.test_client().post(
            path='/images/some_image',
            headers={'Accept': 'application/json'},
            data='{"version":1}')
        self.assertEqual(firstpost.status_code, 201)
        secondpost = self.app.test_client().post(
            path='/images/some_image',
            headers={'Accept': 'application/json'},
            data='{"version":2}')
        self.assertEqual(secondpost.status_code, 201)
        result = self.app.test_client().get(
            path='/images/some_image',
            headers={'Accept': 'application/json'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Content-type'], 'application/json')
        body = json.loads(result.get_data())
        self.assertEqual(body['version'], 2)

if __name__ == '__main__':
    unittest.main()
