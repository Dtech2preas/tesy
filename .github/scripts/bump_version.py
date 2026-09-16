import json
import re
import sys
import os

def bump_version(version_str, bump_type):
    parts = version_str.split('.')
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0

    if bump_type == 'major':
        major += 1
        minor = 0
        patch = 0
    elif bump_type == 'minor':
        minor += 1
        patch = 0
    else:  # patch
        patch += 1

    return f"{major}.{minor}.{patch}"

def main():
    commit_msg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('COMMIT_MSG', '')
    bump_type = 'patch'
    if '#major' in commit_msg.lower():
        bump_type = 'major'
    elif '#minor' in commit_msg.lower():
        bump_type = 'minor'
    elif '#patch' in commit_msg.lower():
        bump_type = 'patch'

    try:
        with open('package.json', 'r') as f:
            pkg = json.load(f)
        old_version = pkg.get('version', '1.0.0')
    except Exception:
        old_version = '1.0.0'
        pkg = {}

    new_version = bump_version(old_version, bump_type)
    pkg['version'] = new_version

    with open('package.json', 'w') as f:
        json.dump(pkg, f, indent=2)
        f.write('\n')

    gradle_path = 'app/build.gradle'
    if os.path.exists(gradle_path):
        with open(gradle_path, 'r') as f:
            gradle_content = f.read()

        def increment_version_code(match):
            old_code = int(match.group(1))
            return f"versionCode {old_code + 1}"

        gradle_content = re.sub(r'versionCode\s+(\d+)', increment_version_code, gradle_content)
        gradle_content = re.sub(r'versionName\s+".*?"', f'versionName "{new_version}"', gradle_content)

        with open(gradle_path, 'w') as f:
            f.write(gradle_content)

    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f"new_version={new_version}\n")
            f.write(f"old_version={old_version}\n")
    print(f"Bumped version from {old_version} to {new_version}")

if __name__ == "__main__":
    main()
