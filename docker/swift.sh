#!/bin/bash
echo '[ERROR] you need to overwrite this file (/swift.sh) with a host file'
echo 'Create a file on your host with the content:
export OS_AUTH_URL=https://keystone.rc.nectar.org.au:5000/v2.0/
export OS_USERNAME="user@edu.au"
export OS_PASSWORD="pass"
export OS_TENANT_NAME="name"
export OS_TENANT_ID="id"
export SWIFT_P="persistent-swift-container-name"
export SWIFT_C="cache-swift-container-name"
'
echo 'Mount the host swift config with: docker -v /path/to/swift.sh:/swiftsh ...'
exit 1
