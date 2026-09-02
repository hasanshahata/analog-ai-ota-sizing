import os
import numpy as np

# Suppress some verbose TF/Gym warnings
import warnings
warnings.filterwarnings('ignore')

from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env

from tech_luts.lut_utils import LUT
from core.device_model import DeviceModel
from circuits.ota5t import OTA5T
from optimizer.cost_function import CostFunction
from optimizer.rl_environment import OTA5tGymEnv

def main():
    print("1. Loading TSMC 65nm LUTs...")
    nch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_nch.pkl'))
    pch = LUT(os.path.join('tech_luts', 'TSMC_fast_65nm_pch.pkl'))
    
    dm = DeviceModel(nch, pch)
    ota = OTA5T(dm, vdd=1.2, cl=1e-12)
    ota.Vicm = 0.5
    
    # We use new, harder targets to test the RL's learning capability!
    new_specs = {
        'Gain_min': 35.0,        # Increased from 30
        'GBW_min': 200e6,        # Increased from 150M
        'PM_min': 60.0,
        'Power_max': 250e-6,     # Stricter power (was 300uW)
        'SR_min': 60e6,          # Increased from 50M
        'Swing_min': 0.8,
        'ICMR_max': 0.5,
        'Sat_margin_min': 0.05
    }
    
    print("\n2. Target RL Specifications:")
    for k, v in new_specs.items():
        print(f"   {k}: {v}")
        
    cost_fn = CostFunction(new_specs, penalty_weight=1e4)
    
    # Action bounds (same physical sizing bounds)
    bounds = [
        (60e-9, 1.0e-6),  # L1
        (5.0, 25.0),      # gmid1
        (60e-9, 1.0e-6),  # L3
        (5.0, 25.0),      # gmid3
        (60e-9, 1.0e-6),  # L5
        (5.0, 25.0),      # gmid5
        (10e-6, 500e-6)   # Itail
    ]
    
    # Initialize the Gym Environment
    env = OTA5tGymEnv(ota, cost_fn, bounds, max_steps=200)
    
    # It's good practice to check if the environment follows Gym API
    check_env(env)
    
    print("\n3. Initializing PPO Agent...")
    # Proximal Policy Optimization (PPO) is the industry standard for continuous control
    model = PPO("MlpPolicy", env, verbose=1, learning_rate=0.001)
    
    print("\n4. Starting Training (Training for 10,000 steps)...")
    # In a real scenario, you might train for 1M+ steps, but 10k is enough for a quick demonstration
    model.learn(total_timesteps=10000)
    
    # Save the model
    model.save("ppo_ota_agent")
    print("Model saved to ppo_ota_agent.zip")
    
    print("\n5. Testing the Trained Agent...")
    obs, info = env.reset()
    total_reward = 0
    best_perf = None
    best_cost = np.inf
    best_state = env.state.copy()
    
    for i in range(100):
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        
        # Track the best configuration found during testing
        if env.current_cost < best_cost:
            best_cost = env.current_cost
            best_state = env.state.copy()
            # Try evaluating to get full perf dict
            try:
                best_perf = ota.evaluate(best_state)
            except Exception:
                pass
                
        if terminated or truncated:
            break
            
    print(f"\n--- RL AGENT TEST RESULTS ---")
    print(f"Final Episode Reward: {total_reward:.2f}")
    
    if best_perf:
        print(f"Best Cost Reached: {best_cost:.2f}")
        print(f"DC Gain: {best_perf['DC_Gain_dB']:.2f} dB")
        print(f"GBW: {best_perf['GBW']/1e6:.2f} MHz")
        print(f"Phase Margin: {best_perf['PM']:.2f} deg")
        print(f"Power: {best_perf['Power']*1e6:.2f} uW")
        
        m1 = best_perf['devices']['M1']
        m3 = best_perf['devices']['M3']
        itail = best_perf['devices']['M5']['ID']
        
        print("\n--- SIZED DEVICES (RL) ---")
        print(f"W12   = {m1['W']*1e6:.2f} um")
        print(f"L12   = {m1['L']*1e6:.3f} um")
        print(f"W34   = {m3['W']*1e6:.2f} um")
        print(f"L34   = {m3['L']*1e6:.3f} um")
        print(f"Itail = {itail*1e6:.2f} uA")
    else:
        print("Agent failed to find a valid operating point during testing.")

if __name__ == '__main__':
    main()
