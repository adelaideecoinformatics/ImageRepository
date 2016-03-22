import swiftclient
import swiftclient.service
import os
import logging
import traceback
import time

from Exceptions import RepositoryError
from Exceptions import RepositoryFailure
from ImageNames import ImageName

class ImageStore(object):
    """
    Base class to provide access to a persistent store where ImagesInstances are kept
    """

    def __init__(self, configuration, cache):
        self._configuration = configuration
        self._download_path = configuration.download_path
        self._credentials = configuration.credentials
        self._store = configuration.container
        self._directory = None
        self._my_cache = cache
        self._logger = logging.getLogger("image_repository")
        
    def get_images(self, base_name):
        pass

    def get_image(self, image_name):
        images = self.get_images([image_name])
        if len(images) != 1:
            self._logger.error("{}  Image retrieval failed for {}, {}".format(self.__class__.__name__, image_name, len(images)))
            raise RepositoryFailure
        else:
            return images[0]

    def store_image(self, image):
        pass

    def delete_image(self, image):
        """
        Delete an image by name from the store
        """
        pass

    def list_images(self):
        """
        Returns a list of all images in the store
        """
        return None
        
    def get_metadata(self, image):
        """
        Returns the XML image metadata for an image if the store supports it.
        """
        return None

    def stats(self):
        """
        Returns a tuple of critical stats for the store
        (bytes_used, object_count)       
        """
        return (0,0)

    def temporary_url(self, lifetime = None):
        """
        Return a URL that can be used to access to element externally.

        Where supported the URL should be temporary, with a lifetime as specified

        :param: lifetime number: Time the URL should remian valid for, in seconds
        :returns: URL string.
        """
        raise RepositoryFailure
        

class SwiftImageStore(ImageStore):

    def __init__(self, configuration, cache):
        super(SwiftImageStore, self).__init__(configuration, cache)

        self._use_file_cache = configuration.use_file_cache
        self._file_cache = None
        self._file_cache_path = None

        self._health_attempts = 0
        self._health_operations = 0
    
        try:
            options = {}
            options["os_username"] = self._credentials._the_username
            options["os_authurl"] = self._credentials._the_authurl
            options["os_tenant_name"] = self._credentials._the_tenant_name
            options["os_key"] = self._credentials._the_password
            
            self._swift = swiftclient.service.SwiftService(options)

            self._swift_connection = swiftclient.service.get_conn(self._swift._options)

            self._credentials.clear_password()

            #            Wipes the store - don't use this unless testing!!!
            if configuration.initialise_store:
                self.initialise_store()


        except swiftclient.exceptions.ClientException as ex:
            self._logger.exception("Exception in connection to Swift store")
            raise RepositoryError
#            exit(1)
        except Exception as ex:
            self._logger.exception("Unhandled exception during connection to Swift store")
            raise RepositoryError
