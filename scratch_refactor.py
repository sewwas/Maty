import os
import re
import glob

def refactor_pickle_to_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replacements
    content = content.replace("import pickle", "import json")
    content = content.replace("pickle.load(", "json.load(")
    content = content.replace("pickle.dump(", "json.dump(")
    content = content.replace(".pkl", ".json")
    content = content.replace('open(state_path, "wb")', 'open(state_path, "w", encoding="utf-8")')
    content = content.replace('open(state_path, "rb")', 'open(state_path, "r", encoding="utf-8")')
    content = content.replace('open(STATE_PATH, "wb")', 'open(STATE_PATH, "w", encoding="utf-8")')
    content = content.replace('open(STATE_PATH, "rb")', 'open(STATE_PATH, "r", encoding="utf-8")')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def refactor_pass_in_except(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find `except Exception:` followed by `pass` with any indentation
    # We will replace `pass` with `import logging; logging.warning("Exception caught", exc_info=True)`
    
    def replacer(match):
        indentation = match.group(1)
        return f"except Exception as e:\n{indentation}import logging; logging.warning(f\"Exception: {{e}}\")"

    # Regex:
    # except Exception:
    #     pass
    pattern = re.compile(r'except Exception:\s*\n(\s*)pass')
    new_content = pattern.sub(replacer, content)

    # Some might be on the same line: `except Exception as e: import logging; logging.warning(f"Exception: {e}")`
    pattern2 = re.compile(r'except Exception:\s*pass')
    new_content = pattern2.sub(r'except Exception as e: import logging; logging.warning(f"Exception: {e}")', new_content)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

# Refactor pickle
for f in ["app.py", "portal_api.py"]:
    if os.path.exists(f):
        refactor_pickle_to_json(f)

# Refactor try...except
for root, _, files in os.walk('.'):
    if '.venv' in root or '__pycache__' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            refactor_pass_in_except(os.path.join(root, file))

print("Refactoring complete.")
