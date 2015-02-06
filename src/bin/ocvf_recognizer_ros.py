# Copyright (c) 2012. Philipp Wagner <bytefish[at]gmx[dot]de> and
# Florian Lier <flier[at]techfak.uni-bielefeld.de>
# Released to public domain under terms of the BSD Simplified license.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# * Redistributions of source code must retain the above copyright
#          notice, this list of conditions and the following disclaimer.
#        * Redistributions in binary form must reproduce the above copyright
#          notice, this list of conditions and the following disclaimer in the
#          documentation and/or other materials provided with the distribution.
#        * Neither the name of the organization nor the names of its contributors
#          may be used to endorse or promote products derived from this software
#          without specific prior written permission.
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

# STD IMPORTS
import os
import cv2
import sys
import time
import rospy
import roslib
import logging
import numpy as np

# ROS IMPORTS
from cv_bridge import CvBridge
from std_msgs.msg import Header
from sensor_msgs.msg import Image
from people_msgs.msg import People
from people_msgs.msg import Person
from geometry_msgs.msg import Point

# LOCAL IMPORTS
from ocvfacerec.helper.video import *
from ocvfacerec.helper.common import *
from ocvfacerec.facerec.feature import Fisherfaces
from ocvfacerec.facerec.model import PredictableModel
from ocvfacerec.facedet.detector import CascadedDetector
from ocvfacerec.facerec.distance import EuclideanDistance
from ocvfacerec.facerec.classifier import NearestNeighbor
from ocvfacerec.facerec.validation import KFoldCrossValidation
from ocvfacerec.facerec.serialization import save_model, load_model


class ExtendedPredictableModel(PredictableModel):
    """ Subclasses the PredictableModel to store some more
        information, so we don't need to pass the dataset
        on each program call...
    """

    def __init__(self, feature, classifier, image_size, subject_names):
        PredictableModel.__init__(self, feature=feature, classifier=classifier)
        self.image_size = image_size
        self.subject_names = subject_names


class RosPeople:
    def __init__(self):
        self.publisher = rospy.Publisher('ocvfacerec/ros/people', People, queue_size=1)
        rospy.init_node('ocvfacerec_people', anonymous=True)


def get_model(image_size, subject_names):
    """ This method returns the PredictableModel which is used to learn a model
        for possible further usage. If you want to define your own model, this
        is the method to return it from!
    """
    # Define the Fisherfaces Method as Feature Extraction method:
    feature = Fisherfaces()
    # Define a 1-NN classifier with Euclidean Distance:
    classifier = NearestNeighbor(dist_metric=EuclideanDistance(), k=1)
    # Return the model as the combination:
    return ExtendedPredictableModel(feature=feature, classifier=classifier, image_size=image_size,
                                    subject_names=subject_names)


def read_subject_names(path):
    """Reads the folders of a given directory, which are used to display some
        meaningful name instead of simply displaying a number.

    Args:
        path: Path to a folder with subfolders representing the subjects (persons).

    Returns:
        folder_names: The names of the folder, so you can display it in a prediction.
    """
    folder_names = []
    for dirname, dirnames, filenames in os.walk(path):
        for subdirname in dirnames:
            folder_names.append(subdirname)
    return folder_names


def read_images(path, image_size=None):
    """Reads the images in a given folder, resizes images on the fly if size is given.

    Args:
        path: Path to a folder with subfolders representing the subjects (persons).
        sz: A tuple with the size Resizes 

    Returns:
        A list [X, y, folder_names]

            X: The images, which is a Python list of numpy arrays.
            y: The corresponding labels (the unique number of the subject, person) in a Python list.
            folder_names: The names of the folder, so you can display it in a prediction.
    """
    c = 0
    X = []
    y = []
    folder_names = []
    for dirname, dirnames, filenames in os.walk(path):
        for subdirname in dirnames:
            folder_names.append(subdirname)
            subject_path = os.path.join(dirname, subdirname)
            for filename in os.listdir(subject_path):
                try:
                    im = cv2.imread(os.path.join(subject_path, filename), cv2.IMREAD_GRAYSCALE)
                    # resize to given size (if given)
                    if (image_size is not None):
                        im = cv2.resize(im, image_size)
                    X.append(np.asarray(im, dtype=np.uint8))
                    y.append(c)
                except IOError, (errno, strerror):
                    print ">> I/O error({0}): {1}".format(errno, strerror)
                except:
                    print ">> Unexpected error:", sys.exc_info()[0]
                    raise
            c = c + 1
    return [X, y, folder_names]


