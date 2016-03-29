"""
Images may be stored in caches, intended to provide improved performance for the repository

Caches are heirachical, and images may migrate from one level to another, or be duplicated in
more than one level. 

A master cache provides an abstraction over the cache hierarchy, and provides a single point of call
for finding images, or adding images to the cache hierachy.

Persistent storage of images interrelates with the caches. 
"""
import re
import time
import weakref
import os
import stat
import wand.image
import traceback
from threading import RLock
import logging

import Configuration
import ImageNames
from ImageType import *

from Exceptions import RepositoryError
from Exceptions import RepositoryFailure

class CacheEntry:
    """Encapsulates the cache record

    Cache entries are used to refer to ImageInstances
    Entries also capture some policy information about retention

    Cache eviction policy is dependant upon retention policy and the time since an
    entry was last referenced.
    """
    def __init__(self, image, size = 0, retain = False, permanent = False, retain_until = 0):
        """Construct a CacheEntry

        :param image: Image the entry refers to
        :type image: ImageInstance
        :param size: size of the image, if known, used for cache housekeeping
        :type size: integer
        :param retain: whether to preferentially retain this entry during cache eviction processes, defaults to False
        :type retain: boolean
        :param permanent: whether the image must be retained somewhere in the storage system, defualts to False
        :type permanent: boolean
        """
        if not isinstance(image, ImageInstance):
            raise RepositoryError("Internal Consistency Error")
            
        self.image = image                  #  ImageInstance
        self.access_time = time.clock()     #  When this cache entry was last referenced
        self._retain_until = retain_until   #  If set the object, must not be deleted from persistent store before this time
        self._prefer_retain = retain        #  Try to retain this entry when cleaning the cache to improve cache performance
        self._must_retain = permanent       #  We must not remove this element from the storeage system.
        self.size = size                    #  size of the Image cached

    def set_must_retain(self, permanent):
        """Set the entry to indicate whether the image must be preserved in persistent storeage.
        
        :param permanent: value to set
        :type permanent: boolean
        """
        self._must_retain = permanent

    def must_retain(self):
        """Return whether the image must be preserved in persistent storeage.

        :rtype: boolean
        """
        return self._must_retain or (self._retain_until is not None and self._retain_until < time.time())

    def set_retain(self, retain):
        """Set the entry to indicate whether the image should be preferentially retained during cache evictions.
        
        :param retain: value to set
        :type retain: boolean
        """
        self._prefer_retain = retain

    def should_retain(self):
        """Return whether the image should be preferentially retained during cache evictions.

        :rtype: boolean
        """
        return self._prefer_retain

    def set_retain_until(self, retain_time):
        """Set a time until which the object must be retained in persistent storage

        :param retain_until: The time until which the object must be retained, seconds since the epoch
        :type retain_until: int or None
        """
        if retain_time is not None and retain_time < time.time():
            retain_time = 0
        self._retain_until = retain_time    

    def get_retain_until(self):
        return self._retain_until

        
    def has_persistence(self):
        """Return whether the image currently has a copy in persistent storage

        :rtype: boolean
        """
        return self.image._image_handle.has_persistence()
   
    
    def __str__(self):
        the_string = "image : {}\n".format(self.image)
        the_string += "delta access : {} seconds\n".format(time.clock() - self.access_time )
        the_string += "size :  {} bytes\n".format(self.size)
        the_string += "{}\n".format("Retain in cache if possible" if self._prefer_retain else "No cache retention")
        the_string += "{}\n".format("Must retain as persistent" if self._must_retain else "No persistent retention")
        the_string += "{}\n".format("Is Persistent" if self.has_persistence() else "Not persistent")
        return the_string

        
