import sys
print("=== Debug Start ===")
import numpy
print(f"Initial Numpy version: {numpy.__version__}")
import torch
print(f"PyTorch version: {torch.__version__}")
try:
    torch.from_numpy(numpy.array([1]))
    print("torch.from_numpy OK after basic import")
except Exception as e:
    print(f"torch.from_numpy FAILED after basic import: {e}")

print("Importing ultralytics...")
try:
    from ultralytics import YOLO
    print("Ultralytics imported.")
except ImportError:
    print("Ultralytics import failed (is it installed?)")

print(f"Numpy version after ultralytics: {numpy.__version__}")

try:
    torch.from_numpy(numpy.array([1]))
    print("torch.from_numpy OK after ultralytics import")
except Exception as e:
    print(f"torch.from_numpy FAILED after ultralytics import: {e}")
