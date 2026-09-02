import os
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from stable_baselines3 import PPO

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.cost_function import CostFunction
from optimizer.rl_environment import OTA5tGymEnv

def main():
    print("1. Loading LUTs and Environment...")
    nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
    pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
    
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    ota.Vicm = 0.5
    
    # Let's say we change the specs slightly
    new_specs = {
        'Gain_min': 32.0,
        'GBW_min': 180e6,
        'PM_min': 60.0,
        'Power_max': 280e-6,
        'SR_min': 60e6,
        'Swing_min': 0.8,
        'ICMR_max': 0.5,
        'Sat_margin_min': 0.05
    }
    
    cost_fn = CostFunction(new_specs, penalty_weight=1e4)
    bounds = [
        (60e-9, 1.0e-6), (5.0, 25.0), (60e-9, 1.0e-6), 
        (5.0, 25.0), (60e-9, 1.0e-6), (5.0, 25.0), (10e-6, 500e-6)
    ]
    
    env = OTA5tGymEnv(ota, cost_fn, bounds, max_steps=200)
    
    print("2. Loading Trained AI Model (ppo_ota_agent.zip)...")
    # This is how you load a saved model!
    model = PPO.load("ppo_ota_agent")
    
    print("3. Running Inference (0.01 seconds)...")
    obs, info = env.reset()
    
    # We let the AI take a few steps to adjust the circuit to the new specs
    for _ in range(20):
        # deterministic=True means the AI takes its best guess without random exploration
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            break
            
    # Print the final result it reached
    perf = ota.evaluate(env.state)
    print(f"\nAI Final Output:")
    print(f"Gain: {perf['DC_Gain_dB']:.1f} dB, GBW: {perf['GBW']/1e6:.1f} MHz, Power: {perf['Power']*1e6:.1f} uW")

if __name__ == '__main__':
    main()