#            exit(1)

    def _health(self, attempts = 0):
        """
        Perform some local health monitoring, to understand how well the store is performing and signal
        and possible issues.
        """
        self._health_attempts += attempts
        self._health_operations += 1
            
    def __str__(self):
        the_string = "Swift Store:\n"
        the_string += "    user        :   {}\n".format(self._credentials.the_username)
        the_string += "    tenant      :   {}\n".format(self._credentials.the_tenant_name)
        the_string += "    download to :   {}\n".format(self._download_path)
        the_string += "    attempts    :   {}\n".format(self._health_attempts)
        the_string += "    operations  :   {}\n".format(self._health_operations)
        the_string += "    \n".format()
        
        return the_string

    def set_file_cache(self, cache):
        self._file_cache = cache
        self._file_cache_path = cache._file_cache_path
    
    def list_images(self):
        options = {"long" : True}
        results = self._swift.list(self._store, options)
        listing = []
        for result in results:  # In principle it seems we could have more than one, although it doesn't seem to happen.
            if result["success"]:
                for element in result["listing"]:
                    listing.append((element["name"], element["bytes"], element["content_type"]))
            else:
                self._logger.error("Failure in Swift container listing : {}".format(result["error"]))
                raise RepositoryError

        return listing


    def download_images(self, image_names, path):
        """
        Downloads the specified images from the store and places them into the specified directory.
        :param: image_names: list of the image names to download
        :parm: path string: full path of where to place the images
        """
        image_paths = []
        try:
            result, the_image =  self._swift_connection.get_object(container = self._store, obj = image_names[0]) 

            if "content-length" in result:
                size_downloaded = result['content-length']
                self._logger.debug("{}   : Downloaded image {} of {} bytes".format(self.__class__.__name__, image_names[0], size_downloaded))
            else:
                if "error" in result:
                    if isinstance(result["error"], Exception):
                        traceback.print_exc()
                        self._logger.exception("Swift image download fails for {} {}\n{}".format(self._store, image_names, result['error']))
                    else:
                        self._logger.error("Swift image download of {} {} fails with {}".format(self._store, image_names, result["error"]))
                else:
                    self._logger.error("Swift image download returns failure for {}\n{}".format(image_names[0], result))

        except (swiftclient.client.ClientException, swiftclient.service.SwiftError) as ex:
            self._logger.exception("Swift Client Exception in download of Swift images {}".format(image_names))
            raise RepositoryError("Swift Client Exception in download of Swift images {}".format(image_names))
        except Exception as ex:
            self._logger.exception("Unhandled exception during download of images {}".format(image_names))
            raise RepositoryError("Unhandled exception during download of images {}".format(image_names))

        try:
            the_filename = os.path.join(path, ImageName.safe_name(image_names[0]))
            image_paths.append((image_names[0],the_filename))
            with open(the_filename, 'w') as the_file:
                the_file.write(the_image)
        except IOError:
            self._logger.exception("Error in writing file {}".format(image_names[0]))
            raise RepositoryError("Error in writing file {}".format(image_names[0]))
            
        return image_paths


    def get_images(self, image_names):
        if self._use_file_cache:
            path = self._file_cache_path
            the_images = self.download_images(image_names, path)
            self._logger.info("Downloaded {} images from Swift for {}".format(len(the_images), image_names))
            full_paths = []
            for image_name, image_path in the_images:
                # add the upload location as a source to the image handle
                handle = self._my_cache._contents[image_name].image.get_image_handle()
                the_image = self._my_cache._contents[image_name].image
                handle.add_file_path(image_path)
                if self._configuration.use_file_cache:
                    # Are we using the same local file area to stage uploads as the local file cache?
                    # If so, inform the file cache that there is a new image in that area
                    # This may trigger a cache clean of the local file cache some time in the future.
                    self._file_cache.add_image_handle(image_name, the_image)
                full_paths.append(image_path)

        else:
            pass
                
        return full_paths
    
    def get_images1(self, image_names):
        the_images = []
        try:
            """
 
            """
            options = {}
            response = self._swift.download(self._store, image_names, options)
            for result in response:

                if result["success"]:
                    the_images.append(result["object"])
                    logger.debug("{}   Downloaded images {}".format(self.__class__.__name__, image_names))
                else:
                    if result.haskey("error"):
                        if isinstance(result["error"], Exception):
                            self.logger.exception("Image download fails for {}\n{}".format(result["path"],result["error"]))
                        else:
                            self.logger.error("Image download of {} fails with {}".format(result["path"], result["error"]))
                    else:
                        self.logger.error("Image download returns failure for {}".format(result["path"]))
                    continue
        except (swiftclient.client.ClientException, swiftclient.service.SwiftError) as ex:
            self._logger.exception("Exception in download of images {}".format(image_names))
            raise RepositoryError
        except Exception as ex:
            self._logger.exception("Unhandled exception during download of images {}".format(image_names))
            raise RepositoryError
        return the_images



    def store_images_async(self, images ):
        """
        Queues a list of name:image pairs for storage to the Swift server

        """
        # Add to upload queue

        # Check there is an upload process running, start if not


    def store_image(self, image, name):
        """
        Upload an image to the Swift store

        :param: image: byte stream object (ie wand.image.blob)
        :param: name: string - name the image will have in the store
        returns: path to uploaded image
        """        
        try:
            options = {}
            swift_upload = [swiftclient.service.SwiftUploadObject(image, object_name = name)]

            response = self._swift.upload(self._store, swift_upload, options)

            for result in response:
                if result["success"]:
                    pass
                    # self._logger.debug("Uploaded image {}".format(name))
                else:
                    if result.haskey("error"):
                        if isinstance(result["error"], Exception):
                            self._logger.exception("{}    Image upload fails for {}\n".format(self.__class__.__name__, name, result["error"]))
                        else:
                            self._logger.error("{}   Image upload fails for {} with {}".format(self.__class__.__name__, name, result["error"]))
                    else:
                        self._logger.error("{}   Image upload returns failure for {}".format(self.__class__.__name__, name))
                    continue

            self._logger.info("{}   Image uploaded {}".format(self.__class__.__name__, name))
            return name
        except (swiftclient.client.ClientException, swiftclient.service.SwiftError) as ex:
            self._logger.exception("Exception in upload of images {}".format(image))
            raise RepositoryError
        except Exception as ex:
            self._logger.exception("Unhandled exception during upload of images {}".format(images))
            raise RepositoryError

    
    def delete_images(self, image_names):
       try:
            options = {}
            response = self._swift.delete(self._store, image_names, options)
            for result in response:
                if result["success"]:
                    self._logger.debug("Deleted image {}".format(image_names))
                else:
                    if "error" in result:
                        if isinstance(result["error"], Exception):
                            self._logger.exception("Image deletion fails for {}\n{}".format(image_names, result["error"]))
                        else:
                            self._logger.error("Image deletion of {} fails with {}".format(image_names, result["error"]))
                    else:
                        self._logger.error("Image deletion returns failure for {}".format(image_names))
                    continue
       except (swiftclient.service.ClientException, swiftclient.service.SwiftError) as ex:
           self._logger.exception("Exception in deletion of images {}".format(image_names))
           raise RepositoryError
       except Exception as ex:
           self._logger.exception("Unhandled exception during deletion of images {}".format(image_names))
           raise RepositoryError
        


    def initialise_store(self):
        images = self.list_images()
        for image in images:
            self.delete_images([image[0]])
            
    def stats(self):

        """
        :returns: dict with keys: 
        account, 
        container, 
        created_at,
        put_timestamp, 
        delete_timestamp, 
        status_changed_at,
        object_count, 
        bytes_used, 
        reported_put_timestamp,
        reported_delete_timestamp, 
        reported_object_count,
        reported_bytes_used, 
        hash, 
        id, 
        x_container_sync_point1,
        x_container_sync_point2,
        storage_policy_index
        """
        
        try:
            options = {}
            stats = self._swift.stat(self._store, None, options)

            if stats["success"]:
                the_string = "Swift stats:\n"
                for x,y in stats["items"]:
                    the_string += "{}     :   {}\n".format(x,y)
                return the_string
            else:
                self._logger.error("Failure in Swift container stat : {}".format(stats["error"]))
                return None
            
        except (swiftclient.service.SwiftError) as ex:
            self._logger.exception("Exception in container stat {}".format(self._store))
            raise RepositoryError
        except Exception as ex:
            self._logger.exception("Unhandled exception during container stat {}".format(self._store))
            raise RepositoryError



    def account_stats(self):        
        """Gets a dict of the form
        
        :rtype: dict
        :raises: RepositoryError

        name: name of the container to create
        put_timestamp: put_timestamp of the container to create
        delete_timestamp: delete_timestamp of the container to create
        object_count: number of objects in the container
        bytes_used: number of bytes used by the container
        storage_policy_index:  the storage policy for this container        
        """

        try:
            options = {}
            stats = self._swift.stat(None, None, options)
            return (stats["name"])
        except (swiftclient.service.SwiftError) as ex:
            self._logger.exception("Exception in container stat {}".format(self._store))
            raise RepositoryError
        except Exception as ex:
            self._logger.exception("Unhandled exception during container stat {}".format(self._store))
            raise RepositoryError        

    @staticmethod
    def _check_response(response, context):
        """Check that a Swift response dict is OK, and handle any errors

        Note:
        The response object can only be traveresed once!!!
        If it is required that both checking for errors and actual results must be
        found in the result, this routine should not be used.

        Returns True if the response is error free
        Returns False if there was a failure
        Raises RepositoryError is there was an error

        :param response: the response dict
        :type response: dict
        :param context: A string describing the context of the response, used for error string
        :type context: string

        :rtype: boolean
        :raises: RepositoryError
        """

        def check_single_response(response):
            result = True
            if response["success"]:
                return True
            else:
                if response.haskey("error"):
                    result = False
                    if isinstance(result["error"], Exception):
                        self._logger.exception("{}   {} response error: \n{}".format(self.__class__.__name__, name, response["error"]))
                    else:
                        self._logger.error("{}  {} response error: \n{}".format(self.__class__.__name__, name, response["error"]))
            return result
                        
        if isinstance(response, dict):
            return check_single_response(response)
        else:
            result = True
            for response_instance in response:
                result &= check_single_response(response_instance)
            return result
                
    def _write_metadata(self, name, metadata):
        """Add the provided metadata to the object in the store

        :param name: Name of the object
        :type name: string
        :param metadata: The metadata to add
        :type metadata: list 
        :raises: RepositoryError
        """
        try:
            response = self._swift.post(container = self._configuration.container,
                                        objects = [str(name)],                       
                                        options = { 'meta' : metadata }
            )
            self._check_response(response, "Addition of metadata for object {}".format(name))
        except (swiftclient.client.ClientException, swiftclient.service.SwiftError) as ex:
            self._logger.exception("Addition of metadata failed for object {}".format(name))
            raise RepositoryError("Addition of metadata failed for object {}".format(name))    


    def _read_metadata(self, names):
        """Return a list of all the application metadata set on the named objects

        :param name: Name of the object to find metadata for
        :type name: string
        :rtype: list of tuples
        :raises: RepositoryError
        """
        response = None
        results = []
        try:
            response = self._swift.stat(container = self._configuration.container,
                                        objects = names
            )

            if isinstance(response, dict):
                headers = [(response['object'], response['headers'])]
            else:
