"""Test how nbtlib handles ByteArray."""

import nbtlib
from nbtlib.tag import ByteArray

# Test different ways of creating ByteArray
data1 = ByteArray([1, 2, 3])
data2 = ByteArray(bytearray([1, 2, 3]))
# data3 = ByteArray(bytes([1, 2, 3]))  # This doesn't work!

print("Method 1 (list):", type(data1), list(data1))
print("Method 2 (bytearray):", type(data2), list(data2))

# Save and reload
test_nbt = nbtlib.File({"": nbtlib.Compound({"TestData": data2})}, gzipped=True)
test_nbt.save("tests/test_bytearray.dat")

loaded = nbtlib.load("tests/test_bytearray.dat")
print("\nLoaded back:", list(loaded[""]["TestData"]))
