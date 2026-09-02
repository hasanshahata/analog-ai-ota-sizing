import numpy as np
from core.mna_engine import MNAEngine

class OTA5T:
    def __init__(self, device_model, vdd=1.2, cl=1e-12):
        self.dm = device_model
        self.mna = MNAEngine()
        self.VDD = vdd
        self.CL = cl
        
        # Nominal Common Mode Voltages
        self.Vicm = self.VDD / 2.0
        self.Vocm = self.VDD / 2.0

    def evaluate(self, x, freqs=None):
        """
        Evaluates the 5T OTA performance for a given design vector.
        x = [L1, gmid1, L3, gmid3, L5, gmid5, Itail]
        Returns a dictionary of performance metrics and device sizings.
        """
        L1, gmid1, L3, gmid3, L5, gmid5, Itail = x
        
        # Current distribution
        Id1 = Itail / 2.0
        Id3 = Itail / 2.0
        
        # 1. Size M5 (Tail Current Source)
        # We don't know VDS5 exactly until we size M1, but we can approximate it or size it first 
        # and refine. Let's do a fast 2-step or just use assumed VDS5.
        # Actually, Vtail = Vicm - VGS1. But we need VGS1. 
        # We can find VGS1 using an approximate VDS1, then update.
        # LUT VDS sensitivity is usually low, so we can use nominal VDS for the first pass.
        
        # First pass to find VGS1
        # Assumed VDS1 = VDD/2 - 0.2
        temp_m1 = self.dm.size_device('nch', gmid1, L1, Id1, VDS=self.VDD/2, VSB=0.0)
        VGS1 = temp_m1['VGS']
        Vtail = self.Vicm - VGS1
        
        # Now we know exact Vtail (which is VDS5)
        VDS5 = max(Vtail, 0.01) # keep it positive
        
        # Size M5
        m5 = self.dm.size_device('nch', gmid5, L5, Itail, VDS=VDS5, VSB=0.0)
        
        # Size M3/M4 (PMOS Current Mirror)
        # Assumed VDS3 = VGS3, we need to iterate once.
        # First guess VDS3 = 0.6
        temp_m3 = self.dm.size_device('pch', gmid3, L3, Id3, VDS=0.6, VSB=0.0)
        VGS3_abs = temp_m3['VGS']
        Vmirror = self.VDD - VGS3_abs
        
        # Re-size M3 with exact VDS
        VDS3_abs = self.VDD - Vmirror # = VGS3_abs
        m3 = self.dm.size_device('pch', gmid3, L3, Id3, VDS=VDS3_abs, VSB=0.0)
        
        # M4 is identical to M3 but VDS is different (Vocm is VDD/2)
        VDS4_abs = self.VDD - self.Vocm
        m4 = self.dm.size_device('pch', gmid3, L3, Id3, VDS=VDS4_abs, VSB=0.0)
        
        # Re-size M1/M2 with exact VDS and VSB
        # VSB for NMOS is Vtail (since Bulk is 0)
        VSB1 = Vtail
        VDS1 = Vmirror - Vtail
        m1 = self.dm.size_device('nch', gmid1, L1, Id1, VDS=max(VDS1, 0.01), VSB=max(VSB1, 0.0))
        
        VSB2 = Vtail
        VDS2 = self.Vocm - Vtail
        m2 = self.dm.size_device('nch', gmid1, L1, Id1, VDS=max(VDS2, 0.01), VSB=max(VSB2, 0.0))
        
        # --- DC & Large Signal Constraints ---
        Power = self.VDD * Itail
        SR = Itail / self.CL
        
        # Saturation Margins
        # Vds - Vdsat > 0 for saturation
        sat_m1 = m1['VDS'] - m1['VDSAT']
        sat_m2 = m2['VDS'] - m2['VDSAT']
        sat_m3 = m3['VDS'] - m3['VDSAT']
        sat_m4 = m4['VDS'] - m4['VDSAT']
        sat_m5 = m5['VDS'] - m5['VDSAT']
        
        min_sat_margin = min([sat_m1, sat_m2, sat_m3, sat_m4, sat_m5])
        
        # Output Swing (approximate)
        # Vout_max = VDD - VDSAT4
        # Vout_min = Vtail + VDSAT2 (and Vtail >= VDSAT5)
        # So Swing = VDD - VDSAT4 - VDSAT2 - VDSAT5
        Swing = self.VDD - m4['VDSAT'] - m2['VDSAT'] - m5['VDSAT']
        
        # ICMR min
        # Vicm_min = VGS1 + VDSAT5
        ICMR_min = m1['VGS'] + m5['VDSAT']
        
        # --- AC Small Signal Evaluation ---
        if freqs is None:
            freqs = np.logspace(0, 10, 100) # 1 Hz to 10 GHz
            
        V_out = self.mna.solve_ac(m1, m2, m3, m4, m5, self.CL, freqs)
        ac_metrics = self.mna.extract_metrics(freqs, V_out)
        
        # Area estimation (Width * Length for all devices)
        Area = 2*(m1['W']*m1['L']) + 2*(m3['W']*m3['L']) + m5['W']*m5['L']
        
        return {
            'Power': Power,
            'SR': SR,
            'Swing': Swing,
            'ICMR_min': ICMR_min,
            'min_sat_margin': min_sat_margin,
            'sat_m1': sat_m1, 'sat_m2': sat_m2, 'sat_m3': sat_m3, 'sat_m4': sat_m4, 'sat_m5': sat_m5,
            'DC_Gain_dB': ac_metrics['DC_Gain_dB'],
            'GBW': ac_metrics['GBW'],
            'PM': ac_metrics['PM'],
            'Area': Area,
            'devices': {
                'M1': m1, 'M2': m2, 'M3': m3, 'M4': m4, 'M5': m5
            }
        }