class ImageCache(object):
    """Provides cache semantics for a single Image via its ImageHandle

    Cache rules

    All caches provide a way of caching ImageHandles indexed by the name of the image as the ImageName.name
    The caches return an ImageHandle, which in combination with the name provided should allow the caller to
    construct a new ImageBase or derived object if needed.

    The ImageHandle class is responsible for the actual movment of data to and from any storage capability,
    it is the responsibility of the cache to provide the name the image data will be known by in the store,
    and to provide any needed credentials.  Thus there should be methods and state in the ImageHandle class 
    that correspond to each of the mechanisms that a cache will be implmented with.  Currently this means
    local files and remote persistent store (ie Swift.)  

    Usually an image will be known by its ImageName.name in a store, but there may be need to vary this. Currently
    the name is simple ascii, but with commas, underscores and dashes.  We may need to encode the name if we get more
    messy.

    The caches are responsible for indexing the stores to reload their state (ie cache lookup tables) upon restart
    if persistence of data in the caches is required.

    Caches may push data down in a heirarchical manner, where the next store down is identified by the approriate next level value.
    This operation is optional, and can be configured.
    """

    def __init__(self, configuration):
        """Instantiate a cache

        :param configuration: Configuration to use for the cache
        :type configuration: Configuration.CacheConfiguration
        """
        self._contents = {}                       # dictionary implmenting the cache index
        self._max_size = configuration.max_size                 # maximum space to use to store cached objects
        self._max_elements = configuration.max_elements         # max number of elements to cache
        self._base_cost = -1                      # metric of the cost (usually in time) to retreive the object from the cache
        self._hysterysis = 0.3                    # slop in the max_size to eviction threshold
        self._size = 0                            # space used to store the elements
        self._next_empemeral = None  #configuration.next_emphemeral                # next level cache to push purged object sto
        self._next_persistent = None
        self._logger = logging.getLogger("image_repository")
        self._previous = None # configuration._previous_level
        self._eager_writeback = configuration.eager_writeback
        self._configuration = configuration
        self._lock = RLock()
        
    def set_next_ephemeral_level(self, cache):
        """Set the cache that will receive ephemeral objects if they are evicted from this cache

        :param cache: ImageCache
        """
        self._next_ephemeral = cache

    def set_next_retained_level(self, cache):
        """Set the cache that will receive persistent objects if they are evicted from this cache

        :param cache: ImageCache
        """
        self._next_persistent = cache

    def set_previous_level(self, cache):
        """Set the cache from which we will objects if they are evicted from that cache

        :param cache: ImageCache
        """
        self._previous = cache
        
    def contains(self, name):
        """Return whether the named element is in this cache

        :param name: key for the image in the cache
        :type name: string
        :rtype: boolean
        """        
        return str(name) in self._contents


    def list_images(self, path = None, separator = '/'):
        """Provide a directory tree like lisiting capability

        :param path: psuedo path within the repository to base list
        :type path: string or None
        :param separator: The path separator chratacter, defaults to '/'
        :type separator: character

        Currently not implemented bar trivial return of all keys
        """
        return self._contents.keys()

    def image_names(self):
        """Return a list of all the ImageNames

        :rtype: list of ImageName
        """
        return ( self._contents[name].image.name for name in self._contents.iterkeys() )
    

    def stressed(self):
        """Returns whether this cache is unwilling to accept images that are not either must_retain or should_retain.
        
        :rtype: boolean
        """
        # Totally arbitray figure - TODO -  provide configuration parameter
        return len(self._contents) > self._max_elements * 0.5        
    
    # We could allow run-time configuration of these policies given Python easily supports such capabilties.

    @staticmethod
    def _is_permanent(name):
        """Returns whether the image should be considered persistent or not based upon its name.

        :param name: The name of the image
        :type name: ImageName or string
        :rtype: boolean
        
        Here the policy on retention by name derived attributes is defined.
        We can expand this as needed, currently only ``original`` images must be permanent.
        """
        if isinstance(name, ImageName):  # Belt and braces in case we are called with a string - should try to avoid this.
            image_name = name
        else:
            image_name = ImageName(name)

        return image_name.is_original()


    @staticmethod
    def _should_retain(name):
        """Returns whether the image should be retained to imporove performance

        :param name: The name by which the image is identified
        :type name: ImageName or string
        :rtype: boolean

        Here the policy on retention by name derived attributes is defined.
        We can expand this as needed, currently only ``thumbnail`` images are retained.
        """ 
        if isinstance(name, ImageName):
            image_name = name
        else:
            image_name = ImageName(name)

        return image_name.is_thumbnail()
    
    def get_contents(self):
        return self._contents.keys()
    
    def get_image(self, name):
        return ImageHandle.from_bytes( self.get(name) )
        
    def get(self, name):
        """Return the named object if is present in the cache or return None

        :param name: Name of the object to find
        :type name: ImageName or string
        
        :rtype: ImageHandle or None
        """
        name = str(name)
        try:
            with self._lock:
                self._contents[name].access_time = time.clock()  # Maintain access time            
                return self._contents[name].image
        except KeyError:
            return None

    def asysnc_add(self, image):
        """Accept enqueue of an image for addition into the cache        
        """
        # Right now there is no support for async IO callback - so just do a synchronous add
        self.add_image(image)        
        return True

    def _async_callback(self, **kwargs):
        """Callback for use by underlying IO subsystem to signal completion of operation
        """
        pass
        
    def add(self, name, element, retain = False, must_retain = False):
        """Add the element, keyed by name, to the cache
        
        :param name: The name by which the element is indexed
        :type name: string
        :param: element: The image
        :type element:  ImageInstance or derived class
        :param retained: Whether to prefer this element over others when performing cache cleaning.
        :type retained: boolean
        :rtype: boolean
        :raises: RepositoryError, RepositoryFailure
        """
        
        #        if name in self._contents.keys():
        #            return  # As a sanity check we may want to check the contents are referencing the right thing here.

        # Stupid sized elements will cause problems quickly - just don't cache them

        if self.contains(name):
            return True
        
        if self._max_size != 0 and element._image_handle.size() > self._max_size * 0.1:
            self._logger.info("{}   Element of size {} exceeds 10% of max size {} ".format(
                self._class__.__name__, element._image_handle.size(), self._max_size))
            # Cope with how to manage this.
            # If ephemeral we can drop it on the floor.
            # If persistent we must ensure it goes back to the persistent object store
            # Return False and let another (hopefully bigger lower level cache have it.
            return False
        # Alternatively we can
        #            raise RepositoryFailure("Request exceeds store capacity", 507)            

        try:
            entry = CacheEntry(element, element._image_handle.size(), retain = retain, permanent = must_retain)
            with self._lock:
                self._contents[name] = entry
                self._size += element._image_handle.size()
            self._store_actual(str(name), element)
            if self._eager_writeback:
                self._write_back(name)
            return True
        except (RepositoryFailure, RepositoryError) as ex:
            raise ex
        except Exception:
            self._logger.exception("Unhandled exception in {} add({})".format(self.__class__.__name__, name))
            raise RepositoryError("Internal Repository Error")

        # TODO - we should initiate a concurrent clean rather than do this sychronously
        with self._lock:
            if self._size + self._max_size or len(self._contents) > self._max_elements:
                self._clean()
        return True
            
    def _clean(self):
        """Initiate a cleanout of the cache.  

        Actual cached objects may take some time to actually vanish, depending upon the 
        storage mechanism for this level.

        Entries are preferentially evicted.
        Entries for which ``should_retain()`` is False are evicted ahead of entries for which it is True.
        Within this preference, entries that have been last accessed further in the past are evicted first.
        
        Clean only removes enough entries to bring the cache to within the configured residency boundaries.
        This is ``hysterysis`` times the maximum size and maximum number of entries.
        """

        kill_list = []
        persistent_write_back = []
        retained_list = []
        retained_size = 0
        persistent_size = 0
        kill_size = 0

        # Sorting by access time - we could add further tweaks to create weightings if needed
        with self._lock:
            sorted_contents =  sorted(self._contents.iteritems(), key = lambda (k,v) : v.access_time)
        
        for entry in sorted_contents:
            # We must not accidentally wipe out any image that is both permanent but not yet part of the persistent store
            if not (entry[1].must_retain() and not entry[1].has_persistence()):
                if entry[1].should_retain():
                    retained_list.append(entry)
                    retained_size += entry[1].size
                else:
                    kill_list.append(entry)
                    kill_size += entry[1].size
            else:
                persistent_write_back.append(entry)
                persistent_size += entry[1].size
        
        # Three lists

        # we can throw away anything on the kill list
        # We can throw away anything on the retained list but maybe at some future cost
        # We must write back to persistent store anything on the persistent list, and may then consider throwing it away.

        # the lists are in access time order,

        # Tactics:
        # We only remove xxx * hysterysis 
        # Quickly wipe out the kill list - queue for write back
        # Queue persistent for write back - only remove when write back is confirmed

        # Sizes may be zero - hence use of >= - in which case the total number will drive the clean
        
        to_delete = min(int(self._max_elements * self._hysterysis), len(self._contents)) + 1
        size_to_delete = min(int(self._max_size * self._hysterysis), self._size)

        self._logger.debug("{} clean.  Currently {} element {} bytes. Targets to free: number = {}, size = {}, kill list size = {}, retained_list size = {}, persistent size = {}".format(
            self.__class__.__name__, len(self._contents), self._size, to_delete, size_to_delete, len(kill_list), len(retained_list), len(persistent_write_back)))

        # Start with the kill list
        index = 0
        while to_delete > 0 and size_to_delete >= 0 and index < len(kill_list):
            delete_this = kill_list[index]
            if self.delete(delete_this[0]):   # It is possible a delete will fail
                to_delete -= 1
                size_to_delete -= delete_this[1].size
            index += 1

        if size_to_delete <= 0 and to_delete <= 0:
            return
            
        index = 0
        while to_delete > 0 and size_to_delete >= 0 and index < len(persistent_write_back):
            delete_this = persistent_write_back[index]
            self._async_write_back(delete_this[0])
            if self.delete(delete_this[0]):   # It is possible a delete will fail
                to_delete -= 1
                size_to_delete -= delete_this[1].size
            index += 1

        if size_to_delete <= 0 and to_delete <= 0:
            return
            
        self._logger.debug("Cache clean for {}. Using retained list of size {}".format(self.__class__.__name__, len(retained_list)))
            
        index = 0
        while to_delete > 0 and size_to_delete >= 0 and index < len(retained_list):
            delete_this = retained_list[index]
            if self.delete(delete_this[0]):   # It is possible a delete will fail
                to_delete -= 1
                size_to_delete -= delete_this[1].size
            index += 1
            
        # At this point the cache should be able to accept new entries
        # Sanity check things
        if self._size > self._max_size or self._max_elements < len(self._contents):
            # Somehow the cache isn't cleaning
            self._logger.error("Cache {} failed to clean properly\n size {} vs max of {}, count of {} vs {}".format(
                self.__class__.__name__, self._size, self._max_size, len(self._contents), self._max_elements))
            self._handle_clean_failure()


    def _handle_clean_failure(self):
        """Cope with failure to clean out the cache to within configuration limits.

        This method should be overridden.

        :raises: RepositoryError
        """
        raise RepositoryError("Internal Cache Error")

    def _async_write_back(self, image_name):
        """Enqueue an entry for writeback to the next lower level

        :rtype: boolean
        :raises: RepositoryError
        """
        name = str(image_name)
        with self._lock:
            entry = self._contents[name]
            
        try:
            if not entry[1].must_retain:
                if self._next_ephemeral is not None:
                    return self._next_ephemeral.async_add(name,
                                                          entry.image,
                                                          entry.prefer_retain,
                                                          entry.must_retain)
            else:
                if self._next_persistent is not None:
                    return self._next_persistent.async_add(name,
                                                           entry.image,
                                                           entry.prefer_retain,
                                                           entry.must_retain)
                else:
                    # We should never not have a capability to accept retained elements
                    raise RepositoryError("Internal Cache Configuration Error")
        except (KeyError) as ex:
            return False
            
    def _flush_down(self):
        """Flush  the entire contents of the cache to the next lower cache."""
        
        self._logger.info("{} starts flush down".format(self.__class__.__name__))
        with self._lock:
            for name in self._contents.iterkeys():
                self._write_back(name)
        self._logger.info("Cache ends flush down")
                
    def delete(self, image_name):
        """Remove a specified image from the cache.

        :param name: name of the entry that the cache has as the key
        :type name: string

        The cache is responsible for removing any local file, persistent, or other storage used.
        However in-memory ImageInstance objects will be removed by normal garbage collection operations.
        """

        name = str(image_name)
        self._logger.debug("Deleting {} from {}".format(name, self.__class__.__name__))
        try:
            with self._lock:
                if self._contents[name].must_retain():
                    self._async_write_back(name)
                entry = self._contents[name]
                self._size -= entry.size
                self._remove_actual(name)
                del self._contents[name]
            return True
        except (KeyError) as ex:
            self._logger.exception("Attempt to delete cache entry not in cache.  {}".format(name))
            return False
        
    def _write_back(self, image_name):
        """Synchronously write the named element back to the next level of the heirarchy

        :param name: name of the element to write back
        :type name: string
        :raises: RepositoryError
        """
        name = str(image_name)
        # It is OK not to have a lower level cache for ephemeral elements, but not for persistent ones.
        try:
            if not self._contents[name].must_retain():
                if self._next_ephemeral is not None:
