"""Device sizing on top of the gm/Id LUTs.

Fixes vs. the legacy `core/device_model.py`:
- Domain errors from the LUT propagate (no silent extrapolation).
- `params_at_geometry` supports *matched* devices: the second device of a
  pair reuses the first device's W/L geometry and is only re-characterized
  at its own bias, so a "matched pair" can no longer end up with two
  different widths (the root cause of the W1 != W2 defect in the legacy
  netlists).
"""

from __future__ import annotations

import numpy as np

from .lut import LUT


class DeviceModel:
    def __init__(self, nch_lut: LUT, pch_lut: LUT):
        self.nch = nch_lut
        self.pch = pch_lut

    def _lut(self, dev_type: str) -> LUT:
        return self.nch if dev_type == "nch" else self.pch

    # ------------------------------------------------------------- sizing ---
    def size_device(self, dev_type: str, gmid_target: float, L: float,
                    ID_target: float, VDS: float, VSB: float = 0.0) -> dict:
        """Size a transistor for a target current and gm/Id (all magnitudes positive).

        Returns a dict with geometry (W, L), terminal voltages, and
        small-signal parameters scaled from the reference-width characterization.
        """
        lut = self._lut(dev_type)
        vgs_arr = lut.lookup_vgs([L], [gmid_target], [VDS], [VSB])
        vgs = float(vgs_arr[0])

        id_char = float(np.abs(lut.lookup("ids", [L], [vgs], [VDS], [VSB])[0]))
        w_ref = lut.W
        id_char = max(id_char, 1e-15)

        W = (ID_target / id_char) * w_ref
        return self._params_at(lut, dev_type, W, L, vgs, VDS, VSB,
                               ID_target=ID_target, gmid=gmid_target)

    def params_at_geometry(self, dev_type: str, W: float, L: float,
                           VGS: float, VDS: float, VSB: float = 0.0) -> dict:
        """Small-signal parameters of a FIXED geometry (W, L) at a given bias.

        Used to keep matched devices matched: the partner of a pair reuses the
        reference device's width and is only re-characterized at its own VDS.
        """
        lut = self._lut(dev_type)
        return self._params_at(lut, dev_type, W, L, VGS, VDS, VSB)

    # ------------------------------------------------------------ intern ---
    def _params_at(self, lut: LUT, dev_type: str, W: float, L: float, vgs: float,
                   vds: float, vsb: float, ID_target: float | None = None,
                   gmid: float | None = None) -> dict:
        scale = W / lut.W
        ids_char = float(np.abs(lut.lookup("ids", [L], [vgs], [vds], [vsb])[0]))
        params = dict(
            type=dev_type, W=W, L=L, VGS=vgs, VDS=vds, VSB=vsb,
            ID=(ID_target if ID_target is not None else ids_char * scale),
            gm=abs(lut.lookup("gm", [L], [vgs], [vds], [vsb])[0]) * scale,
            gds=abs(lut.lookup("gds", [L], [vgs], [vds], [vsb])[0]) * scale,
            cgg=abs(lut.lookup("cgg", [L], [vgs], [vds], [vsb])[0]) * scale,
            cgs=abs(lut.lookup("cgs", [L], [vgs], [vds], [vsb])[0]) * scale,
            cgd=abs(lut.lookup("cgd", [L], [vgs], [vds], [vsb])[0]) * scale,
            cdd=abs(lut.lookup("cdd", [L], [vgs], [vds], [vsb])[0]) * scale,
        )
        if "gmbs" in lut.interpolators:
            params["gmbs"] = abs(lut.lookup("gmbs", [L], [vgs], [vds], [vsb])[0]) * scale
        else:  # pragma: no cover - legacy LUTs without body effect data
            params["gmbs"] = 0.2 * params["gm"]
        # Voltage quantities do not scale with W.
        params["VTH"] = abs(lut.lookup("vth", [L], [vgs], [vds], [vsb])[0])
        params["VDSAT"] = abs(lut.lookup("vdsat", [L], [vgs], [vds], [vsb])[0])
        # Diagnostics: current the characterized geometry would actually pass at
        # this bias (differs from ID when the operating point is imposed, not solved).
        params["id_at_bias"] = ids_char * scale
        if gmid is not None:
            params["gmid"] = gmid
        return params
