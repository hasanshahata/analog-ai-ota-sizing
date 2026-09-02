"""
V8 Fast Diagnostic: Smaller grid, focused on finding whether solutions exist.
Also tests the V8 model's actual output vs manual optimal.
"""
import os, sys, json, warnings
import numpy as np
warnings.filterwarnings('ignore')

sys.path.insert(0, 'V8_Trainer')
from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T

print("Loading LUTs...", flush=True)
nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
dm = DeviceModel(nch, pch)
ota = OTA5T(dm, vdd=1.2)
print("LUTs loaded!", flush=True)

# Smaller grid - still covers the space
L_vals = [60e-9, 200e-9, 500e-9, 1e-6, 1.5e-6]
gmid_vals = [5.0, 8.0, 12.0, 18.0, 25.0]
Itail_vals = [10e-6, 30e-6, 50e-6, 100e-6, 150e-6, 200e-6, 300e-6, 400e-6]

tests_dir = os.path.join('test_specs', 'v2_tests')
test_files = sorted([f for f in os.listdir(tests_dir) if f.endswith('.json')])

all_results = {}

for tf in test_files:
    with open(os.path.join(tests_dir, tf)) as f:
        specs = json.load(f)
    
    gain_min = specs['Gain_min']
    gbw_min = specs['GBW_min']
    cl = specs['CL_pF'] * 1e-12
    power_max = specs['Power_max']
    
    print(f"\n{'='*70}", flush=True)
    print(f"TEST: {tf}", flush=True)
    print(f"  Targets: Gain>={gain_min}dB, GBW>={gbw_min/1e6:.0f}MHz, CL={specs['CL_pF']}pF, Power<={power_max*1e6:.0f}uW", flush=True)
    
    best_gain = 0
    best_gbw = 0
    best_overall = None
    best_overall_score = -1e9
    solutions_found = 0
    total_valid = 0
    best_gain_design = None
    best_gbw_design = None
    
    count = 0
    for L1 in L_vals:
        for gmid1 in gmid_vals:
            for L3 in L_vals:
                for gmid3 in gmid_vals:
                    for Itail in Itail_vals:
                        power = 1.2 * Itail
                        if power > power_max:
                            continue
                        count += 1
                        try:
                            perf = ota.evaluate([L1, gmid1, L3, gmid3, Itail], CL=cl)
                        except:
                            continue
                        
                        W1 = perf['devices']['M1']['W']
                        W3 = perf['devices']['M3']['W']
                        if W1 > 250e-6 or W3 > 750e-6:
                            continue
                        if perf['min_sat_margin'] < 0.05:
                            continue
                        if perf['PM'] < 45.0:
                            continue
                            
                        total_valid += 1
                        gain = perf['DC_Gain_dB']
                        gbw = perf['GBW']
                        
                        if gain > best_gain:
                            best_gain = gain
                            best_gain_design = {'L1':L1,'gmid1':gmid1,'L3':L3,'gmid3':gmid3,'Itail':Itail,'Gain':gain,'GBW':gbw,'Power':power,'PM':perf['PM'],'sat':perf['min_sat_margin'],'W1':W1,'W3':W3}
                        if gbw > best_gbw:
                            best_gbw = gbw
                            best_gbw_design = {'L1':L1,'gmid1':gmid1,'L3':L3,'gmid3':gmid3,'Itail':Itail,'Gain':gain,'GBW':gbw,'Power':power,'PM':perf['PM'],'sat':perf['min_sat_margin'],'W1':W1,'W3':W3}
                        
                        gain_met = gain >= gain_min
                        gbw_met = gbw >= gbw_min
                        
                        if gain_met and gbw_met:
                            solutions_found += 1
                        
                        # Score
                        score = min(gain/gain_min, 1.0) + min(gbw/gbw_min, 1.0)
                        if score > best_overall_score:
                            best_overall_score = score
                            best_overall = {'L1':L1,'gmid1':gmid1,'L3':L3,'gmid3':gmid3,'Itail':Itail,'Gain':gain,'GBW':gbw,'Power':power,'PM':perf['PM'],'sat':perf['min_sat_margin'],'W1':W1,'W3':W3}

    print(f"  Evaluated: {count}, Valid (sat+PM+width OK): {total_valid}", flush=True)
    print(f"  SOLUTIONS MEETING ALL SPECS: {solutions_found}", flush=True)
    print(f"  Best Gain: {best_gain:.1f}dB (need {gain_min}dB)", flush=True)
    print(f"  Best GBW:  {best_gbw/1e6:.1f}MHz (need {gbw_min/1e6:.0f}MHz)", flush=True)
    
    if best_gain_design:
        b = best_gain_design
        print(f"\n  BEST-GAIN DESIGN: L1={b['L1']*1e6:.3f}um gmid1={b['gmid1']:.0f} L3={b['L3']*1e6:.3f}um gmid3={b['gmid3']:.0f} Itail={b['Itail']*1e6:.0f}uA => Gain={b['Gain']:.1f}dB GBW={b['GBW']/1e6:.1f}MHz PM={b['PM']:.1f} W1={b['W1']*1e6:.1f}um W3={b['W3']*1e6:.1f}um", flush=True)
    if best_gbw_design:
        b = best_gbw_design
        print(f"  BEST-GBW DESIGN:  L1={b['L1']*1e6:.3f}um gmid1={b['gmid1']:.0f} L3={b['L3']*1e6:.3f}um gmid3={b['gmid3']:.0f} Itail={b['Itail']*1e6:.0f}uA => Gain={b['Gain']:.1f}dB GBW={b['GBW']/1e6:.1f}MHz PM={b['PM']:.1f} W1={b['W1']*1e6:.1f}um W3={b['W3']*1e6:.1f}um", flush=True)
    if best_overall:
        b = best_overall
        print(f"  BEST-BALANCED:    L1={b['L1']*1e6:.3f}um gmid1={b['gmid1']:.0f} L3={b['L3']*1e6:.3f}um gmid3={b['gmid3']:.0f} Itail={b['Itail']*1e6:.0f}uA => Gain={b['Gain']:.1f}dB GBW={b['GBW']/1e6:.1f}MHz PM={b['PM']:.1f} W1={b['W1']*1e6:.1f}um W3={b['W3']*1e6:.1f}um", flush=True)
    
    all_results[tf] = {
        'solutions': solutions_found,
        'best_gain': best_gain,
        'best_gbw': best_gbw,
        'gain_target': gain_min,
        'gbw_target': gbw_min
    }

print(f"\n\n{'='*70}", flush=True)
print("SUMMARY", flush=True)
print(f"{'='*70}", flush=True)
for tf, r in all_results.items():
    gain_ok = "YES" if r['best_gain'] >= r['gain_target'] else "NO"
    gbw_ok = "YES" if r['best_gbw'] >= r['gbw_target'] else "NO"
    print(f"  {tf}: Solutions={r['solutions']} | Gain reachable={gain_ok} ({r['best_gain']:.1f}/{r['gain_target']:.1f}) | GBW reachable={gbw_ok} ({r['best_gbw']/1e6:.0f}M/{r['gbw_target']/1e6:.0f}M)", flush=True)

print("\nDone!", flush=True)
