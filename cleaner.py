import glob
import logging
import os
import re

from lib.classifier import Classifier
from lib.logger import Logger
from lib.utils import Utils
from lib.threaded import Threaded


class Cleaner:
    def __init__(self, dirs):
        self.dirs = dirs
        self.log = Logger(__name__)
        self.empty_dirs = []
        self.small_files = []
        self.threaded = Threaded(5)
        self.media = {}

    def move_trailers(self):
        self.log.info(f"Moving trailers from {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for file in glob.iglob(glob.escape(media_dir) + '/**', recursive=True):
                filename = os.path.basename(file)
                if ("trailer" in str.lower(filename) and '@eadir' not in str.lower(file) and
                        Utils.is_video_file(file) and '/trailers/' not in str.lower(file)):
                    dst = Utils.media_dir(file)
                    trailer_dir = Utils.trailers_dir(dst)
                    self.threaded.run(Utils.move, file, os.path.join(trailer_dir, filename))
        self.threaded.wait()
        self.log.info(f"Trailers moved.")

    def collect_media_info(self):
        files = []
        for d in self.dirs:
            if not os.path.exists(d):
                self.log.error(f"Directory {d} does not exist.")
                continue
            for media_dir in os.listdir(d):
                media_path = os.path.join(d, media_dir)

                if not os.path.exists(media_path) or self.is_ignore_file(media_path) or not os.path.isdir(media_path):
                    self.log.debug(f"Ignoring: {media_path}")
                    continue
                for filename in glob.iglob(glob.escape(media_path) + '/**', recursive=True):
                    p = os.path.join(media_path, filename)
                    if self.is_ignore_file(p, False) or not Utils.is_video_file(p) or not Utils.is_big_file(p):
                        self.log.debug(f"Skipping: {p}")
                        continue
                    classifier = Classifier(p)
                    self.threaded.run(classifier.classify)
                    files.append(p)

        self.threaded.wait()

        for p in files:
            media_info = Classifier(p).classify().info
            if not media_info or not media_info['title']:
                self.log.error(f"Failed to get title for: {p}")
                continue
            title = media_info['title']
            if title not in self.media:
                self.media[title] = {}
            key = f"{media_info['old_path']}_S{media_info['season']}_E{media_info['episode']}"
            self.media[title][key] = media_info

    def delete_low_quality(self):
        self.collect_media_info()

        for title, v in self.media.items():
            v = dict(sorted(v.items(), key=lambda item: item[1]['rank'], reverse=True))
            self.log.info(f"Ranking: {title} with {len(v)} files")
            i = 0
            for f, r in v.items():
                i += 1
                if i == 1:
                    self.log.debug(f"Keeping: {r['old_path']}")
                    continue
                if i < 4:
                    self.log.debug(f"Moving: {r['old_path']} to extras")
                    parent_dir = Utils.media_dir(r['old_path'])
                    extras_dir = Utils.extras_dir(parent_dir)
                    new_path = os.path.join(extras_dir, os.path.basename(r['old_path']))
                    self.threaded.run(Utils.move, r['old_path'], new_path)
                    continue
                self.threaded.run(Utils.delete, r['old_path'])
        self.threaded.wait()
        return

    def flatten_media_dirs(self):
        self.log.info(f"Flattening {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            self.flatten_one_level(media_dir)

    def clean(self):
        self.flatten_media_dirs()
        self.log.info(f"Cleaning {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for f in os.listdir(media_dir):
                file_path = os.path.join(media_dir, f)
                self.threaded.run(self.set_files, file_path)
        self.threaded.wait()

        all_files = self.stats()

        for f in all_files:
            # Utils.delete(f['path'])
            self.threaded.run(Utils.delete, f['path'])
        self.threaded.wait()
        self.log.info(f"Cleanup Done.")

    def is_ignore_file(self, file_path, ignore_extras=True):
        f = str.lower(file_path)
        fn = os.path.basename(f)
        return (
                '@eadir' in f or
                'plex' in f or
                'trailer' in f or
                '/subs' in f or
                (ignore_extras and '/extras' in f) or
                str.endswith(f, '.subs') or
                # str.startswith(fn, '.') or
                str.endswith(f, '.meta') or
                str.endswith(f, '.nfo') or
                str.startswith(fn, '.smbdelete')
        )

    def set_files(self, file_path):
        if self.is_ignore_file(file_path) or not os.path.exists(file_path):
            self.log.debug(f"Ignoring: {file_path}")
            return
        if os.path.isdir(file_path):
            size = Utils.size(file_path, False)
            if size < 50000000:  # 50MB
                self.log.debug(f"Found empty dir size[{Utils.convert_size(size)}]: {file_path}")
                self.empty_dirs.append({'path': file_path, 'size': size})
        if os.path.isfile(file_path):
            size = Utils.size(file_path, False)
            if size < 50000000:  # 50MB
                self.log.debug(f"Found small file size[{Utils.convert_size(size)}]: {file_path}")
                self.small_files.append({'path': file_path, 'size': size})

    def stats(self):
        # sort by size
        self.empty_dirs.sort(key=lambda x: x['size'])
        self.small_files.sort(key=lambda x: x['size'])
        all_files = self.empty_dirs + self.small_files
        total_size = 0
        self.log.info(f"Biggest files:")
        for f in all_files[-10:]:
            if self.log.level <= logging.INFO:
                print(f"    - {Utils.convert_size(f['size'])} - {f['path']}")
            total_size += f['size']

        self.log.info(f"Small Files: {len(self.small_files)}")
        self.log.info(f"Empty dirs: {len(self.empty_dirs)}")
        self.log.info(f"Total size: {Utils.convert_size(total_size)}")

        return all_files

    def flatten_one_level(self, media_dir):
        for rootdir in os.listdir(media_dir):
            rootdir_path = os.path.join(media_dir, rootdir)

            if not os.path.isdir(rootdir_path) or self.is_ignore_file(rootdir_path) or rootdir_path == media_dir:
                continue

            for file in glob.iglob(glob.escape(rootdir_path) + '/**', recursive=True):
                if self.is_ignore_file(file) or '/season' in str.lower(file):
                    continue

                if os.path.isdir(file) or file == os.path.join(rootdir_path, os.path.basename(file)):
                    continue

                # Making sure the new filename is unique in case of duplicates
                destination = Utils.new_unique_file(rootdir_path, file)

                self.threaded.run(Utils.move, file, destination)
        self.threaded.wait()
        return
