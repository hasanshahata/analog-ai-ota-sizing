import os
import zipfile

def zip_project(output_filename):
    directories_to_zip = ['core', 'circuits', 'optimizer', 'tech_luts']
    
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for directory in directories_to_zip:
            for root, _, files in os.walk(directory):
                for file in files:
                    # Skip massive LUT files
                    if file.endswith('.pkl'):
                        continue
                    if file.endswith('.pyc') or '__pycache__' in root:
                        continue
                        
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, arcname=file_path)
                    print(f"Added {file_path}")

if __name__ == '__main__':
    zip_project('analog-ai-code-v12.zip')
