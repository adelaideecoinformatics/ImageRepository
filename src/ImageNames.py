"""
Image Names
-----------

Provide a name generation and image derivation naming capability for reposity images


Image names convey the processing history of derived images.  The intent is that images are unique in the system,
although they may be cached at multiple levels.  If the name of two images is the same, they are guarenteeded to tbe the 
same image. This means that a request for a derived image can be made, and used to create the image name.  If there is 
an image with that name, it can be guarenteed to be the image needed.
"""

import re
import os
import urllib
import logging
from Exceptions import RepositoryError
from Exceptions import RepositoryFailure

logger = logging.getLogger("image_repository")

class ImageName:
    """
    Encapsulates the name an individual image will have in whatever file repository is used.

    There will always be an original image - this is the the native image that was loaded.
    In general the original image will not be served from the repository, and images derived from it will be.
    Image names are required to encapsulate the information that is needed to create them from the original image.
    This allows any image caching layer to find a cached image simply by checking the names of images to see if
    any derivation step can be avoided.


    We must define a syntax for derived image names.
    All images are named from the original image with optional suffixes.  The suffix syntax must be
    unambiguous. This allows extention of the system to provide for caching of new processing steps.


    Format of base or derived image

    * Unique name for image source

        -     MD5 hash of base image (ie without metadata) = 32 hexadecimal digits
        -     Path name and unique name within psuedo directory

    * Optional derivation operations

        -    Plus ``+``
        -    operation: one of ``crop``, ``size``, ``thumbnail``, ``convert``, ``clone``, ``original``, ``metadata``
        -    open parenthesis ``(``
        -    parameters - comma separated list
        -   close parenthesis ``)``

    * dot ``.``
    * image format

    In principle multiple operations may be cascaded, although currently this feature isn't used by the
    client classes.  Mathematical purity would suggest that the apppication of image derivation steps is
    done in a heirarchical manner, of function applied to function application, but currently they are simply 
    appended.

    The operation ``original`` can't be combined with any other operation, it conveys the semantics that this image is 
    the unchanged original uploaded image. 

    The ``clone`` operation should never actually appear in the wild, and is a placeholder for internal use to avoid any
    potential problems with aliasing of images whilst derivation steps occur.

    The ``metadata`` operator does not yield an image
    """

    #    regexp = re.parse("")

    _configuration = None
    
    @classmethod
    def set_configuration(cls, config):
        cls._configuration = config

    
    def __init__(self, image_name, kind = None):
        """
        Create a new image name.
        :param image_name: Name from which the ImageName is created
        :type image_name: string
        :param kind: An ImageMagic format string that represents the format of the image
        :type kind: string or None
        """

        self._is_thumbnail = False
        self._is_derived = False
        self._is_base = False
        self._is_original = False
        self._liquid = False
        self._equalise = False
        self._sharpen = False
        self._clone = False       # If an imagename is cloned we must keep it unique up until a new image is derived - this flags a clone
        self._is_metadata = False
        self._is_resize = False
        self._is_convert = False
        
        self._base_name = None
        self._original_name = None
        self._image_kind = kind
        self._image_size = (None, None)
        self._operations = []

        self._image_name = image_name
        
        # parse the image name down to its constituents and fill in the operations
        if image_name is not None:
            try:
                self._parse_name(image_name, kind)
            except Exception as ex:
                print "Failure in image name parse of {}".format(image_name)
                print ex            


    @classmethod
    def from_raw(cls, raw_name):
        """Create an ImageName from a raw path.

        :param raw_name:
        :type raw_name: string        
        """
        # Encode everything in the name that could cause us problems
        try:
