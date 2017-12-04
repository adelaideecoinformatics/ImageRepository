# How to get this docker-compose stack up and running

Make sure you have the following installed, configured:
 1. [docker](https://www.docker.com/)
 1. [docker-compose](https://docs.docker.com/compose/install/)
 1. API keys for an OpenStack instance
 1. two buckets created in OpenStack Swift to store images in (you'll update the config to point to these shortly)

## Starting the stack
Running is super simple:
```bash
cd paratoo-image-repo/docker
./build.sh                        # build the image
# define the required OpenStack env vars if you haven't already
export OS_USERNAME=somevalue
export OS_PASSWORD=somevalue
export OS_TENANT_NAME=somevalue
export OS_TENANT_ID=somevalue
# optionally, override the default Swift URL and bucket names
# export OS_AUTH_URL=https://keystone.rc.nectar.org.au:5000/v2.0/
# export SWIFT_P=image-repo        # name of the persistent store bucket
# export SWIFT_C=image-repo-cache  # name of the cache bucket
docker-compose up                  # start the stack
curl http://localhost:8880/images  # list the available images, might be empty
```
