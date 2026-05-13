import os
import platform
import shutil
import tarfile
import json
import requests
import re
import time
import subprocess
from pathlib import Path
from tor_launcher import get_paths, generate_torrc, run_tor, PROJECT_FOLDER

PROXY_PORT = 9750
UPDATE_URL = "https://www.torproject.org/download/tor/"
TOR_LATEST_DIR = PROJECT_FOLDER / "tor_latest"
BACKUP_DIR = PROJECT_FOLDER / "backup"

def get_system_info():
    os_name = platform.system().lower()
    arch = platform.machine().lower()
    
    if "windows" in os_name:
        os_name = "windows"
    elif "linux" in os_name:
        os_name = "linux"
    elif "darwin" in os_name:
        os_name = "macos"
    
    if arch in ["x86_64", "amd64"]:
        arch = "x86_64"
    elif arch in ["i386", "i686"]:
        arch = "i686"
    elif arch in ["aarch64", "arm64"]:
        arch = "aarch64"
        
    return os_name, arch

def get_bridges():
    return ["webtunnel [2001:db8:cf6:ce7:c7fc:5a42:72d5:8c8b]:443 D0A1F802127A925F47A7C9713F17A9E1D1292E54 url=https://cdn-131.airstrip1.net/4c5d6e7f8g9h0i1j2k3l4m5n ver=0.0.2", 
            "webtunnel [2001:db8:50c6:f177:293a:6612:f682:feb0]:443 6736F1245C77FBDCE4252F5711DE3137A7C10125 url=https://www.itssohotrightnow.com/0bc106e5688f206329e24a350b084c43 ver=0.0.4", 
            "webtunnel [2001:db8:1ecc:edad:a642:10d8:adc1:c886]:443 C2176476CDD39DFAB550BBC94E1DF3980398E5FC url=https://mstdn.plus/Lohguu6eequaethu ver=0.0.2"]

def parse_download_url(html_content, os_name, arch, channel):
    links = re.findall(r'href="(https://[^"]+tor-expert-bundle-[^"]+\.tar\.gz)"', html_content)
    target_pattern = f"tor-expert-bundle-{os_name}-{arch}"
    filtered_links = [l for l in links if target_pattern in l]
    
    if not filtered_links:
        print(f"No links found for {target_pattern}")
        return None
        
    if channel == "alpha":
        result = [l for l in filtered_links if "a" in l.split('/')[-2]]
    else:
        result = [l for l in filtered_links if "a" not in l.split('/')[-2]]
        
    return result[0] if result else filtered_links[0]

def download_file(url, session):
    local_filename = PROJECT_FOLDER / url.split('/')[-1]
    print(f"Downloading {url}...")
    with session.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename

def update_tor():
    os_name, arch = get_system_info()
    print(f"System detected: {os_name} ({arch})")
    
    channel = input("Choose channel (stable/alpha) [default: stable]: ").strip().lower() or "stable"
    
    base_dir = PROJECT_FOLDER
    update_info_path = PROJECT_FOLDER / "update_info.json"
    if update_info_path.exists():
        try:
            with open(update_info_path, 'r') as f:
                info = json.load(f)
                folder_name = info.get('use_folder')
                if folder_name and (PROJECT_FOLDER / folder_name).exists():
                    base_dir = PROJECT_FOLDER / folder_name
                    print(f"Using folder: {folder_name}")
        except Exception:
            pass

    paths = get_paths(base_dir)
    if not paths['tor_exe'].exists():
        paths = get_paths(PROJECT_FOLDER)
        if not paths['tor_exe'].exists():
            print(f"Error: Tor executable not found at {paths['tor_exe']}")
            return

    config = {
        'port': PROXY_PORT,
        'bridges': get_bridges(),
        'countries': None
    }
    
    torrc_path = generate_torrc(config, paths)
    
    env = os.environ.copy()
    if platform.system().lower() != "windows":
        lib_path = str(paths['tor_exe'].parent)
        if 'LD_LIBRARY_PATH' in env:
            env['LD_LIBRARY_PATH'] = f"{lib_path}:{env['LD_LIBRARY_PATH']}"
        else:
            env['LD_LIBRARY_PATH'] = lib_path
        os.chmod(paths['tor_exe'], 0o755)
        if paths['lyrebird_exe'].exists():
            os.chmod(paths['lyrebird_exe'], 0o755)

    tor_process = subprocess.Popen(
        [str(paths['tor_exe']), "-f", str(torrc_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        env=env
    )
    
    print("Waiting for Tor to bootstrap...")
    bootstrapped = False
    start_time = time.time()
    timeout = 360
    
    while True:
        line = tor_process.stdout.readline()
        if not line:
            break
        print(line, end="")
        if "Bootstrapped 100%" in line:
            bootstrapped = True
            break
        if time.time() - start_time > timeout:
            print("\nTimeout waiting for Tor to bootstrap.")
            break
            
    if not bootstrapped:
        print("Tor failed to bootstrap.")
        tor_process.terminate()
        return
    
    print("\nTor is ready. Fetching download page...")
    
    proxies = {
        'http': f'socks5h://127.0.0.1:{PROXY_PORT}',
        'https': f'socks5h://127.0.0.1:{PROXY_PORT}'
    }
    
    session = requests.Session()
    session.proxies = proxies
    
    try:
        response = session.get(UPDATE_URL)
        response.raise_for_status()
        html_content = response.text
        
        download_url = parse_download_url(html_content, os_name, arch, channel)
        if not download_url:
            print("Could not find download URL.")
            tor_process.terminate()
            return
            
        archive_path = download_file(download_url, session)
        print(f"Downloaded to {archive_path}")
    except Exception as e:
        print(f"Operation failed: {e}")
        tor_process.terminate()
        return

    print("Stopping temporary Tor...")
    tor_process.terminate()
    tor_process.wait()

    print("Updating folders...")
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    
    if TOR_LATEST_DIR.exists():
        shutil.move(TOR_LATEST_DIR, BACKUP_DIR)
    else:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for d in ['tor', 'data', 'docs']:
            src = PROJECT_FOLDER / d
            if src.exists():
                shutil.move(src, BACKUP_DIR / d)

    TOR_LATEST_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Unpacking {archive_path} to {TOR_LATEST_DIR}...")
    with tarfile.open(archive_path, "r:gz") as tar:
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(path=TOR_LATEST_DIR, filter='data')
        else:
            tar.extractall(path=TOR_LATEST_DIR)
    
    os.remove(archive_path)
    print("Update complete.")
    
    with open(PROJECT_FOLDER / "update_info.json", 'w') as f:
        json.dump({'use_folder': 'backup'}, f)

if __name__ == "__main__":
    update_tor()
