import os
import json
import numpy as np
import warnings
import sys
warnings.filterwarnings('ignore')

# Add V11_Trainer to the path so we can import its modules
sys.path.append(os.path.abspath("V11_Trainer"))

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.rl_environment import OTA5tGymEnv
from stable_baselines3 import PPO

def test_v11_model():
    print("Initializing Physics Engine (V11)...")
    nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
    pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
    
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2)
    
    bounds = [
        (60e-9, 1.5e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.5e-6),  # L3
        (5.0, 25.0),      # gmid3
        (10e-6, 500e-6)   # Itail
    ]
    
    env = OTA5tGymEnv(ota, bounds=bounds, max_steps=200)
    
    print("Loading Universal PPO Agent V11...")
    model_path = 'universal_ppo_agent_65nm_v11.zip'
    if not os.path.exists(model_path):
        print(f"Error: {model_path} not found.")
        return
    
    model = PPO.load(model_path)
    
    test_dir = os.path.join('test_specs', 'v2_tests')
    tests = sorted(os.listdir(test_dir))
    
    results = []
    
    for t in tests:
        if not t.endswith('.json'): continue
        with open(os.path.join(test_dir, t), 'r') as f:
            specs = json.load(f)
            
        print(f"\nRunning {t}...")
        
        env.target_specs = specs
        
        env.current_step = 0
        env.state = env._get_random_valid_state()
        env.current_cost, perf = env._evaluate_state(env.state)
        obs = env._normalize_state(perf)
        
        # Inference loop
        for step in range(200):
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break

        final_perf = ota.evaluate(env.state, CL=specs['CL_pF']*1e-12)
        results.append({
            'name': t,
            'target': specs,
            'achieved': final_perf,
            'action': env.state
        })
        
    # Build markdown table
    md = "# V11 Evaluation Results\n\n"
    md += "| Test | Gain | GBW | CL | Power | W1/L1 (um) | W3/L3 (um) | Itail (uA) |\n"
    md += "|---|---|---|---|---|---|---|---|\n"
    for r in results:
        t = r['target']
        a = r['achieved']
        state = r['action']
        
        W1 = a['devices']['M1']['W'] * 1e6
        L1 = a['devices']['M1']['L'] * 1e6
        W3 = a['devices']['M3']['W'] * 1e6
        L3 = a['devices']['M3']['L'] * 1e6
        Itail = state[4] * 1e6
        
        md += f"| {r['name'].replace('.json','')} | {t['Gain_min']:.1f}/**{a['DC_Gain_dB']:.1f}** | {t['GBW_min']/1e6:.0f}M/**{a['GBW']/1e6:.0f}M** | {t['CL_pF']}p | {t['Power_max']*1e6:.0f}/**{a['Power']*1e6:.0f}** | {W1:.2f}/{L1:.2f} | {W3:.2f}/{L3:.2f} | {Itail:.1f} |\n"
        
    with open(os.path.join('Evaluation_Results', 'v11_evaluation_results.md'), 'w') as f:
        f.write(md)
    print("\nSaved results to Evaluation_Results/v11_evaluation_results.md")

if __name__ == "__main__":
    test_v11_model()
