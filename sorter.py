import glob
import os

from lib.threaded import Threaded
from lib.classifier import Classifier
from lib.logger import Logger
from lib.utils import Utils


class Sorter:
    def __init__(self, unsorted_media_dirs):
        self.unsorted_media_dirs = unsorted_media_dirs
        self.log = Logger(__name__)
        self.threaded = Threaded(5)

    def sort(self):
        for media_dir in self.unsorted_media_dirs:
            for filepath in glob.iglob(glob.escape(media_dir) + '/**', recursive=True):
                if not (os.path.exists(filepath) and Utils.is_video_file(filepath) and Utils.is_big_file(filepath)):
                    # self.log.debug(f"Ignoring: {filepath}")
                    continue
                self.log.info(f"Sorting: {filepath}")
                classifier = Classifier(filepath)
                self.threaded.run(classifier.classify_move)

        self.threaded.wait()

        self.log.info(f"Done")
