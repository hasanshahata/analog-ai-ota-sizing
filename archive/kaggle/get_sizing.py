import sys
import os
import warnings

# Suppress warnings for cleaner output in CMD
warnings.filterwarnings("ignore")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.cost_function import CostFunction
from optimizer.global_optimizer import GlobalOptimizer

def main():
    print("Initializing Analog AI Optimizer...")
    print("Loading LUTs (this takes a few seconds)...")
    
    try:
        nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
        pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
    except FileNotFoundError:
        print("Error: Could not find LUT files in the tech_luts/ directory.")
        return
        
    dm = DeviceModel(nch, pch)
    # Note: Using Vincm = 0.5V to match your Cadence testbench exactly
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    ota.Vicm = 0.5 
    
    specs = {
        'Gain_min': 30.0,
        'GBW_min': 150e6,
        'PM_min': 60.0,
        'Power_max': 300e-6,
        'SR_min': 50e6,
        'Swing_min': 0.8,
        'ICMR_max': 0.5,
        'Sat_margin_min': 0.05
    }
    
    cost_fn = CostFunction(specs, penalty_weight=1e4)
    
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    
    print("Running Differential Evolution Optimization...")
    print("Please wait while the AI searches for the best sizing...\n")
    
    opt = GlobalOptimizer(ota, cost_fn, bounds, popsize=15, maxiter=50)
    
    # Hide the internal convergence prints for a cleaner CMD output
    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    result, best_perf = opt.optimize()
    sys.stdout = old_stdout
    
    if best_perf is not None:
        m1 = best_perf['devices']['M1']
        m3 = best_perf['devices']['M3']
        itail = best_perf['devices']['M5']['ID']
        
        print("="*40)
        print("      OPTIMIZED SIZING RESULTS")
        print("="*40)
        print(f"W12   = {m1['W']*1e6:.2f} u")
        print(f"L12   = {m1['L']*1e6:.3f} u")
        print(f"W34   = {m3['W']*1e6:.2f} u")
        print(f"L34   = {m3['L']*1e6:.3f} u")
        print(f"Itail = {itail*1e6:.2f} u")
        print("="*40)
        print("\nPredicted Performance:")
        print(f"DC Gain      : {best_perf['DC_Gain_dB']:.2f} dB")
        print(f"GBW          : {best_perf['GBW']/1e6:.2f} MHz")
        print(f"Phase Margin : {best_perf['PM']:.2f} deg")
        print(f"Power        : {best_perf['Power']*1e6:.2f} uW")
        
    else:
        print("Optimization failed.")

if __name__ == '__main__':
    main()
