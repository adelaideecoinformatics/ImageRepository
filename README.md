================
Image Repository
================

An image repository that provides for on-demand creation of derived images, in particular: thumbnails, different formats, scaled images.

The repository presents a simple RestFul interface, where images can be uploaded, or requests made for images to be either downloaded, or
provided as a URL, that accesses a Swift Object store.  Such URLs are temporary.

The repository maintains a local cache of images, both in-memory of the running server, and on local disk. Further it can maintain a cache
of derived images on the Swift backing store, in addition to keeping the original images in the Swift store.  Images for which a URL has
been created must reside within the Swift store.

The Repository can be wrapped with Gunicorn and Nginx to provide a fully functioning web service.

Currently no authentication is provided on the external inferface.


