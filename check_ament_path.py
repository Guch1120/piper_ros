from ament_index_python.packages import get_packages_with_prefixes

try:
    pkgs = get_packages_with_prefixes()
    target = 'cotyaka_omega_flexbe_behaviors'
    if target in pkgs:
        print(f"Package '{target}' found at: {pkgs[target]}")
        if '/install/' in pkgs[target]:
            ws_root = pkgs[target].split('/install/')[0]
            print(f"Deduced Workspace Root: {ws_root}")
        else:
            print("Path does not contain '/install/', source detection logic might fail.")
    else:
        print(f"Package '{target}' NOT found in ament index.")
except Exception as e:
    print(f"Error: {e}")
