#!/usr/bin/python
import requests # http://docs.python-requests.org/en/master/
import sys
if len(sys.argv) == 1:
  print "ERROR: supply an image as the first arg"
  print "usage: " + sys.argv[0] + " <image-path>" 
  print "   eg: " + sys.argv[0] + " /tmp/some-image.jpg" 
  sys.exit(1)
image = sys.argv[1]

fileName = image[image.rfind("/")+1:]
url = 'http://127.0.0.1:5000/images/'+fileName
files = {'file': open(image, 'rb')}

r = requests.post(url, files=files)
print r.text