#            raw_name.
            encoded_name = urllib.quote(raw_name.encode('utf-8', errors = 'backslashreplace'))
        except UnicodeError:
            raise RepositoryFailure("Failure in encoding raw_name")

        # can we see a kind?
        kind = None
        # sanity check the kind
        return cls(encoded_name, kind = kind)


    @classmethod
    def from_safe(cls, safe_name):
        """Create an image name from a known safe name.

        :param safe_name: A name that has been generated from ``safe_name``
        :type safe_name: string        
        """

        demangled_name = urllib.unquote(safe_name)
        kind = None
        return cls(demangled_name, kind)

    @staticmethod
    def unsafe_name(name):
        """Reverse the safe_name encoding
        """
        return urllib.unquote(name)
    
    @staticmethod
    def safe_name(name):
        """Return a safely encoded name that can be used as a filename

        :param name: the name to encode
        :type name: string
        :rtype: string
        """
        return urllib.quote(name, safe = '')
    
    @classmethod
    def from_cannonical(cls, image_name):
        """Construct an ImageName from a known good cannonical name

        :param image_name: name of image in cannonical format
        :type image_name: string
        """
        return cls(image_name)        
                
    def _parse_name(self, image_name, kind = None):
        """Parse the image name into its components.
        
        :param image_name: the name to be parsed
        :type image_name: string
        :param kind: An ImageMagic format string that represents the format of the image
        :type kind: sting or None

        If supplied the `kind` parameter defines the image type, and it is assumed that there is 
        no image type suffix as part of the `image_name`.

        Parsing creates an internal representation of the image name semantics that both allows the image name to be
        generated and allows derivation step to be added.
        """
        if kind is None:
            try:
                head, ext = os.path.splitext(image_name)
                kind = ext[1:]
            except ValueError:
                head = image_name
                kind = None
        else:
            head = image_name
            kind = kind
        try:
            components = re.split("\+", head)
        except TypeError:
            components = [head]
            self._is_base = True
        self._base_name = components[0]
        self._image_kind = kind

        self._is_base = True
        x_size = 0
        y_size = 0
        if len(components) <= 1:
            return

        for op in components[1:]:
            self._is_base = False
            try:
                operation, parameters = re.split("\(",op)
            except ValueError:
                print "failure in splitting operation at - {}".format(op)
                continue
            if operation == "clone":
                self._clone = True
                continue    # Prevent the clone operation going into the _operations list
            if operation == "original":
                self._is_original = True
                self._is_derived = False
                self._is_base = False
                # We must not let any meta characters sneak into the final name - in particular underscores or periods
                encoded = urllib.quote(parameters[:-1], safe = "")
                self._original_name = encoded
            elif operation == "size":
                self._is_base = False
                self._is_derived = True
                self._is_resize = True
                x_size, y_size = re.split(",", parameters[:-1])  # Need to convert to int
            elif operation == "crop":
                self._is_base = False
                self._is_derived = True
                x_size, y_size, x_offset, y_offset = re.split(",", parameters[:-1])
            elif operation == "thumbnail":
                self._is_base = False
                self._is_derived = True
                self._thumbnail = True
                x_size, y_size, options = re.split(",", parameters[:-1])  # Need to convert to int
                self._liquid = "l" in options
                self._equalise = "e" in options
                self._sharpen = "s" in options
            elif operation == "convert":
                self._is_base = False #  Maybe  can be overridden
                self._is_derived = True
                self._is_original = False
                self._is_convert = True
            elif operation == "metadata":
                self._is_base = False #  Maybe  can be overridden
                self._is_derived = True
                self._is_original = False
                self._is_metadata = True
                # We can ignore the parameter, it only serves as housekeeping information for the moment
            else:
                print("Unknown operation {} in imagename {}".format(operation, image_name))
                continue
            self._operations.append(op)

        self._image_size = (x_size, y_size)
            
    def rename(self, name):
        """Change the entire name represented by this ImageName object.

        :param name: The base name to redefine the ImageName from.
        :type name: string
        """
        self._parse_name(name)
            
    def clone(self, kind = None):
        """Return a new ImageName instance that has the current state of this name as its initial name.

        :rtype: ImageName

        We add a check component to cloned names to avoid some possible nasty outcomes.  String representations
        of ImageNames are used to key dictionaries (typically caches) throughout the repository.  A cloned ImageName
        is intentded to be the halfway point in creating a derived image name.  But if a string representation of a
        cloned ImageName is used to add an entry to a dictornary prior to performing the needed dreivation steps
        it may result in a conflict.  We add an ephemeral `clone` operation to the new ImageName that will automatically
        vanish again once any derivation step is performed.
        """
        the_string = "{}".format(self._base_name)
        the_string += "+clone()"
        for op in self._operations:
            the_string += "+{}".format(op)
            
        return ImageName(the_string, kind if kind is not None else self._image_kind)


    def is_cannonical_name(self):
        """Determine whether the ImageName represents a properly created name.

        :rtype: Boolean

        It is possible that external actions may lead to files or objects appearing in the various
        persistent and cache stores used. This function attempts to weed out names that may have passed through
        the parsing stage but are none-the-less not image names that were generated by this system.

        Currently this is very simplistic.  We assume that no nefarious activity is occuring and that a simple error
        has been made.  We should note that the system should never touch files starting with a ``.`` anyway. 

        If this becomes a real concern, we can use a different hash function to create the name prefix that is
        convolved with a private key. Thus making names essentially unforgable.
        """
        return True
        return len(self._base_name) == 32

 
    
    
    def base_name(self):
        """Return the name from which this ImageName was derived

        :rtype: string
        """
        return self._base_name

    def master(self):
        """Return a string containing name of the image from which an image of this name can be derived.

        :rtype: string

        This will usually be the name of the BaseImageInstance this image was derived from.
        """
        return "{}.{}".format(self._base_name, self._image_kind)

    def is_original(self):
        """Determine if the name represents an original image

        :rtype: Boolean
        """
        return self._is_original

    def set_original(self, original):
        self._is_original = original

    def is_base(self):
        """Determine if the name represents a base image
        
        :rtype: Boolean
        """
        return self._is_base
    
    def is_derived(self):
        """Determine if the name represents a derived image

        :rtype: Boolean
        """
        return self._is_derived

    def is_thumbnail(self):
        """Determine if the name represents a thumbnail image

        :rtype: Boolean
        """
        return self._is_thumbnail

    def is_resize(self):
        """Determine if the name represents a resized image

        :rtype: Boolean
        """
        return self._is_resize
    
    def is_convert(self):
        """Determine if the name represents a resized image

        :rtype: Boolean
        """
        return self._is_convert

    def is_metadata(self):
        return self._is_metadata
    
    def size(self):
        """
        """
        return self._size

    def image_kind(self):
        """
        """
        return self._image_kind

    def set_kind(self, kind):
        """Set the format of the image.

        """
        self._image_kind = kind
        self._image_name = str(self)
        
    def make_original(self, name = None):
        """The name behaves as original image.

        Any derivation steps are removed, and the image behaves as an original image.

        :param name: An optional name that overwrites the current name.
        :type name: string or None
        
        """
        self._clone = False
        self._operations = []
        self._is_original = True
        if name is not None:
            self._original_name = name
        self._image_name = str(self)
    
    def apply_thumbnail(self, size = None, kind = None, **kwargs ):
        """Apply the thumbnail creation operation to the image name

        If not specified, parameters are taken from the system configuration defaults.

        :param size: The size constraints of the thumbnail.  The thumbnail will fit inside a box of these dimensions
        :type size: tuple (x_size, y_size) or None
        :param kind: Optional image format for the thumbnail. If not specified the system configuration default is used.
        :type kind: string or None
        :param equalise: Whether to apply histogram equalisation to the thumbnail image to improve clarity.
        :param sharpen: Whether to apply an unshparp mask sharpening operation to improve clarity
        :param liquid: Whether to allow resizing operations that need to distort the image aspect ratio to use liquid resizing.

        The derived name encodes the equalise, sharpen and liquid parameters via the letters ``els``.
        """
        self._clone = False
        self._is_derived = True
        self._is_thumbnail = True
        self._is_base = False
        if size is None or (size[0] is None and size[1] is None):
            size = self._configuration.thumbnail_default_size
            #            x_size = self._configuration.thumbnail_default_xsize
            #            y_size = self._configuration.thumbnail_default_ysize
            #        else:
        x_size = size[0]
        y_size = size[1]
            
        if x_size is None:
            x_size = y_size

        if y_size is None:
            y_size = x_size

        if kind is None:
            kind = self._configuration.thumbnail_default_format
        self._size = (x_size, y_size)
        self._image_kind = kind

        self._equalise = self._configuration.thumbnail_equalise
        self._liquid = self._configuration.thumbnail_liquid_resize
        self._sharpen = self._configuration.thumbnail_sharpen

        # Allow overriding of the config defaults
        if "equalise" in kwargs:
            self._equalise = kwargs["equalise"]

        if "sharpen" in kwargs:
            self._sharpen = kwargs["sharpen"]

        if "liquid" in kwargs:
            self._liquid = kwargs["liquid"]

        #Place simple one letter codes in the name
        encoded_options = ""
        if self._equalise:
            encoded_options += "e"
        if self._liquid:
            encoded_options += "l"
        if self._sharpen:
            encoded_options += "s"
        self._operations.append("thumbnail({},{},{})".format(x_size, y_size, encoded_options))

        self._image_name = str(self)
        
    def apply_resize(self, size, kind = None):
        """Apply an image resizing operation to the image

        :param scale: The size for the image
        :type size: tuple (x_size, y_size)
        :param kind: Image format for the resized image. Defaults to the current format if not specified.
        :type kind: string or None

        """
        self._clone = False
        self._is_derived = True
        self._is_base = False
        self._is_resize = True
        self._operations.append("size({},{})".format(size[0],size[1]))
        self._image_size = size
        if kind is not None:
            self._image_kind = kind
        else:
            kind = self._configuration.image_default_format
        self._image_name = self.__str__()
        self._image_size = size
            
    def apply_crop(self, size, origin, kind = None):
        """Apply an image crop operation to the image

        :param scale: The size for the image
        :type size: tuple (x_size, y_size)
        :param origin: the image coordinates form where the crop is made
        :type origin: tuple (x_start, y_start)
        :param kind: Image format for the resized image. Defaults to the current format if not specified.
        :type kind: string or None
        """
        self._clone = False
        self._is_derived = True
        self._is_base = False
        self._operations.append("crop({},{},{},{})".format(size[0], size[1], origin[0], origin[1])  )
        self._crop_size = size
        self._crop_origin = origin
        if kind is not None:
            self._image_kind = kind
        self._image_name = self.__str__()
        self._image_size = size

    def apply_metadata(self, kind = 'jsn'):
        """Apply an extract metadata operation

        """
        self._clone = False
        self._is_derived = True
        self._is_metadata = True
        self._operations = ["metadata({})".format(kind)]
        self._image_kind = kind
        self._image_size = None        
        self._image_name = self.__str__()
        
    def apply_convert(self, kind):
        """Apply an image format conversion operation.

        :param kind: The new format for the image
        :type kind: string
        """
        self._clone = False
        if self._is_derived:   # this is only needed if the original image is to be converted with no other action.
            return
        self._is_derived = True
        self._operations.append("convert({})".format(kind))
        self._image_kind = kind
        self._image_name = self.__str__()
        
    def __str__(self):
        """String representation of the ImageName

        This is the full cannonical representation of the name, and is used as the static name for images
        """
        the_string = "{}".format(self._base_name)
        if self._clone:
            the_string += "+clone()"
        if len(self._operations) != 0:
            for op in self._operations:
                the_string += "+{}".format(op)
        else:
            if self._original_name is not None or self._is_original:
                the_string += "+original({})".format(self._original_name)
        
        the_string += ".{}".format(self._image_kind)
        return the_string

    def image_name(self):
        """Return the effective filename (including type suffix) that include all operations.

        :rtype: string
        """
        return self._image_name
    
def test():
    a = ImageName("test1.jpg")
    print a
    a.apply_crop((100,200),(300,400),'jpg')
    print a
    a.apply_resize((200,300))
    print a


if __name__ == "__main__":
    test()
