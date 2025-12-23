import json
import os
import pathlib
import subprocess
import sys

from ament_index_python.packages import get_packages_with_prefixes, get_package_share_directory
import xml.etree.ElementTree as ET

def check_for_relevance(pkg_name, pkg_root_path):
    # Check if package.xml exists in root
    package_xml_path = os.path.join(pkg_root_path, "package.xml")
    if not os.path.exists(package_xml_path):
        # Fallback to share path if we were passed an install path without package.xml at root (which shouldn't happen for src, but check share)
        package_xml_path = os.path.join(pkg_root_path, "share", pkg_name, "package.xml")

    if os.path.exists(package_xml_path):
        try:
            xml_tree = ET.parse(package_xml_path)
            root = xml_tree.getroot()
            pkg_export = root.find("export")
            if pkg_export:
                has_states = pkg_export.find("flexbe_states") is not None
                has_behaviors = pkg_export.find("flexbe_behaviors") is not None
                return has_states, has_behaviors
        except Exception as exc:
            pass

    return False, False

def find_source_paths(pkg_list):
    # Try to deduce workspace src root
    # We look for '/install/' in paths to find workspace root
    src_map = {}
    ws_roots = set()
    for _, path in pkg_list.items():
        if '/install/' in path:
            ws_root = path.split('/install/')[0]
            ws_roots.add(ws_root)
    
    for ws_root in ws_roots:
        src_root = os.path.join(ws_root, 'src')
        if os.path.exists(src_root):
             # Walk to find packages
             for root, dirs, files in os.walk(src_root):
                if 'package.xml' in files:
                    try:
                        tree = ET.parse(os.path.join(root, 'package.xml'))
                        name_node = tree.getroot().find('name')
                        if name_node is not None:
                            src_map[name_node.text] = root
                    except:
                        pass
    return src_map


def find_flexbe_packages():

    pkg_list = get_packages_with_prefixes()
    src_map = find_source_paths(pkg_list)

    flexbe_packages = []

    for pkg_name, pkg_path in pkg_list.items():
        # Prefer source path if available
        check_path = pkg_path
        if pkg_name in src_map:
            check_path = src_map[pkg_name]
        
        has_states, has_behaviors = check_for_relevance(pkg_name, check_path)

        if has_states or has_behaviors:
            # If we found it in source, return source path, otherwise install path (with limited functionality likely)
            final_path = check_path
            package = {"name": pkg_name, "path": final_path, "python_path": None}
            flexbe_packages.append(package)

    return flexbe_packages

if __name__ == "__main__":
    flexbe_packages = find_flexbe_packages()
    print(json.dumps(flexbe_packages, indent=2))