#                headers = []
#                for thing in response:
#                    if 'headers' in thing.keys():
#                        headers.append((thing['object'], thing['headers']))

                headers = [ (thing['object'], thing['headers']) for thing in response if 'headers' in thing.keys() ]

            for the_object, the_header in headers:
                metadata = {}
                for the_key in the_header.iterkeys():
                    if "x-object-meta-" in the_key:
                        metadata[the_key] = the_header[the_key]
                results.append((the_object, metadata))

            return results
        except (swiftclient.client.ClientException, swiftclient.service.SwiftError) as ex:
            self._logger.exception("Read of metadata failed for object {}".format(name))
            raise RepositoryError("Read of metadata failed for object {}".format(name))  

    def find_metadata(self, names, metadata_keys):
        """Find the requested application metadata for an object

        :param name: The names of the objects
        :type name: list
        :param metadata: List of metadata items to find for each object
        :type metadata: list
        :rtype: list of pairs (name, dict)

        Swift automatically prepends x-object-meta- to the start of application created metadata items.
        This routine will find every object in the store in the list of names, and will find every
        metadata item that starts with x-object-meta- for each object.  It creates a list of tuples
        (object_name, meta_dictionary) where the dictionary contains the application metadata for which
        the names match the names in the list metadata_keys (without the prefix x-object-meta-)

        Annoyingly Swift has added x-object-meta-mtime to the standard object metadata, which means
        we always have a large list to process.
        """
        results = []
        meta = self._read_metadata(names)
        for the_object, the_meta in meta:
            the_metadata = {}
            useful = False
            for key in metadata_keys:
                if "x-object-meta-{}".format(key) in the_meta.keys():
                    the_metadata[key] = the_meta["x-object-meta-{}".format(key)]
                    useful = True
            if useful:
                results.append((the_object, the_metadata))
        return results
    
    def temporary_url(self, name, lifetime = None):
        """
        Return a URL for the instance
        :param name: Name of object in store
        :type name: string
        :param lifetime: time in seconds since the epoch the URL should be valid until.
        :type lifetime: integer

        """
        if lifetime is None:
            lifetime = self._configuration.url_lifetime
            
        key = self._configuration.url_key
        method = self._configuration.url_method
        path =  "/v1/AUTH_" + self._configuration.credentials._the_tenant_id + "/" + self._configuration.container + "/" + str(name)
        url = swiftclient.utils.generate_temp_url(path, lifetime, key, method, absolute=False)
        # need to record that the url has been generated so that the image isn't deleted during a cleanup
        # Something of a problem as we don't want to lose this information between server instances
        # Maybe add a metadata item to the stored object in the Swift store
        #        self._url_expiry = now + seconds

        self._write_metadata(name, [ u'lifetime:{}'.format(lifetime) ] )
#        metadata = self._read_metadata(name)
        return self._configuration.server_url + url

        
def test(configuration = None):


    store_name = configuration.server
    credentials = configuration.credentials
    
    swift = SwiftImageStore( store_name, credentials)
    swift.set_logger(configuration._logger)

    print swift
    print swift.stats()
    
if __name__ == "__main__":
    test()
