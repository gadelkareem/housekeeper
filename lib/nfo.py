import os
import xml.etree.ElementTree as ET

import xmltodict

from .logger import Logger


# from xml.etree import cElementTree as ElementTree


class NFO:
    def __init__(self, file_path):
        if not file_path.endswith('.nfo') or not os.path.exists(file_path):
            raise ValueError(f"Invalid NFO file path {file_path}.")
        self.path = file_path
        self.nfo = self.get_nfo()
        self.log = Logger(__name__)

    def get_nfo(self):
        with open(self.path, 'r') as f:
            return f.read()

    # chatgpt https://chat.openai.com/c/a7137f22-b3da-49bd-9841-a6068510d637
    def replace_text(self):
        try:
            content = self.nfo

            # Replace the specified text
            new_content = content.replace('/Volumes/Media', 'smb://192.168.1.139/Media')

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

            print(f"{self.path} updated successfully.")
        except Exception as e:
            self.log.error(f"Error: {e}")

        return

    def dict(self):
        print('nfo contents', self.nfo)
        d = xmltodict.parse(self.nfo)
        print('nfo dict', d)
        exit()
        return d
#
# class XmlListConfig(list):
#     def __init__(self, aList):
#         for element in aList:
#             if element:
#                 # treat like dict
#                 if len(element) == 1 or element[0].tag != element[1].tag:
#                     self.append(XmlDictConfig(element))
#                 # treat like list
#                 elif element[0].tag == element[1].tag:
#                     self.append(XmlListConfig(element))
#             elif element.text:
#                 text = element.text.strip()
#                 if text:
#                     self.append(text)
#
#
# class XmlDictConfig(dict):
#     """
#     Example usage:
#
#     >>> tree = ElementTree.parse('your_file.xml')
#     >>> root = tree.getroot()
#     >>> xmldict = XmlDictConfig(root)
#
#     Or, if you want to use an XML string:
#
#     >>> root = ElementTree.XML(xml_string)
#     >>> xmldict = XmlDictConfig(root)
#
#     And then use xmldict for what it is... a dict.
#     """
#
#     def __init__(self, parent_element):
#         if parent_element.items():
#             self.update(dict(parent_element.items()))
#         for element in parent_element:
#             if element:
#                 # treat like dict - we assume that if the first two tags
#                 # in a series are different, then they are all different.
#                 if len(element) == 1 or element[0].tag != element[1].tag:
#                     aDict = XmlDictConfig(element)
#                 # treat like list - we assume that if the first two tags
#                 # in a series are the same, then the rest are the same.
#                 else:
#                     # here, we put the list in dictionary; the key is the
#                     # tag name the list elements all share in common, and
#                     # the value is the list itself
#                     aDict = {element[0].tag: XmlListConfig(element)}
#                 # if the tag has attributes, add those to the dict
#                 if element.items():
#                     aDict.update(dict(element.items()))
#                 self.update({element.tag: aDict})
#             # this assumes that if you've got an attribute in a tag,
#             # you won't be having any text. This may or may not be a
#             # good idea -- time will tell. It works for the way we are
#             # currently doing XML configuration files...
#             elif element.items():
#                 self.update({element.tag: dict(element.items())})
#             # finally, if there are no child tags and no attributes, extract
#             # the text
#             else:
#                 self.update({element.tag: element.text})
