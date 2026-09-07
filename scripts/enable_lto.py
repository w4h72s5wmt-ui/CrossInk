# Measurement-only GCC LTO hook for the X4 Pro optimization experiment.
Import("env")

env.Append(
    CCFLAGS=["-flto"],
    LINKFLAGS=["-flto"],
)

print("Point 5 LTO experiment: enabled -flto for compile and link")
