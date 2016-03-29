"""
We provide access to the image repository via a RestFul interface.

This a provided by the RestFul Flask library.

We use the Marshmallow Schema and parsing library rather than the Flask one
as it is indicated that the Flask system is deprecated, and Marshmallow is preferred.



"""

import uuid
import os
import os.path
import tempfile
import zipfile
import logging
from flask import Flask
from flask_restful import reqparse, abort, Api, Resource
from flask_restful import fields
from flask_restful import inputs
from flask_restful import request
from flask import send_file

from marshmallow import Schema, fields, ValidationError, pre_load, validates

from ImageNames import ImageName
import ImageType
import Caches
import Configuration
import Stores
from Exceptions import RepositoryError, RepositoryFailure


#app = Flask(__name__)

master = None
repo = None
repo_logger = None

# TODO - make this list complete - use Wand's definitions
valid_image_formats = ["jpg","tif","png", "bmp","bpg"]

class ImageSchema(Schema):
    """Schema for requests for an image within the repository including derived images
    """
    xsize = fields.Int(missing = None, default = None)
    ysize = fields.Int(missing = None)
    kind = fields.Str(missing = 'jpg')
    thumbnail = fields.Boolean(missing = False)
    url = fields.Boolean(missing = False)
    meta = fields.Boolean(missing = False)
    regex = fields.Str(missing = None)

    @validates('kind')
    def validate_kind(self, value):
        if value.lower() not in valid_image_formats:
            raise ValidationError("{} is not a valid image format".format(value))
    
    @validates('xsize')
    def validate_x_size(self, value):
        if value is None:
            return True
        if value <= 0 or value >= 10000:
            raise ValidationError("Image xsize {} is unreasonable".format(value))

    @validates('ysize')
    def validate_y_size(self, value):
        if value is None:
            return True
        if value <= 0 or value >= 10000:
            raise ValidationError("Image ysize {} is unreasonable".format(value))
        
class ImageUpload(Schema):
    """Schema for requests to upload an image to the repository
    """
    username = fields.Str(missing = None)
#    name = fields.Str(required = True)   # Not using this - using path name of URL
    
    
class Image(Resource):
    """
    """
    def get(self, image_name):

        try:
            args, errors = ImageSchema(strict=True).load(request.args)
        except ValidationError as ex:
            abort(400, message = ex.messages)
