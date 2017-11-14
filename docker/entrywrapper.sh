#!/bin/bash
function checkvar {
  varname=$1
  dontleak=$2
  varval=`echo ${!varname}`
  if [ -z "$varval" ]; then
    echo "[ERROR] $varname is not defined, cannot continue"
    exit 1
  fi
  if [ ! -z "$dontleak" ]; then
    echo "$varname is defined"
  else
    echo "$varname=$varval"
  fi
}

echo '[INFO] checking all environment variables are present...'
checkvar OS_AUTH_URL
checkvar OS_USERNAME
checkvar OS_PASSWORD true
checkvar OS_TENANT_NAME
checkvar OS_TENANT_ID
checkvar SWIFT_P
checkvar SWIFT_C

sed -i "s/%SWIFT_STORE_PERSISTENT%/$SWIFT_P/" /config.yml
sed -i "s/%SWIFT_STORE_CACHE%/$SWIFT_C/" /config.yml
/entrypoint.sh $@
