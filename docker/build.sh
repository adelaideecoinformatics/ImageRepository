#!/bin/bash
# Builds the docker image
set -e
cd `dirname "$0"`/..
docker build -t asia.gcr.io/image-repo-1234/imagerepository:test .
echo "[INFO] Build complete, push to registry with:"
echo "  gcloud docker -- push asia.gcr.io/image-repo-1234/imagerepository:test"
