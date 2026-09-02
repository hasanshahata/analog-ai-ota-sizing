import json

notebook = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Goal-Conditioned Analog AI Sizing (V9) - Kaggle Version\n",
    "V9 Features (Architecture Fix):\n",
    "- Rich 15D Observation: design params + performance + targets\n",
    "- Direct Parameter Output (no delta-based movement)\n",
    "- Absolute Normalized Reward (no delta-based reward)\n",
    "- V8 Hierarchy of Needs cost function preserved\n",
    "- Training: 500,000 steps\n",
    "\n",
    "## Setup Instructions\n",
    "1. **Upload Code:** Upload the `analog-ai-code-v9.zip` (from the V9_Trainer folder) as a Kaggle Dataset.\n",
    "2. **Google Drive Quota Fix:** Make sure your LUT Google Drive IDs are correct.\n",
    "3. Click **Save Version -> Save & Run All (Commit)**."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "!pip install stable-baselines3[extra] gymnasium numpy scipy tensorboard gdown"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import os\n",
    "import sys\n",
    "\n",
    "WORKING_DIR = '/kaggle/working/'\n",
    "os.makedirs('/kaggle/working/tech_luts', exist_ok=True)\n",
    "os.chdir('/kaggle/working/tech_luts')\n",
    "\n",
    "# --- PASTE YOUR NEW GOOGLE DRIVE FILE IDs HERE ---\n",
    "NCH_FILE_ID = '10YDQaHxinCaGA3ayCe0LMTS_mCYx4mkA'\n",
    "PCH_FILE_ID = '1oEEmU5b3nJONe9dolYPGp8w9DacyU8Qf'\n",
    "\n",
    "print(\"Downloading NCH LUT...\")\n",
    "!gdown --id {NCH_FILE_ID} -O TSMC_fast_65nm_nch.pkl\n",
    "\n",
    "print(\"Downloading PCH LUT...\")\n",
    "!gdown --id {PCH_FILE_ID} -O TSMC_fast_65nm_pch.pkl\n",
    "\n",
    "os.chdir('/kaggle/working/')\n",
    "print(\"Download Complete!\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# Smart Script: Automatically find the code dataset\n",
    "project_found = False\n",
    "for root, dirs, files in os.walk('/kaggle/input/'):\n",
    "    if 'circuits' in dirs and 'core' in dirs:\n",
    "        print(f\"Found project root at: {root}\")\n",
    "        sys.path.append(root)\n",
    "        project_found = True\n",
    "        break\n",
    "\n",
    "if not project_found:\n",
    "    print(\"ERROR: Project folders not found in Kaggle input!\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "from tech_luts.lut_utils import LUT\n",
    "from core.device_model import DeviceModel\n",
    "from circuits.ota5t import OTA5T\n",
    "from optimizer.rl_environment import OTA5tGymEnv\n",
    "\n",
    "print(\"Loading LUTs into memory...\")\n",
    "nch_path = '/kaggle/working/tech_luts/TSMC_fast_65nm_nch.pkl'\n",
    "pch_path = '/kaggle/working/tech_luts/TSMC_fast_65nm_pch.pkl'\n",
    "\n",
    "nch = LUT(nch_path)\n",
    "pch = LUT(pch_path)\n",
    "\n",
    "dm = DeviceModel(nch, pch)\n",
    "ota = OTA5T(dm, vdd=1.2)\n",
    "print(\"Physics Engine Ready!\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "bounds = [\n",
    "    (60e-9, 1.5e-6),  # L1\n",
    "    (5.0, 25.0),      # gmid1\n",
    "    (60e-9, 1.5e-6),  # L3\n",
    "    (5.0, 25.0),      # gmid3\n",
    "    (10e-6, 500e-6)   # Itail\n",
    "]\n",
    "\n",
    "env = OTA5tGymEnv(ota, bounds=bounds, max_steps=200)\n",
    "\n",
    "from stable_baselines3 import PPO\n",
    "from stable_baselines3.common.callbacks import CheckpointCallback\n",
    "\n",
    "checkpoint_callback = CheckpointCallback(\n",
    "    save_freq=100000, \n",
    "    save_path=os.path.join(WORKING_DIR, 'checkpoints'),\n",
    "    name_prefix='kaggle_ppo_model_v9'\n",
    ")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "tb_log_dir = os.path.join(WORKING_DIR, 'ppo_ota_tensorboard')\n",
    "\n",
    "# V9: Larger network (256x256) to handle the richer 15D observation space.\n",
    "# Lower learning rate for stability with direct parameter output.\n",
    "policy_kwargs = dict(net_arch=[256, 256])\n",
    "model = PPO(\"MlpPolicy\", env, verbose=1, learning_rate=0.0001, batch_size=512, n_steps=2048, policy_kwargs=policy_kwargs, tensorboard_log=tb_log_dir)\n",
    "\n",
    "print(\"Starting 500,000 Steps Training on Kaggle (V9 - Architecture Fix)...\")\n",
    "model.learn(total_timesteps=500000, callback=checkpoint_callback)\n",
    "\n",
    "final_model_path = os.path.join(WORKING_DIR, 'universal_ppo_agent_65nm_v9')\n",
    "model.save(final_model_path)\n",
    "print(f\"Training Complete! Model saved to {final_model_path}.zip\")"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.10.12"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}

with open('../V9_Trainer/Kaggle_Analog_RL_Trainer.ipynb', 'w') as f:
    json.dump(notebook, f, indent=1)

print("V9 notebook built successfully!")
