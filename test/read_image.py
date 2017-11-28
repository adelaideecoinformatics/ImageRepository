"""
Reads an image into a base64 encoded byte string so you can easily inline
into a test where you need to create an image in memory.
"""
import sys
import os
DIRPATH = os.path.dirname(os.path.realpath(__file__))
sys.path.append('{}/../src/'.format(DIRPATH)) # need to be able to import our stuff
import logging
from base64 import b64encode, b64decode
from ImageType import ImageInstance, ImageHandle, OriginalImage, ImageName

logging.basicConfig()

# Edit this type to be what you want. We can convert to what you want.
desired_file_type = 'jpeg'

input_file_path = '{}/1pixel.png'.format(DIRPATH)
image = OriginalImage.from_file(filename = input_file_path)
base64str = b64encode(image.convert(desired_file_type).as_bytes())
print(base64str)

# In a test, you can then decode it with
rawbytes = b64decode(base64str)
# ...and probably use it like
name = ImageName('1pixel')
handle = ImageHandle.from_bytes(the_bytes = rawbytes)
ii = ImageInstance(image_name = name, image_handle = handle)
print('\n' + str(ii)) # just printing to prove it works
