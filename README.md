# Image Repository

An image repository that provides for on-demand creation of derived images, in particular: thumbnails, different formats, scaled images.

The repository presents a simple RestFul interface, where images can be uploaded, or requests made for images to be either downloaded, or
provided as a URL, that accesses a Swift Object store.  Such URLs are temporary.

The repository maintains a local cache of images, both in-memory of the running server, and on local disk. Further it can maintain a cache of derived images on the Swift backing store, in addition to keeping the original images in the Swift store.  Images for which a URL has been created must reside within the Swift store.

The Repository can be wrapped with Gunicorn and Nginx to provide a fully functioning web service.

Currently no authentication is provided on the external inferface.

The repository is essentially stateless in that there is no additional database of images, or need for tracking of content beyond the contents of the base Swift object store contents. Images are uniquley defined by their name, and derived images are uniquely identified and regeneratable by their name. As such a repository server can be run up from scratch with nothing more than the location of the Swift object container where the original images are.  Once running it will proceed to cache images as needed, and maintain local and persistent copies of the caches as it sees fit.  If it is run up and these caches exist, it will use them.

The repository is configured from a single YAML configuration file, however defaults are provided internally for almost all options. Credentials for accessing the Swift object store must be provided.

Images that are served are, by default, stripped of any metadata that may be present in them. This provides default security, preventing image metadata (especially geo-location data) from inadvertently leaking sensitive information.  Limited metadata can be seperately retrieved for images.

