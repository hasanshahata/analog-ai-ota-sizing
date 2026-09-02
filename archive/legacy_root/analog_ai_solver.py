import os
import sys
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from stable_baselines3 import PPO

# Use V6 environment
sys.path.insert(0, 'V6_Trainer')
from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.rl_environment import OTA5tGymEnv

def main():
    print("========================================")
    print("      Analog AI Sizing Solver (V6)      ")
    print("========================================\n")
    
    try:
        gain_target = float(input("Enter Target Gain (dB) [e.g., 35]: "))
        gbw_target = float(input("Enter Target GBW (MHz) [e.g., 150]: ")) * 1e6
        cl_target = float(input("Enter Load Capacitance (pF) [e.g., 2]: "))
        power_target = float(input("Enter Max Power (uW) [e.g., 250]: ")) * 1e-6
    except ValueError:
        print("Invalid input. Please enter numbers only.")
        return
        
    specs = {
        'Gain_min': gain_target,
        'GBW_min': gbw_target,
        'CL_pF': cl_target,
        'Power_max': power_target
    }
    
    print("\nLoading Physics Engine (TSMC 65nm)...")
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
    
    env = OTA5tGymEnv(ota, bounds=bounds, max_steps=100)
    
    model_path = "universal_ppo_agent_65nm_v6.zip"
    # Fallback to V3 if V6 isn't downloaded yet
    if not os.path.exists(model_path):
        print(f"Warning: {model_path} not found. Falling back to V3 model for demonstration.")
        model_path = "universal_ppo_agent_65nm_v3.zip"
        
    print(f"Loading AI Model ({model_path})...")
    model = PPO.load(model_path)
    
    print("AI is solving for the optimal sizes...\n")
    
    env.target_specs = specs
    env.current_step = 0
    env.state = env._get_random_valid_state()
    env.current_cost, perf = env._evaluate_state(env.state)
    obs = env._normalize_state(perf)
    
    # Let AI optimize
    for _ in range(50):
        action, _ = model.predict(obs, deterministic=True)
        env.current_step += 1
        delta = action * (env.bounds[:, 1] - env.bounds[:, 0]) * 0.1
        new_state = np.clip(env.state + delta, env.bounds[:, 0], env.bounds[:, 1])
        new_cost, perf = env._evaluate_state(new_state)
        env.state = new_state
        env.current_cost = new_cost
        obs = env._normalize_state(perf)

    # Final Evaluation
    final_perf = ota.evaluate(env.state, CL=cl_target*1e-12)
    
    W1 = final_perf['devices']['M1']['W'] * 1e6
    L1 = final_perf['devices']['M1']['L'] * 1e6
    W3 = final_perf['devices']['M3']['W'] * 1e6
    L3 = final_perf['devices']['M3']['L'] * 1e6
    Itail = env.state[4] * 1e6
    
    print("========================================")
    print("             FINAL SIZINGS              ")
    print("========================================")
    print(f"Input Pair (M1/M2) Width  = {W1:.2f} um")
    print(f"Input Pair (M1/M2) Length = {L1:.2f} um")
    print(f"Load Mirror (M3/M4) Width = {W3:.2f} um")
    print(f"Load Mirror (M3/M4) Length= {L3:.2f} um")
    print(f"Tail Current (Itail)      = {Itail:.1f} uA")
    print("========================================")
    print("            ACHIEVED SPECS              ")
    print("========================================")
    print(f"Gain      : {final_perf['DC_Gain_dB']:.1f} dB (Target: {gain_target} dB)")
    print(f"GBW       : {final_perf['GBW']/1e6:.1f} MHz (Target: {gbw_target/1e6} MHz)")
    print(f"Power     : {final_perf['Power']*1e6:.1f} uW (Max: {power_target*1e6} uW)")
    print(f"Phase Marg: {final_perf['PM']:.1f} deg")
    print(f"Total Area: {final_perf['Area']*1e12:.1f} pm^2")
    print("========================================\n")

if __name__ == '__main__':
    main()
