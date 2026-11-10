"""Convert a STEP file to GLB with OpenCASCADE, keeping one mesh per solid.

Used for the semi finger cot before tools/export_hardware_glb.py:
  pip install cascadio
  python tools/step_to_glb.py V7_1.5mm_Fingercot_Silicon_Index_Middle.step fingercot.glb
The tessellation is fine (0.05 mm); the export script decimates it.
"""

import sys

import cascadio

if len(sys.argv) != 3:
    sys.exit("usage: python tools/step_to_glb.py in.step out.glb")
status = cascadio.step_to_glb(sys.argv[1], sys.argv[2], tol_linear=0.00005, tol_angular=0.2)
if status != 0:
    sys.exit(f"cascadio failed with status {status}")
print(f"wrote {sys.argv[2]}")