# Requirements

 1. python 2.7 (probably won't work with 3+)
 1. internet connection, the server cannot run offline
 1. access credentials to a Swift object store on OpenStack, probably on NECTAR

If you want to build Docker images of the repo or run pre-built ones, you'll also need Docker.

# Quickstart installing using pip

You can install this app directly from github using pip. You should probably use a virtualenv too, like:
```bash
cd /some/dir/
mkdir my-image-repo
cd my-image-repo
virtualenv .
. bin/activate
pip install --upgrade git+git://github.com/adelaideecoinformatics/ImageRepository
image_repo -Yt > config.yml
# edit config.yml. At a minimum you'll want to change the following properties:
#  - local_cache_configuration.cache_path
#  - local_file_cache_path
#  - persistent_store_configuration.container
#  - swift_cache_configuration.container
#  - pid_file
chmod 700 /var/tmp/image_server # or whatever you set local_cache_configuration.cache_path to
# export all required Swift env vars:
export OS_AUTH_URL=https://keystone.rc.nectar.org.au:5000/v2.0/
export OS_USERNAME="user@edu.au"
export OS_PASSWORD="pass"
export OS_TENANT_NAME="name"
export OS_TENANT_ID="id"
# now we can run it
image_repo -y config.yml
```
You can install from the filesystem if you've cloned/downloaded the repo:
```bash
pip install --upgrade git+file:/home/user/git/ImageRepository
```
**Beware** that this will only install from the latest commit. It won't read dirty workspace changes.

# Developer workflow - running the app locally using uwsgi+Flask

Doing the `pip install` method is too cumbersome when developing locally. Instead, you can directly run the app using uwsgi and Flask with hot reloading. Follow these steps to create a virtualenv, install the requirements and start the app:

```bash
git clone <this repo>
cd ImageRepository
export git_dir=`pwd`
export repo_dir=~/my-image-repo
mkdir $repo_dir
cd $repo_dir
virtualenv .
. bin/activate
pip install Flask uwsgi # see https://uwsgi-docs.readthedocs.io/en/latest/Install.html if you have uWSGI issues
cd $git_dir
python setup.py install
cd $repo_dir
image_repo -Yt > config.yml
# You need to edit the config.yml file. At a minimum you'll want to change the following properties:
#  - local_cache_configuration.cache_path       consider $repo_dir/cache
#  - local_file_cache_path                      consider $repo_dir/file_cache
#  - pid_file                                   consider $repo_dir/pid
sed -i "s+/var/tmp+$repo_dir+" config.yml # this will put update these 3 local paths to your $repo_dir
#  - persistent_store_configuration.container
#  - swift_cache_configuration.container
# You need to edit these by hand to match the bucket names you've created in Swift
mkdir $repo_dir/image_server $repo_dir/image_repo # assuming you configured these dirs in the config
chmod 700 $repo_dir/image_server # or whatever you set local_cache_configuration.cache_path to
# export all required Swift env vars (it might be easier to put this in a file and source that file):
export OS_AUTH_URL=https://keystone.rc.nectar.org.au:5000/v2.0/
export OS_USERNAME="user@edu.au"
export OS_PASSWORD="pass"
export OS_TENANT_NAME="name"
export OS_TENANT_ID="id"
# now we can run it
# NOTE: we can't use Flask directly becuase that won't let us pass parameters to our app
uwsgi\
  --http :5000\
  --callable=app\
  --pythonpath=$git_dir/src/\
  --wsgi-file=$git_dir/src/main.py\
  --py-autoreload=1\
  --pyargv="-y $repo_dir/config.yml --debug" # add args to our app here
# open http://localhost:5000/images to get a list of images the server knows about
```

# Building and running docker image

This app can be built into a docker container by doing:
```bash
cd ImageRepository/
docker build -t image-repo .
```
You'll need to create a `swift.sh` file to provide your Swift credentials inside the container. You can find a template in `ImageRepository/docker/swift.sh` or copy from the following:
```bash
export OS_AUTH_URL=https://keystone.rc.nectar.org.au:5000/v2.0/
export OS_USERNAME="user@uni.edu.au"
export OS_PASSWORD="somepass"
export OS_TENANT_NAME="tenant"
export OS_TENANT_ID="id"
export SWIFT_P="image-repo"        # swift persistent bucket
export SWIFT_C="image-repo-cache"  # swift cache bucket

```
You can then run the built image using (edit `/path/to/host/` to suit your machine):
```bash
docker run -d -p 80:80 -v /path/to/host/swift.sh:/swift.sh image-repo
```
You can then access a listing of the stored images at http://localhost:80/images (or whatever host you ran the container on). See the section '*Interacting with the repository*' for more details on how to interact with the repo.

# Simple Use

To use the repository in its most simple form a very basic configuration is all that need be specified.
All the configuration can be specified in a YAML format configuration file. All configuration has defaults,
and the server will run with no additional configuration except for credentials for the Swift store.

A full configuration file can be created by running the server as `image_repo -Yt`. This will output a
configuration file that contains all of the possible options with their default values and then exit. 

It is assumed that a local file cache will be used, by default `/var/tmp/image_server` is used.

Two Swift containers are used, one for holding the permanent data (which is usually the uploaded image files) and
another that contains cached copies of derived images, and images that have been made available via a temporary URL.
These can be the same container, separating them simply allows for easy management or different deployment options.
By default these containers are `test_image_repo` and `test_image_repo_cache`. 

If temporary URLs are to be created a key must be set on the image cache Swift container.  This is a pain to set, as the
Web interface does not provide a mechanism to set it.  The Swift command package must be used. (Installing this on a Mac
is further fraught due to conflicts with various parts of the default Python and with the language *Swift*.  Use of a
`virtualenv` is essentially mandatory to have any hope of it working.)  The key set on the container is set in the
configuration file with the `url_key` option.  By default it is `123456789`, which is hardly secure.  When temporay URLs
are created there is no actual interaction with the Swift store (unless a new derived image must be created and stored).
The URL contains a signed request that the store uses its key to verify.

Credentials for accessing the Swift store must be provided.  The usual manner of doing this is to place the required
components in environment variables.  The automaticaly generated script (provided by the Swift Web interface) does this.
The default configuration is to read these environemnt variables.  They may also be read from files, or embedded
in the configuration file. Note that the password is not set in the autogenerated script, and must be entered interactively.
For long term use, reading it from a suitably secure file, or explicitly injecting it into the process as an environment variable
will be needed.

# Interacting with the repository

Run in test mode (with the default Werkzeug server) provides access on `http://127.0.0.1:5000/`.

The repository is visible at `/images`

Under `/images/` are the images.  Image paths are expected to be unique. No effort is made by the store to enforce uniqueness.
If a new image with the same path as an existing one is uploaded, the results are not defined.

Extention components (eg `.jpg` or `.png`) of the image names are not considered as part of the name. Images are considered to be abstract entities that
can be made real in any desired format or size. By default, all images are served in `jpeg` format, no matter what format they are uploaded in. Any
request for an image may request a different format.

Requests for an image may also include a size, which is taken to be a bounding box into which the image must fit. A specific form of resized image
is the thumbnail, which is generated as a distinct entity.  By default thumbnails fit into a 50x50 pixel box. They may also have image enhancement
operations performed to improve their clarity when viewed at such small resolutions.

Unless a temporary URL is requested for an image, the image requested will be returned in the response.  A single image will come as raw data. Multiple
images will be returned as a zip archive. Request for metadata will be returned in JSON format.

The accepted requests are as follows:

* `url=True`   Return a temporary URL from which the image my be retrieved.
* `xsize=<x>`    Rescale the image to fit within a width of at most x pixels.
* `ysize=<y>`    Rescale the image to fit within a height of at most y pixels.
* `thumbnail=True`  Return a thumbnail of the image. May be used with `xsize` and `ysize` to control the size of the thumbnail
* `meta=True`       Return a JSON representation of the metadata that was attached to the uploaded image. Not all possible metadata will be included.
* `kind=<format>`       Image format the image should be in. Defaults to `jpg`
* `regex=<expression>`     Apply the provided regular expression to the path.  The expression allows for finding multiple images, and allows for easy use of the psuedo-directory nature of paths.
Note: The regex is in Perl/Python syntax. This is not URL safe, and if the expressions are to be used, approriate quoting (URL safe `UTF-8`) of the expression will usually be needed. This makes use of them painful when used on the command-line (such as with `curl`).

* A `GET` request on `/images` will provide a listing of all images in the repository. `regex` is supported on this request.
* A `POST` request on `/images/path/to/image` will upload an image with an image name as specified in the path.
* A `GET` request on `/images/path/to/image` will return the designated image as modified by the appropriate modifiers.