#            return ex.messages, 500
        
        # Find if the original image exists

        # In principle we could have both an image_name and a regex.
        # Currently the regex takes precedence.  TODO - We could contrive a
        # a reasonable way of combining the two - at least for some values.
        regexp = args['regex']
        try:
            if regexp is not None:
                if image_name is not None and image_name[-1] != u'/':
                    image_name += u'/'

                image_names = master.list_base_images(image_name, regexp)

                if len(image_names) == 0:
                    abort(404, message="No images match '{}  regex={}'".format( '' if image_name is None else image_name, regexp))
            else:
                if image_name is None or len(image_name) == 0 or image_name[-1] == u'/':
                    regexp = '\S+'   # path ends in a /  - make it a directory like search
                    image_names =  master.list_base_images(image_name, regexp)
                    if len(image_names) == 0:
                        abort(404, message="No images found in '{}'".format(image_name if image_name is not None else '/'))                    
                else:
                    if not master.contains_original(image_name, regexp):
                        print image_name, regexp
                        abort(404, message="Image '{}' not found".format(image_name))
                    image_names = [image_name]
            
            # If it is metadata request, we can just return that now.
            if args['meta']:                
                return [ ( str(image.name), image._get_metadata()) for image in master.get_original_images(image_names, regexp) ]

            # Otherwise it is an image request
            # Name includes desired image format
            new_names = [ImageName(the_name, kind = args['kind']) for the_name in image_names]
            
            # Simple default behaviour for size parameters
            x_size = None
            y_size = None

            if args['xsize'] is not None:
                x_size = args['xsize']
            if args['ysize'] is not None:
                y_size = args['ysize']
                    
            if x_size is None:
                x_size = y_size
            if y_size is None:
                y_size = x_size

            if args['thumbnail']:
                for the_name in new_names:
                    the_name.apply_thumbnail((args['xsize'], args['ysize']), kind = args['kind'])
            else:
                if x_size is not None or y_size is not None:
                    for the_name in new_names:
                        the_name.apply_resize((x_size, y_size), kind = args['kind'])

            new_images = [ master.get_as_defined(the_name) for the_name in new_names ]
            
            # If a URL is requested we generate that and return it
            if args['url']:
                return [the_image.url() for the_image in new_images]

            # Otherwise we return the actual image
            if len(new_images) == 1:        
                return send_file(new_images[0].as_filelike(), mimetype = new_images[0].mimetype())
            else:
                # Only way to return multiple files is to create a zip archive and send that
                the_uuid = str(uuid.uuid1())
                the_temp_file = os.path.join("/var/tmp", the_uuid + ".zip")
                zf = zipfile.ZipFile(the_temp_file, "w", zipfile.ZIP_DEFLATED)
                for the_image in new_images:
                    filename = master.as_local_file(str(the_image.name))                    
                    imagename = str(the_image.name)
                    repo_logger.debug("Adding {} as {} to zip archive".format(filename, imagename))
                    
                    zf.write(filename = filename, arcname = imagename)
                zf.close()
                return send_file(the_temp_file, mimetype = 'application/zip')
        except (RepositoryError, RepositoryFailure) as ex:
            return ex.http_error()

        
    @staticmethod
    def _allowed_file(filename):
        """Sanity check that the only file types we operate upon are images or metadata from images
        
        Image types should be the same set of types supported by Wand.Image or a subset thereof.
        """
        return '.' in filename and \
            filename.rsplit('.', 1)[1] in valid_image_formats
        
    def delete(self, image_name):
        """DELETE operation
        
        Request deletion of the image.
        This becomes complex as deletion of derived images may make no sense.
        Deletion of an original image should require the deletion of all derived images.
        Further authentication/authorisation may be reasonable.
    """
        return 'Deletion not currently supported', 204

    def put(self, image_name):
        return None, 201

    
    def post(self, image_name):
        """POST operation
        
        :param image_name: Path of image as described in the resquest URL
        :type image_name: string
        
        Allows upload of file. 
        
        The file name it will have within the repository is the path of the request 

        
        If the path includes an image name the filename in the upload is ignored, although we may do some sanity checking on type.
        If the path terminates in a ``/`` we use the filename as passed by the upload, and the path as a psuedo-directory specification
        """
        try:
            args, errors = ImageUpload(strict=True).load(request.args)
        except ValidationError as ex:
            abort(400, message = ex.messages)
        file_req = request.files['file']
        
        if file_req is not None:
            if not self._allowed_file(file_req.filename):
                return 'Filename {} is not a supported file type'.format(file_req.filename), 415

            if image_name[-1] == '/':
                image_name += file_req.filename
            else:
                # Is a full pathname
                # Has a suffix
                if len(image_name.rsplit('.', 1)) > 1:                
                    if not self._allowed_file(image_name):
                        return 'Target name {} is not a supported file type'.format(image_name), 415
                else:
                    # assume it is a base name, turn it into a full name
                    # use the suffix of the input file - which has already been checked
                    image_name += "." + file_req.filename.rsplit('.', 1)[1]
            try:
                the_name = ImageName.from_raw((image_name))
                image = ImageType.OriginalImage.from_filelike(file_req, name = the_name, full_name = True)
                the_name.set_original(True)
                master.add(the_name, image)
                master.make_persistent(the_name)
            except (RepositoryError, RepositoryFailure) as ex:
                return ex.http_error()
            return "{}".format(image.name.base_name())  # Return the name by which the repository addresses the image
        

class Image1(Image):
    def get(self):
        return super(Image1, self).get(None)
        
        
class ListSchema(Schema):
    regex = fields.Str(missing = None)
    
class ImageList(Resource):
    """Interface provides an endpoint at ``/images`` which allows listing and upload

    """
    def get(self):
        """GET operation

        GET requests can either list the entire repository from ``../images`` down, or
        a regexp can be provided that allows for filtering the traverse - essentially allowing for
        traversal of sub-directories, and for some other useful searches
        """
        try:
            args, errors = ListSchema(strict=True).load(request.args)
        except ValidationError as ex:
            abort(400, message = ex.messages)
        regexp = args['regex']
        #  Some sanity checking on the regexp here?
        try:
            return master.list_base_images(regexp = regexp)
        except (RepositoryError, RepositoryFailure) as ex:
            return ex.http_error()
            
    def post(self):
        """POST operation 

        Allows upload of files, with the name of the file within the repository as defined in the upload.
        Not allowing this currently. 
        """
        return "Operation not supported. Upload files relative to images/  ", 405        


def prestart():
    """Bring up the image repository to the point where we can field requests"""
    global master, repo
    repo.repository_start()  # load the cache controllers ready to begin fielding requests
    master = repo.cache_master() # master is the interface to the caches
        
def startup(app):
    """Configure and run the repository

    :param app: the Flask application instance that will control us
    :type app: Instance of Flask
    """
    global master, repo, repo_logger

    repo = Configuration.ImageRepository()
    repo.repository_server()    # perform instantiation of static components
    repo_logger = logging.getLogger("image_repository")    
    path_base = repo.configuration().repository_base_pathname

    api = Api(app)
    api.add_resource(ImageList, '/{}'.format(path_base), methods = ['GET'])
    api.add_resource(Image, '/{}/<path:image_name>'.format(path_base), methods = ['GET', 'POST', 'DELETE'])
    api.add_resource(Image1, '/{}/'.format(path_base), methods = ['GET'])

    app.before_first_request(prestart) # defer startup until we need to load the caches etc. 
    app.run(debug=True)         # Away we go

def main():
    """Bring up the server as a simple, single app, Flask instance."""
    app = Flask('image_repo')
    startup(app)
    
if __name__ == '__main__':
    main()
