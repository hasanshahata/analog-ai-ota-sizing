import numpy as np
try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    gym = None

class OTA5tGymEnv(gym.Env):
    """
    Goal-Conditioned Gymnasium environment for RL agents.
    Agent learns to size the OTA to hit randomly sampled specifications.
    """
    def __init__(self, ota, bounds, max_steps=100):
        if gym is None:
            raise ImportError("gymnasium is required for the RL environment")
            
        self.ota = ota
        self.bounds = np.array(bounds)
        self.max_steps = max_steps
        
        # Action space: 7 parameters (L1, gmid1, L3, gmid3, L5, gmid5, Itail)
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(7,), dtype=np.float32)
        
        # Observation space: 8 (Current Perf) + 8 (Target Specs) = 16
        # Perf/Targets: [Gain, GBW, PM, Power, SR, Swing, ICMR, Sat_Margin]
        self.observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(16,), dtype=np.float32)
        
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost = self._evaluate_state(self.state)
        
    def _sample_target_specs(self):
        """Randomly sample achievable targets so the AI learns generalized physics."""
        # We define ranges for achievable targets in 65nm
        gain = np.random.uniform(20.0, 45.0)          # dB
        gbw = np.random.uniform(50e6, 300e6)          # Hz
        pm = np.random.uniform(50.0, 80.0)            # Degrees
        power = np.random.uniform(50e-6, 400e-6)      # Watts
        sr = np.random.uniform(20e6, 100e6)           # V/us
        swing = np.random.uniform(0.6, 1.0)           # V
        icmr = np.random.uniform(0.3, 0.6)            # V
        margin = 0.05                                 # 50mV fixed minimum
        
        return {
            'Gain_min': gain,
            'GBW_min': gbw,
            'PM_min': pm,
            'Power_max': power,
            'SR_min': sr,
            'Swing_min': swing,
            'ICMR_max': icmr,
            'Sat_margin_min': margin
        }
        
    def _calc_cost(self, perf):
        """Dynamic cost based on current targets."""
        if perf is None:
            return 1e9
            
        penalty = 0.0
        
        # Minimization goals (Penalty for falling short of min, or exceeding max)
        if perf['DC_Gain_dB'] < self.target_specs['Gain_min']:
            penalty += ((self.target_specs['Gain_min'] - perf['DC_Gain_dB']) / 10.0) ** 2
            
        if perf['GBW'] < self.target_specs['GBW_min']:
            penalty += ((self.target_specs['GBW_min'] - perf['GBW']) / 100e6) ** 2
            
        if perf['PM'] < self.target_specs['PM_min']:
            penalty += ((self.target_specs['PM_min'] - perf['PM']) / 10.0) ** 2
            
        if perf['Power'] > self.target_specs['Power_max']:
            penalty += ((perf['Power'] - self.target_specs['Power_max']) / 100e-6) ** 2
            
        if perf['SR'] < self.target_specs['SR_min']:
            penalty += ((self.target_specs['SR_min'] - perf['SR']) / 10e6) ** 2
            
        if perf['Swing'] < self.target_specs['Swing_min']:
            penalty += ((self.target_specs['Swing_min'] - perf['Swing']) / 0.1) ** 2
            
        if perf['ICMR_min'] > self.target_specs['ICMR_max']:
            penalty += ((perf['ICMR_min'] - self.target_specs['ICMR_max']) / 0.1) ** 2
            
        if perf['min_sat_margin'] < self.target_specs['Sat_margin_min']:
            penalty += ((self.target_specs['Sat_margin_min'] - perf['min_sat_margin']) / 0.01) ** 2
            
        # Reward reducing power even if constraints are met
        base_cost = perf['Power'] * 1e6
        
        return base_cost + (penalty * 1e4)

    def _get_random_valid_state(self):
        return np.random.uniform(self.bounds[:, 0], self.bounds[:, 1])
        
    def _evaluate_state(self, x):
        try:
            perf = self.ota.evaluate(x)
            return self._calc_cost(perf), perf
        except Exception:
            return 1e9, None
            
    def _normalize_state(self, perf):
        """Construct the 16-D Observation: [Current Perf] + [Target Specs]"""
        if perf is None:
            current = np.zeros(8, dtype=np.float32)
        else:
            current = np.array([
                perf['DC_Gain_dB'] / 40.0,
                perf['GBW'] / 1e8,
                perf['PM'] / 90.0,
                perf['Power'] / 300e-6,
                perf['SR'] / 5e7,
                perf['Swing'] / 1.0,
                perf['ICMR_min'] / 0.5,
                perf['min_sat_margin'] / 0.1
            ], dtype=np.float32)
            
        targets = np.array([
            self.target_specs['Gain_min'] / 40.0,
            self.target_specs['GBW_min'] / 1e8,
            self.target_specs['PM_min'] / 90.0,
            self.target_specs['Power_max'] / 300e-6,
            self.target_specs['SR_min'] / 5e7,
            self.target_specs['Swing_min'] / 1.0,
            self.target_specs['ICMR_max'] / 0.5,
            self.target_specs['Sat_margin_min'] / 0.1
        ], dtype=np.float32)
        
        return np.concatenate([current, targets])
        
    def reset(self, seed=None, options=None):
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._get_random_valid_state()
        self.current_cost, perf = self._evaluate_state(self.state)
        return self._normalize_state(perf), {}
        
    def step(self, action):
        self.current_step += 1
        
        # Action scales delta dynamically
        delta = action * (self.bounds[:, 1] - self.bounds[:, 0]) * 0.1
        new_state = np.clip(self.state + delta, self.bounds[:, 0], self.bounds[:, 1])
        
        new_cost, perf = self._evaluate_state(new_state)
        
        # Reward: Difference in cost
        reward = self.current_cost - new_cost
        
        self.state = new_state
        self.current_cost = new_cost
        
        # Terminate if cost is exceptionally low (e.g., all penalties 0 and power minimized)
        terminated = bool(new_cost < 50.0) 
        truncated = bool(self.current_step >= self.max_steps)
        
        return self._normalize_state(perf), reward, terminated, truncated, {}
