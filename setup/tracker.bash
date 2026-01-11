#!/bin/bash

set -e
cd ~/.ros/dasimrpn

wget wget "https://www.dropbox.com/s/rr1lk9355vzolqv/dasiamrpn_model.onnx?dl=1" -O dasiamrpn_model.onnx
wget "https://www.dropbox.com/s/999cqx5zrfi7w4p/dasiamrpn_kernel_r1.onnx?dl=1" -O dasiamrpn_kernel_r1.onnx
wget "https://www.dropbox.com/s/qvmtszx5h339a0w/dasiamrpn_kernel_cls1.onnx?dl=1" -O dasiamrpn_kernel_cls1.onnx


#参考元
# samples/dnn/dasiamrpn_tracker.cpp内
# OpenCVの公式Gitリポジトリ内
#  DaSiamRPN tracker.
#  Original paper: https://arxiv.org/abs/1808.06048
#  Link to original repo: https://github.com/foolwood/DaSiamRPN
#  Links to onnx models:
#  - network:     https://www.dropbox.com/s/rr1lk9355vzolqv/dasiamrpn_model.onnx?dl=0
#  - kernel_r1:   https://www.dropbox.com/s/999cqx5zrfi7w4p/dasiamrpn_kernel_r1.onnx?dl=0
#  - kernel_cls1: https://www.dropbox.com/s/qvmtszx5h339a0w/dasiamrpn_kernel_cls1.onnx?dl=0
