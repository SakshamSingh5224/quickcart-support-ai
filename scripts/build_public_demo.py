"""Build a publishable demo from an allowlist; never copy the user's CSVs.

Example: python -m scripts.build_public_demo --output ~/Desktop/quickcart-public-demo
"""
from pathlib import Path
import argparse
import shutil
from scripts.generate_demo_data import generate
from scripts.check_demo_safety import check

ROOT=Path(__file__).resolve().parents[1]
FILES=[
    'app.py','policy_engine.py','policy_audit.py','conversation.py','ticket_store.py',
    'auth_store.py','access_control.py','analytics.py','dashboard_ui.py','requirements.txt',
    '.gitignore','.streamlit/config.toml','DEMO_DATA_ONLY.md','PHASE_2E_NOTES.md',
    'scripts/__init__.py','scripts/manage_users.py','scripts/generate_demo_data.py',
    'scripts/check_demo_safety.py','scripts/build_public_demo.py',
    '.github/workflows/ci.yml','pytest.ini',
]


def build(dest):
    dest=Path(dest).resolve()
    if dest == ROOT or ROOT in dest.parents:
        raise ValueError('Demo output must be outside the private project directory.')
    if dest.exists() and any(dest.iterdir()):
        raise ValueError('Demo destination must be new or empty; refusing to overwrite user files.')
    dest.mkdir(parents=True,exist_ok=True)
    for filename in FILES:
        source=ROOT/filename
        target=dest/filename
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    for test_file in sorted((ROOT/'tests').glob('test_*.py')):
        target=dest/'tests'/test_file.name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(test_file,target)
    safe_readme = ROOT/'README_PUBLIC.md'
    shutil.copyfile(safe_readme if safe_readme.exists() else ROOT/'README.md', dest/'README.md')
    generate(dest/'data')
    check(dest)
    return dest


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print('Created synthetic demo:',build(args.output))
