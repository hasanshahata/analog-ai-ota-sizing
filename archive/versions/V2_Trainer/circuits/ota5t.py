import numpy as np
from core.mna_engine import MNAEngine

class OTA5T:
    def __init__(self, device_model, vdd=1.2):
        self.dm = device_model
        self.mna = MNAEngine()
        self.VDD = vdd
        
        # Nominal Common Mode Voltages
        self.Vicm = self.VDD / 2.0
        self.Vocm = self.VDD / 2.0

    def evaluate(self, x, CL, freqs=None):
        """
        Evaluates the 5T OTA performance for a given design vector.
        x = [L1, gmid1, L3, gmid3, Itail]
        CL = Load Capacitance in Farads
        Returns a dictionary of performance metrics and device sizings.
        """
        L1, gmid1, L3, gmid3, Itail = x
        
        # Current distribution
        Id1 = Itail / 2.0
        Id3 = Itail / 2.0
        
        # First pass to find VGS1
        # Assumed VDS1 = VDD/2 - 0.2
        temp_m1 = self.dm.size_device('nch', gmid1, L1, Id1, VDS=self.VDD/2, VSB=0.0)
        VGS1 = temp_m1['VGS']
        Vtail = self.Vicm - VGS1
        
        # Size M3/M4 (PMOS Current Mirror)
        # Assumed VDS3 = 0.6
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
        
        # M5 is an Ideal Current Source (Infinite output resistance, 0 capacitance)
        m5 = {'W': 0, 'L': 0, 'gds': 0.0, 'gm': 0.0, 'cdd': 0.0, 'css': 0.0, 'cgg': 0.0, 'cgs': 0.0, 'cgd': 0.0, 'VDSAT': 0.0, 'VDS': Vtail}
        
        # --- DC & Large Signal Constraints ---
        Power = self.VDD * Itail
        SR = Itail / CL
        
        # Saturation Margins
        sat_m1 = m1['VDS'] - m1['VDSAT']
        sat_m2 = m2['VDS'] - m2['VDSAT']
        sat_m3 = m3['VDS'] - m3['VDSAT']
        sat_m4 = m4['VDS'] - m4['VDSAT']
        
        min_sat_margin = min([sat_m1, sat_m2, sat_m3, sat_m4])
        
        # Output Swing (approximate)
        # Vout_max = VDD - VDSAT4
        # Vout_min = Vtail + VDSAT2
        Swing = self.VDD - m4['VDSAT'] - m2['VDSAT'] - m5['VDSAT']
        
        # ICMR min
        ICMR_min = m1['VGS']
        
        # --- AC Small Signal Evaluation ---
        if freqs is None:
            freqs = np.logspace(0, 10, 100) # 1 Hz to 10 GHz
            
        V_out = self.mna.solve_ac(m1, m2, m3, m4, m5, CL, freqs)
        ac_metrics = self.mna.extract_metrics(freqs, V_out)
        
        # Area estimation (Width * Length for all devices)
        Area = 2*(m1['W']*m1['L']) + 2*(m3['W']*m3['L'])
        
        return {
            'Power': Power,
            'SR': SR,
            'Swing': Swing,
            'ICMR_min': ICMR_min,
            'min_sat_margin': min_sat_margin,
            'DC_Gain_dB': ac_metrics['DC_Gain_dB'],
            'GBW': ac_metrics['GBW'],
            'PM': ac_metrics['PM'],
            'Area': Area,
            'devices': {
                'M1': m1, 'M2': m2, 'M3': m3, 'M4': m4, 'M5': m5
            }
        }
