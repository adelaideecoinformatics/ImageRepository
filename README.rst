================
Image Repository
================

An image repository that provides for on-demand creation of derived images, in particular: thumbnails, different formats, scaled images.

The repository presents a simple RestFul interface, where images can be uploaded, or requests made for images to be either downloaded, or
provided as a URL, that accesses a Swift Object store.  Such URLs are temporary.

The repository maintains a local cache of images, both in-memory of the running server, and on local disk. Further it can maintain a cache of derived images on the Swift backing store, in addition to keeping the original images in the Swift store.  Images for which a URL has been created must reside within the Swift store.

The Repository can be wrapped with Gunicorn and Nginx to provide a fully functioning web service.

Currently no authentication is provided on the external inferface.

The repository is essentially stateless in that there is no additional database of images, or need for tracking of content beyond the contents of the base Swift object store contents. Images are uniquley defined by their name, and derived images are uniquely identified and regeneratable by their name. As such a repository server can be run up from scratch with nothing more than the location of the Swift object container where the original images are.  Once running it will proceed to cache images as needed, and maintain local and persistent copies of the caches as it sees fit.  If it is run up and these caches exist, it will use them.

The repository is configured from a single YAML configuration file, however defaults are provided internally for almost all options. Credentials for accessing the Swift object store must be provided.

Images that are served are, by default, stripped of any metadata that may be present in them. This provides default security, preventing image metadata (especially geo-location data) from inadvertently leaking sensitive information.  Limited metadata can be seperately retrieved for images.




