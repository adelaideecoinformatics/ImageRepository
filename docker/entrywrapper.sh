#!/bin/bash
source /swift.sh
sed -i "s/%SWIFT_STORE_PERSISTENT%/$SWIFT_P/" /config.yml
sed -i "s/%SWIFT_STORE_CACHE%/$SWIFT_C/" /config.yml
/entrypoint.sh $@
