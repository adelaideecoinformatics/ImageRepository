"""
Image Handling
--------------

Encapsulates images and the processing of images.  Further, associates images
with ImageNames, and interfaces with Cache implementations.

Provides for lazy generation and importation of images in an attempt to avoid or
spread out cost of moving data.

Images are managed by the Wand library, which itslef provides a layer over the ImageMagik image
processing libraries.
"""

from ImageNames import ImageName
import os
import wand.image
import hashlib
import uuid
import cStringIO
import Stores
import wand.exceptions
import logging
import weakref
from threading import RLock

from Exceptions import RepositoryError
from Exceptions import RepositoryFailure

logger = logging.getLogger("image_repository")

class ImageHandle(object):
    """Encapsulates the notion of a handle on an image.

    Images may exist in:

    * Persistent storage (ie Swift)
    * Local file system (ie ``/var/tmp/xxx``)
    * In memory (ie as a blob of bytes, or a Wand ``wand.image.Image`` object)

    An image can exist in more than one of these at once.

    The class allows a client object to refer to the image abstractly, and only when it is
    required that data is present (to serve an image, or derive an image) will the data be
    loaded. This class abstracts over the location of the data, and handles all interfacing to
    storeage and caches.
    """

    _configuration = None   # The system wide configuration for managing ImageHandles


    @classmethod
    def set_configuration(cls, config):
        """Set the configuration for the class

        :param config:  The configuration that covers defaults and policies for this class
        :type config: instance of Configuration
        """
        cls._configuration = config

    _cache = None
       
    def __init__(self,
                 filename = None,
                 filelike = None,
                 store = None,
                 path = None,
                 bytes = None,
                 kind = None,
                 image = None,
                 eager = False,
                 size = 0):

        """Class constructor

        : Note
        This constructor is not intended to be directly used.  The classmethods provided
        call this method as approriate to the manner in which the image is created.

        :param filename: Path to the image in a local file system
        :type filename: string
        :param filelike: Image contained in a file-like stream object
        :type filelike: Python file-like object
        :param store: Persistent store where the image resides
        :type store: Store
        :param path: Path is the persistgent store to find the image
        :type path: string
        :param bytes: image as a simple collection of bytes
        :type bytes: byte blob
        :param kind: ImageMagik definition of image format
        :type kind: string
        :param image: encapsulated image for use by Wand/ImageMagik
        :type image: wand.image.Image
        :param eager: Whether to immeadiatly load the data
        :type eager: Boolean
        :param size: Size of the image if known
        :type size: integer
        """
        
        # Add whatever is needed to create a full path name here.
        self._local_file_path = filename 
        self._bytes = bytes
        self._persistent_path = path
        self._persistent_store = store
        
        if image is None:
            self._kind = kind     # how the image is encoded.  String, must be a member of the Wand.images supported types
        else:
            self._kind = image.format  # if we have a Wand image, believe it rather than the function parameter
            
        self._file_like = filelike

        #  Weakref to Wand images.  To avoid cluttering up memory we
        #  maintain a weak ref and a strong ref to a Wand Image, and allow the memory cache level
        #  to remove the strong reference (_keep_alive_ref) when the ImageInstance is no longer in that cache.
        #  We depend upon Python's garbage collection to effect the safe reclamation of the object
        if image is not None:
            self._image = weakref.ref(image) # A wand.image.Image
        else:
            self._image = None
            
        self._keep_alive_ref = image
        
        if bytes is not None:
            self._size = len(bytes)
        else:
            self._size = size
        #  Some input methods may want us to evaluate the stream right away.
        #  Others can wait.
        if eager and self._image is None:
            try:
                self._get_image()
            except RepositoryFailure:
                # TODO Need to decide on how to propagate this error
                logger.error("Eager _get_image fails")
                raise
                
    def __str__(self):
        the_string = "\nImageHandle: \n"
        the_string += "    filename : {}\n".format(self._local_file_path)
        the_string += "    persistent path : {}\n".format(self._persistent_path)
        the_string += "    wand image : {}\n".format( "exists" if self._image is not None else "None")
        the_string += "    blob : {}\n".format( "exists" if self._bytes is not None else "None")
        if self._image is None:
            the_string += "    kind : {}\n".format(self._kind)
        else:
            the_string += "    kind : {}\n".format(self._image().format)
            the_string += "    size = {} x {}".format(self._image().width, self._image().height)
        return the_string

    def size(self):
        """The size (in bytes) of the image, if known

        May return zero if the image is not loaded and there is no cheap
        mechanism to determine its size.

        :rtype: integer
        """        
        return self._size


    def add_file_path(self, path):
        """Add a local file path to the set of mechanisms available to find this image

        :param path: Full path to local file containg the image
        :type path: string
        """        
        self._local_file_path = path
    
    def md5(self):
        """Compute the MD5 hash of the image

        :rtype: string (32 chars long)
        """
        try:
            image = self._get_image()
        except RepositoryFailure:
            return None
        hasher = hashlib.md5()
        hasher.update(image.make_blob())
        return hasher.hexdigest()
        
    def clone(self):
        """Create a clone of the image handle

        A cloned image handle refers to a new copy of the image.  This requires the image to be loaded. It is excpected
        that the next step will be to execute derivation functions on the cloned image otherwise the cloning serves no useful purpose.

        :rtype: ImageHandle
        """
        try:
            image = self._get_image()
        except RepositoryFailure:
            # TODO work through handling of failures
            logger.error("clone - _get_image fails")
            return None
        return ImageHandle(image = image.clone())

    def convert(self, kind):
        """Convert the image to a different format

        :param kind: Format to convert the image to in ImageMagik form
        :type kind: string
        :rtype: ImageHandle

        If the format is the same as the current format no action is performed and this
        instance is returned.
        If the formats differ, the image is cloned and the clone has its format converted, and then returned.
        """
        try:
            image = self._get_image()
        except RepositoryFailure:
            logger.error("Convert - _get_image fails")
        # Wand implicitly creates a clone when creating a new format
        if kind == self._kind:  # avoid unneeded conversion, or accidental cloning
            return self
        return ImageHandle(image = image.convert(kind), kind = kind)

    def strip(self):
        """Remove any metadata within the image
        """
        image = self._get_image()
        image.strip()
    
    def stripped(self):
        """Create a new image devoid of metadata

        :rtype: ImageHandle
        """
                # strip does not create a new Image, so we must
        try:
            image = self.clone()
        except RepositoryFailure:
            logger.error("Stripped - clone fails")
        image.strip()
        return image
    
    def crop(self, x_size, y_size, x_offset, y_offset):
        try:
            image = self._get_image()
        except RepositoryFailure:
            return None
        # Wand implicitly creates a clone when creating a new sliced image
        x_size = min(x_size, self._image().width)
        x_offset = min(x_offset, self._image().width)
        y_size = min(y_size, self._image().height)
        y_offset = min(y_offset, self._image().height)
        
        new_image = ImageHandle(image = image[x_offset:(x_offset+x_size), y_offset:(y_offset+y_size)])
        return new_image
        
    def resize(self, size):
        the_clone = self.clone()
        new_image = the_clone._get_image()

        desired_aspect_ratio = float(size[0])/float(size[1])
        image_aspect_ratio = float(new_image.width)/float(new_image.height)      

        if desired_aspect_ratio > image_aspect_ratio:  # Image taller, keep desired Y
            x_size = int(size[0] * image_aspect_ratio)
            y_size = size[1]
        else:                                          # Image wider, keep desired X
            x_size = size[0]
            y_size = int(size[1] / image_aspect_ratio)
        
        new_image.resize(x_size, y_size)
        return the_clone


    def thumbnail(self, size, kind = None, **kwargs):
        """
        Create a thumbnail of the image.  

        :param size: Box to fit the thumbnail within.  The thumbnaill may be smaller than this, but will fill one dimension, if not both.
        :type size: tuple (x_size, y_size)
        :param options: set of options that may govern exactly how the thumbnail is created. These override the global configuration options
        :type options: dict
        :rtype: ImageHandle instance

        We allow options to make the thumbnail more generally useful.  We try to avoid situations where the thumbnail is cropped, we may
        allow liquid resize to preserve information in the case of very wide or tall images, and we allow some sharpening and brightness correction of the image
        to make it generally easier to view at reduced scale.
        """

        the_clone = self.clone()
        clone_image = the_clone._get_image()
        
        desired_aspect_ratio = float(size[0])/float(size[1])
        image_aspect_ratio = float(clone_image.width)/float(clone_image.height)

        try_liquid = True
        liquid_limit = self._configuration.thumbnail_liquid_cutin_ratio
        
        if desired_aspect_ratio / image_aspect_ratio < 1/liquid_limit:  # original too wide
            try_liquid = "liquid" in kwargs and kwargs["liquid"]
            image_aspect_ratio = liquid_limit   # Limit how wide

        if  desired_aspect_ratio / image_aspect_ratio > liquid_limit:   # original too tall
            try_liquid = "liquid" in kwargs and kwargs["liquid"]
            image_aspect_ratio = 1/liquid_limit  # Limit how tall
            
        if desired_aspect_ratio > image_aspect_ratio:  # Image taller, keep desired Y
            x_size = int(size[0] * image_aspect_ratio)
            y_size = size[1]
        else:                                          # Image wider, keep desired X
            x_size = size[0]
            y_size = int(size[1] / image_aspect_ratio)
                        
        if try_liquid:
            try:
                clone_image.liquid_rescale(x_size, y_size)
            except wand.image.MissingDelegateError:
                # Liquid rescale was not built into the underlying ImageMagik library.
                # We will do a simple non-recilinear rescale
                clone_image.resize(x_size, y_size)
        else:
            clone_image.resize(x_size, y_size)

        if "equalise" in kwargs and kwargs["equalise"] :
            clone_image.equalize()
            
        if "sharpen" in kwargs and kwargs["sharpen"] :        
            clone_image.unsharp_mask(radius = 0.0, sigma = 1.0, amount = 1.0, threshold = 1.0)

        if kind is None:
            kind = self._configuration.thumbnail_default_format
        if self._kind != kind:
            clone_image.convert(kind)
            the_clone._kind = kind
            
        return the_clone
            
    
    def _get_image(self):
        """
        Return a Wand Image

        The actual Wand image is not created until needed, allowing the image handle to refer to as yet unloaded files, or
        files that are only resident in caches.  If the Wand Image does not exist, it will be created from whatever
        source is available, in order of increasing expense.  An ImageHandle should never exist that does not provide at least
        one mechanism to create the Image.

        This function is usefully called by other routines to ensure that there is a Wand Image present before proceeding.
        """
        # This is the core lazy evaluation of the handle. In order to make any other type we need to convert the input
        # In order to do any processing we want a Wand Image as well
        image = None
        if self._image is not None:
            if self._image() is None:
                self._image = None
        if self._image is None:
            # go through the list in easiest to hardest order
            if self._bytes is not None:
                image = wand.image.Image(blob = self._bytes, format = self._kind)
            elif self._file_like is not None:
                image = wand.image.Image(file = self._file_like)
            elif self._local_file_path is not None:
                try:
                    image = wand.image.Image(filename = self._local_file_path)
                except (wand.exceptions.CoderError) as ex:
                    logger.exception("Wand image create fails for {} of {}".format(self._local_file_path, self._kind))
                    raise RepositoryFailure("Unable to build image")
                except Exception as ex:
                    logger.exception("Wand image creation from file fails for {}".format(self._local_file_path))
                    raise RepositoryError("Image creation error")
            elif self._persistent_path is not None:
                try:
                    self._local_file_path = self._persistent_store.get_image(self._persistent_path)
                except RepositoryError:
                    logger.error("Persistent download to local file fails for {}".format(self._persistent_path))
                    raise
                try:
                    image = wand.image.Image(filename = self._local_file_path, format = self._kind)
                except (wand.exceptions.CoderError):
                    logger.error("Wand image create from uploaded file fails for {} of {}".format(self._local_file_path, self._kind))
                    raise RepositoryFailure("Unable to create image")
                except Exception:
                    logger.exception("Wand image creation from uploaded file fails for {} of {}".format(self._local_file_path, self._kind))
                    raise RepositoryError("Image creation error")
            else:
                # No way of creating the image data.                
                logger.error("Attempt to create ImageHandle data with no description")
                raise RepositoryError("Image has no data")

            # The internal link to an in memory image is weak
            # This avoids potential memory leaks - we maintain liveness via a cache reference
            self._image = weakref.ref(image)
            self._size = len(image)
            self._keep_alive_ref = image    # Ensure there is a keep-alive reference
        return self._image()


    def allocated_memory(self):
        """Estimate of the memory consumed by this image
        """
        # Becuse the Wand.Image itself uses a weakref to the image data this not trivial
        return 0
    
    def weaken_liveness(self):
        """Remove the special liveness keeping reference to the Wand Image

        The only reference to the Image left will be the weak reference. If the Image is garbage collected
        the weakref will become None and the next attempted use of the Image will result in its reconstruction.
        """
        self._keep_alive_ref = None
    
    def as_filelike(self):
        """Return the image bytestream as a Python file-like object
        
        :rtype: file-like  object
        """
        # Wand can create a byte blob, and we just use the C implemented StringIO to get an efficient file-like object
        bytes = self.bytes()
        strio = cStringIO.StringIO(bytes)
        self._bytes = None   # wipe the reference again to free memory
        return strio

        
    def as_file(self, name, dir_path, mode = None):
        """Return a file path of a copy of the Image

        The returned file_path is the concatenation of the provided directory path and the (mangled if nesessary)
        file name of the created image file.  The provided name must include any file type suffix if needed.
        This routine is usually used to create local file cache copies of the image, but can be used
        to create image files anywhere on the local machine as needed.  

        :param name: name to use for the image, usually the ImageName.name of image
        :type name: string
        :param: dir_path: path to the directory where the image should be stored
        :type dir_path: string
        :param: mode: if set, protection mode bits on file.  
        :type mode: integer or None
        :rtype: string
        """
        try:
            # Additional mangling of the name may be applied here if needed
            mangled_name = ImageName.safe_name(name)
            
            file_path = os.path.join(dir_path, mangled_name)
            try:
                image = self._get_image()
            except RepositoryFailure:
                return None        
            image.save(filename = file_path)   # Use the Wand file save capability - we may want to use a proper write to allow mode bits.
            logger.debug("File saved to local file cache at {}".format(file_path))
            if mode is not None:
                try:
                    os.chmod(file_path, mode)
                except IOError:
                    logger.exception("Unable to change mode on file {} to mode {}".format(file_path, mode))
                    # What else might we do?  We could delete the file and report failure. That may be more secure.
        except IOError:
            logger.exception("Image save to local file {} fails".format(file_path))
            raise RepositoryFailure
        self._bytes = None
        return file_path


    def has_persistence(self):
        """Returns whether there is a persistent copy of this image.

        Useful to decide if, and when, a persistent copy of a must_retain image should be written back, or
        whether to force persistent caching of a derived image.

        :rtype: boolean
        """
        return self._persistent_store is not None and self._persistent_path is not None
    
    def  as_persistent(self, name, store = None):
        """Return a reference to a persistent object.

        If the object is not currently in the store it will be uploaded so the reference is good.
        Note, if the object has been loaded to the store once, calling this a second time, even with a different name,
        will not effect a new upload. 

        :param name:  Name by which the image object will be known in the store is it not already there
        :type name: string
        :param: store:  The persistent store to place the image
        :type store: instance of a subclass of ImageStore.
        :rtype: string reference that can be used to retrieve the object from the store
        """

        if self._persistent_store is None and store is None:
            raise RepositoryError("No persistent store set")
        if store is not None:
            self._persistent_store = store
        if self._persistent_path is None:
            self._persistent_path = self._persistent_store.store_image(self.as_filelike(), name = str(name))

        self._bytes = None
            
        return self._persistent_path
    
    def kind(self):
        """Returns the format of the image, as defined by the Wand image format strings.

        If the kind has not been determined from the name or otherwise set, the actual image will need to be
        loaded and the format Wand believes it to be returned.  Thus this can be an unexpectedly expensive operation.

        :rtype: string
        """
        if self._kind is None:
            try:
                self._kind = self._get_image().format
            except RepositoryFailure:
                return None
        return self._kind


    def mimetype(self):
        """Return the mimetype of the image

        """
        # This isn't good.
        return self._get_image().mimetype()
        
    def bytes(self):
        """Return a blob of bytes encapsulating the image, as provided by Wand.image

        If there is no extant Wand Image it will be downloaded from either the local cache or the persistent store

        :rtype: bytes
        """
        if self._bytes is None:
            try:
                image = self._get_image()
            except RepositoryFailure:
                return None                
            self._bytes = image.make_blob()
        self._size = len(self._bytes)
        return self._bytes

    @classmethod
    def from_file(cls, filename, kind = None, eager = False):
        """Create an ImageHandle from a locally present file

        :param filename: Path to the local file holding the image
        :type filename: string
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string or None
        :param eager: If true load the file immedeatly, default False
        :type eager: boolean
        :rtype: ImageHandle
        """
        return cls(filename = filename, kind = kind, eager = eager)

    @classmethod
    def from_persistent(cls, store, path, kind = None, eager = False, size = 0):
        """Create an ImageHandle from an object resident in a persistent object store

        :param store: The persistent store the object resides
        :type store: Store
        :param path: path within the store to find the image
        :type path: string
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string or None
        :param eager: If true load the file immedeatly, default False
        :type eager: boolean
        :param size: size of the image if known, defaults to 0
        :type size: integer
        :rtype: ImageHandle
        """
        return cls(store = store, path = path, kind = kind, eager = eager, size = size)
    
    @classmethod
    def from_filelike(cls, the_file, kind = kind, eager = True):
        """Create an ImageHandle from a file-like object

        :param filename: Path to the local file holding the image
        :type filename: string
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string or None
        :param eager: If true load the image immedeatly, default False
        :type eager: boolean
        :rtype: ImageHandle
        """
        return cls(filelike = the_file, kind = kind, eager = eager)
    
    @classmethod
    def from_bytes(cls, the_bytes, kind = None):
        """Create an ImageHandle from a bytes blob

        :param the_bytes: image
        :type the_bytes: bytes
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string or None
        :rtype: ImageHandle
        """
        return cls(bytes = the_bytes, kind = kind, eager = True)

    @classmethod
    def from_image(cls, the_image):
        """Create an ImageHandle from an wand.image.Image object

        :param the_image: the image
        :type the_image: wand.image.Image
        :rtype: ImageHandle
        """
        return cls(image = the_image, kind = the_image.format, size = the_image.size)


