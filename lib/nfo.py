import os
import xml.etree.ElementTree as ET

import xmltodict

from .config import config
from .logger import Logger
from .utils import Utils


# from xml.etree import cElementTree as ElementTree


class NFO:
    def __init__(self, file_path):
        if not file_path.endswith('.nfo') or not os.path.exists(file_path):
            raise ValueError(f"Invalid NFO file path {file_path}.")
        self.path = file_path
        self.nfo = self.get_nfo()
        self.log = Logger(__name__)

    def get_nfo(self):
        with open(self.path, encoding="utf-8", errors='ignore') as f:
            return f.read()

    def fix_jellyfin_nfo(self):
        try:
            content = self.nfo
            new_content = content

            # Replace the specified text
            if config.jellyfin_nfo_fix and config.jellyfin_nfo_fix['replace_text'] in content:
                new_content = content.replace(config.jellyfin_nfo_fix['replace_text'],
                                              config.jellyfin_nfo_fix['replace_with_text'])

            # Parse the XML
            root = ET.fromstring(new_content)

            # Check if thumb and fanart elements already exist
            thumb_exists = root.find(".//thumb[@aspect='poster']") is not None
            fanart_exists = root.find(".//fanart/thumb") is not None

            if thumb_exists and fanart_exists:
                self.log.debug(f"Thumb and Fanart tags already exist in {self.path}. No modifications needed.")
                return

            # Handle the poster element
            if not thumb_exists:
                poster_element = root.find('.//art/poster')
                if poster_element is not None:
                    poster_path = poster_element.text
                    thumb = ET.SubElement(root, 'thumb', aspect="poster", preview="")
                    thumb.text = poster_path
            # Extract and handle all fanart paths
            if not fanart_exists:
                art_element = root.find('.//art')
                if art_element is not None:
                    fanart_elements = art_element.findall('fanart')
                    if fanart_elements:
                        new_fanart_element = ET.SubElement(root, 'fanart')  # Create only one fanart element
                        for fanart_element in fanart_elements:
                            fanart_path = fanart_element.text
                            thumb = ET.SubElement(new_fanart_element, 'thumb', preview="")
                            thumb.text = fanart_path

            # Write the updated XML back to the file, with the specific XML declaration
            with open(self.path, 'w', encoding='utf-8') as out_file:
                out_file.write('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n')
                ET.ElementTree(root).write(out_file, encoding='unicode')

            self.log.debug(f"nfo file: {self.path} updated successfully.")
        except Exception as e:
            self.log.error(f"Error: Failed to update {self.path}.")
            self.log.debug(repr(e))
            Utils.delete(self.path)

        return

    def dict(self):
        self.log.debug(f"Converting NFO to dict: {self.path}")
        d = xmltodict.parse(self.nfo)
        return d
