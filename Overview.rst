================
Image Repository
================
Operational Design
------------------

Images will be kept as individual file/objects. Most likely Swift will be the most useful of the object stores used, although others may be reasonable.

The key metadata for images will be maintained in a simple database, managed by the Django based Restfull interface.  The database will be only updated upon the addition of new images, or the need to update the metadata. Normal operation of the store should not require update of the database.  This especially means that the creation of derived images (such as thumnials, and images of intermediate resolution or other image formats will not ential an entry into the database.  This allows us to maintain the database in ephemeral local storage as much as possible.

The database must be backed up to reliable persistent storage (again mostly likely  a swift object, but others should be possible as well). This backup contitutes the durability step of maintaining database state.  An internal commit of a change to the local database state cannot be considered as durable.  Snapshots of the local database state to resilient storage are thus an essential part of the semantics of operation.

The object store may contain cached versions of the base image.  These will typically include thumbnails, and the most common requested image size and formats. Cached images are subject to deletion by the system as needed.  The main database will not contain cache image information.  The result of this is that cached images will need to be self describing.  The proposed mechanism is as follows.

1. The name of all versions (including the base) of images will contain a common unique base. Thus all versions of an image are associated.
2. The common name will be created from the hash of the base image. 
3. Derived images will apend the parameters needed to create them from the base image in a simple form.
   This will typically be the size and formal.  For instance:  ``xxxx-1024x512.jpg``.  The grammar for creating the suffix must be unambiguous.
4. The metadata database will refer to images via the common base name (essentially treating it as a foreign key).
5. The store manager interface will be responsible for providing whatever images, in whatever requested formats. Images are requested as (base_ident, size, format). Whether the images needs to be created on demand or supplied from a cached version is only the responsibility of the store manager layer.

Updates to the repository will all be done via a Django Restful interface.  However to avoid the expense of forcing a snapshot of the database being created upon each modification, a seperate commit changes operation will be provided. Upon successful completion, we guarentee that the store and database are in sync. We will allow snapshots of the database to be made asynchronosly as well.  As an improvemnt to the semantics of the user experiance we may wish to make update sessions to the databse atomic.  This means that only when the entire update session has completed do the changes become live, and visible to a general user browsing the repository.
   
It is possible that failure of the system (particularly part way through an upload of images) may result in the metadata database being out of sync with objects in the store.  The store may contain images that are not listed in the database, or the database my contain images that are not visible in the store.  A mechanism to bring the two into sync is needed.  This will involve nothing more than deleting either the database entry or the stored image so that the store and database become consistent. 

It is assumed that the system will be deployed within a Docker Container. This should not make any noticable difference to its design or operation, although, in general, it should be as self contained as reasonably possible, to avoid overly complicating th container deployment.  Little more than mapping the aproriate ports and access to Swift (or whatever back end is used) should be needed. 

