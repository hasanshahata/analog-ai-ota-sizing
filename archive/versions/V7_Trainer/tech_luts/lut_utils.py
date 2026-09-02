import pickle
import numpy as np
from scipy.interpolate import RegularGridInterpolator

class LUT:
    def __init__(self, filepath):
        with open(filepath, 'rb') as f:
            self.data = pickle.load(f)
        
        self.L = self.data['L']
        self.VGS = self.data['VGS']
        self.VDS = self.data['VDS']
        self.VSB = self.data['VSB']
        self.W = 5e-6 # Explicitly set to 5um as per user spec

        # Calculate derived parameters
        # Add epsilon to prevent division by zero for gm/id. Use abs() since PMOS ids might be negative.
        ids_abs = np.abs(self.data['ids'])
        ids_safe = np.maximum(ids_abs, 1e-15)
        
        # We also want gm to be positive just in case
        gm_abs = np.abs(self.data['gm'])
        self.gmid = gm_abs / ids_safe
        
        # Create interpolators for fast lookups.
        # Original grid is (L, VGS, VDS, VSB)
        grid = (self.L, self.VGS, self.VDS, self.VSB)
        
        # Dictionary to store interpolators to avoid recreating them
        self.interpolators = {}
        for key in ['ids', 'gm', 'gds', 'cgg', 'cgs', 'cgd', 'cdd', 'vth', 'vdsat', 'gmbs', 'gmid']:
            if key in self.data:
                self.interpolators[key] = RegularGridInterpolator(
                    grid, self.data[key], bounds_error=False, fill_value=None)
            elif key == 'gmid':
                 self.interpolators[key] = RegularGridInterpolator(
                    grid, self.gmid, bounds_error=False, fill_value=None)

    def lookup(self, param, L, VGS, VDS, VSB):
        """Looks up a parameter given L, VGS, VDS, VSB."""
        pts = np.column_stack([L, VGS, VDS, VSB])
        return self.interpolators[param](pts)

    def lookup_vgs(self, L, gmid_target, VDS, VSB):
        """
        Reverse lookup: Finds the VGS required to achieve a target gm/ID.
        This uses 1D interpolation along the VGS axis for each operating point.
        """
        L = np.atleast_1d(L)
        gmid_target = np.atleast_1d(gmid_target)
        VDS = np.atleast_1d(VDS)
        VSB = np.atleast_1d(VSB)
        
        # Ensure they are the same length
        n_pts = max(len(L), len(gmid_target), len(VDS), len(VSB))
        L = np.broadcast_to(L, n_pts)
        gmid_target = np.broadcast_to(gmid_target, n_pts)
        VDS = np.broadcast_to(VDS, n_pts)
        VSB = np.broadcast_to(VSB, n_pts)
        
        vgs_out = np.zeros(n_pts)
        
        for i in range(n_pts):
            # For this L, VDS, VSB, we extract the 1D slice of gmid vs VGS
            # We can use the interpolator to get the gmid curve along VGS
            # We sample at all original VGS points
            pts = np.column_stack([
                np.full_like(self.VGS, L[i]),
                self.VGS,
                np.full_like(self.VGS, VDS[i]),
                np.full_like(self.VGS, VSB[i])
            ])
            gmid_curve = self.interpolators['gmid'](pts)
            
            # gmid is a monotonically decreasing function of VGS (usually)
            # We use numpy interp, but it requires the x-axis (gmid) to be increasing.
            # So we reverse the arrays.
            idx_sort = np.argsort(gmid_curve)
            gmid_sorted = gmid_curve[idx_sort]
            vgs_sorted = self.VGS[idx_sort]
            
            vgs_out[i] = np.interp(gmid_target[i], gmid_sorted, vgs_sorted)
            
        return vgs_out

    def lookup_with_gmid(self, param, L, gmid, VDS, VSB):
        """Looks up a parameter given L, gm/ID, VDS, VSB."""
        vgs = self.lookup_vgs(L, gmid, VDS, VSB)
        return self.lookup(param, L, vgs, VDS, VSB)
