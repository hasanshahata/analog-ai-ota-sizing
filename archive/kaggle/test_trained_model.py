import os
import numpy as np
from stable_baselines3 import PPO
from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.rl_environment import OTA5tGymEnv

def main():
    print("1. Loading Physics Engine (LUTs)...")
    # Make sure you have the heavy .pkl files back in the tech_luts folder or adjust the path!
    nch_path = 'tech_luts/TSMC_fast_65nm_nch.pkl'
    pch_path = 'tech_luts/TSMC_fast_65nm_pch.pkl'
    
    if not os.path.exists(nch_path) or not os.path.exists(pch_path):
        print(f"ERROR: Cannot find {nch_path} or {pch_path}.")
        print("Please move the 5.5GB .pkl files back into the 'tech_luts' folder first!")
        return

    nch = LUT(nch_path)
    pch = LUT(pch_path)
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    ota.Vicm = 0.5
    
    print("2. Setting up the RL Environment...")
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    env = OTA5tGymEnv(ota, bounds=bounds, max_steps=200)
    
    print("3. Loading the Universal AI Model...")
    model_path = 'universal_ppo_agent_65nm.zip'
    if not os.path.exists(model_path):
        print(f"ERROR: Cannot find {model_path}.")
        return
        
    model = PPO.load(model_path, env=env)
    
    # ---------------------------------------------------------
    # Let's test the AI with a very hard custom target specification
    # ---------------------------------------------------------
    custom_target = {
        'Gain_min': 40.0,       # High Gain
        'GBW_min': 200e6,       # High Speed (200 MHz)
        'PM_min': 60.0,         # Stable
        'Power_max': 150e-6,    # Low Power (< 150uW)
        'SR_min': 50e6,         # Good Slew Rate
        'Swing_min': 0.8,       # Good Voltage Swing
        'ICMR_max': 0.4,        # Good ICMR
        'Sat_margin_min': 0.05
    }
    
    print("\n--- AI Target Specs ---")
    for k, v in custom_target.items():
        print(f"{k}: {v}")
    
    # Reset env and force the custom target
    obs, _ = env.reset()
    env.target_specs = custom_target
    
    # Re-normalize observation with our custom targets
    perf = ota.evaluate(env.state)
    obs = env._normalize_state(perf)
    
    print("\n4. AI is Thinking (Optimizing Circuit)...")
    
    # Let the AI interact for 100 steps to reach the target
    # Because it's a trained policy, it usually converges in < 50 steps
    for step in range(100):
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        
        if terminated:
            print(f"Target achieved at step {step}!")
            break
            
    # Print the Final Performance!
    final_perf = ota.evaluate(env.state)
    print("\n--- Final Achieved Specs ---")
    print(f"Gain:  {final_perf['DC_Gain_dB']:.2f} dB (Target: > {custom_target['Gain_min']} dB)")
    print(f"GBW:   {final_perf['GBW']/1e6:.2f} MHz (Target: > {custom_target['GBW_min']/1e6} MHz)")
    print(f"PM:    {final_perf['PM']:.2f} Deg (Target: > {custom_target['PM_min']} Deg)")
    print(f"Power: {final_perf['Power']*1e6:.2f} uW (Target: < {custom_target['Power_max']*1e6} uW)")
    print(f"SR:    {final_perf['SR']/1e6:.2f} V/us (Target: > {custom_target['SR_min']/1e6} V/us)")
    print(f"Swing: {final_perf['Swing']:.2f} V (Target: > {custom_target['Swing_min']} V)")
    print(f"ICMR:  {final_perf['ICMR_min']:.2f} V (Target: < {custom_target['ICMR_max']} V)")
    
    # Print the Final Sizes (W, L, Itail)
    print("\n--- AI Generated Circuit Sizing ---")
    L1, gmid1, L3, gmid3, L5, gmid5, Itail = env.state
    # Re-calculate W internally from gmid
    # Just print the parameters the optimizer decided:
    print(f"Itail = {Itail*1e6:.2f} uA")
    print(f"Diff Pair (M1,M2): L = {L1*1e9:.1f} nm, gm/Id = {gmid1:.2f}")
    print(f"Current Mirror (M3,M4): L = {L3*1e9:.1f} nm, gm/Id = {gmid3:.2f}")
    print(f"Tail Current (M5): L = {L5*1e9:.1f} nm, gm/Id = {gmid5:.2f}")

if __name__ == '__main__':
    main()
