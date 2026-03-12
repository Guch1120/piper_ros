import importlib
import os
import sys
import xml.etree.ElementTree as ET

pkg_name = 'cotyaka_omega_flexbe_behaviors'
found_path = ""

print(f"Checking package: {pkg_name}...")
print(f"Current working directory: {os.getcwd()}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not Set')}")
print(f"sys.path: {sys.path}")

try:
    # 1. Get install path as fallback
    try:
        mod = importlib.import_module(pkg_name)
        install_path = mod.__path__[0] # list
        print(f"Imported module path: {install_path}")
        found_path = install_path # Default to install path
    except ImportError:
        print(f"Failed to import module {pkg_name}. Proceeding to manual scan assuming /ros2_ws...")
        install_path = "/ros2_ws/install/share/" + pkg_name # Dummy path to trigger workspace logic if needed, but better to force scan
        
    
    # 2. Find workspace root
    ws_root = "/ros2_ws" # Hardcoded assumption for Docker environment if import fails
    if 'install_path' in locals() and '/install/' in install_path:
        ws_root = install_path.split('/install/')[0]
    
    src_root = os.path.join(ws_root, 'src')
    print(f"Using workspace root: {ws_root}")
    print(f"Scanning src root: {src_root}")
    
    # 3. Search src for package
    source_pkg_path = None
    if os.path.exists(src_root):
         for root, dirs, files in os.walk(src_root):
            if 'package.xml' in files:
                try: 
                    tree = ET.parse(os.path.join(root, 'package.xml'))
                    root_node = tree.getroot()
                    name_node = root_node.find('name')
                    # print(f"Checking {os.path.join(root, 'package.xml')} -> {name_node.text}")
                    if name_node is not None and name_node.text == pkg_name:
                         source_pkg_path = root
                         print(f"Found source package.xml at: {source_pkg_path}")
                         break
                except Exception as e:
                    print(f"Error parsing {os.path.join(root, 'package.xml')}: {e}")
                    pass
    else:
        print(f"src root does not exist: {src_root}")
    
    if source_pkg_path:
         # 4. Find python module in source
         # Check for src/pkg_name or pkg_name (ROS 2 python package structures)
         possible_paths = [
             os.path.join(source_pkg_path, pkg_name),
             os.path.join(source_pkg_path, 'cotyaka_omega_flexbe_behaviors'), # Explicit check using pkg_name string just in case
             os.path.join(source_pkg_path, 'src', pkg_name) # ROS 2 pure python pkg structure
         ]
         print(f"Checking possible python paths in source: {possible_paths}")
         for p in possible_paths:
             if os.path.isdir(p) and os.path.exists(os.path.join(p, '__init__.py')):
                 found_path = p
                 print(f"Found python module at: {p}")
                 break
         else:
             print("Could not find python module in source paths.")

except Exception as e:
    print(f"Exception happened: {e}")
    # import traceback
    # traceback.print_exc()
    pass

print(f"FINAL RESULT: {found_path}")
