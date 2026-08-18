#!/usr/bin/env python3
# Copyright 2014 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helper for the Build Flutter Engine GitHub Actions workflow."""

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
source_dir = os.environ.get('ENGINE_SOURCE_DIR')
REPO_ROOT = os.path.abspath(source_dir) if source_dir else WORKFLOW_ROOT
ENGINE_SRC = os.path.join(REPO_ROOT, 'engine', 'src')
THIRD_PARTY_ROOT = os.path.join(ENGINE_SRC, 'third_party')
PATCHES_DIR = os.path.join(WORKFLOW_ROOT, '.github', 'patches')
VC_LTL_URL = (
    'https://github.com/Chuyu-Team/VC-LTL5/releases/download/'
    'v5.3.1/VC-LTL-Binary.7z'
)
YY_THUNKS_URL = (
    'https://github.com/Chuyu-Team/YY-Thunks/releases/download/'
    'v1.2.2/YY-Thunks-Objs.zip'
)


def env_value(name, default):
    value = os.environ.get(name)
    return value.strip() if value else default


def host_os():
    if sys.platform.startswith('win'):
        return 'windows'
    if sys.platform == 'darwin':
        return 'macos'
    return 'linux'


def machine():
    return platform.machine().lower()


def run(cmd, cwd):
    print('+ %s' % subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def git_apply_check(patch, reverse=False, ignore_whitespace=False):
    args = ['git', 'apply', '--check']
    if reverse:
        args.append('--reverse')
    if ignore_whitespace:
        args.append('--ignore-whitespace')
    args.append(patch)
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True)


def apply_build_patch(patch):
    if git_apply_check(patch).returncode == 0:
        run(['git', 'apply', patch], REPO_ROOT)
        return
    if git_apply_check(patch, reverse=True).returncode == 0:
        print('%s already applied; skipping.' % os.path.basename(patch), flush=True)
        return
    if git_apply_check(patch, ignore_whitespace=True).returncode == 0:
        run(['git', 'apply', '--ignore-whitespace', patch], REPO_ROOT)
        return
    if git_apply_check(patch, reverse=True, ignore_whitespace=True).returncode == 0:
        print('%s already applied; skipping.' % os.path.basename(patch), flush=True)
        return
    raise SystemExit(
        'Unable to apply %s to the selected ref. The ref must contain a '
        'matching target file.' % os.path.basename(patch)
    )


def apply_build_patches():
    if host_os() != 'windows':
        return
    patches = sorted(
        os.path.join(PATCHES_DIR, name)
        for name in os.listdir(PATCHES_DIR)
        if name.endswith('.patch')
    )
    if not patches:
        raise SystemExit('No build patches found in %s' % PATCHES_DIR)
    for patch in patches:
        apply_build_patch(patch)


def repo_url():
    url = os.environ.get('ENGINE_REPO_URL')
    if url:
        return url
    repository = os.environ.get('GITHUB_REPOSITORY')
    if repository:
        return 'https://github.com/%s.git' % repository
    return 'https://github.com/flutter/flutter.git'


def download(url, dest):
    print('+ download %s -> %s' % (url, dest), flush=True)
    request = urllib.request.Request(
        url, headers={'User-Agent': 'flutter-engine-gha'}
    )
    with urllib.request.urlopen(request) as response, open(dest, 'wb') as f:
        shutil.copyfileobj(response, f)


