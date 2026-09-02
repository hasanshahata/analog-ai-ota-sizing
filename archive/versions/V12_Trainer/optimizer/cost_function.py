import numpy as np

class CostFunction:
    def __init__(self, specs, penalty_weight=1e4):
        """
        Initializes the cost function.
        specs: dict of target specifications (e.g. {'Gain_min': 30.0, ...})
        penalty_weight: multiplier for penalty terms
        """
        self.specs = specs
        self.penalty_weight = penalty_weight

    def __call__(self, perf):
        """
        Calculates a scalar cost from the OTA performance dictionary.
        Lower cost is better.
        """
        # Objective: Minimize Power. We scale it to uW to keep numbers reasonable.
        # Alternatively, we could maximize FoM = GBW * CL / Power -> Minimize -FoM
        cost = perf['Power'] * 1e6 # Base cost is power in uW
        
        penalty = 0.0
        
        # 1. DC Gain >= 30 dB
        if perf['DC_Gain_dB'] < self.specs.get('Gain_min', 30.0):
            penalty += (self.specs.get('Gain_min', 30.0) - perf['DC_Gain_dB'])**2
            
        # 2. GBW >= 150 MHz
        if perf['GBW'] < self.specs.get('GBW_min', 150e6):
            penalty += ((self.specs.get('GBW_min', 150e6) - perf['GBW']) / 1e6)**2
            
        # 3. PM >= 60 deg
        if perf['PM'] < self.specs.get('PM_min', 60.0):
            penalty += (self.specs.get('PM_min', 60.0) - perf['PM'])**2
            
        # 4. Power <= 300 uW
        if perf['Power'] > self.specs.get('Power_max', 300e-6):
            penalty += ((perf['Power'] - self.specs.get('Power_max', 300e-6)) * 1e6)**2
            
        # 5. SR >= 50 V/us
        if perf['SR'] < self.specs.get('SR_min', 50e6):
            penalty += ((self.specs.get('SR_min', 50e6) - perf['SR']) / 1e6)**2
            
        # 6. Swing >= 0.8 V
        if perf['Swing'] < self.specs.get('Swing_min', 0.8):
            penalty += ((self.specs.get('Swing_min', 0.8) - perf['Swing']) * 100)**2
            
        # 7. ICMR Min <= 0.5 V
        if perf['ICMR_min'] > self.specs.get('ICMR_max', 0.5):
            penalty += ((perf['ICMR_min'] - self.specs.get('ICMR_max', 0.5)) * 100)**2
            
        # 8. Saturation margin >= 50mV
        margin_target = self.specs.get('Sat_margin_min', 0.05)
        if perf['min_sat_margin'] < margin_target:
            # Penalize heavily for leaving saturation
            penalty += ((margin_target - perf['min_sat_margin']) * 100)**2
            
        return cost + self.penalty_weight * penalty
