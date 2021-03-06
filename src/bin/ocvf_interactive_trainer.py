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
# * Redistributions of source code must retain the above copyright
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

# STD Imports
import os
import sys
import cv
import cv2
import Image
import signal
import optparse
import traceback
import shutil
import glob
import time

# OCVF Imports
from ocvfacerec.helper.common import *
from ocvfacerec.trainer.thetrainer import TheTrainer


class Trainer(object):

    tmp_storage = "/tmp/ocvf_retraining"

    def __init__(self, _options, _middelware_connector):
        self.counter = 0
        self.middleware = _middelware_connector
        self.image_source = _options.image_source
        self.mugshot_size = _options.mugshot_size
        self.retrain_source = _options.retrain_source
        self.restart_target = _options.restart_target
        self.restart_recgonizer = _options.restart_target
        self.middleware_type = _options.middleware_type
        self.training_data_path = _options.training_data_path
        self.training_image_number = _options.training_image_number
        self.cascade_filename = _options.cascade_filename
        try:
            self.image_size = (int(_options.image_size.split("x")[0]), int(_options.image_size.split("x")[1]))
        except Exception, e:
            print ">> Error: Unable to parse the given image size '%s'. Please pass it in the format [width]x[height]!" \
                  % _options.image_size
            sys.exit(1)

        self.model_path = _options.model_path
        self.abort_training = False
        self.doRun = True

        def signal_handler(signal, frame):
            print ">> Exiting.."
            self.doRun = False
            self.abort_training = True

        signal.signal(signal.SIGINT, signal_handler)

    def run(self):
        print ">> Middleware %s" % self.middleware_type.upper()
        print ">> Path to Training Images <-- %s " % self.training_data_path
        print ">> Resize Images before Training to %s " % str(self.image_size)
        print ">> Path to Model File <-- --> %s" % self.model_path
        print ">> Remote Camera Source <-- %s " % self.image_source
        print ">> Re-Train Command Scope/Topic <-- %s" % self.retrain_source
        print ">> Restart Recognizer Scope/Topic --> %s" % self.restart_recgonizer

        try:
            self.middleware.activate(self.image_source, self.retrain_source, self.restart_target)
        except Exception, ex:
            print ">> Error: Can't Activate Middleware ", ex
            traceback.print_exc()
            sys.exit(1)

        self.re_train()

        print ">> Ready!"

        while self.doRun:
            try:
                train_name = self.middleware.wait_for_start_training()
            except Exception, e:
                # Check every timeout seconds if we are supposed to exit
                continue

            try:
                # Given name == learn person and then restart classifier
                if train_name is not "":
                    print ">> Training for '%s' (run %d)" % (train_name, self.counter)
                    if self.record_images(train_name):
                        self.re_train()
                        self.restart_classifier()
                        self.counter += 1
                    else:
                        print ">> Unable to Collect Enough Images"
                # Empty name == only restart classifier (manual data set change)
                else:
                    print ">> Re-training and restarting only ..."
                    self.re_train()
                    self.restart_classifier()

            except Exception, e:
                print ">> Error: ", e
                traceback.print_exc()
                continue

        print ">> Deactivating Middleware"
        self.middleware.deactivate()

    def record_images(self, train_name):
        print ">> Recording %d Images From %s..." % (self.training_image_number, self.image_source)
        tmp_person_image_path = os.path.join(self.tmp_storage, train_name)
        cascade = cv.Load(self.cascade_filename)
        mkdir_p(tmp_person_image_path)
        num_mugshots = 0
        abort_threshold = 80
        abort_count = 0
        switch = False
        while num_mugshots < self.training_image_number and not self.abort_training and abort_count < abort_threshold:

            # Take every second frame to add some more variance
            switch = not switch
            if switch:
                input_image = self.middleware.get_image()
            else:
                continue

            im = Image.fromarray(cv2.cvtColor(input_image, cv2.COLOR_BGR2RGB))
            cropped_image = face_crop_single_image(im, cascade)

            ok_shot = False
            if cropped_image:
                if cropped_image.size[0] >= self.mugshot_size and cropped_image.size[1] >= self.mugshot_size:
                    sys.stdout.write("+")
                    sys.stdout.flush()
                    cropped_image.save(os.path.join(tmp_person_image_path, "%03d.jpg" % num_mugshots))
                    num_mugshots += 1
                    ok_shot = True

            if ok_shot is False:
                abort_count += 1
                sys.stdout.write("-")
                sys.stdout.flush()

            # Sleep between mug shots
            time.sleep(0.01 * 20)

        print ""
        if abort_count >= abort_threshold:
            return False
        else:
            person_image_path = os.path.join(self.training_data_path, train_name)
            try:
                shutil.rmtree(person_image_path)
            except Exception as e:
                pass
            mkdir_p(person_image_path)
            for filename in glob.glob(os.path.join(tmp_person_image_path, '*.*')):
                shutil.copy(filename, person_image_path)
            return True

    def re_train(self):
        print ">> Training is running.."
        walk_result = [x[0] for x in os.walk(self.training_data_path)][1:]
        if len(walk_result) > 0:
            print ">> Persons Available for Re-Training ", ", ".join([x.split("/")[-1] for x in walk_result])
        else:
            print ">> No Persons Found for Re-Training"
            return

        trainer = TheTrainer(self.training_data_path, self.image_size, self.model_path, _numfolds=options.numfolds)

        [images, labels, subject_names] = trainer.read_images(self.training_data_path, self.image_size)

        if len(labels) == 0:
            self.doRun = False
            raise Exception(">> No Images in Folder %s" % self.training_data_path)
        else:
            trainer.train()

    def restart_classifier(self):
        print ">> Restarting Recognizer"
        self.middleware.restart_classifier()