#                    print "Ephemeral add for {}".format(name)
                    print self._contents[name]
                    self._next_ephemeral.add(name, self._contents[name].image, self._contents[name].should_retain(), self._contents[name].must_retain())
            else:
                if self._next_persistent is not None:
#                    print "Persistent add for {}".format(name)
                    self._next_persistent.add(name, self._contents[name].image, self._contents[name].should_retain(), self._contents[name].must_retain())
                else:
                    raise RepositoryError("Internal Cache Configuration Error")
        except (KeyError) as ex:
            raise RepositoryError("Internal Consistency Error")
        
    def _remove_actual(self, name):
        """Remove the actual image from whatever manner it is stored.

        Returns whether the element was sucessfully removed

        Must be overridden in concrete class

        :param: name: name by which the element can be found in the cache
        :type name: string
        :rtype: Boolean
        """
        raise RepositoryFailure("Not Overrriden")


    def _store_actual(self, reference, element):
        """
        Store the actual image from whatever manner it is stored.
        Must be overridden in concrete class

        :param: reference: reference by which the element can be found in the cache
        :param: element:  The actual element data to be stored
        :returns: internal reference for the stored element (depends upon the cache) or None if not stored
        :throws: RepositoryFailure if the cache storage cannot accept the element
        """
        raise RepositoryFailure("Not Overriden")
        
    def cost(self, name):
        """
        Return a unitless cost metric representing the relative cost of retreiving the object from
        the cache.  self._base_cost must be initialised in the sub-class or this method must be overridden.
        """
        if self.contains(name):
            return self._base_cost
        else:
            return None  # No cost means the image does not exist

    def trigger_clean(self):
        """
        Queue a cache clean operation
        :returns: Boolean: Whether the request was sucessfully queued
        """
        return False

    def trigger_flush(self):
        """
        Trigger a cache flush operation
        :returns: Boolean: Whether the request was sucessfully queued
        """
        return False

    def cancel_clean(self):
        """
        De-queue any cache clean operation not yet started
        :returns: Boolean: Whether the request was sucessfully de-queued
        """
        return False

    def cancel_flush(self):
        """
        De-queue and cache flush operation not yet started
        :returns: Boolean: Whether the request was sucessfully de-queued
        """
        return False


    def url(self, name):
        """Return a temporary URL from which the image may be obtained

        :rtype: string
        :raises: RepositoryFailure

        Currently the only mechanism for obtaining a URL is via a Persistent Store/Cache.
        Other cache levels are unable to perform this, since it would require additional
        HTTP server capabilities. Method is overridden as approriate
        """
        raise RepositoryError("Must be specialised") 

    def __str__(self):
        the_string = "    Base Cache:"
        the_string += "    elements : {}".format(len(self._contents))
        return the_string
        
    