class ImageMetadata:
    """Encapsulates the metadata stored for an image
    """

    def __init__(self, xml):
        _xlm = xml
        # Parse XML and check for sensible content

    def __str__(self):
        """
        Return XML represenation of metadata suitable for injection back into the store.
        """
        pass
                
class ImageSet:
    """
    Encapsulates everything about a specific image, including anything derived from it
    Provides methods to create new derived images.

    Currently not used, and may be depricated.

    """
    def __init__(self):
        
        self._base_image = None      # Image from which we can derive other images easily
        self._original_image = None  # The original image
        self._instances = {}         # Derived Images 

    def add(self, instance):
        self._instances[instance.get_name()] = instance
        

class ImageInstance(object):
    """
    Encapsulates a single image 
    An image instance is essentially a name/image pair
    
    Does not internally store image data - this is managed by an ImageHandle
    Names are encapsulated by ImageName

    Image instances are single objects per image, where uniquness is defined by name.
    Names within the system are created in such a way as to be (for all useful purposes)
    uniquely determined by the image content.  Derived images append derivation information
    to the name.  Thus an operation to derive an image from an existing one will always yield
    a name unique that derivation. An attempt to create a new ImageInstance with that name
    will yield the existing one.
    """

    _cache = None          # The master cache to use for caching operations
    _image_instances = {}  # The class static list of all instances
    _configuration = None
    _lock = RLock()        # Protects use of _image_instances
    
    def __new__(klass, image_name, image_handle, *args, **kwargs):
        """Override __new__ so as to provide a unique ImageInstance for each image.
    
        Uniqueness is determined by the name of the image, as it contains the derivation history.
        A class static dictionary is used to maintain uniqueness. If the named image has not already
        been created, it will be created, otherwise the existing one will be returned.

        :param image_name: name of the image being created
        :type image_name: ImageName
        :param image_handle: The image being bound to the name
        :type image_handle: ImageHandle
        """

        with klass._lock:
            if image_name is not None and image_name.image_name in klass._image_instances:
                new_image = klass._image_instances[image_name.image_name]
            else:
                new_image = super(ImageInstance, klass).__new__(klass, image_name, image_handle, *args, **kwargs)
                if image_name is not None:
                    # None is allowed if we are building a name via BaseImage  --- TODO change this
                    klass._image_instances[image_name.image_name] = new_image
        return new_image


    
    
    def __init__(self, image_name = None, image_handle = None, kind = None, size = None):
        """Construct an ImageInstance or derived class

        :param image_name: name of the image instance to create
        :type image_name: ImageName

        In order to cope with instance uniqueness we must cope with ``__init__`` being called on
        already extant, and thus initialised objects.
        Since ``__init__`` is allowed to create new object variables, and newly constructed objects start with an empty ``__dict__``
        it is as simple as checking to see if a variable exists or not.
        """
        
        if "_name" in self.__dict__:  # We are modifying an existing object, update as approriate
            if image_handle is not None and self._image_handle is None:        
                self._image_handle = image_handle
                self._size = image_handle.size()
            if kind is not None and self._kind is None:
                self._kind = kind
            if size is not None and self._size is None:
                self._size = size
        else:                            # init for a new object
            self._kind = None
            self._size = None
            self.name = image_name               # an ImageName
            self._image_handle = image_handle
            if image_handle is not None:
                self._size = image_handle.size()
            else:
                self._kind = kind
                self._size = size
            self._url_expiry = 0
            self._persistent_url = None    # URL for the image instance that is essentially infinite - if there is one


    @classmethod
    def set_configuration(cls, config):
        """Set the run-time configuration for ImageInstances and derived classes

        :param config: the configuration object
        :type config: Configuration
        """
        cls._configuration = config

    @classmethod
    def from_file(cls, filename, name, kind = None):
        """Create an ImageInstance from a locally present file

        :param filename: Path to the local file holding the image
        :type filename: string
        :param name: name to associate the image with
        :type name: ImageName
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string
        :rtype: ImageInstance
        """
        the_name = ImageName.from_safe(name)  # Filename may have been encoded to allow inclusion of /s
        if kind is None:
            kind = the_name.image_kind()
        handle = ImageHandle.from_file(filename = filename, kind = kind)
        return cls(image_name = the_name, image_handle = handle)

    @classmethod
    def from_filelike(cls, file, name, kind = None):
        """Create an ImageInstance from a file-like object

        :param file: File-like object containing image
        :type file: file-like
        :param name: name to associate the image with
        :type name: ImageName
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string
        :rtype: ImageInstance
        """
        the_name = ImageName(name)
        handle = ImageHandle.from_filelike(file, kind)
        return cls(image_name = the_name, image_handle = handle)
    
    @classmethod
    def from_bytes(cls, bytes, name, kind = None):
        """Create an ImageInstance from a blob of bytes

        :param bytes: Bytes blob containing image
        :type bytes: bytes
        :param name: name to associate the image with
        :type name: ImageName
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string
        :rtype: ImageInstance
        """
        the_name = ImageName(name)
        handle = ImageHandle.from_bytes(bytes, kind)
        return cls(image_name = the_name, image_handle = handle, kind = kind)

    @classmethod
    def from_persistent(cls, store, path, name, kind = None, size = 0):
        """Create an ImageInstance from an image resident in a persistent store

        :param store:  The store where the image resides
        :type store: Store
        :param name: name to associate the image with
        :type name: ImageName
        :param kind: Optional format of the image as a Wand image format string
        :type kind: string
        :param size: The size of the image (in bytes) if known
        :type size: integer
        :rtype: ImageInstance
        """
        the_name = ImageName(name)
        handle = ImageHandle.from_persistent(store, path)
        return cls(image_name = the_name, image_handle = handle, kind = kind, size = size)

    @classmethod
    def set_cache(cls, cache):
        """Set the master cache instance used when interacitng with any cache heirarchy
        
        :param cache: The cache to use
        :type cache: CacheMaster
        """
        cls._cache = cache
    
    def clone(self, name):
        """Returns a new ImageHandle that encasulates a copy of this handle's image

        :rtype: ImageInstance
        """
        name = self.name.clone() 
        return ImageInstance(image_name = name, image_handle = self._image_handle.clone())

    def convert(self, kind):
        """Create a copy of this image in a new format.

        :param kind: ImageMagik format to convert the image to
        :type kind: string

        Note, the rules on image uniqueness apply.  If the kind specified is the same as the current format
        this function acts as a clone().  If an image of the designated format already exists, that will be returned.

        :rtype: ImageInstance
        """
        the_name = self.name.clone(kind)        
        the_name.apply_convert(kind)
        return ImageInstance(image_name = the_name, image_handle = self._image_handle.convert(kind))
    
    def crop(self, size, offset = (0,0), kind = None):
        the_name = self.name.clone()
        the_name.apply_crop(size, offset, kind)
        handle = self._cache.get(the_name)
        if handle is not None:
            return handle
        handle = self._image_handle.crop(size[0], size[1], offset[0], offset[1])
        if kind is not None:
            handle = handle.convert(kind)
        return ImageInstance(image_name = the_name, image_handle = handle)

    def resize(self, size, kind = None):
        the_name = self.name.clone()
        the_name.apply_resize(size, kind = kind)
        instance = self._cache.get(the_name)
        if instance is not None:
            return instance
        instance = ImageInstance(image_name = the_name, image_handle = self._image_handle.resize(size))
        if kind is not None:
            instance = instance.convert(kind)
        return instance


    def thumbnail(self, size, options = None, kind = None):
        """
        Returns a new ImageInstance that contains a thumbnail image of this image.

        options are, "liquid" : Boolean - whether to allow liquid rescaling
        "equalize" : Boolean - whether to apply histogram equalisation
        "sharpen" : Boolean - whether to apply an unsharp mask sharpening
        Default is to apply all three. 

        If kind is provided the thumbnail will be in that image format, otherwise the system
        default format for thumbnails will be used.

        :param size:  The constraining box size to fit the tumbnail into.
        :type size: tuple (x_size, y_size)
        :param options: enhancement options
        :type options: dict
        :param kind: Wnad image format to create the thumbnail in
        :type kind: string
        """
        the_name = self.name.clone()
        if options is None:
            options = {"liquid": True, "equalize" : True, "sharpen": True}
        the_name.apply_thumbnail(size, kind, **options)
        instance = self._cache.get(the_name)
        if instance is not None:
            return instance
        handle = self._image_handle.thumbnail(the_name.size(), the_name.image_kind(), **options)
        if kind is not None:
            handle =  handle.convert(kind)
        return ImageInstance(image_name = the_name, image_handle = handle)
    
    def get_name(self):
        """Return the ImageName object for this instance.

        :rtype: ImageName:
        """
        return self.name

    def get_image_handle(self):
        """Returns the ImageHandle for the image instance

        :rtype: ImageHandle
        """
        return self._image_handle

    def kind(self):
        """Return the format of the image

        :rtype: string
        """
        return self._image_handle.kind()
    
    def file_path(self, basepath = None):
        """Return a file path where a copy of the image can be found.

        The image will be loaded or otherwise created if needed in order to complete this call.
        
        :param basepath: File system path to a directory where the image should be placed
        :type basepath: string
        :rtype: string
        """
        try:
            path = os.path.join(basepath, str(self.name))
            f = self.get_image_handle().as_file(path)
            return f
        except IOError:
            logger.exception("File creation for image {} to path {} fails".format(self.name, basepath))
            return RepositoryError

    def url(self):
        """Return a temporary URL by which the image can be accessed.
        """

        #        if not self._image_handle.has_persistence():
        #            self._cache.persistent_write_back(self.name, self, must_retain = True)
        self._cache.add_image(self)
        return self._cache.url(self.name)
    
    def mimetype(self):
        """Return the mimetype for the image format

        :rtype: string
        """
        return self.get_image_handle()._image().mimetype

    def as_bytes(self):
        return self.get_image_handle().bytes()

    def as_filelike(self):
        return self.get_image_handle().as_filelike()    

    def as_defined(self, name):
        """Create an image as specified by the name

        :param name: Image name that describes a possibly derived image
        :type name: ImageName
        :rtype: ImageInstance

        The image derivation steps as defined in the image name are applied to this image.
        The actual base name need not match, thus it is possible to apply the image derivation steps for
        another image to this one, as well as lazily creating an image from a name specification.
        """
        
        if not name.is_derived():
            return self
        
        if name.is_metadata():
            return self.get_image_handle().metadata()
        
        if name.is_thumbnail():
            options = {"liquid": name._liquid, "equalize" : name._equalise, "sharpen": name._sharpen}
            return self.thumbnail(name.size(), options)
        
        if name.is_resize():
            return self.resize(name._image_size, kind = name.kind())

        if name.image_kind() != self.kind():
            return self.convert(name.image_kind())

        raise RepositoryError("Consistency error in name {}".format(name))

    
    def __str__(self):
        the_string = "Name : {}\n".format(self.name)
        the_string += "Kind : {}\n".format(self._kind)
        the_string += "Handle : {}".format(self._image_handle)
        return the_string
    
