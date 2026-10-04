#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コチャカ (mobile_manipulator) の xacro から Unity インポート用 URDF を生成するスクリプト。"""

import os
import re
import subprocess
import sys


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.dirname(script_dir)
    xacro_path = os.path.join(pkg_dir, 'urdf', 'mobile_manipulator.urdf.xacro')
    output_dir = os.path.join(pkg_dir, 'unity_urdf')
    output_urdf = os.path.join(output_dir, 'mobile_manipulator.urdf')

    os.makedirs(output_dir, exist_ok=True)

    print(f"[INFO] Converting xacro to URDF...")
    print(f"       Input : {xacro_path}")
    print(f"       Output: {output_urdf}")

    cmd = ['xacro', xacro_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        urdf_text = res.stdout

        # Unity URDF Importer 用にパスを package://<pkg_name>/meshes/... 形式に統一
        # 例: file:///ros2_ws/install/piper_description/share/piper_description/meshes/link5.STL -> package://piper_description/meshes/link5.STL
        urdf_text = re.sub(r'file://.*?/(piper_description|realsense2_description|kobuki_description)/(share/\1/)?meshes/', r'package://\1/meshes/', urdf_text)
        urdf_text = re.sub(r'package://(piper_description|realsense2_description|kobuki_description)/share/\1/meshes/', r'package://\1/meshes/', urdf_text)
        urdf_text = re.sub(r'file://\$\(find (.*?)\)/meshes/', r'package://\1/meshes/', urdf_text)

        with open(output_urdf, 'w', encoding='utf-8') as f:
            f.write(urdf_text)
        print("[SUCCESS] URDF generated successfully with clean package:// paths!")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to run xacro: {e}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
