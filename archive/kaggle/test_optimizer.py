import sys
import os
import numpy as np

# Ensure path is correct
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.cost_function import CostFunction
from optimizer.global_optimizer import GlobalOptimizer
from utils.netlist_exporter import NetlistExporter

def test_full_optimization():
    print("1. Loading TSMC 65nm LUTs...")
    nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
    pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
    
    print("2. Initializing Core Engine...")
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    
    # Define Target Specs
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
    
    print("3. Target Specifications:")
    for k, v in specs.items():
        print(f"   {k}: {v}")
        
    cost_fn = CostFunction(specs, penalty_weight=1e4)
    
    # x = [L1, gmid1, L3, gmid3, L5, gmid5, Itail]
    # Bounds matching 65nm logic rules and gmid charts
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    
    print("4. Running Global Optimizer (Differential Evolution)...")
    # Small maxiter and popsize for quick test
    opt = GlobalOptimizer(ota, cost_fn, bounds, popsize=10, maxiter=20)
    result, best_perf = opt.optimize()
    
    print("\n--- OPTIMIZATION RESULTS ---")
    if best_perf is not None:
        print(f"DC Gain: {best_perf['DC_Gain_dB']:.2f} dB")
        print(f"GBW: {best_perf['GBW']/1e6:.2f} MHz")
        print(f"Phase Margin: {best_perf['PM']:.2f} deg")
        print(f"Power: {best_perf['Power']*1e6:.2f} uW")
        print(f"Slew Rate: {best_perf['SR']/1e6:.2f} V/us")
        print(f"Output Swing: {best_perf['Swing']:.2f} V")
        print(f"ICMR Min: {best_perf['ICMR_min']:.2f} V")
        print(f"Min Sat Margin: {best_perf['min_sat_margin']*1000:.1f} mV")
        
        print("\n--- SIZED DEVICES ---")
        for name in ['M1', 'M3', 'M5']:
            d = best_perf['devices'][name]
            print(f"{name}: W = {d['W']*1e6:.2f} um, L = {d['L']*1e6:.3f} um, VGS = {d['VGS']:.3f} V, ID = {d['ID']*1e6:.1f} uA")
            
        print("\n5. Exporting Netlist...")
        NetlistExporter.export_spectre(best_perf, "test_5t_ota_sized.scs")
    else:
        print("Optimization failed to find a valid operating point.")

if __name__ == '__main__':
    test_full_optimization()
