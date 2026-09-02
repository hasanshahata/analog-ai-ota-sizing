import os
import zipfile

def zip_project(output_path, target_dir):
    # Files and extensions to completely ignore
    ignore_exts = ['.pkl', '.zip']
    ignore_files = ['zip_for_kaggle.py']
    ignore_dirs = ['.git', '__pycache__', '.pytest_cache', '.ipynb_checkpoints']

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(target_dir):
            # Ignore specific directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for file in files:
                # Ignore specific file types
                if any(file.endswith(ext) for ext in ignore_exts) or file in ignore_files or file.startswith('.'):
                    continue
                    
                file_path = os.path.join(root, file)
                # Ensure the zip structure starts from the root of the project
                arcname = os.path.relpath(file_path, target_dir)
                zipf.write(file_path, arcname)

if __name__ == '__main__':
    zip_project('analog-ai-code.zip', '.')
    print("Success: analog-ai-code.zip has been created!")
