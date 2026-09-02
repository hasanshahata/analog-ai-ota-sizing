"""Central design contract for the 65 nm 5T-OTA sizing problem.

Every bound, normalization constant, and default constraint limit lives here.
No module may hardcode its own copy (correction plan Phase 1: one canonical contract).
"""

from __future__ import annotations

# ---------------------------------------------------------------- supply ---
VDD = 1.2  # volts
VICM = VDD / 2.0  # input common mode (imposed, see ota5t docstring)
VOCM = VDD / 2.0  # output common mode

# ------------------------------------------------------- design vector -----
# 5-parameter design vector, compatible with the V2-V12 trained models:
#   x = [L1, gmid1, L3, gmid3, Itail]
DESIGN_PARAM_NAMES = ("L1", "gmid1", "L3", "gmid3", "Itail")
DESIGN_BOUNDS = (
    (60e-9, 1.5e-6),   # L1    NMOS input pair channel length [m]
    (5.0, 25.0),       # gmid1 NMOS input pair gm/Id       [1/V]
    (60e-9, 1.5e-6),   # L3    PMOS load channel length    [m]
    (5.0, 25.0),       # gmid3 PMOS load gm/Id             [1/V]
    (10e-6, 500e-6),   # Itail tail bias current           [A]
)

# 7-parameter vector (adds a physical tail device) used by the legacy root
# package and available here via OTA5T(tail_device="finite").
DESIGN_PARAM_NAMES_7 = ("L1", "gmid1", "L3", "gmid3", "L5", "gmid5", "Itail")
DESIGN_BOUNDS_7 = DESIGN_BOUNDS[:4] + (
    (60e-9, 1.5e-6),   # L5
    (5.0, 25.0),       # gmid5
)

# ------------------------------------------------- hard constraint limits --
# Defaults; a request may tighten but not silently relax them (docs/DESIGN_CONTRACT.md).
PM_MIN_DEFAULT = 45.0          # degrees
SAT_MARGIN_MIN_DEFAULT = 0.05  # volts (VDS - VDSAT, every device)
W_NMOS_MAX = 250e-6            # meters
W_PMOS_MAX = 750e-6            # meters

# ------------------------------------------------------------ AC sweep -----
AC_FREQ_MIN_HZ = 1.0
AC_FREQ_MAX_HZ = 10e9
AC_POINTS_PER_DECADE = 30      # 100 points total was too coarse for GBW/PM extraction

# ------------------------------------------------------- RL environment ----
# Cost normalization constants (V10 smooth relative-squared cost, kept for
# comparability with the V9-V12 trained models).
COST_INVALID = 2000.0          # finite cost assigned to invalid evaluations
REWARD_SCALE = 100.0           # reward = -cost / REWARD_SCALE  (V12)
OBS_GAIN_NORM = 40.0           # dB
OBS_GBW_NORM = 3e8             # Hz
OBS_POWER_NORM = 400e-6        # W
OBS_PM_NORM = 90.0             # deg
OBS_SAT_NORM = 0.3             # V
OBS_CL_NORM = 5.0              # pF

# Target sampling ranges used during V9-V12 training (documented, NOT a
# feasibility guarantee - see docs/DESIGN_CONTRACT.md).
TARGET_RANGES = {
    "Gain_min": (20.0, 45.0),        # dB
    "GBW_min": (50e6, 300e6),        # Hz
    "CL_pF": (0.1, 5.0),             # pF
    "Power_max": (50e-6, 400e-6),    # W
}