class BaseImageInstance(ImageInstance):
    """The image instance from which all the derived images are created

    This image is dervied from the OriginalImage.
    Normally it will be a lossless copy of the original image, but without any of the ebedded metadata that may have
    come with the original image.
    By default it will be stored as an ImageMagic miff format file
    

    This class may be deprecated - it isn't clear it is as useful a concept as it first appeared.
    """

    master_format = "miff"


    def __new__(klass, image_name, image_handle, *args, **kwargs):
        """Override __new__ so as to provide a unique ImageInstance for each image.
    
        :param image_name: name of the image being created
        :type image_name: ImageName
        :param image_handle: The image being bound to the name
        :type image_handle: ImageHandle
        """
        return super(BaseImageInstance, klass).__new__(klass, image_name, image_handle, *args, **kwargs)
    
    def __init__(self, image_name, image_handle):
        # Currently this is where the cannonical name is created. So we must do this
        # before we call the super constructor.
        if image_name is None:
            # Configuration choice here
            self._base_name = self._generate_name(image_handle)
        else:
            self._base_name = str(image_name)
            
        super(BaseImageInstance, self).__init__(image_name = ImageName(self._base_name), image_handle = image_handle)
        self._base_image = self    # we are our own base image

    @staticmethod
    def _generate_name(image_handle):
        """
        We use the ImageHandle's md5 hash function to generate the main name component.

        Note:  Simply using the MD5 hash leaves a possible issue, in that if an identical image is uploaded by two users,
        the second upload will resolve to the existing image, and from then on that image will be used.  If there are
        image ownership attributes applied in the future we will need to fold the owner into the hash function as
        well as the image to ensure semantic uniqueness. The same issue may apply for other possible additional
        access or authority attributes.
        
        :rtype string:
        """
        return image_handle.md5()
                
    def get_base_name(self):
        """
        Return the base name component for this image.

        :rtype: string
        """
        if self._base_name is None:
            self._base_name = self._generate_name(self._image_handle)
        return self._base_name

    def __str__(self):
        the_string = "Base Image\n"
        the_string += super(BaseImageInstance, self).__str__() + "\n"
        the_string += "Base Name: {}".format(self._base_name)
        return the_string

    @classmethod
    def from_image(cls, image, name):