class MemoryImageCache(ImageCache):
    """
    Provide a cache of images that reside within the running address space
    """
    def __init__(self, configuration):
        super(MemoryImageCache, self).__init__(configuration)
        self._base_cost = 0
        self._live_ref = {}    # Keeps a set of references to in-memory wand.image.Image instances to keep them live

    def __str__(self):
        the_string =  "  Memory Cache:\n"
        the_string += "    elements   : {}\n".format(len(self._contents))
        the_string += "    size       : {}".format(self._size)
        return the_string

    def _store_actual(self, reference, element):
        """Maintain a reference to the in-memory instance to keep it live
        """
#        self._live_ref[reference] = element._image_handle._image
        return element

    def _remove_actual(self, reference):
        """Delete the liveness reference to the in-memory instance
        """
        self._contents[reference].image._image_handle.weaken_liveness()
        return True

class LocalFileImageCache(ImageCache):
    """Provide a cache for images using storage on a local file system

    Images cached in local files can outlive instances of the program,
    but are subject to removal on system reboot, or general cleaning up.
    Thus we can usefully reuse them on restart, but cannot assume that they will be there.
    """
    def __init__(self, configuration):
        """Construct a local file cache

        :param configuration: Configuration for the cache
        :type configuration: CacheConfiguration
        """
        super(LocalFileImageCache, self).__init__(configuration)
        self._base_cost = 1
        self._file_cache_path = configuration.cache_path

        if configuration.initialise:
            self._initialise()
        else:
            self._check_state()



    def add_image_handle(self, image_name, instance, retain = None, permanent = None):
        """Tell the cache that a file has appeared within its storage area that it should include in its contents.

        This provides a backdoor for mechanisms like Swift to upload a file directly into the cache. 
        This is useful as Swift can only upload into a local file, not memory. 

        :param name: name by which the entry is keyed in the cache
        :type name: string
        :param instance: The image instance that holds the uploaded image
        :type instance: ImageInstance
        :param retain: Whether to preferentially retain the entry
        :type retain: boolean
        :param permanent: Whether the entry musyt always have a persistent version extant
        :type permanent: boolean
        """
        name = str(image_name)
        if name in self._contents:
            # We may only need to tell the cache it always was persistent
            pass
