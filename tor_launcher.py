import os
import subprocess
import signal
import sys
import time
import argparse
import json
from pathlib import Path

PROJECT_FOLDER = Path(__file__).parent.absolute()

def get_paths(base_dir=PROJECT_FOLDER):
    base_path = Path(base_dir)
    ext = ".exe" if sys.platform == "win32" else ""
    return {
        'tor_exe': base_path / "backup" / "tor" / f"tor{ext}",
        'lyrebird_exe': base_path / "backup" / "tor" / "pluggable_transports" / f"lyrebird{ext}",
        'data_dir': base_path / "backup"  / "data",
        'geoip': base_path / "backup" / "data" / "geoip",
        'geoip6': base_path / "backup" / "data" / "geoip6",
        'torrc': base_path / "backup"  / "torrc"
    }

CONFIG_FILE = PROJECT_FOLDER / "tor_config.json"

LOG_LEVELS = {
    'notice': '[notice]',
    'warn': '[warn]',
    'err': '[err]'
}

def load_config(config_name=None):
    if not CONFIG_FILE.exists():
        return None
    
    with open(CONFIG_FILE, 'r') as f:
        configs = json.load(f)
    
    if config_name:
        return configs.get(config_name)
    return configs.get('default') if configs else None

def save_config(config_name, config_data):
    configs = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            configs = json.load(f)
    
    configs[config_name] = config_data
    with open(CONFIG_FILE, 'w') as f:
        json.dump(configs, f, indent=2)

def generate_torrc(config, paths=None):
    if paths is None:
        paths = get_paths()
        
    if config.get('countries'):
        exit_nodes = ",".join([f"{{{country}}}" for country in config['countries']])
    else:
        exit_nodes = ""
    
    torrc_content = f"""
DataDirectory {paths['data_dir']}
GeoIPFile {paths['geoip']}
GeoIPv6File {paths['geoip6']}
SocksPort 0.0.0.0:{config['port']}
"""
    
    if exit_nodes:
        torrc_content += f"ExitNodes {exit_nodes}\n"
    
    torrc_content += f"""UseBridges 1
ClientTransportPlugin meek_lite,obfs2,obfs3,obfs4,scramblesuit,webtunnel exec {paths['lyrebird_exe']}
AvoidDiskWrites 1
HardwareAccel 1
ClientOnly 1
AutomapHostsOnResolve 1
SafeLogging 1
"""
    
    if config.get('bridges'):
        for bridge in config['bridges']:
            torrc_content += f"Bridge {bridge}\n"
    
    torrc_path = paths['torrc']
    torrc_path.write_text(torrc_content.strip())
    return torrc_path

def run_tor(torrc_path, tor_exe_path=None, log_filter=None):
    if tor_exe_path is None:
        tor_exe_path = get_paths()['tor_exe']
        
    if not tor_exe_path.exists():
        raise FileNotFoundError(f"Tor not found: {tor_exe_path}")
    
    env = os.environ.copy()
    if sys.platform != "win32":
        lib_path = str(tor_exe_path.parent)
        if 'LD_LIBRARY_PATH' in env:
            env['LD_LIBRARY_PATH'] = f"{lib_path}:{env['LD_LIBRARY_PATH']}"
        else:
            env['LD_LIBRARY_PATH'] = lib_path
        os.chmod(tor_exe_path, 0o755)
        lyrebird_path = get_paths(tor_exe_path.parents[1])['lyrebird_exe']
        if lyrebird_path.exists():
             os.chmod(lyrebird_path, 0o755)

    process = subprocess.Popen(
        [str(tor_exe_path), "-f", str(torrc_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
        env=env
    )
    
    def filter_log(stream):
        for line in iter(stream.readline, ''):
            if not log_filter:
                print(line, end="")
            else:
                for level in log_filter:
                    if LOG_LEVELS[level] in line:
                        print(line, end="")
                        break
    
    import threading
    threading.Thread(target=filter_log, args=(process.stdout,), daemon=True).start()
    threading.Thread(target=filter_log, args=(process.stderr,), daemon=True).start()
    
    return process

def get_user_config():
    config = {}
    config['port'] = input("Enter port (default 9050): ") or "9050"
    
    countries_input = input("Enter countries separated by comma (us,de,fr etc. or leave empty): ").strip()
    if countries_input:
        config['countries'] = [c.strip() for c in countries_input.split(',')]
    else:
        config['countries'] = ['us', 'de', 'fr', 'nl', 'se']
    
    print("Enter bridges (empty line to finish, default is webtunnel):")
    bridges = []
    while True:
        bridge = input("Bridge: ").strip()
        if not bridge:
            if not bridges:
                bridges = [
                    "webtunnel [2001:db8:2ba7:5f68:dc7e:27ca:1f5d:128d]:443 2B936CD554AF5B16678DE517CC3866AA11170BC4 url=https://tech.linuxenby.is/D0CX0ykTaxzAgALpPd2hBMU6 ver=0.0.3",
                    "webtunnel [2001:db8:888f:6b82:e4f2:19a9:81d3:659a]:443 626D6E238C6E19C09E551508A2C5EA5A514C64BA url=https://www2.notriddle.com/rPROWV6KWnDb2AA7xE2oTu3t ver=0.0.1"
                ]
            break
        bridges.append(bridge)
    config['bridges'] = bridges
    
    print("Select log levels (comma separated): notice, warn, err")
    log_input = input("Levels (default all): ").strip()
    if log_input:
        config['log_levels'] = [l.strip() for l in log_input.split(',') if l.strip() in LOG_LEVELS]
    else:
        config['log_levels'] = list(LOG_LEVELS.keys())
    
    save = input("Save configuration? (y/n): ").lower()
    if save == 'y':
        config_name = input("Config name: ").strip()
        if config_name:
            save_config(config_name, config)
            print(f"Config '{config_name}' saved.")
    
    return config

def main():
    parser = argparse.ArgumentParser(description="Tor Launcher")
    parser.add_argument('--config', help="Config name to load")
    args = parser.parse_args()
    
    base_dir = PROJECT_FOLDER
    update_info_path = PROJECT_FOLDER / "update_info.json"
    if update_info_path.exists():
        with open(update_info_path, 'r') as f:
            info = json.load(f)
            folder_name = info.get('use_folder')
            if folder_name:
                base_dir = PROJECT_FOLDER / folder_name
                print(f"Using folder: {folder_name}")

    paths = get_paths(base_dir)
    
    if args.config:
        config = load_config(args.config)
        if not config:
            print(f"Config '{args.config}' not found.")
            return
        print(f"Loaded config: {args.config}")
    else:
        config = get_user_config()
    
    print("Generating torrc...")
    torrc_path = generate_torrc(config, paths)
    
    print("Starting Tor...")
    tor_process = run_tor(torrc_path, paths['tor_exe'], config.get('log_levels'))
    
    def signal_handler(sig, frame):
        print("\nStopping Tor...")
        tor_process.terminate()
        try:
            tor_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tor_process.kill()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    print("Tor started. Press Ctrl+C to stop.")
    try:
        tor_process.wait()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

if __name__ == "__main__":
    main()