if __name__ == '__main__':
    usage = ">> Usage: %prog [options] model_filename"
    # Add options for training, resizing, validation:
    parser = optparse.OptionParser(usage=usage)
    group_mw = optparse.OptionGroup(parser, 'Middleware Options')
    group_algorithm = optparse.OptionGroup(parser, 'Algorithm Options')
    group_io = optparse.OptionGroup(parser, 'IO Options')

    group_mw.add_option("-w", "--middleware", action="store", dest="middleware_type", type="string", default="rsb",
                        help="Type of middleware to use. Currently supported: 'rsb' and 'ros' (default: %default).")
    group_mw.add_option("-s", "--image-source", action="store",
                        dest="image_source", default="/rsbopencv/ipl",
                        help="Source Topic [RSB] or Scope [ROS] of video images (default: %default).")
    group_mw.add_option("-e", "--re-train-source", action="store",
                        dest="retrain_source", default="/ocvfacerec/trainer/retrainperson",
                        help="Source (topic/scope) from which to get a re-train message (String, name of the person) (default: %default).")
    group_mw.add_option("-p", "--restart-target", action="store",
                        dest="restart_target", default="/ocvfacerec/restart",
                        help="Target (topic/scope) to where a simple restart message is sent (String 'restart') (default: %default).")

    group_io.add_option("-m", "--model-path", action="store", dest="model_path", default="/tmp/model.pkl",
                        help="Storage path for the model file (default: %default).")
    group_io.add_option("-t", "--training-path", action="store",
                        dest="training_data_path", default="/tmp/training_data",
                        help="Storage path for the training data files (default: %default).")

    group_algorithm.add_option("-n", "--training-images", action="store",
                               dest="training_image_number", type="int", default=70,
                               help="Number of images to use for training of a new person(default: %default).")
    group_algorithm.add_option("-r", "--resize", action="store", type="string", dest="image_size", default="70x70",
                               help="Resizes the given and new dataset(s) to a given size in format [width]x[height] (default: %default).")
    group_algorithm.add_option("-v", "--validate", action="store", dest="numfolds", type="int", default=None,
                               help="Performs a k-fold cross validation on the dataset, if given (default: %default).")
    group_algorithm.add_option("-c", "--cascade", action="store", dest="cascade_filename",
                               help="Sets the path to the HaarCascade file used for the face detection algorithm [haarcascade_frontalface_alt2.xml].")
    group_algorithm.add_option("-l", "--mugshot-size", action="store", type="int", dest="mugshot_size", default=100,
                               help="Sets minimal size (in pixels) required for a mugshot of a person in order to use it for training (default: %default).")

    parser.add_option_group(group_mw)
    parser.add_option_group(group_io)
    parser.add_option_group(group_algorithm)
    (options, args) = parser.parse_args()

    try:
        mkdir_p(os.path.dirname(os.path.abspath(options.model_path)))
        mkdir_p(os.path.dirname(os.path.abspath(options.training_data_path)))
    except Exception as e:
        print ">> Error: ", e
        sys.exit(1)

    if options.middleware_type == "rsb":
        from ocvfacerec.mwconnector.rsbconnector import RSBConnector

        Trainer(options, RSBConnector()).run()
    elif options.middleware_type == "ros":
        from ocvfacerec.mwconnector.rosconnector import ROSConnector

        Trainer(options, ROSConnector()).run()
    else:
        print ">> Error: Middleware %s not supported" % options.middleware_type
        sys.exit(1)
