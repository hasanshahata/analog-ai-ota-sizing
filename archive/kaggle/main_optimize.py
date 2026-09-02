import os
import argparse
import numpy as np

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.cost_function import CostFunction
from optimizer.global_optimizer import GlobalOptimizer
from utils.netlist_exporter import NetlistExporter
from utils.visualizer import Visualizer

def main():
    parser = argparse.ArgumentParser(description="5T OTA AI Optimizer & Sizing Engine (TSMC 65nm)")
    parser.append_argument("--popsize", type=int, default=15, help="Population size for Differential Evolution")
    parser.append_argument("--maxiter", type=int, default=50, help="Maximum iterations")
    parser.append_argument("--netlist", type=str, default="5t_ota_sized.scs", help="Output Spectre netlist file")
    parser.append_argument("--plot", type=str, default="bode_plot.png", help="Output Bode plot image")
    
    args, unknown = parser.parse_known_args()
    
    print("Initializing 5T OTA Sizing Engine...")
    print("Loading LUTs (this may take a moment)...")
    
    nch_path = os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl')
    pch_path = os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl')
    
    if not os.path.exists(nch_path) or not os.path.exists(pch_path):
        print("Error: LUT files not found in tech_luts/")
        return
        
    nch = LUT(nch_path)
    pch = LUT(pch_path)
    
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    
    # Target Specs for 65nm
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
    
    # x = [L1, gmid1, L3, gmid3, L5, gmid5, Itail]
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    
    opt = GlobalOptimizer(ota, cost_fn, bounds, popsize=args.popsize, maxiter=args.maxiter)
    result, best_perf = opt.optimize()
    
    if best_perf:
        Visualizer.print_design_summary(best_perf)
        NetlistExporter.export_spectre(best_perf, args.netlist)
        
        # To plot bode, we need to extract freqs and re-solve or we can just re-evaluate AC
        freqs = np.logspace(0, 10, 100)
        V_out = ota.mna.solve_ac(
            best_perf['devices']['M1'], 
            best_perf['devices']['M2'], 
            best_perf['devices']['M3'], 
            best_perf['devices']['M4'], 
            best_perf['devices']['M5'], 
            ota.CL, freqs)
            
        Visualizer.plot_bode(freqs, V_out, args.plot)
    else:
        print("Optimization failed to find a valid solution.")

if __name__ == '__main__':
    main()