def find_7z():
    candidates = [
        shutil.which('7z'),
        r'C:\Program Files\7-Zip\7z.exe',
        r'C:\Program Files (x86)\7-Zip\7z.exe',
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise SystemExit('7z.exe not found; install 7-Zip or add it to PATH')


def extract_7z(archive, dest):
    os.makedirs(dest, exist_ok=True)
    run([find_7z(), 'x', '-y', '-o%s' % dest, archive], REPO_ROOT)


def extract_zip(archive, dest):
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(archive) as archive_file:
        archive_file.extractall(dest)


def prepare_third_party():
    if host_os() != 'windows':
        return
    archive_dir = os.path.join(THIRD_PARTY_ROOT, 'downloads')
    os.makedirs(archive_dir, exist_ok=True)
    vc_archive = os.path.join(archive_dir, 'VC-LTL-Binary.7z')
    yy_archive = os.path.join(archive_dir, 'YY-Thunks-Objs.zip')
    vc_root = os.path.join(THIRD_PARTY_ROOT, 'VC-LTL-Binary')
    yy_root = os.path.join(THIRD_PARTY_ROOT, 'YY-Thunks-Objs')
    if not os.path.isfile(os.path.join(vc_root, '_msvcrt.h')):
        if not os.path.isfile(vc_archive):
            download(VC_LTL_URL, vc_archive)
        extract_7z(vc_archive, vc_root)
    if not os.path.isfile(
        os.path.join(yy_root, 'objs', 'x64', 'YY_Thunks_for_Win7.obj')
    ):
        if not os.path.isfile(yy_archive):
            download(YY_THUNKS_URL, yy_archive)
        extract_zip(yy_archive, yy_root)


def write_gclient(target):
    custom_vars = {
        'download_android_deps': target == 'android',
        'download_emsdk': False,
        'download_esbuild': False,
        'download_fuchsia_deps': False,
        'download_jdk': target == 'android',
        'setup_githooks': False,
    }
    lines = [
        'solutions = [',
        '  {',
        "    'deps_file': 'DEPS',",
        '    "managed": False,',
        "    'name': '.',",
        "    'safesync_url': '',",
        "    'url': '%s'," % repo_url(),
        "    'custom_vars': {",
    ]
    for key, value in sorted(custom_vars.items()):
        lines.append("      '%s': %s," % (key, repr(value)))
    lines.extend([
        '    },',
        '  },',
        ']',
    ])
    with open(os.path.join(REPO_ROOT, '.gclient'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def sync():
    apply_build_patches()
    target = env_value('ENGINE_TARGET', 'host')
    write_gclient(target)
    if os.name == 'nt':
        cmd = ['cmd', '/c', 'gclient.bat', 'sync', '-D', '--no-history']
    else:
        cmd = ['gclient', 'sync', '-D', '--no-history']
    run(cmd, REPO_ROOT)


def effective_cpu(target, cpu, simulator):
    cpu = cpu or ''
    if target == 'android':
        return cpu or 'arm64'
    if target == 'ios':
        return (cpu or 'x64') if simulator else 'arm64'
    if target in ('macos', 'windows'):
        return cpu or ('arm64' if machine() in ('arm64', 'aarch64') else 'x64')
    if target == 'host':
        if host_os() == 'macos':
            return cpu or ('arm64' if machine() in ('arm64', 'aarch64') else 'x64')
        if host_os() == 'windows':
            return cpu or 'x64'
    return ''


def gn_args(target, runtime_mode, optimized, cpu, simulator):
    args = []
    if not optimized:
        args.append('--unoptimized')
    if runtime_mode != 'debug':
        args.extend(['--runtime-mode', runtime_mode])
    args.append('--no-lto')
    args.append('--no-enable-unittests')
    eff = effective_cpu(target, cpu, simulator)
    if target == 'host':
        if host_os() == 'macos':
            args.extend(['--mac-cpu', eff])
        elif host_os() == 'windows' and eff:
            args.extend(['--windows-cpu', eff])
    elif target == 'android':
        args.extend(['--android', '--android-cpu', eff])
    elif target == 'ios':
        args.append('--ios')
        if simulator:
            args.extend(['--simulator', '--simulator-cpu', eff])
    elif target == 'macos':
        args.extend(['--mac', '--mac-cpu', eff])
    elif target == 'windows':
        args.extend(['--windows-cpu', eff])
    else:
        raise SystemExit('Unknown target: %s' % target)
    return args


def config_label(target, runtime_mode, optimized, cpu, simulator):
    eff = effective_cpu(target, cpu, simulator)
    label = 'gha_%s' % target
    if target == 'ios' and simulator:
        label += '_sim'
    label += '_%s' % runtime_mode
    if not optimized:
        label += '_unopt'
    if eff:
        label += '_%s' % eff
    return label


def run_gn(label, args):
    gn_script = os.path.join('flutter', 'tools', 'gn')
    cmd = [sys.executable, gn_script, '--target-dir', label] + args
    run(cmd, ENGINE_SRC)


def run_ninja(label):
    run(['ninja', '-C', os.path.join('out', label)], ENGINE_SRC)


def build():
    apply_build_patches()
    prepare_third_party()
    target = env_value('ENGINE_TARGET', 'host')
    runtime_mode = env_value('ENGINE_RUNTIME_MODE', 'debug')
    optimized = env_value('ENGINE_OPTIMIZED', 'false') == 'true'
    cpu = env_value('ENGINE_CPU', '')
    simulator = env_value('ENGINE_SIMULATOR', 'false') == 'true'

    if target not in ('host', 'android', 'ios', 'macos', 'windows'):
        raise SystemExit('Unknown target: %s' % target)

    configs = []
    if target == 'host':
        configs.append(('host', cpu, simulator))
    elif target == 'android':
        configs.append(('android', cpu, simulator))
        configs.append(('host', '', False))
    elif target == 'ios':
        configs.append(('ios', cpu, simulator))
        configs.append(('host', '', False))
    elif target == 'macos':
        configs.append(('macos', cpu, simulator))
    elif target == 'windows':
        configs.append(('windows', cpu, simulator))
        configs.append(('host', '', False))

    labels = {}
    for key, config_cpu, config_simulator in configs:
        args = gn_args(key, runtime_mode, optimized, config_cpu, config_simulator)
        label = config_label(key, runtime_mode, optimized, config_cpu, config_simulator)
        labels[key] = label
        run_gn(label, args)

    for key, _, _ in configs:
        run_ninja(labels[key])


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'build'
    if command == 'sync':
        sync()
    elif command == 'build':
        build()
    else:
        raise SystemExit('Usage: build_engine.py <sync|build>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
