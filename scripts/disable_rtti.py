Import("env")

# Point 2 experiment: compile C++ translation units without RTTI.
# This is intentionally scoped through platformio.local.ini to the personal
# X4 Pro build so Build #14 remains the exact baseline.
env.Append(CXXFLAGS=["-fno-rtti"])
