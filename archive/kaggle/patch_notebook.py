import json

with open('V2_Trainer/Kaggle_Analog_RL_Trainer.ipynb', 'r') as f:
    nb = json.load(f)

smart_script = [
    'import sys\n',
    'import os\n',
    '\n',
    '# --- SMART KAGGLE SETUP ---\n',
    'print("Searching for project root in Kaggle input...")\n',
    'project_root = None\n',
    'for root, dirs, files in os.walk("/kaggle/input"):\n',
    '    if "core" in dirs and "circuits" in dirs and "optimizer" in dirs:\n',
    '        project_root = root\n',
    '        break\n',
    '\n',
    'if project_root:\n',
    '    print(f"Found project root at: {project_root}")\n',
    '    if project_root not in sys.path:\n',
    '        sys.path.append(project_root)\n',
    'else:\n',
    '    print("WARNING: Could not find project root. Check dataset structure.")\n',
    '\n',
    'WORKING_DIR = "/kaggle/working/"\n'
]

for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        source = ''.join(cell['source'])
        if 'sys.path.append(PROJECT_PATH)' in source:
            cell['source'] = smart_script
            break

with open('V2_Trainer/Kaggle_Analog_RL_Trainer.ipynb', 'w') as f:
    json.dump(nb, f, indent=1)