#        the_name = ImageName(name)
        return cls(image_name = name, image_handle = image)
    

class ImageMetaData:
    """
    Encalsulates whatever metadata we find in an image
    """
    def __init__(self, metadata):
        self._metadata = metadata


    # Intent is to add a range of useful accessor methods to encasulate information.

    def __str__(self):
        the_string =  "MetaData\n"
        for meta in self._metadata.keys():
            the_string += "{}   :   {}\n".format(meta, self._metadata[meta])
        return the_string
            
class OriginalImage(ImageInstance):
    """
    Encasulates the actual image as uploaded to the repository.
    In general these images are never served out, and should never be, in any manner, altered.
    They are preserved byte for byte from the original upload.

    An original image may be constructed from a new image file gthat is to be added to the repository, or may
    be constructed from a stored image file that is resident within the repository stores. 
    The only difference is that a new image will need to have a base name determined for it from the image content.
    Existing OriginalImages already have a generated name.  Generation of new names is suppressed when reloading
    existing images.
    """

    def __new__(klass, image_name, image_handle, *args, **kwargs):
        """Override __new__ so as to provide a unique ImageInstance for each image.
    
        :param image_name: name of the image being created
        :type image_name: ImageName
        :param image_handle: The image being bound to the name
        :type image_handle: ImageHandle
        """
        return super(OriginalImage, klass).__new__(klass, image_name, image_handle, *args, **kwargs)
    
    def __init__(self, image_name, image_handle, kind = None, full_name = False):
        """
        Construct a new OriginalImage
        :param image_name:  Name of the image as recieved from the store, cache, or uploading client
        :type name: string
        :param image_handle: handle for the image
        :type image_handle: ImageHandle
        :param kind: Optional guidance on image format. Format as used by ImageMagik
        :type kind: string
        :param full_name: Whether the provided name has already been turned into a cannonical name
        :type full_name: boolean
        """        
        super(OriginalImage, self).__init__(image_name, image_handle)

        self._base_image = None
        # Ensure that if an unexpected image is injected from a store we generate a proper name for it.
        if not (image_name.is_cannonical_name() or full_name):
            self.baseimage()
            base, ext = os.path.splitext(image_name.image_name())            
            new_name = ImageName(self._base_image.name.base_name(), kind = ext[1:])
            new_name.make_original(str(new_name))
            image_name = new_name
            
        self.name = image_name


        logger.debug("OriginalImage {}".format(image_name))
        
        if kind is not None:
            self._kind = kind            # Determine which of the ImageMagic formats the image is
        else:
            self._kind = self.name.image_kind()  # Try to use the image name.  Avoid using the handle's kind() as it is often very expensive.

    def url(self, seconds = None):
        """
        We never give out URLs for original images.
        Overrides the base class function to disable the capability.

        :rtype: None
        """
        return None
        
    @classmethod
    def from_file(cls, filename):
        """Create an OriginalImage from a local file

        :param file: Path to the local file holding the image
        :type file: string
        :param image_name:  Name of the image
        :type name: ImageName
        :rtype: OriginalImage
        """
        handle = ImageHandle.from_file(filename)
        base, name = os.path.split(filename)
        image_name = ImageName.from_safe(name)
        image_name.make_original(name)
        return cls(image_name = image_name, image_handle = handle, full_name = False )

    @classmethod
    def from_filelike(cls, file, name, full_name = False):
        """Create an OriginalImage from a file-like object

        :param file: File-like object containing image
        :type file: File-like
        :param image_name:  Name of the image
        :type name: ImageName
        :rtype: OriginalImage
        """
        handle = ImageHandle.from_filelike(file)
        # do some name sanity massaging here
        return cls(image_name = name, image_handle = handle, full_name = full_name)

    @classmethod
    def from_cache(cls, name, handle):
        """Create an OriginalImage from a handle held in a cache

        :param name:  Name of the image
        :type name: ImageName
        :param handle: Handle encapsulating the image, typically as returned by a cache ``get()``
        :type handle: ImageHandle
        :rtype: OriginalImage
        """
        return cls(image_name = name, image_handle = handle, kind = None, full_name = True)
    
    @classmethod
    def from_bytes(cls, bytes, name):
        """Create an OriginalImage from a blob of bytes

        :param bytes: bytes blob holding raw image data
        :type bytes: bytes
        :param name:  Name of the image
        :type name: ImageName
        :rtype: OriginalImage
        """
        handle = ImageHandle.from_bytes(bytes)
        return cls(image_name = name, image_handle = handle, full_name = True)

    @classmethod
    def from_persistent(cls, store, path):
        """Create an OriginalImage from a persistent store
                
        :param store: The store where the image resides
        :type store: Store
        :param path: The path within the store designating the image
        :type path: string
        :rtype: OriginalImage
        """
        handle = ImageHandle.from_persistent(store, path)
        name = path  # hack of the name here
        return cls(image_name = name, image_handle = handle)

    # Act as a factory for a BaseImage instance
    def baseimage(self, full_name = False):
        """Create a BaseImage from the original Image

        BaseImages have no meta-data, and may be stored in a universal format.
        They are otherwise identical in content to the OriginalImage
        """
        if self._base_image is None:
            self.get_image_handle()._get_image()
            if self._configuration.cannonical_format_used:
                handle = self._image_handle.convert(self._configuration.cannonical_format)
                handle.strip()                     # We do not let metadata leak into derived images.
            else:
                handle = self._image_handle.stripped()
            if full_name:
                self._base_image = BaseImageInstance.from_image(name = ImageName(self.name.base_name(), self.name.image_kind()), image = handle)
            else:
                self._base_image = BaseImageInstance.from_image(name = None, image = handle)
        return self._base_image
        
    # Metadata is never stored in derived images.  We extract it here and nowhere else.
        
    def _get_metadata(self):
        """Return a dictionary of whatever metadata the image encasulates

        :rtype: dict
        """
        return self._image_handle._get_image().metadata.items()

    def get_exif(self):
        """Return a dictionary of any EXIF data in the image

        :rtype: dict
        """
        exif = {}
        try:
            exif.update((k[5:], v) for k, v in self._image_handle._get_image().metadata.items()
                        if k.startswith('exif:'))
            return exif
        except RepositoryFailure:
            return None