#            self._contents[name].set_persistent(True)
        else:
            if retain is None:
                retain = self._should_retain(name)                
            if permanent is None:
                permanent = self._is_permanent(name)
            size = instance.get_image_handle().size()
            entry = CacheEntry(instance, size, retain, permanent)
            with self._lock:
                self._contents[name] = entry
                self._size += size
        # TODO - Remaining issue - do we check for cache size limits here or not?
        # There is some danger we can get locked into a performance destroying battle with the persistemt cache.
            
    def _initialise(self):
        """Initialise a new file storage area.

        If the storage area alreay exists, permissions are checked and the contents are cleared out.
        If no storage area exists it is created with aprorpriate permissions.

        :raises: RepositoryError
        """
        path = self._file_cache_path
        try:
            if os.path.isdir(self._file_cache_path):
                # check the permissions and clear the contents
                if os.path.isdir(path):
                    mode = os.stat(path).st_mode
                    if stat.S_IRUSR & mode :
                        if mode & (stat.S_IRWXG | stat.S_IRWXO) :
                            self._logger.error("Existing cache directory {} has insecure permissions".format(path))
                            raise RepositoryError("Existing cache directory {} has insecure permissions".format(path))
                    else:
                        self._logger.error("Existing cache directory {} is not accessible".format(path))
                        raise RepositoryError("Existing cache directory {} is not accessible".format(path))

                    self._reinitialise()
            else:
                # create the cache directory
                permissions = 0700     # Owner rwx - nobody anything else
                os.mkdir(path, permissions)
        except IOError as ex:
            self._logger.exception("Error in _initialise for {}".format(self.__class__.__name__))
            raise RepositoryError("Error in _initialise for {}".format(self.__class__.__name__))

    def _check_state(self):
        """Check the state of an existing storage area and read the contents. 

        Permissions must be correct before proceedeing.
        Cache entries are created from valid image names, but are not loaded until needed.

        :raises: RepositoryError
        """
        try:
            path = self._file_cache_path
            if os.path.isdir(path):
                mode = os.stat(path).st_mode
                if stat.S_IRUSR & mode :
                    if mode & (stat.S_IRWXG | stat.S_IRWXO) :
                        self._logger.error("Cache directory {} has insecure permissions".format(path))
                        raise RepositoryError("Cache directory {} has insecure permissions".format(path))
                else:
                    self._logger.error("Cache directory {} is not accessible".format(path))
                    raise RepositoryError("Cache directory {} is not accessible".format(path))              

                for root, dirs, files in os.walk(path, followlinks = True):
                    for name in files:
                        # Avoid actually loading the image - so stat the file to find the size
                        image_name = ImageName.unsafe_name(name)
                        if name[0] != ".":
                            size = os.stat(path).st_size
                            retain = self._should_retain(image_name)
                            permanent = self._is_permanent(image_name)
                            self._contents[image_name] = CacheEntry(ImageInstance.from_file(os.path.join(root,name), image_name), size, retain, permanent)
                            self._size += size
            else:
                self._logger.error("Specifed existing cache directory {}  does not exist.".format(path))
                raise RepositoryError("Specifed existing cache directory {}  does not exist.".format(path))
        except IOError as ex:
            self._logger.exception("IOError in File Cache init")
            raise RepositoryError("IOError in File Cache init")
            
    def _reinitialise(self):
        """Removes the contents of the cache directory.
        
        :raises: RepositoryError
        """
        try:
            for root, dirs, files in os.walk(self._file_cache_path, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
        except Exception as ex:
            self._logger.exception("Failure in reinitialsation of local file cache {}".format(self._file_cache_path))
            raise RepositoryError("Failure in reinitialsation of local file cache {}".format(self._file_cache_path))


    def _set_passthrough(self):
        """Set the cache to pass all references through, and perform no further action itself.

        In the face of a serious problem, such as a full file system, and an inability to further operate
        we can cause the cache to stop operating in a manner that doesn't stop the repository working.


        Note: Swift may still need to upload images to the local files system - we can't fix things to allow this to work
        at the moment. It may be possible to fudge things with a memory file system. 
        """
        self._logger.critical("Cache {} for {} set to passthrough mode.".format(self.__class__.__name__, self._file_cache_path))
        print "Not yet implemented"
        

    def _handle_clean_failure(self):
        """Handle failure to clean out the cache by writing out persistent entries and reinitialising

        Try to free up the referred elements before we dump the references
        """
        try:
            for name, element in self._contents.iteritems():
                try:
                    self._size -= element.size()
                    self._remove_actual(name)
                except RepositoryFailure:   # Just keep going in the face of individual failures
                    continue
        except RepositoryError as ex:
            # Assume a proper error during removal is unrecoverable and just try to push on past it
            self._logger.exception("Cache reinit - removal of elements fails", exc_info = ex) 

        try:
            self._reinitialise()
        except RepositoryError:
            # it has all gone seriously bad, try to stay afloat
            self._set_passthrough()
            return
        self._contents = {}
        self._size = 0
        
    def __str__(self):
        the_string =  "  Local File Cache:\n"
        the_string += "    cache path : {}\n".format(self._file_cache_path)
        the_string += "    elements   : {}\n".format(len(self._contents))
        the_string += "    size       : {}".format(self._size)
        return the_string

    def _remove_actual(self, ref):
        """
        Delete the refered to file from the local file cache
        """
        try:
            os.delete(os.path.join(self._file_cache_path, ref))
            return True
        except Exception as ex:
            self._logger.exception("Error in deleting local file cache image {}".format(os.path.join(self._file_cache_path, ref)), exc_info = ex)
            return False

    def _store_actual(self, ref, element):
        """
        Write the image to the local file system.
        Uses ImageHandle to perform the task, as it encapsulates the file write capability of the Wand image.
        """
        try:
            element.get_image_handle().as_file(ref, self._file_cache_path)
            return element
        except (IOError) as ex:
            self._logger.exception("Failure to write file for local file cache".format(ref))
            raise RepositoryError("Failure to write file for local file cache".format(ref))
        

    def as_local_file(self, name, element):
        """Provide the path to a local file containing the named image

        :param name: Name of the image to provide a file for
        :type name: string
        :param element: The element to provide the path for
        :type element: ImageInstance
        :rtype: string
        """
        if name not in self._contents:
            self._store_actual(name, element)
            self.add_image_handle(name, element)
        return element.get_image_handle().get_file_path()


        
class PersistentImageCache(ImageCache):
    """Provide a cache for images that are stored on remote persistent storeage

    Images stored in persistent storage outlive instances of the server, or
    even instances of the server host machine.  They are however subject to
    removal if pressure on storage space so requires.

    OriginalImagesInstances are never subject to removal. They are not considered to be cached.
    BaseImageInstances are also never subject to removal. They are not considered to be cached.

    Intermediate images may be cached - and images for which external URLs have been issued must
    be retained at least until the time on the URL has expired.

    Thumbnails are almost certainly a good idea to preferentially retain. 
    """

    def __init__(self, configuration):
        super(PersistentImageCache, self).__init__(configuration)
        self._base_cost = 10
        self._persistent_store_path = configuration.container
        #        self._store_kind = store_kind
        #        self._store = store_kind(configuration)

        swift = Stores.SwiftImageStore( configuration, self )

        self._store = swift
        self._initialise()

        
    def _initialise(self):
        names = []
        for name, size, kind in self._store.list_images():
            image_name = ImageName(name)
            if not image_name.is_original():
                format = self.from_content_type(kind)
                entry = CacheEntry(GeneralImage.from_persistent(self._store, path = name), size = size, retain = self._should_retain(name), permanent = False)
                self._contents[name] = entry
                self._size += size
                names.append(name)

        logger.info("{} Starts with {} objects".format(self.__class__.__name__, len(names)))        
        image_metadata = self._store.find_metadata(names, ['lifetime'])
        logger.info("{} {} objects with lifetime values".format(self.__class__.__name__, len(image_metadata)))
        for the_object, meta in image_metadata:
            try:
                self._contents[the_object].set_retain_until(float(meta['lifetime']))
            except KeyError, ValueError:
                continue
            
    # In principle a Swift store can hold an arbitrary amount of metadata as key:value pairs
    # By default we get the content_type from which we can get the image type that Swift thinks it is.
            
    @staticmethod
    def from_content_type(kind):
        is_image, format = kind.split("/")
        if is_image != "image":
            return None
        return format
        
    def set_file_cache(self, cache):
        """Set the file cache that this instance may use as a staging area for downloading files.

        Swift seems unable to download a file into anything other than a file, which restricts things.
        We can usefully download into a local file cache's storage area and thus imnplicity add the file
        to that cache.  Since names are unique to the image, there is no danger of overwriting an image
        with the wrong data.
        """
        self._store.set_file_cache(cache)
            
    def __str__(self):
        the_string   =  "  Persisent Cache:\n"
        the_string.join("    store : {}\n".format(self._store))
        the_string.join("    path       : {}\n".format(self._persistent_store_path))
        the_string.join("    elements   : {}\n".format(len(self._contents)))
        the_string.join("    size       : {}".format(self._size))
        return the_string

    #  We use the ImageHandle to perform the communication with the persistent store 
    
    def _store_actual(self, ref, element):
        return element._image_handle.as_persistent(ref, self._store)
    
    def _remove_actual(self, ref):
        if self.may_remove(ref):
            logger.debug( "deleting {} from persistent store".format(ref))
            return self._store.delete_images([ref])
        return False
        
    def _write_back(self, name):
        pass



    # BAD - this conflicts with the operation on the cache entry.
    def may_remove(self, image_name):
        """Return if it is safe to remove the named object


        :param image_name: The name of the object to check
        :type image_name: string or ImageName
        :rtype: boolean
        """
        name = str(image_name)
        if self._contents[name]._retain_until is None:
            metadata = {'lifetime':None }
            self._store.find_metadata(name, metadata)
            if metadata['lifetime'] is not None:
                self._contents[name].set_retain_until(int( metadata['lifetime']))
                print "Got retain until for {}".format(name)
        return not self._contents[name].must_retain()

    def url(self, name):
        """Return a temporary URL by which the image can be obtained

        
        :rtype: string
        """
        try:
            # Not persistent, must force it back
            if not self._contents[str(name)].has_persistence():
                self._store_actual(str(name), self._contents[str(name)][1].image)
            # try to avoid constant updates to the metadata by using a slack period
            lifetime = self._contents[str(name)].get_retain_until()
            update_metadata = False
            # If the retain time is less than we are asking for, bump it up, and add the slack
            if lifetime < self._configuration.url_lifetime + time.time():
                lifetime = self._configuration.url_lifetime + time.time() + self._configuration.url_lifetime_slack
                update_metadata = True

            url = self._store.temporary_url(str(name), lifetime, update_metadata)
            self._contents[str(name)].set_retain_until(lifetime)
            logger.debug("{}   Temp URL for {}. lifetime = {} update meta = {},  {}".format(self.__class__.__name__, name, lifetime, update_metadata, url))
            return url
        except KeyError:
            logger.error("{}   name {} not in cache for url creation".format(self.__class__.__name__, name))
            raise RepositoryFailure("{}   name {} not in cache for url creation".format(self.__class__.__name__, name))
        except Exception:
            logger.exception("{} Unhandled exception in creating url for {}".format(self.__class__.__name__, name))
            raise RepositoryError("{} Unhandled exception in creating url for {}".format(self.__class__.__name__, name))

class ImageStore(ImageCache):
    
    def __init__(self, configuration):
        super(ImageStore, self).__init__(configuration)
    

class PersistentImageStore(PersistentImageCache):
    """Provides the permanent image storage for images that are expected to be retained.

    Derived from the PersistentImageCache class to provide most of the useful functionality, and
    allowing it to usefully exist within the cache heirarchy.

    This can be used next to or instead of the PersisentImage Cache.
    """

    def __init__(self, configuration):
        super(PersistentImageStore, self).__init__(configuration)
        self._base_cost = 10
        self._persistent_store_path = configuration.container
        #        self._store_kind = store_kind
        #        self._store = store_kind(configuration)

        swift = Stores.SwiftImageStore( configuration, self )

        self._store = swift        
        
        self._initialise()

        
    def _initialise(self, use_name = True):
        """Start up the persisent image store

        :param: use_name:  If the store should check to see whether images are retained from their names.
        This is only needed if the store is shared with a cache of derived images.
        :type use_name: boolean
        """
        for name, size, kind in self._store.list_images():
            image_name = ImageName(name)
            if not use_name or image_name.is_original():
                format = self.from_content_type(kind)
                entry = CacheEntry(GeneralImage.from_persistent(self._store, path = name), size = size, retain = self._should_retain(name), permanent = True)
                self._contents[name] = entry
                self._size += size


    # In principle a Swift store can hold an arbitrary amount of metadata as key:value pairs
    # By default we get the content_type from which we can get the image type that Swift thinks it is.
            
            
    def __str__(self):
        the_string =  "  Persisent Store:\n"
        the_string += "    store : {}".format(self._store)
        the_string += "    path       : {}\n".format(self._persistent_store_path)
        the_string += "    elements   : {}\n".format(len(self._contents))
        the_string += "    size       : {}".format(self._size)
        return the_string

    # Override actions that need additional care

    def delete(self, name):
        # TODO - decide how much checking this needs to perform
        # Deletion of persistent elements from the store should be a very unusual event.
        try:
            self._remove_actual(self._contents[name])
            self._size -= element._image_handle.size()
            return True
        except KeyError:
            return False

    def add(self, image_name, element, retain = None, must_retain = True):
        """Add the element, keyed by name, to the cache
        
        :param image_name: The name by which the element is indexed
        :type image_name: string or ImageName
        :param: element: the element being added to the cache
        :type element: ImageHandle
        :rtype: Boolean
        """

        name = str(image_name)
        if self.contains(name):
            return True

        if retain is None:
            retain = self._should_retain(name)
                
        try:
            entry = CacheEntry(element, element._image_handle.size(), retain = retain, permanent = True)
            self._contents[name] = entry
            self._store_actual(name, element)
            self._size += element._image_handle.size()
            return True
        except RepositoryError as ex:
            self._logger.error("Add to {} fails".format(self.__class__.__name__))
            raise ex
    
    def _remove_actual(self, ref):
        self._logger.info( "deleting {} from persistent store".format(ref[0]))
        return self._store.delete_images([ref.image._persistent_path])
        
    # Disable cache-like behavior

    def write_back(self, name):
        return
#        raise RepositoryError()  
    
    # We do not allow any automatic deletion of preserved images
    
    def _clean(self):
        return
#        raise RepositoryFailure()

    def _flush_down(self):
        return
#        raise RepositoryFailure()
    
class CacheMaster(ImageCache):
    """Controlling cache interface
    
    Acts as a cache in its own right, but uses the other levels of cache objects to implment
    the cache heirarchy.
    """
    
    def __init__(self, configuration):
        """Instantiate the cache heirarchy

        :param configuration: The configuration for the entire cache system
        :type configuration: Configuration.CacheConfiguration

        Creates the designated caches, and binds them into a cache hierarchy.
        """
        self._logger = logging.getLogger("image_repository")
        self._base_images = None
        self._memory_cache = MemoryImageCache(configuration.memory_cache_configuration)

#        print self._memory_cache
        
        self._file_cache = LocalFileImageCache(configuration.local_cache_configuration)

#        print self._file_cache

        configuration.swift_cache_configuration._file_cache_path = configuration.local_cache_configuration.cache_path
        configuration.persistent_store_configuration._file_cache_path = configuration.local_cache_configuration.cache_path

        self._persistent_cache = PersistentImageCache(configuration.swift_cache_configuration)
#        print self._persistent_cache

        self._persistent_store = PersistentImageStore(configuration.persistent_store_configuration)
#        print self._persistent_store        
        
        self._memory_cache.set_next_ephemeral_level(self._file_cache)
        self._memory_cache.set_next_retained_level(self._file_cache)

        self._file_cache.set_next_ephemeral_level(self._persistent_cache)
        self._file_cache.set_next_retained_level(self._persistent_store)

        self._file_cache.set_previous_level(self._memory_cache)
        self._persistent_cache.set_previous_level(self._file_cache)

        self._persistent_store.set_previous_level(self._file_cache)


        self._search_caches = (self._memory_cache,  self._file_cache, self._persistent_cache, self._persistent_store)
        
                        
    def cost(self, image_name):

        name = str(image_name)
        cost = self._memory_cache.cost(name)
        if cost is not None:
            return cost
        cost = self._file_cache.cost(name)
        if cost is not None:
            return cost
        return self._persistent_cache.cost(name)

    def use_local_master(self, image_name):
        """Returns if the most efficient way of producing the image is to derive it from a locally held
        copy of the master.

        This allows short circuiting of access to files that may take longer to fetch than to recreate.  
        
        :param name: The name of the image we wish to create
        :type name: ImageName
        """
        
        master_cost = self.cost(name.master())
        if master_cost is None:
            raise RepositoryError("Request for master image {} that does not exist".format(name.master()))
        image_cost = self.cost(name.image_name())
        if image_cost is None:
            return True
        return image_cost > master_cost
    
    def _get_entry(self, name):
        """Implement the cache heirarchy get function

        :param name: name of the image to get
        :type name: string
        :rtype: ImageInstance or None
        
        """
        image = self._memory_cache.get(name)
        if image is not None:
            return image
        image = self._file_cache.get(name)
        if image is not None:
            return image
        image = self._persistent_cache.get(name)
        if image is not None:
            return image
        image = self._persistent_store.get(name)
        if image is not None:
            return image        
        return None

    def get(self, name):
        """Get the image from its name from any cache

        :param name: name of the image to get
        :type name: string
        :rtype: ImageInstance or None        
        """
        if isinstance(name, ImageName):
            the_name = str(name)
        else:
            the_name = name
        return self._get_entry(the_name)
    
    def get_as_defined(self, definition_name):
        """Get the image as defined by name

        The image name may or may not describe an extant derived image.  If an image with the name
        exists, return it. If it does not exist, use the name to construct it.

        :param name: Name describing the image to be returned
        :type name: ImageName
        """
        image = self.get(definition_name)
        if image is not None:
            return image

        # Find the original image - we don't care about the image format, so we can simply look in the base_images
        try:
            base_image = self._base_images[definition_name.base_name()].baseimage(full_name = True)
            base_kind = base_image.name.image_kind()
        except KeyError:
            raise RepositoryError("Expected name: {} not in base image names".format(definition_name))

        # Cope with an edge case in the naming scheme. 
        # If there is no other derivation operation we need to force the format conversion
        # so the as_defined call will process it.
        if not definition_name.is_derived() and definition_name.image_kind() != base_kind:
            definition_name.apply_convert(definition_name.image_kind())
            logger.debug("Applied format conversion to base {} from {}".format(definition_name, base_image.name))
            
        new_image = base_image.as_defined(definition_name)
        self.add(definition_name, new_image)
        if new_image is None:
            logger.error("As defined returns None image from {}".format(name))
            raise RepositoryFailure("As defined returns None image from {}".format(name))
        if str(new_image.name) != str(definition_name):
            logger.error("Failure to create required defined image {}, got {} from {}".format(definition_name, new_image.name, base_image.name))
            raise RepositoryFailure("Failure to create required defined image {}, got {} from {}".format(definition_name, new_image.name, base_image.name))
        return new_image



    def add_image(self, image):
        """Place the image into the cache/store heirachy

        :param image: The image to add
        :type image: ImageInstance
        """
        must_retain = image.name.is_original()
        should_retain = image.name.is_thumbnail()
        self.add( str(image.name), image, retain = should_retain, must_retain = must_retain) 
        
    
    def add(self, name, image, retain = False, must_retain = False):
        """Place the image into the cache heirarchy

        :param name:
        :type name: string
        :param image: the image instance to add to the caches
        :image: ImageInstance
        :param retain: whether to consider the image as usefully retained during cache eviction operations. Default False
        :type retain: boolean
        """

        logger.debug("Adding image {} to master cache".format(name))
        
        ref = self._memory_cache.add(str(name), image, retain, must_retain)
        if ref is None:
            ref = self._file_cache.add(str(name), image, retain, must_retain)
        if ref is None:
            ref = self._persistent_cache.add(str(name), image, retain, must_retain)
        if ref is None:
            raise RepositoryFailure("Request exceeds store capacity", 507)
        #            raise RepositoryError("Failed to add {} to any cache".format(name))

        # Keep the base name list up to date
        if image.name.is_original():
            self._get_base_images()[image.name.base_name()] = image
        return ref
        

    def cache(self, image):
        raise RepositoryError("Deprecated")
        return

    def flush_memory(self):
        self._memory_cache._flush_down()

    def clean_memory(self):
        self._memory_cache._clean()

    def flush_local_file(self):
        self._file_cache._flush_down()

    def clean_local_file(self):
        self._file_cache._clean()

    def clean_persistent(self):
        self._persistent_cache._clean()


    def as_local_file(self, name):
        """
        """
        element = self.get(name)
        if element is None:
            logger.error("Failed to find {} when attempting to get local file for image".format(name))
            return None
        return self._file_cache.as_local_file(name, element)
        
    def make_persistent(self, name):
        """Force the named object back into the approriate persistent store

        :param name: Name of the obejct to force back
        :type name: string
        :raises: RepositoryFailure, RepositoryError
        """
        entry = self.get(name)                
        if entry is not None:
            if not entry.get_image_handle().has_persistence():
                if self._is_permanent(name):
                    self._persistent_store._store_actual(str(name), entry)
                else:
                    self._persistent_cache._store_actual(str(name), entry)
        else:
            raise RepositoryFailure("Image name {} not in any cache to allow persistent copy creation".format(name))

        
    def url(self, name):
        """Create a temporary URL for the named image
        """
        entry = self.get(name)                
        if entry is not None:
            if self._is_permanent(name):
                self._persistent_store.add(str(name), entry)
                return self._persistent_store.url(name)
            else:
                self._persistent_cache.add(str(name), entry)
                return self._persistent_cache.url(name)
        else:
            raise RepositoryFailure("Image name {} not in any cache for url generation".format(name))

    def _get_base_images(self):
        """Return the list of all the names of images in the repository.

        :rtype: list of strings

        Base images names are the full name without suffix that the images were loaded as.
        Base names do not correspond to any actual image name, but form the basis for 
        cannonical names.  Base names can contain ``/`` 
        """
        if self._base_images is None:
            self._base_images = {}
            for cache in (self._memory_cache,  self._file_cache, self._persistent_store):
                for name in cache.image_names():        
                    if name.is_original():
                        self._base_images[name.base_name()] = cache.get(name)
        return self._base_images


    @staticmethod
    def _match_found(exp, name):
        match = exp.match(name)
        if match is None:
            return False
        else:
            return match.group(0) == name
                
    def list_base_images(self, path = None, regexp = None):
        if regexp is None:
            return self._get_base_images().keys()
        else:
            try:
                exp = re.compile(regexp) #, flags=re.DEBUG)
                if path is not None:
                    base_images = [ name for name in self._get_base_images() if name.find(path) == 0 ]
                else:
                    base_images = [ name for name in self._get_base_images().keys() ]
                return [name for name in base_images if self._match_found(exp, name)]
            except re.error as ex:
                raise RepositoryFailure("Regular expression fails {}".format(re.error))
            
    def get_base_images(self, name, regexp = None):
        """Return the BaseImageInstance for which the string name is the base name

        :param name: name (with no extension or derivation)
        :type name: string
        :param regexp: regular expression describing image names
        :type regexp: string
        :rtype: list
        """
        base_images = self._get_base_images()
        if regexp is None:
            try:
                return [base_images[name].baseimage()]
            except KeyError:
                return None
        else:
            try:
                exp = re.compile(regexp)
                return [base_images[the_name].baseimage() for the_name in base_images if self._match_found(exp, the_name)]
            except re.error as ex:
                raise RepositoryFailure("Regular expression fails {}".format(re.error))
                
    def get_original_images(self, name, regexp = None):
        """Return the OriginalImages for which the string name is the base name

        :param name: name (with no extension or derivation)
        :type name: string
        :param regexp: regular expression describing image names
        :type regexp: string
        :rtype: list
        """
        base_images = self._get_base_images()
        if regexp is None:
            try:
                return [base_images[name]]
            except KeyError:
                return None
        else:
            try:
                exp = re.compile(regexp)
                return [base_images[the_name] for the_name in base_images if self._match_found(exp, the_name)]
            except re.error as ex:
                raise RepositoryFailure("Regular expression fails {}".format(re.error))


            
    def contains_original(self, name, regexp = None):
        """Returns whether name is the name of an image for which we have an original, and can thus create derived images
        """

        if regexp is None:
            return name in self._get_base_images()
        else:
            try:
                exp = re.compile(regexp)
                for name in self._get_base_images():
                    if self._match_found(exp, name):
                        return True
            except re.error as ex:
                raise RepositoryFailure("Regular expression fails {}".format(re.error))
        return False
        
    def list_images(self):
        return None
                
    def shutdown(self):
        """Shutdown the cache system, ensuring that all persistent images are safe

        :raises: RepositoryError
        """
        self.flush_memory()
        self.flush_local_file()
        
        
    def __str__(self):
        the_string = "Image Cache Master\n"
        the_string += str(self._memory_cache) + "\n"
        the_string += str(self._file_cache) + "\n"
        the_string += str(self._persistent_cache) + "\n"
        the_string += str(self._persistent_store) + "\n"
        return the_string



def startup(configuration):
    configuration.memory_cache_configuration.max_elements = 50


#    configuration.swift_cache_configuration.initialise_store = True
#    configuration.persistent_store_configuration.initialise_store = True
    
    cache = CacheMaster(configuration)

    print "Startup cache"
    
#    print cache

    ImageInstance.set_cache(cache)
    ImageInstance.set_configuration(configuration)
    
    test_dir = "../test/image_test/images"


    swift_cache = cache._persistent_cache
    swift_store = cache._persistent_store
    file_cache = cache._file_cache
    mem_cache = cache._memory_cache

    
    swift_cache.set_file_cache(file_cache)
    swift_store.set_file_cache(file_cache)
    
    swift_cache_contents = swift_cache.get_contents()
    swift_store_contents = swift_store.get_contents()

    test_dir = "../test/image_test/images"

    return cache
    
    
def stress_test(configuration):


    configuration.memory_cache_configuration.max_elements = 50


#    configuration.swift_cache_configuration.initialise_store = True
#    configuration.persistent_store_configuration.initialise_store = True
    
    cache = CacheMaster(configuration)

    print "Start cache stress test"
    
#    print cache

    ImageInstance.set_cache(cache)
    ImageInstance.set_configuration(configuration)
    
    test_dir = "../test/image_test/images"


    swift_cache = cache._persistent_cache
    swift_store = cache._persistent_store
    file_cache = cache._file_cache
    mem_cache = cache._memory_cache

    
    swift_cache.set_file_cache(file_cache)
    swift_store.set_file_cache(file_cache)
    
    swift_cache_contents = swift_cache.get_contents()
    swift_store_contents = swift_store.get_contents()

    test_dir = "../test/image_test/images"

    print "Adding Images"

    image_count = 1000
    try:
        for root, dirs, files in os.walk(os.path.join(test_dir,"misc"), topdown=True):
            for name in files:
                if name[:1] == ".":
                    continue
                if image_count == 0:
                    raise StopIteration
                print "test with {}".format(name)
                img = OriginalImage.from_file(os.path.join(root,name))
                cache.add_image(img)
                imgt = img.thumbnail((50,50))
                cache.add_image(imgt)
                imgtt = img.thumbnail((100,100))
                cache.add_image(imgtt)
                imgtt = img.thumbnail((200,200))
                cache.add_image(imgtt)
                imgtt = img.resize((100,100))
                cache.add_image(imgtt)
                imgtt = img.resize((200,200))
                cache.add_image(imgtt)
                imgtt = img.crop((100,100))
                cache.add_image(imgtt)
                imgtt = img.crop((200,200))
                cache.add_image(imgtt)
                imgtt = img.crop((700,700))
                cache.add_image(imgtt)
                imgtt = img.convert("png")
                cache.add_image(imgtt)
                imgtt = img.resize((700,700), "png")
                cache.add_image(imgtt)
                image_count -= 1
    except StopIteration:
        pass
    except Exception as ex:
        logger.exception("Unhandled exception in add in images")
        exit(1)
        
#    print cache

    
#    cache.clean_memory()

#    print "flush file cache"
    
    cache.flush_local_file()
    
#    print cache        
    
#    print "Swift cache store contains {} elements".format(len(swift_cache_contents))
#    print "Swift persistent store contains {} elements".format(len(swift_store_contents))

#    print "get all swift cache"

#    for entry in swift_cache_contents:
#        cache.get(entry)
#        print cache.url(entry)
        
#    print cache

    print "get all swift persistent"

#    for entry in swift_store_contents:
#        print entry
#        cache.get(entry)
        
#    print cache
    
    print "clean persistent cache"

#    cache.clean_persistent()

#    print cache

    print "cache shutdown"
    
    cache.shutdown()
    
    print cache


    
    print "End cache stress test"
    

    
def test1(configuration):

    configuration.memory_cache_configuration.max_elements = 10
    
    cache = CacheMaster(configuration)
    
#    print cache

    ImageInstance.set_cache(cache)
    ImageInstance.set_configuration(configuration)
    test_dir = "../test/image_test/images"


    print "build orig image"
    
    img1 = OriginalImage.from_file(os.path.join(test_dir, "nacra.jpg"))
    print img1

    print "add to cache"
    
    cache.add_image(img1)


    print "make baseimage"
    
    base1 = img1.baseimage()
#    exif = img1.get_exif()
#    for m in exif.keys():
#        print "{} : {}".format(m, exif[m])
    print base1


    cache.add_image(base1)


    print "make crop"
    
    crop1 = base1.crop((1000,1000),(500,500), kind = 'jpg')


    print "made crop"

    
    print crop1
    #   f = crop1.file_path(".")
    #   print f


    print "add to cache"
 
    cache.add_image(crop1)


    print "look for crop1"

    
    x = cache.get(crop1.name)

    print "got {} back".format(crop1.name)
    print x

    
#    print cache


#    try:
#        for root, dirs, files in os.walk(os.path.join(test_dir,"misc"), topdown=True):
#            for name in files:
#                img = OriginalImage.from_file(os.path.join(root,name))
#                cache.add_image(img)
#                imgt = img.thumbnail((50,50))
#                cache.add_image(imgt)
#                imgtt = img.thumbnail((100,100))
#                cache.add_image(imgtt)
#    except Exception as ex:
#        print "Failure in adding images"
#        print ex
#        logger.exception("", exc_info = ex)

#    print cache

    print "clean cache"

    cache.flush_memory()


    print "Find crop1 again"

    x = cache.get(str(crop1.name))
    
    #    print x

    print "make thumbnail from original"
    
    t = img1.thumbnail((50,50))
    cache.add_image(t)

    print "clean memory cache"
    
    cache.clean_memory()

    print "flush file cache"
    
    cache.flush_local_file()
    
    print cache

    
#    y = x.crop((100,100),(0,0), kind = 'png')

#    print y
    #    print cache

#    for z in cache._file_cache ._contents.iterkeys():
#        print z



#if __name__ == "__main__":
#    stress_test()