class Recognizer(object):
    def __init__(self, model, camera_id, cascade_filename, run_local, wait, rp):
        self.rp = rp
        self.model = model
        self.wait = wait
        self.detector = CascadedDetector(cascade_fn=cascade_filename, minNeighbors=5, scaleFactor=1.1)
        if run_local:
            self.cam = create_capture(camera_id)
        else:
            self.bridge = CvBridge()

    def callback(self, ros_data):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(ros_data, "bgr8")
        except Exception, e:
            print e
            return
        # Resize the frame to half the original size for speeding up the detection process.
        # In ROS we can control the size, so we are sending a 320*240 image by default.
        # img = cv2.resize(cv_image, (cv_image.shape[1] / 2, cv_image.shape[0] / 2), interpolation=cv2.INTER_CUBIC)
        img = cv_image
        imgout = img.copy()
        # Remember the Persons found in current image
        persons = []
        for _i, r in enumerate(self.detector.detect(img)):
            x0, y0, x1, y1 = r
            # (1) Get face, (2) Convert to grayscale & (3) resize to image_size:
            face = img[y0:y1, x0:x1]
            face = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
            face = cv2.resize(face, self.model.image_size, interpolation=cv2.INTER_CUBIC)
            prediction = self.model.predict(face)
            predicted_label = prediction[0]
            classifier_output = prediction[1]
            # Now let's get the distance from the assuming a 1-Nearest Neighbor.
            # Since it's a 1-Nearest Neighbor only look take the zero-th element:
            distance = classifier_output['distances'][0]
            # Draw the face area in image:
            cv2.rectangle(imgout, (x0, y0), (x1, y1), (0, 0, 255), 2)
            # Draw the predicted name (folder name...):
            draw_str(imgout, (x0 - 20, y0 - 40), "Label " + self.model.subject_names[predicted_label])
            draw_str(imgout, (x0 - 20, y0 - 20), "Distance " + "%1.2f" % distance)
            msg = Person()
            point = Point()
            # Send the center of the person's bounding box
            mid_x = float(x1 + (x1 - x0)*0.5)
            mid_y = float(y1 + (y1 - y0)*0.5)
            point.x = mid_x
            point.y = mid_y
            # Z is "mis-used" to represent the size of the bounding box
            point.z = x1 - x0
            msg.position = point
            msg.name = str(self.model.subject_names[predicted_label])
            msg.reliability = float(distance)
            persons.append(msg)
        if len(persons) > 0:
            h = Header()
            h.stamp = rospy.Time.now()
            h.frame_id = '/ros_cam'
            msg = People()
            msg.header = h
            for x in persons:
                msg.people.append(x)
            self.rp.publisher.publish(msg)
        cv2.imshow('OCVFACEREC ROS CAMERA', imgout)
        cv2.waitKey(self.wait)

    def run_distributed(self, topic):
        subscriber = rospy.Subscriber(topic, Image, self.callback, queue_size=1)
        # print ">> Subscribed Topic " + topic
        rospy.spin()