class GeneralImage(object):
    """
    Psuedo class that encapsulates the creation of the appropriate ImageInstance class

    Depending upon the contents of the image's name the constructors will create
    the correct class.  Either ImageInstance, BaseImageInstance, OriginalImage.

    The policy of how the structure of an image name relate to the ImageInstance classes is implemented here.

    There is no actual GeneralImage class in the sense of extant objects.

    This probably isn't considered all that Pythonic a way of doing this.
    """
    def __new__(klass, image_name, image_handle, full_name, *args, **kwargs):
        if not isinstance(image_name, ImageName):
            image_name = ImageName(image_name)
        if image_name.is_original():
            return OriginalImage(image_name, image_handle, full_name = full_name, *args, **kwargs)
        elif image_name.is_base():
            return BaseImageInstance(image_name, image_handle, *args, **kwargs)
        else:
            return ImageInstance(image_name, image_handle, *args, **kwargs)

    # Since __new__ always returns a type other than GeneralImage, __init__ is never called.
        
    @classmethod
    def from_file(cls, filename):
        """Create an ImageInstance or approriate derived class from a local file

        :param file: Path to the local file holding the image
        :type file: string
        :param image_name:  Name of the image
        :type name: ImageName
        :rtype: ImageInstance or derived class
        """
        handle = ImageHandle.from_file(filename)
        base, name = os.path.split(filename)
        
        return cls(image_name = name, image_handle = handle, full_name = False )

    @classmethod
    def from_filelike(cls, file, name):
        """Create an ImageInstance or approriate derived class from a file-like object

        :param file: File-like object containing image
        :type file: File-like
        :param image_name:  Name of the image
        :type name: ImageName
        :rtype: ImageInstance or derived class
        """
        handle = ImageHandle.from_filelike(file)
        # TODO - do some name sanity massaging here
        return cls(image_name = name, image_handle = handle, full_name = False)

    @classmethod
    def from_cache(cls, name, handle):
        """Create an ImageInstance or approriate derived class from a handle held in a cache

        :param name:  Name of the image
        :type name: ImageName
        :param handle: Handle encapsulating the image, typically as returned by a cache ``get()``
        :type handle: ImageHandle
        :rtype: ImageInstance or derived class
        """
        return cls(image_name = name, image_handle = handle, kind = None, full_name = True)
    
    @classmethod
    def from_bytes(cls, bytes, name):
        """Create an ImageInstance or approriate derived class from a blob of bytes

        :param bytes: bytes blob holding raw image data
        :type bytes: bytes
        :param name:  Name of the image
        :type name: ImageName
        :rtype: ImageInstance or derived class
        """
        handle = ImageHandle.from_bytes(bytes)
        return cls(image_name = name, image_handle = handle, full_name = True)

    @classmethod
    def from_persistent(cls, store, path):
        """Create an ImageInstance or approriate derived class from a persistent store
                
        :param store: The store where the image resides
        :type store: Store
        :param path: The path within the store designating the image
        :type path: string
        :rtype: ImageInstance or derived class
        """
        handle = ImageHandle.from_persistent(store, path)
        name = path  # hack of the name here
        return cls(image_name = name, image_handle = handle, full_name = True)






        
def test():

    test_dir = "../test/image_test/images"
    
    img1 = OriginalImage.from_file(os.path.join(test_dir, "nacra.jpg"))
    print img1
    base1 = img1.baseimage()
    exif = img1.get_exif()
    for m in exif.keys():
        print "{} : {}".format(m, exif[m])
    print base1
    crop1 = base1.crop((1000,1000),(500,500), kind = 'jpg')
    print crop1
    f = crop1.file_path(".")
    print f
    pass
    
    
if __name__ == "__main__":
    test()
