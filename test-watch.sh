#!/bin/bash
# watches all python files and re-runs tests upon changes
cd `dirname "$0"`
which nodemon > /dev/null
rc=$?
if [ $rc != 0 ]; then
  echo "[ERROR] the nodemon command isn't installed. Install it with:"
  echo "[ERROR]   npm install -g nodemon"
  echo "[ERROR] ...then you can re-run this script"
  exit $rc
fi
nodemon --ext py --exec nose2
