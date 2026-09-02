import numpy as np

class DeviceModel:
    def __init__(self, nch_lut, pch_lut):
        """
        Initializes the device model with NMOS and PMOS lookup tables.
        nch_lut, pch_lut: Instances of LUT from tech_luts.lut_utils
        """
        self.nch = nch_lut
        self.pch = pch_lut

    def size_device(self, dev_type, gmid_target, L, ID_target, VDS, VSB=0.0):
        """
        Sizes a transistor to meet a specific ID and gm/ID.
        Returns a dictionary containing W, VGS, and small-signal parameters.
        All input voltages/currents are assumed to be absolute values for both NMOS and PMOS.
        """
        lut = self.nch if dev_type == 'nch' else self.pch
        
        # 1. Find the required VGS for the target gm/ID
        # lookup_vgs returns an array; extract the first element if it's an array
        vgs_array = lut.lookup_vgs([L], [gmid_target], [VDS], [VSB])
        vgs = vgs_array[0]
        
        # 2. Look up the characterization ID and other parameters at this operating point
        id_char = np.abs(lut.lookup('ids', L, vgs, VDS, VSB)[0])
        
        # Calculate W
        W_char = lut.W
        
        # Prevent division by zero
        if id_char < 1e-15:
            id_char = 1e-15
            
        W = (ID_target / id_char) * W_char
        scale = W / W_char
        
        # Look up and scale parameters
        gm = np.abs(lut.lookup('gm', L, vgs, VDS, VSB)[0]) * scale
        gds = np.abs(lut.lookup('gds', L, vgs, VDS, VSB)[0]) * scale
        
        cgg = np.abs(lut.lookup('cgg', L, vgs, VDS, VSB)[0]) * scale
        cgs = np.abs(lut.lookup('cgs', L, vgs, VDS, VSB)[0]) * scale
        cgd = np.abs(lut.lookup('cgd', L, vgs, VDS, VSB)[0]) * scale
        cdd = np.abs(lut.lookup('cdd', L, vgs, VDS, VSB)[0]) * scale
        
        try:
            gmbs = np.abs(lut.lookup('gmbs', L, vgs, VDS, VSB)[0]) * scale
        except KeyError:
            gmbs = 0.2 * gm
        
        # Voltage parameters don't scale with W
        vth = np.abs(lut.lookup('vth', L, vgs, VDS, VSB)[0])
        vdsat = np.abs(lut.lookup('vdsat', L, vgs, VDS, VSB)[0])
        
        return {
            'type': dev_type,
            'W': W,
            'L': L,
            'VGS': vgs,
            'VDS': VDS,
            'VSB': VSB,
            'VDSAT': vdsat,
            'VTH': vth,
            'ID': ID_target,
            'gm': gm,
            'gds': gds,
            'gmbs': gmbs,
            'cgg': cgg,
            'cgs': cgs,
            'cgd': cgd,
            'cdd': cdd
        }
