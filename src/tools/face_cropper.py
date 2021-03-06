# Copyright (c) 2015.
# Philipp Wagner <bytefish[at]gmx[dot]de> and
# Florian Lier <flier[at]techfak.uni-bielefeld.de> and
# Norman Koester <nkoester[at]techfak.uni-bielefeld.de>
#
#
# Released to public domain under terms of the BSD Simplified license.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the organization nor the names of its contributors
#     may be used to endorse or promote products derived from this software
#     without specific prior written permission.
#
#    See <http://www.opensource.org/licenses/bsd-license>

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# Source: http://www.lucaamore.com/?p=638

# Adaption: Florian Lier | flier[at]techfak.uni-bielefeld.
# + Name Prefix for images
# + More Pythonic Syntax
# + Cropped Images Folder
# + Bounding Box Margin for Cropped Images

import shutil
import Image
import glob
import sys
import os
import cv


def detect_face(image, face_cascade, return_image=False):
    
    # This function takes a grey scale cv image and finds
    # the patterns defined in the haarcascade function

    min_size = (20, 20)
    haar_scale = 1.1
    min_neighbors = 5
    haar_flags = 0

    # Equalize the histogram
    cv.EqualizeHist(image, image)

    # Detect the faces
    faces = cv.HaarDetectObjects(
        image, face_cascade, cv.CreateMemStorage(0),
        haar_scale, min_neighbors, haar_flags, min_size
    )

    # If faces are found
    if faces and return_image:
        for ((x, y, w, h), n) in faces:
            # Convert bounding box to two CvPoints
            pt1 = (int(x), int(y))
            pt2 = (int(x + w), int(y + h))
            cv.Rectangle(image, pt1, pt2, cv.RGB(255, 0, 0), 5, 8, 0)

    if return_image:
        return image
    else:
        return faces


def pil2_cvgrey(pil_im):
    # Convert a PIL image to a greyscale cv image
    # from: http://pythonpath.wordpress.com/2012/05/08/pil-to-opencv-image/
    pil_im = pil_im.convert('L')
    cv_im = cv.CreateImageHeader(pil_im.size, cv.IPL_DEPTH_8U, 1)
    cv.SetData(cv_im, pil_im.tostring(), pil_im.size[0])
    return cv_im


def cv2_pil(cv_im):
    # Convert the cv image to a PIL image
    return Image.frombytes("L", cv.GetSize(cv_im), cv_im.tostring())


def img_crop(image, crop_box, box_scale=1):
    # Crop a PIL image with the provided box [x(left), y(upper), w(width), h(height)]

    # Calculate scale factors
    x_delta = max(crop_box[2] * (box_scale - 1), 0)
    y_delta = max(crop_box[3] * (box_scale - 1), 0)

    # Convert cv box to PIL box [left, upper, right, lower]
    pil_box = [crop_box[0] - x_delta, crop_box[1] - y_delta, crop_box[0] + crop_box[2] + x_delta,
               crop_box[1] + crop_box[3] + y_delta]

    return image.crop(pil_box)


def face_crop(image_pattern, prefix, haar, box_scale=1):
    # Select one of the haarcascade files:
    #  haarcascade_frontalface_alt.xml
    #  haarcascade_frontalface_alt2.xml
    #  haarcascade_frontalface_alt_tree.xml
    #  haarcascade_frontalface_default.xml
    #  haarcascade_profileface.xml
    face_cascade = cv.Load(haar)

    img_list = glob.glob(image_pattern)
    if len(img_list) <= 0:
        print '>> No Images Found'
        return

    img_count = 0

    for img in img_list:
        pil_im = Image.open(img)
        cv_im = pil2_cvgrey(pil_im)
        faces = detect_face(cv_im, face_cascade)
        if faces:
            n = 0
            for face in faces:
                cropped_image = img_crop(pil_im, face[0], box_scale=box_scale)
                f_name, ext = os.path.splitext(img)
                cropped_image_name = f_name + '_crop' + str(n) + ext
                cropped_image.save(cropped_image_name)

                dir_name = os.path.dirname(cropped_image_name)
                rename_name = dir_name + "/" + prefix + "_crop" + str(img_count) + ext
                os.rename(cropped_image_name, rename_name)

                cropped_folder = dir_name + '/cropped'

                if not os.path.exists(cropped_folder):
                    os.mkdir(dir_name + '/cropped')

                shutil.move(rename_name, cropped_folder)

                print ">> Saving cropped image " + cropped_folder + '/' + prefix + "_crop" + str(img_count) + ext
                n += 1
                img_count += 1
        else:
            print '>> No faces found in image ', img


# Crop all jpegs in a folder. Note: the code uses glob which follows unix shell rules.
# Use the box_scale to scale the cropping area. 1=opencv box, 2=2x the width and height
if __name__ == '__main__':
    if not len(sys.argv) > 3:
        print ">> USAGE: face_cropper.py <name prefix> </path/to/images> </path/to/cascade.xml>"
        sys.exit(1)
    else:
        prefix = sys.argv[1]
        folder = sys.argv[2]
        haar   = sys.argv[3]
        path = folder + '/*'
        print ">> Loading all images in path " + path
        face_crop(path, prefix, haar, box_scale=1)