if __name__ == '__main__':
    from optparse import OptionParser
    # model.pkl is a pickled (hopefully trained) PredictableModel, which is
    # used to make predictions. You can learn a model yourself by passing the
    # parameter -d (or --dataset) to learn the model from a given dataset.
    usage = "usage: %prog [options] model_filename"
    # Add options for training, resizing, validation and setting the camera id:
    parser = OptionParser(usage=usage)
    parser.add_option("-r", "--resize", action="store", type="string", dest="size", default="70x70",
                      help="Resizes the given dataset to a given size in format [width]x[height] (default: 70x70).")
    parser.add_option("-v", "--validate", action="store", dest="numfolds", type="int", default=None,
                      help="Performs a k-fold cross validation on the dataset, if given (default: None).")
    parser.add_option("-t", "--train", action="store", dest="dataset", type="string", default=None,
                      help="Trains the model on the given dataset.")
    parser.add_option("-i", "--id", action="store", dest="camera_id", type="int", default=0,
                      help="Sets the Camera Id to be used (default: 0).")
    parser.add_option("-c", "--cascade", action="store", dest="cascade_filename",
                      default="haarcascade_frontalface_alt2.xml",
                      help="Sets the path to the Haar Cascade used for the face detection part (default: haarcascade_frontalface_alt2.xml).")
    parser.add_option("-s", "--ros-source", action="store", dest="ros_source", help="Grab video from ROS Middleware")
    parser.add_option("-w", "--wait", action="store", dest="wait_time", default=20, type="int",
                      help="Amount of time (in ms) to sleep between face identifaction runs (frames). Default is 20 ms. Increase this value on low-end machines.")
    (options, args) = parser.parse_args()
    print "\n"
    # Check if a model name was passed:
    if options.ros_source is None:
        print ">> [Error] No ROS Topic provided use: -r /some/topic/name"
        sys.exit(1)
    if len(args) == 0:
        print ">> [Error] No prediction model was given."
        sys.exit(1)
    # This model will be used (or created if the training parameter (-t, --train) exists:
    model_filename = args[0]
    # Check if the given model exists, if no dataset was passed:
    if (options.dataset is None) and (not os.path.exists(model_filename)):
        print ">> [Error] No prediction model found at '%s'." % model_filename
        sys.exit(1)
    # Check if the given (or default) cascade file exists:
    if not os.path.exists(options.cascade_filename):
        print ">> [Error] No Cascade File found at '%s'." % options.cascade_filename
        sys.exit(1)
    # We are resizing the images to a fixed size, as this is neccessary for some of
    # the algorithms, some algorithms like LBPH don't have this requirement. To 
    # prevent problems from popping up, we resize them with a default value if none
    # was given:
    try:
        image_size = (int(options.size.split("x")[0]), int(options.size.split("x")[1]))
    except:
        print ">> [Error] Unable to parse the given image size '%s'. Please pass it in the format [width]x[height]!" % options.size
        sys.exit(1)
    # We have got a dataset to learn a new model from:
    if options.dataset:
        # Check if the given dataset exists:
        if not os.path.exists(options.dataset):
            print ">> [Error] No Dataset Found at '%s'." % dataset_path
            sys.exit(1)
        # Reads the images, labels and folder_names from a given dataset. Images
        # are resized to given size on the fly:
        print ">> Loading Dataset..."
        [images, labels, subject_names] = read_images(options.dataset, image_size)
        # Zip us a {label, name} dict from the given data:
        list_of_labels = list(xrange(max(labels) + 1))
        subject_dictionary = dict(zip(list_of_labels, subject_names))
        # Get the model we want to compute:
        model = get_model(image_size=image_size, subject_names=subject_dictionary)
        # Sometimes you want to know how good the model may perform on the data
        # given, the script allows you to perform a k-fold Cross Validation before
        # the Detection & Recognition part starts:
        if options.numfolds:
            print ">> Validating Model With %s Folds..." % options.numfolds
            # We want to have some log output, so set up a new logging handler
            # and point it to stdout:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            # Add a handler to facerec modules, so we see what's going on inside:
            logger = logging.getLogger("facerec")
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            # Perform the validation & print results:
            crossval = KFoldCrossValidation(model, k=options.numfolds)
            crossval.validate(images, labels)
            crossval.print_results()
        # Compute the model:
        print ">> Computing Model..."
        model.compute(images, labels)
        # And save the model, which uses Pythons pickle module:
        print ">> Saving Model..."
        save_model(model_filename, model)
    else:
        print ">> Loading Model... " + str(model_filename)
        model = load_model(model_filename)
    # We operate on an ExtendedPredictableModel. Quit the Recognizerlication if this
    # isn't what we expect it to be:
    if not isinstance(model, ExtendedPredictableModel):
        print ">> [Error] The given model is not of type '%s'." % "ExtendedPredictableModel"
        sys.exit(1)
    # Now it's time to finally start the Recognizerlication! It simply get's the model
    # and the image size the incoming webcam or video images are resized to:
    print ">> Using Remote ROS Camera Stream <-- " + options.ros_source
    print ">> Publishing People Info --> /ocvfacerec/ros/people"
    # Init ROS People Publisher
    rp = RosPeople()
    Recognizer(model=model, camera_id=options.camera_id, cascade_filename=options.cascade_filename, run_local=False, wait=options.wait_time, rp=rp).run_distributed(options.ros_source)