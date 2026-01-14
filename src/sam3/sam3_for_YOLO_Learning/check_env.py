import sys
print(f"Python version: {sys.version}")

print("Importing numpy...")
import numpy
print(f"Numpy version: {numpy.__version__}")

print("Importing torch...")
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

print("Testing torch.from_numpy...")
try:
    a = numpy.array([1, 2, 3])
    t = torch.from_numpy(a)
    print("Success: torch.from_numpy works!")
    print(t)
except Exception as e:
    print(f"Error in torch.from_numpy: {e}")
    import traceback
    traceback.print_exc()
