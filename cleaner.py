import glob
import logging
import os
import re
import traceback

from lib.plex import Plex
from lib.trakt_client import Trakt
from lib.config import config
from lib.classifier import Classifier
from lib.logger import Logger
from lib.utils import Utils
from lib.threaded import Threaded
from lib.nfo import NFO


class Cleaner:
    def __init__(self, dirs):
        self.dirs = dirs
        self.log = Logger(__name__)
        self.empty_dirs = []
        self.small_files = []
        self.threaded = Threaded(5)
        self.media = {}

    def fix_jellyfin_nfo(self):
        if not config.jellyfin_nfo_fix:
            return
        self.log.info(f"Fixing jellyfin nfo files in {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for file in glob.iglob(glob.escape(media_dir) + '/**', recursive=True):
                if file.endswith('.nfo'):
                    n = NFO(file)
                    n.fix_jellyfin_nfo()
        self.log.info(f"Jellyfin nfo files fixed.")

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

                if (not media_path or not os.path.exists(media_path) or
                        self.is_ignore_file(media_path) or not os.path.isdir(media_path)):
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
            key = f"{media_info['title']}_{media_info['year']}_S{media_info['season']}_E{media_info['episode']}"

            if key not in self.media:
                self.media[key] = []
            self.media[key].append(media_info)

    def delete_low_quality(self):
        self.collect_media_info()

        for k, v in self.media.items():
            v = sorted(v, key=lambda x: x['rank'])
            self.log.info(f"Ranking: {k} with {len(v)} files")
            i = 0
            for r in v:
                i += 1
                if i == 1:
                    self.log.debug(f"Keeping: {r['old_path']}")
                    continue
                if i < 4:
                    parent_dir = Utils.media_dir(r['old_path'])
                    extras_dir = Utils.extras_dir(parent_dir)
                    new_path = os.path.join(extras_dir, os.path.basename(r['old_path']))

                    self.log.debug(f"Moving: {r['old_path']} to extras")
                    self.threaded.run(Utils.move, r['old_path'], new_path)
                    continue
                self.log.debug(f"Deleting: {r['old_path']}")
                self.threaded.run(Utils.delete, r['old_path'])
        self.threaded.wait()
        return

    def move_pre_seeded(self):
        if not config.pre_seeding_dir and config.seeding_dir:
            self.log.info("Pre-seeding is not set.")
            return
        if os.path.exists(os.path.join(config.pre_seeding_dir, '.transferring')):
            self.log.info("Pre-seeding is in progress.")
            return
        for f in os.listdir(config.pre_seeding_dir):
            file_path = os.path.join(config.pre_seeding_dir, f)
            if os.path.isfile(file_path):
                self.threaded.run(Utils.move, file_path, os.path.join(config.seeding_dir, f))
            else:
                is_synced = True
                for f1 in os.listdir(file_path):
                    if f1.startswith('.'):
                        is_synced = False
                        break
                if is_synced:
                    self.threaded.run(Utils.move, file_path, os.path.join(config.seeding_dir, f))

    def flatten_media_dirs(self):
        self.log.info(f"Flattening {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            self.flatten_one_level(media_dir)

    def move_watched(self):
        if not config.watched_movies_media_dir:
            self.log.error(f"Watched media directories or trakt config not set.")
            return False
        self.log.info(f"Moving watched media.")
        watched = Trakt().watched()
        watched.extend(Plex().watched())
        if not watched:
            self.log.info(f"No watched media found.")
            return False
        self.log.debug(f"Moving watched media on trakt.")
        try:
            watched_index = []
            # move watched media to watched folder
            for media in watched:
                title = f"{media['title']} ({media['year']})"
                title1 = media['title']
                watched_index.extend([title, title1, Utils.clean_path(title), Utils.clean_path(title1)])
                final_path = self.find_media(title) or self.find_media(title1) or \
                             self.find_media(Utils.clean_path(title)) or \
                             self.find_media(Utils.clean_path(title1))
                if not final_path:
                    self.log.debug(f"Could not find watched media folder: {title} ")
                    continue
                watched_dir = config.watched_series_media_dir if \
                    'series' in final_path else \
                    config.watched_movies_media_dir
                Utils.move(final_path, os.path.join(watched_dir, Utils.clean_path(title)))
            # move back the ones that are not in watched
            for filename in os.listdir(config.watched_movies_media_dir):
                self.move_unwatched(filename, watched_index, config.watched_movies_media_dir)
                self.move_unwatched(filename, watched_index, config.watched_series_media_dir)

        except Exception as e:
            self.log.error(f"Error moving watched: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            return False

    def move_unwatched(self, filename, watched_index, dirpath):
        file_path = os.path.join(dirpath, filename)
        if filename not in watched_index:
            Utils.move(file_path, os.path.join(config.media_dirs['unsorted'], filename))

    def find_media(self, title):
        if len(title) < 3:
            self.log.debug(f"Title too short: {title}")
            return False
        for dir in config.final_media_dirs:
            final_path = os.path.join(dir, title)
            if os.path.exists(final_path):
                return final_path
        self.log.debug(f"Could not find media folder: {final_path}")
        return False

    def clean(self):
        self.log.info(f"Cleaning {len(self.dirs)} directories...")
        for media_dir in self.dirs:
            for f in os.listdir(media_dir):
                file_path = os.path.join(media_dir, f)
                self.threaded.run(self.find_deletable_files, file_path)
                if os.path.isdir(file_path):
                    for nf in os.listdir(file_path):
                        self.threaded.run(self.find_deletable_files, os.path.join(file_path, nf))
        self.threaded.wait()

        all_files = self.stats()

        for f in all_files:
            # Utils.delete(f['path'])
            self.threaded.run(Utils.delete, f['path'])
        self.threaded.wait()
        self.log.info(f"Cleanup Done.")

    @staticmethod
    def is_ignore_file(file_path, ignore_extras=True):
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

    @staticmethod
    def is_ignore_flattening(file_path):
        f = str.lower(file_path)
        return any(substring in f for substring in
                   ['@eadir', 'plex', 'trailer', '/subs', '/extras'])  #

    @staticmethod
    def is_deletable_dir(file_path):
        f = str.lower(file_path)
        return not any(substring in f for substring in
                       ['@eadir', 'plex', 'trailer', '/subs', '/season', '/extras'])  #

    @staticmethod
    def is_deletable_file(file_path):
        f = str.lower(file_path)
        return not f.endswith(('.jpg', '.jpeg', '.png', '.nfo', '.srt', '.sub'))

    def find_deletable_files(self, file_path):
        if not os.path.exists(file_path):
            self.log.debug(f"Ignoring: {file_path}")
            return
        if os.path.isdir(file_path) and self.is_deletable_dir(file_path):
            size = Utils.size(file_path, False)
            if size < config.min_dir_size:
                self.log.debug(f"Found empty dir size[{Utils.convert_size(size)}]: {file_path}")
                self.empty_dirs.append({'path': file_path, 'size': size})
        if os.path.isfile(file_path) and self.is_deletable_file(file_path) and self.is_deletable_dir(file_path):
            size = Utils.size(file_path, False)
            if size < config.min_file_size:
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

            if not os.path.isdir(rootdir_path) or rootdir_path == media_dir:
                continue

            for file in glob.iglob(glob.escape(rootdir_path) + '/**', recursive=True):
                if self.is_ignore_flattening(file) or '/season' in str.lower(file):
                    continue

                if os.path.isdir(file) or file == os.path.join(rootdir_path, os.path.basename(file)):
                    continue

                self.log.debug(f"Found nested file: {file} under {rootdir_path}")
                # Making sure the new filename is unique in case of duplicates
                destination = os.path.join(rootdir_path, os.path.basename(file))
                if os.path.exists(destination):
                    destination = Utils.new_unique_file(rootdir_path, file)

                self.threaded.run(Utils.move, file, destination)
        self.threaded.wait()
        return
