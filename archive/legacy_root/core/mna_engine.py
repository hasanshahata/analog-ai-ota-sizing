import numpy as np

class MNAEngine:
    """
    Numerical 3x3 Modified Nodal Analysis (MNA) solver for the 5T OTA.
    Nodes:
    1: V_tail (source of M1/M2, drain of M5)
    2: V_mirror (drain of M1, gate/drain of M3, gate of M4)
    3: V_out (drain of M2, drain of M4, C_L)
    """
    def __init__(self):
        pass

    def solve_ac(self, m1, m2, m3, m4, m5, CL, freqs):
        """
        Solves the AC response across a frequency array.
        m1..m5 are dictionaries containing small-signal parameters from DeviceModel.
        """
        # Note: We assume symmetry m1 == m2 and m3 == m4 for simpler expression, 
        # but here we use exact parameters from the dicts for full generality.
        # Ensure we have a numpy array for frequencies
        freqs = np.atleast_1d(freqs)
        s = 1j * 2 * np.pi * freqs
        
        num_freqs = len(s)
        V_out = np.zeros(num_freqs, dtype=np.complex128)
        
        # We can vectorize the matrix solve using np.linalg.solve on a batch of matrices (num_freqs, 3, 3)
        Y = np.zeros((num_freqs, 3, 3), dtype=np.complex128)
        I_inj = np.zeros((num_freqs, 3, 1), dtype=np.complex128)
        
        # Node 1: V_tail
        # connected to: M1 source, M2 source, M5 drain
        # Substrate of M1/M2 is connected to bulk (usually ground for NMOS), so Vsb = Vtail.
        # This gives a gmb transconductance. We approximate gmb ~ 0.2 * gm if not in LUT, or take it from LUT.
        gmb1 = m1.get('gmb', 0.2 * m1['gm'])
        gmb2 = m2.get('gmb', 0.2 * m2['gm'])
        
        Y[:, 0, 0] = (m5['gds'] + m1['gds'] + m2['gds'] + 
                      m1['gm'] + m2['gm'] + gmb1 + gmb2 + 
                      s * (m1['cgs'] + m2['cgs'] + m5['cdd'] + m1['cgs']*0.0 + m2['cgs']*0.0)) # approx Csb
        Y[:, 0, 1] = -m1['gds'] - s * m1['cgd']
        Y[:, 0, 2] = -m2['gds'] - s * m2['cgd']
        
        # Node 2: V_mirror
        # connected to: M1 drain, M3 gate/drain, M4 gate
        Y[:, 1, 0] = -(m1['gds'] + m1['gm']) - s * m1['cgs']
        Y[:, 1, 1] = (m1['gds'] + m3['gds'] + m3['gm'] + 
                      s * (m1['cdd'] + m1['cgd'] + m3['cdd'] + m3['cgs'] + m4['cgs'] + m3['cgd']))
        Y[:, 1, 2] = 0
        
        # Node 3: V_out
        # connected to: M2 drain, M4 drain, CL
        Y[:, 2, 0] = -(m2['gds'] + m2['gm']) - s * m2['cgs']
        Y[:, 2, 1] = m4['gm'] + s * m4['cgd']
        Y[:, 2, 2] = (m2['gds'] + m4['gds'] + 
                      s * (m2['cdd'] + m2['cgd'] + m4['cdd'] + m4['cgd'] + CL))
        
        # Differential input excitation: Vin+ = 0.5, Vin- = -0.5
        # I_inj1 (Vtail node) = 0.5*gm1 + (-0.5*gm2) = 0 (for symmetric)
        # I_inj2 (Vmirror node) = -0.5*gm1 (Wait, current leaves node 2 if Vin+ applied to M1 gate? 
        # Actually, if Vg1 = +0.5, Id1 increases, so current gm1*0.5 is drawn from node 2. 
        # Let's say current enters node: -0.5 * gm1.
        # However, for consistency with standard definitions where I = Y V, 
        # we inject current gm1*Vgs. 
        # I_inj2 = -gm1 * Vg1 = -0.5 * gm1
        # I_inj3 = -gm2 * Vg2 = -gm2 * (-0.5) = 0.5 * gm2
        I_inj[:, 0, 0] = 0.5 * m1['gm'] - 0.5 * m2['gm']
        I_inj[:, 1, 0] = -0.5 * m1['gm']
        I_inj[:, 2, 0] = 0.5 * m2['gm']
        
        # Solve the batch of systems
        V_nodes = np.linalg.solve(Y, I_inj)
        
        # Output voltage is Node 3
        V_out = V_nodes[:, 2, 0]
        return V_out

    def extract_metrics(self, freqs, V_out):
        """
        Extracts DC Gain, GBW, and Phase Margin from the AC response.
        """
        # DC Gain (assume freqs[0] is very low, e.g., 1 Hz)
        A_v0_mag = np.abs(V_out[0])
        A_v0_db = 20 * np.log10(A_v0_mag)
        
        # Find GBW (frequency where magnitude crosses 1)
        mags = np.abs(V_out)
        
        # Check if we even reach 0 dB
        if mags[0] < 1.0:
            return {
                'DC_Gain_dB': A_v0_db,
                'GBW': 0.0,
                'PM': 0.0,
                'A_v0_mag': A_v0_mag
            }
            
        # Find the index where magnitude drops below 1
        idx_cross = np.where(mags < 1.0)[0]
        if len(idx_cross) == 0:
            # GBW is beyond the max frequency sweep
            gbw = freqs[-1]
            pm = 180.0 + np.angle(V_out[-1], deg=True)
        else:
            idx = idx_cross[0]
            if idx == 0:
                gbw = freqs[0]
                pm = 180.0 + np.angle(V_out[0], deg=True)
            else:
                # Interpolate for better accuracy
                f1, f2 = freqs[idx-1], freqs[idx]
                m1, m2 = mags[idx-1], mags[idx]
                # Log-linear interpolation
                log_f = np.log10(f1) + (np.log10(f2) - np.log10(f1)) * (1.0 - m1) / (m2 - m1)
                gbw = 10**log_f
                
                # Interpolate phase
                p1, p2 = np.angle(V_out[idx-1], deg=True), np.angle(V_out[idx], deg=True)
                phase = p1 + (p2 - p1) * (np.log10(gbw) - np.log10(f1)) / (np.log10(f2) - np.log10(f1))
                pm = 180.0 + phase
                
        return {
            'DC_Gain_dB': A_v0_db,
            'GBW': gbw,
            'PM': pm,
            'A_v0_mag': A_v0_mag
        }
