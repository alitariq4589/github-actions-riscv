#!/usr/bin/python3
import os
import sys
import requests
import subprocess
import logging
import re
import yaml
from urllib.parse import urlparse
from datetime import datetime, timezone
from flask import Flask, request, render_template, redirect, url_for

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define paths relative to the application root
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
RUNNER_REGISTRY_FILE = os.path.join(APP_ROOT, "runner_registry.yaml")
INVENTORY_FILE = os.path.join(APP_ROOT, "ansible", "inventory.ini")
LOG_FILE = os.path.join(APP_ROOT,"logs", "ansible-registration.log")
ANSIBLE_SETUP_LOG_FILE = os.path.join(APP_ROOT, "logs", "ansible-setup.log")
ANSIBLE_UNREGISTER_BOARD_LOG_FILE = os.path.join(APP_ROOT, "logs", "ansible-unregister-board.log") # Renamed for clarity
ANSIBLE_UNREGISTER_RUNNER_LOG_FILE = os.path.join(APP_ROOT, "logs", "ansible-unregister-runner.log") # New log file for unregistering runner

RUNNER_REGISTRATION_PLAYBOOK = os.path.join(APP_ROOT, "ansible", "register-runner.yml")
SETUP_BOARD_PLAYBOOK = os.path.join(APP_ROOT, "ansible", "setup-board.yml") # Corrected filename
UNREGISTER_BOARD_PLAYBOOK = os.path.join(APP_ROOT, "ansible", "unregister_board.yml") # Corrected filename
UNREGISTER_GITLAB_RUNNER_PLAYBOOK = os.path.join(APP_ROOT, "ansible", "unregister_runner.yml") # New playbook path

# --- Utility Functions ---

def check_github_server(url):
    """
    Checks if a given URL is a valid and reachable GitHub instance.
    This version is more robust against Cloudflare and similar protections.
    """
    url = url.rstrip("/")
    URL_REGEX = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
    if not URL_REGEX.match(url):
        logger.info(f"'{url}' does not appear to be a valid URL format.")
        return False
    logger.info(f"\n--- Checking URL: {url} ---")

    # Add a User-Agent header to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # Attempt 1: HEAD request and X-Gitlab-Instance header
    try:
        logger.info(f"Attempting HEAD request to {url}")
        head_resp = requests.head(url, timeout=5, allow_redirects=True, headers=headers)
        logger.info(f"HEAD response status: {head_resp.status_code}, headers: {head_resp.headers.get('X-Gitlab-Instance')}")
        if 'X-Gitlab-Instance' in head_resp.headers:
            logger.info(f"'{url}' is a GitHub URL (X-Gitlab-Instance header confirmed via HEAD).")
            return True
    except requests.exceptions.RequestException as e:
        logger.info(f"HEAD request to {url} failed: {e}")
        pass

    # Attempt 2: GET request to base URL and X-Gitlab-Instance header or content check
    try:
        logger.info(f"Attempting GET request to {url}")
        base_resp = requests.get(url, timeout=5, allow_redirects=True, headers=headers)
        logger.info(f"GET response status: {base_resp.status_code}, headers: {base_resp.headers.get('X-Gitlab-Instance')}")
        if 'X-Gitlab-Instance' in base_resp.headers:
            logger.info(f"'{url}' is a GitHub URL (Homepage content 'GitHub' confirmed via GET header).")
            return True
        if "GitHub" in base_resp.text:
            logger.info(f"'{url}' is a GitHub URL (Homepage content 'GitHub' confirmed via GET text).")
            return True
    except requests.exceptions.RequestException as e:
        logger.info(f"GET request to {url} failed: {e}")
        pass

    # Attempt 3: GET request to /api/v4/version endpoint
    api_version_url = f"{url}/api/v4/version"
    logger.info(f"Attempting to reach GitHub API at: {api_version_url}")
    try:
        api_resp = requests.get(api_version_url, timeout=5, headers=headers)
        logger.info(f"API /version response status: {api_resp.status_code}, content-type: {api_resp.headers.get('Content-Type')}")
        if api_resp.status_code == 200:
            if 'application/json' in api_resp.headers.get('Content-Type', ''):
                try:
                    data = api_resp.json()
                    if 'version' in data and 'revision' in data:
                        logger.info(f"'{url}' is a GitHub URL (API /version confirmed, version: {data['version']}).")
                        return True
                except requests.exceptions.JSONDecodeError:
                    logger.info(f"API /version response is not valid JSON.")
                    pass
        if 'X-Gitlab-Instance' in api_resp.headers:
            logger.info(f"'{url}' is a GitHub URL (API /version header confirmed, even with status {api_resp.status_code}).")
            return True
        if "GitHub" in api_resp.text:
            logger.info(f"'{url}' is a GitHub URL (API /version content 'GitHub' confirmed, even with status {api_resp.status_code}).")
            return True
    except requests.exceptions.RequestException as e:
        logger.info(f"API /version request to {api_version_url} failed: {e}")
        pass

    # Attempt 4: GET request to /-/health endpoint
    health_url = f"{url}/-/health"
    logger.info(f"Attempting to reach GitHub health endpoint at: {health_url}")
    try:
        health_resp = requests.get(health_url, timeout=5, headers=headers)
        logger.info(f"/-/health response status: {health_resp.status_code}, content-type: {health_resp.headers.get('Content-Type')}")
        if health_resp.status_code == 200:
            if 'application/json' in health_resp.headers.get('Content-Type', ''):
                try:
                    data = health_resp.json()
                    if 'status' in data and data['status'] == 'ok':
                        logger.info(f"'{url}' is a GitHub URL (/-/health endpoint confirmed).")
                        return True
                except requests.exceptions.JSONDecodeError:
                    logger.info(f"/-/health response is not valid JSON.")
                    pass
        if 'X-Gitlab-Instance' in health_resp.headers:
            logger.info(f"'{url}' is a GitHub URL (/-/health header confirmed, even with status {health_resp.status_code}).")
            return True
        if "GitHub" in health_resp.text:
            logger.info(f"'{url}' is a GitHub URL (/-/health content 'GitHub' confirmed, even with status {health_resp.status_code}).")
            return True
    except requests.exceptions.RequestException as e:
        logger.info(f"/-/health request to {health_url} failed: {e}")
        return False # Return False here as this is a critical check
    except Exception as e:
        logger.info(f"An unexpected error occurred while checking '{url}': {e}")
        return False

    # Attempt 5: Fallback to login page check
    login_page_url = f"{url}/users/sign_in"
    logger.info(f"All API checks failed/undetermined. Falling back to login page check at: {login_page_url}")
    try:
        login_resp = requests.get(login_page_url, timeout=5, allow_redirects=True, headers=headers)
        logger.info(f"Login page response status: {login_resp.status_code}")
        if "_github_session" in login_resp.headers.get("Set-Cookie", ""):
            logger.info(f"'{url}' is a GitHub URL (login page cookie confirmed).")
            return True
        if "GitHub" in login_resp.text:
            logger.info(f"'{url}' is a GitHub URL (login page content 'GitHub' confirmed).")
            return True
    except requests.exceptions.RequestException as e:
        logger.info(f"Could not reach '{url}' or an error occurred during login page check: {e}")
        return False
    except Exception as e:
        logger.info(f"An unexpected error occurred while checking '{url}': {e}")
        return False

    logger.info(f"'{url}' is not a GitHub URL (no conclusive evidence found after all checks).")
    return False


def is_online(target_node):
    """
    Runs an Ansible ping module to check if a target node is alive.
    Returns True if alive, False otherwise.
    """
    logger.info(f"--- Checking if {target_node} is online via Ansible ping...")
    try:
        result = subprocess.run(
            [
                "ansible",
                "-i", INVENTORY_FILE,
                "-m", "ping",
                target_node
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True
        )
        output = result.stdout
        logger.info(f"--- Ansible Ping Output for {target_node}:\n{output[:500]}...")
        if f"SUCCESS" in output and "ping" in output and "pong" in output:
            logger.info(f"--- ✅ {target_node} is online.")
            return True
        else:
            logger.info(f"--- ❌ {target_node} is not responding or ping failed.")
            return False
    except FileNotFoundError:
        logger.error("Error: 'ansible' command not found. Is Ansible installed and in your PATH?")
        return False
    except Exception as e:
        logger.error(f"Error running Ansible ping for {target_node}: {e}")
        return False


def get_healthy_targets(registry, runner_type):
    """
    Gets a list of healthy nodes for a specific type,
    sorted by the number of runners (least first).
    """
    healthy_nodes = {
        name: data for name, data in registry.get("nodes", {}).items()
        if data.get("health") == "good" and data.get("type") == runner_type
    }
    if not healthy_nodes:
        return []
    sorted_nodes = sorted(
        healthy_nodes.items(),
        key=lambda x: len(x[1].get("runners", []))
    )
    return [name for name, data in sorted_nodes]  
        
        
def find_and_select_online_target(registry, runner_type):
    """
    Finds the first healthy and online target for the given type.
    """
    logger.info(f"Searching for an online '{runner_type}' target...")
    potential_targets = get_healthy_targets(registry, runner_type)
    if not potential_targets:
        logger.info(f"No healthy nodes found for type '{runner_type}'.")
        return None
    logger.info(f"Found {len(potential_targets)} healthy candidates, checking online status...")
    for target in potential_targets:
        if is_online(target):
            logger.info(f"🎉 Selected target: {target}")
            return target
    logger.info(f"❌ No healthy *and* online nodes found for type '{runner_type}'.")
    return None


def load_registry(registry_path):
    """
    This function loads the runners_registry.yaml YAML file.
    If any such file does not exist, it creates an empty file
    with just a 'nodes' key. If the file exists but is empty or malformed,
    it also initializes it with an empty 'nodes' structure.
    It ensures each node has required fields if they are present.
    """
    # No default nodes are defined here; the 'nodes' dictionary will be empty initially.
    default_empty_registry_structure = {"nodes": {}}

    registry = None
    if not os.path.exists(registry_path):
        logger.info(f"Registry file not found at {registry_path}. Creating with empty structure.")
        registry = default_empty_registry_structure
        with open(registry_path, "w") as f:
            yaml.dump(registry, f, default_flow_style=False)
    else:
        try:
            with open(registry_path, "r") as f:
                registry = yaml.safe_load(f)
                if registry is None:
                    logger.warning(f"Registry file at {registry_path} is empty or invalid. Initializing with empty structure.")
                    registry = default_empty_registry_structure
                
                # Ensure 'nodes' key exists and is a dictionary
                if "nodes" not in registry or not isinstance(registry["nodes"], dict):
                    logger.warning(f"Registry file at {registry_path} has missing or malformed 'nodes' section. Reinitializing with empty structure.")
                    registry = default_empty_registry_structure
                else:
                    # For existing nodes, ensure required fields are present (if they were added previously)
                    # This loop now only ensures consistency for *already existing* nodes, not adding new defaults.
                    for node_name, node_data in list(registry["nodes"].items()): # Use list() to allow modification during iteration
                        if "health" not in node_data:
                            node_data["health"] = "unknown" # Default health for existing, untracked nodes
                        if "type" not in node_data:
                            node_data["type"] = "Unknown"
                        if "runner_count" not in node_data:
                            node_data["runner_count"] = 0
                        if "runners" not in node_data or not isinstance(node_data["runners"], list):
                            node_data["runners"] = []
                        if "ip_address" not in node_data:
                            node_data["ip_address"] = "N/A"
                        if "ssh_port" not in node_data:
                            node_data["ssh_port"] = "22"
                        # Remove setup_status if it exists from previous versions
                        if "setup_status" in node_data:
                            del node_data["setup_status"]

        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML from {registry_path}: {e}. Initializing with empty structure.")
            registry = default_empty_registry_structure
        
        # Always write back the potentially updated/initialized registry
        with open(registry_path, "w") as wf:
            yaml.dump(registry, wf, default_flow_style=False)
        
    return registry


def register_runner_attempt(target, github_repo_url, runner_reg_token, log_file, inventory_file, runner_name, runner_registeration_playbook):
    """
    Runs the Ansible playbook to register the GitHub runner on the requested machine.
    Returns True if successful, False otherwise.
    """
    
    registered_at = datetime.now(timezone.utc).isoformat()
    
    cmd = [
        "ansible-playbook", runner_registeration_playbook,
        "-i", inventory_file,
        "-e", f"target_node={target}",
        "-e", f"registration_token={runner_reg_token}",
        "-e", f"github_repo_url={github_repo_url}",
        "-e", f"runner_name={runner_name}",
        "-e", f"created_at={registered_at}"
    ]
    
    logger.info(f"Executing Ansible command for runner registration: {' '.join(cmd)}")
    try:
        with open(log_file, "a") as f:
            f.write(f"\n--- Runner Registration Attempt Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            process = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
        logger.info(f"Ansible registration playbook return code: {process.returncode}")
        return process.returncode == 0
    except FileNotFoundError:
        logger.error("Error: 'ansible-playbook' command not found. Is Ansible installed and in your PATH?")
        return False
    except Exception as e:
        logger.error(f"Error running Ansible playbook for runner registration: {e}")
        return False

def setup_board_attempt(target_node, log_file, inventory_file, setup_playbook):
    """
    Runs the Ansible playbook to set up a new RISC-V board.
    Returns True if successful, False otherwise.
    """
    cmd = [
        "ansible-playbook", setup_playbook,
        "-i", inventory_file,
        "-e", f"target_node={target_node}", # Pass the target node dynamically
        "--extra-vars", f"ansible_user=root" # Ensure ansible_user is passed for setup
    ]
    logger.info(f"Executing Ansible command for board setup: {' '.join(cmd)}")
    try:
        with open(log_file, "a") as f: # Use the dedicated setup log file
            f.write(f"\n--- Board Setup Attempt Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            process = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
        logger.info(f"Ansible board setup playbook return code: {process.returncode}")
        return process.returncode == 0
    except FileNotFoundError:
        logger.error("Error: 'ansible-playbook' command not found. Is Ansible installed and in your PATH?")
        return False
    except Exception as e:
        logger.error(f"Error running Ansible playbook for board setup: {e}")
        return False

def unregister_board_attempt(target_node, log_file, inventory_file, unregister_playbook):
    """
    Runs the Ansible playbook to unregister and clean up a RISC-V board.
    Returns True if successful, False otherwise.
    """
    cmd = [
        "ansible-playbook", unregister_playbook,
        "-i", inventory_file,
        "-e", f"target_node={target_node}",
        "--extra-vars", f"ansible_user=root" # Ensure ansible_user is passed for cleanup
    ]
    logger.info(f"Executing Ansible command for board unregistration: {' '.join(cmd)}")
    try:
        with open(log_file, "a") as f: # Use the dedicated unregister log file
            f.write(f"\n--- Board Unregistration Attempt Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            process = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
        logger.info(f"Ansible board unregistration playbook return code: {process.returncode}")
        return process.returncode == 0
    except FileNotFoundError:
        logger.error("Error: 'ansible-playbook' command not found. Is Ansible installed and in your PATH?")
        return False
    except Exception as e:
        logger.error(f"Error running Ansible playbook for board unregistration: {e}")
        return False

def unregister_github_runner_attempt(target_node, runner_id, log_file, inventory_file, unregister_runner_playbook):
    """
    Runs the Ansible playbook to unregister a specific GitHub runner.
    Returns True if successful, False otherwise.
    """
    cmd = [
        "ansible-playbook", unregister_runner_playbook,
        "-i", inventory_file,
        "-e", f"target_node={target_node}",
        "-e", f"runner_id={runner_id}",
        "--extra-vars", f"ansible_user=github-runner-user"
    ]
    logger.info(f"Executing Ansible command for GitHub runner unregistration: {' '.join(cmd)}")
    try:
        with open(log_file, "a") as f:
            f.write(f"\n--- GitHub Runner Unregistration Attempt Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            process = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
        logger.info(f"Ansible GitHub runner unregistration playbook return code: {process.returncode}")
        return process.returncode == 0
    except FileNotFoundError:
        logger.error("Error: 'ansible-playbook' command not found. Is Ansible installed and in your PATH?")
        return False
    except Exception as e:
        logger.error(f"Error running Ansible playbook for GitHub runner unregistration: {e}")
        return False


def save_registry(registry, runner_registry_file_path):
    """
    This function saves the newer registry data passed as argument to the registry yaml file
    """
    with open(runner_registry_file_path, "w") as f:
        yaml.dump(registry, f, default_flow_style=False)

def check_latest_failed_attempt(log_file):
    """
    Parses the Ansible log to identify the most recent failing task related to
    GitLab Runner registration.

    Returns:
        1: Container could not start properly
        2: Invalid GitHub Registration Token or Github repo url
        3: There is already a podman container running with the same name
        4: Generic error (fatal but not matched above)
    """
    if not os.path.exists(log_file):
        logger.info(f"Log file not found: {log_file}")
        return 0

    with open(log_file, "r") as f:
        lines = f.readlines()

    # Reverse the log lines for last error scanning
    for i in range(len(lines)-1, -1, -1):
        line = lines[i]

        if "TASK [Inspect the container to check if it's still running]" in line:
            logger.info("Internal Error: Container did not start properly.")
            return 1
        if "TASK [Fail if container did not start properly]" in line:
            logger.info("Either the token is invalid or the GitHub server URL is incorrect.")
            return 2
        else:
            logger.info("Unknown error occurred during registration.")
            return 4


# Currently getting core dumped illegal instruction error when using repo name as well as url if it makes a very long string

def extract_owner_repo(repo_url):
    """
    Extracts owner and repo name from GitHub URL.
    Example: https://github.com/owner/repo -> owner-repo
    """
    path = urlparse(repo_url).path.strip("/")
    if len(path.split("/")) != 2:
        raise ValueError("Invalid GitHub URL format.")
    owner, repo = path.split("/")
    return f"{owner}-{repo}"


def register_runner_name(repo_url, compute_target_name):
    try:
        base_name = extract_owner_repo(repo_url)
    except ValueError as e:
        logger.info(f"Error: {e}")
        sys.exit(1)

    runner_name = f"{base_name}-{compute_target_name}"
    return runner_name


# Check if the repository is already registered with the same board type in YAML registry

def is_project_already_registered(repo_url, compute_type, yaml_path):
    """
    Check if the given repo URL is already registered on any node of the given type.

    :param repo_url: str - GitHub/GitLab repository URL
    :param compute_type: str - The type (e.g. 'visionfive2', 'jupiter') to match against
    :param yaml_path: str - Path to YAML registry
    :return: bool - True if already registered in same type, False otherwise
    """
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"YAML registry not found: {yaml_path}")

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f) or {}

    nodes = data.get("nodes", {})

    for node_data in nodes.values():
        if node_data.get("type") != compute_type:
            continue
        for runner in node_data.get("runners", []):
            print(runner.get("github_repo_link"))
            if runner.get("github_repo_link") == repo_url:
                return True

    return False

# --- Flask Routes ---

@app.route('/', methods=['GET'])
def render_index_page():
    """
    Renders the main landing page with options to add a board or register a runner.
    """
    return render_template('index.html')

@app.route('/add-board', methods=['GET'])
def render_add_board_page():
    """
    Renders the form to add a new RISC-V board.
    """
    return render_template('add_board.html')

@app.route('/add-board', methods=['POST'])
def handle_add_board_post():
    """
    Handles the submission of the form to add a new RISC-V board.
    This function first adds the board to inventory.ini, then attempts to set up the board.
    If setup fails, the board is removed from inventory.ini.
    """
    board_name = request.form.get('board_name')
    ip_address = request.form.get('ip_address')
    ssh_port = request.form.get('ssh_port')
    runner_type = request.form.get('runner_type')
    
    if not all([board_name, ip_address, runner_type]):
        return render_template('add_board.html', message="Board Name, IP Address, and Runner Type are required.", is_error=True)

    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_address) and \
       not re.match(r"^[a-zA-Z0-9.-]+$", ip_address):
        return render_template('add_board.html', message="Invalid IP Address or Hostname format.", is_error=True)

    registry = load_registry(RUNNER_REGISTRY_FILE)
    if board_name in registry["nodes"]:
        return render_template('add_board.html', message=f"A board with the name '{board_name}' already exists. Please choose a different name.", is_error=True)

    # Prepare the inventory line content
    inventory_line_content = f"{board_name} ansible_host={ip_address} ansible_user=github-runner-user"
    if ssh_port and ssh_port.isdigit() and 1 <= int(ssh_port) <= 65535:
        inventory_line_content += f" ansible_port={ssh_port}"
    else:
        inventory_line_content += f" ansible_port=22"
    inventory_line_to_add = inventory_line_content + "\n"

    # Define the specific group header for this runner type
    runner_type_group_header = f"[{runner_type}]\n"

    original_inventory_content = ""
    try:
        # Read current inventory content
        if os.path.exists(INVENTORY_FILE):
            with open(INVENTORY_FILE, 'r') as f:
                original_inventory_content = f.read()

        # Temporarily add the board to inventory.ini for setup
        with open(INVENTORY_FILE, 'a') as f:
            # Check if the specific runner_type group header already exists
            if runner_type_group_header.strip() not in original_inventory_content:
                f.write(f"\n{runner_type_group_header}") # Add specific group header if not present
            f.write(inventory_line_to_add)
        logger.info(f"Temporarily added board '{board_name}' to inventory under group '{runner_type}' for setup attempt.")

        # Attempt to set up the board
        setup_success = setup_board_attempt(board_name, ANSIBLE_SETUP_LOG_FILE, INVENTORY_FILE, SETUP_BOARD_PLAYBOOK)

        if setup_success:
            # Setup successful: The board is already in inventory.ini.
            # Now add it to runner_registry.yaml permanently.
            registry["nodes"][board_name] = {
                "health": "good",
                "type": runner_type,
                "runner_count": 0,
                "runners": [],
                "ip_address": ip_address,
                "ssh_port": ssh_port if ssh_port and ssh_port.isdigit() else "22",
            }
            save_registry(registry, RUNNER_REGISTRY_FILE)
            logger.info(f"Board '{board_name}' successfully added to runner registry.")
            message = f"Board '{board_name}' successfully added and set up!"
            is_error = False
        else:
            # Setup failed: Remove the board from inventory.ini
            logger.warning(f"Board '{board_name}' setup failed. Removing from inventory.ini.")
            
            # Read current inventory content again to ensure we have the latest state
            current_inventory_lines = []
            if os.path.exists(INVENTORY_FILE):
                with open(INVENTORY_FILE, 'r') as f:
                    current_inventory_lines = f.readlines()

            updated_inventory_lines = []
            removed_line = False
            for line in current_inventory_lines:
                # Only remove the exact line we added
                if line.strip() == inventory_line_content.strip() and not removed_line:
                    removed_line = True # Ensure only the first match is removed
                    continue
                updated_inventory_lines.append(line)

            # Check if the specific runner_type group header needs to be removed
            temp_content_after_removal = "".join(updated_inventory_lines)
            
            group_pattern = re.compile(r'\[{}\]\s*\n(?P<hosts>.*?)(?=\n\[|\Z)'.format(re.escape(runner_type)), re.DOTALL)
            match = group_pattern.search(temp_content_after_removal)
            
            if match and not match.group('hosts').strip():
                final_inventory_lines = []
                skip_group_section = False
                for line in updated_inventory_lines:
                    if line.strip() == runner_type_group_header.strip():
                        skip_group_section = True
                        continue
                    if skip_group_section and line.strip().startswith('['):
                        skip_group_section = False
                    if not skip_group_section:
                        final_inventory_lines.append(line)
                updated_inventory_lines = final_inventory_lines
            elif not match and runner_type_group_header.strip() in temp_content_after_removal:
                 updated_inventory_lines = [line for line in updated_inventory_lines if line.strip() != runner_type_group_header.strip()]


            with open(INVENTORY_FILE, 'w') as f:
                f.write("".join(updated_inventory_lines))
            
            message = f"Board '{board_name}' setup failed. It has not been added to the inventory or registry. Please check the logs for details or contact support."
            is_error = True
    except IOError as e:
        logger.error(f"Error managing inventory file {INVENTORY_FILE}: {e}")
        message = f"Failed to manage inventory file during board setup: {e}"
        is_error = True
    except Exception as e:
        logger.error(f"An unexpected error occurred while adding board: {e}")
        message = f"An unexpected error occurred: {e}"
        is_error = True
    
    logger.info(f"Board '{board_name}' final outcome: {'Success' if setup_success and not is_error else 'Failure'}.")
    return render_template('add_board.html', message=message, is_error=is_error)


@app.route('/github-riscv-runner', methods=['GET'])
def render_runner_registration_page():
    """
    Renders the GitHub Runner registration form.
    Dynamically fetches available runner types from runner_registry.yaml.
    """
    registry = load_registry(RUNNER_REGISTRY_FILE)
    available_runner_types = sorted(list(set(
        node_data["type"] for node_name, node_data in registry.get("nodes", {}).items()
        if "type" in node_data and node_data["type"] # Ensure 'type' exists and is not empty
    )))
    return render_template('register-runner.html', runner_types=available_runner_types)

@app.route('/github-runner-result-page', methods=['POST'])
def handle_runner_registration_post():
    """
    Handles the submission of the GitHub Runner registration form.
    """
    logger.info('Starting handle_runner_registration_post function')
    
    runner_creation_token = request.form.get('runner_token')
    target_platform = request.form.get('target_platform')
    user_email = request.form.get('user_email')
    github_repo_link = request.form.get('github_repo_link')        
    
    if (is_project_already_registered(github_repo_link, target_platform, RUNNER_REGISTRY_FILE)):
        logger.warning(f"Repository {github_repo_link} is already registered on a board of type {target_platform}.")
        return render_template('no_registration_token.html',
            error_message="This project is already registered on a board of the same type. Currently only one repository can be configured per board type. Please check the runner registry file for details."
        )
    
    if not all([runner_creation_token, target_platform, user_email, github_repo_link]):
        logger.warning("Missing form fields in POST request.")
        return render_template('no_registration_token.html',
            error_message="It looks like you've landed here directly or submitted an incomplete form! To get started, please visit the registration page to provide the necessary details."
        )
    
    runner_registry = load_registry(RUNNER_REGISTRY_FILE)
    
    runner = find_and_select_online_target(runner_registry, target_platform)
    
    if runner is None:
        logger.warning(f"No healthy and online runner found for platform: {target_platform}")
        return render_template('no_registration_token.html',
            error_message="We are sorry. Due to current limitations, the requested machine cannot be allocated at this time. Kindly try again briefly, or contact support at cloud-v@10xengineers.ai for further help."
        )

    if runner not in runner_registry["nodes"] or "runners" not in runner_registry["nodes"][runner]:
        logger.error(f"Registry structure error for runner: {runner}. 'runners' list not found.")
        return render_template('no_registration_token.html',
            error_message="An internal configuration error occurred. Please check the logs."
        )
    
    current_runner_count = len(runner_registry["nodes"][runner]["runners"])
    next_runner_id =  next_id = register_runner_name(github_repo_link, target_platform)
    
    registration_status = register_runner_attempt(
        runner, github_repo_link, runner_creation_token, LOG_FILE,
        INVENTORY_FILE, next_runner_id, RUNNER_REGISTRATION_PLAYBOOK
    )
    
    if registration_status:
        runner_registry["nodes"][runner]["runners"].append({
            "id": next_runner_id,
            "token": runner_creation_token,
            "user_email": user_email,
            "github_repo_link": github_repo_link,
            "registered_at": datetime.now(timezone.utc).isoformat()
        })
        
        if "runner_count" not in runner_registry["nodes"][runner]:
            runner_registry["nodes"][runner]["runner_count"] = 0
        runner_registry["nodes"][runner]["runner_count"] += 1

        save_registry(runner_registry, RUNNER_REGISTRY_FILE)
        logger.info("Runner registered successfully")
        
        return render_template('runner_creation_complete.html', runner_name=target_platform)
        
    else:
        logger.warning("Runner registration failed via Ansible.")
        
        fail_code = check_latest_failed_attempt(LOG_FILE)
        if fail_code == 1:
            return render_template('no_registration_token.html',
                error_message="The setup is currently unable to register your GitHub Actions runner on specified machine. Please check the logs for details, and create an issue if necessary."
            )
        elif fail_code == 2:
            return render_template('no_registration_token.html',
                error_message="Your GitHub runner token is invalid or expired, or the GitHub repository URL is incorrect. Please verify these details or generate a new token."
            )        
        return render_template('no_registration_token.html',
            error_message="The setup has encountered an internal issue and was unable to assign the requested machine. Please check your runner registration token and GitHub repository URL and try again shortly. If the error persists, check the logs and create an issue."
        )

# Add new route for board status
@app.route('/board-status', methods=['GET'])
def render_board_status_page():
    """
    Renders the page showing the setup status of all RISC-V boards.
    """
    registry = load_registry(RUNNER_REGISTRY_FILE)
    boards_to_display = {
        name: data for name, data in registry.get("nodes", {}).items()
    }
    return render_template('board_status.html', boards=boards_to_display)

@app.route('/unregister-board', methods=['GET'])
def render_unregister_board_page():
    """
    Renders the form to unregister a RISC-V board.
    """
    return render_template('remove_board.html')

@app.route('/unregister-board', methods=['POST'])
def handle_unregister_board_post():
    """
    Handles the submission of the form to unregister a RISC-V board.
    This function attempts to unregister the board using Ansible.
    If successful, it removes the board from inventory.ini and runner_registry.yaml.
    """
    board_name = request.form.get('board_name')

    if not board_name:
        return render_template('remove_board.html', message="Board Name/ID is required.", is_error=True)

    registry = load_registry(RUNNER_REGISTRY_FILE)
    if board_name not in registry["nodes"]:
        return render_template('remove_board.html', message=f"Board '{board_name}' not found in the registry. Please ensure the name is correct.", is_error=True)
    
    # Get board details from registry to construct inventory line for removal
    board_data = registry["nodes"][board_name]
    ip_address = board_data.get("ip_address", "N/A")
    ssh_port = board_data.get("ssh_port", "22")
    runner_type = board_data.get("type", "Unknown")

    # Construct the inventory line that would have been added
    inventory_line_content = f"{board_name} ansible_host={ip_address} ansible_user=github-runner-user"
    inventory_line_content += f" ansible_port={ssh_port}" if ssh_port != "22" else f" ansible_port=22"
    
    runner_type_group_header = f"[{runner_type}]" # No newline here for comparison

    unregister_success = False
    try:
        # Attempt to unregister the board using the playbook
        unregister_success = unregister_board_attempt(board_name, ANSIBLE_UNREGISTER_BOARD_LOG_FILE, INVENTORY_FILE, UNREGISTER_BOARD_PLAYBOOK)

        if unregister_success:
            # Unregistration successful: Remove from inventory.ini and runner_registry.yaml
            
            # Remove from runner_registry.yaml
            del registry["nodes"][board_name]
            save_registry(registry, RUNNER_REGISTRY_FILE)
            logger.info(f"Board '{board_name}' successfully removed from runner registry.")

            # Remove from inventory.ini
            current_inventory_lines = []
            if os.path.exists(INVENTORY_FILE):
                with open(INVENTORY_FILE, 'r') as f:
                    current_inventory_lines = f.readlines()

            updated_inventory_lines = []
            removed_board_line = False
            for line in current_inventory_lines:
                # Remove the exact board line
                if line.strip() == inventory_line_content.strip() and not removed_board_line:
                    removed_board_line = True
                    continue
                updated_inventory_lines.append(line)

            # Check if the group header for this runner_type is now empty and should be removed
            temp_content_after_removal = "".join(updated_inventory_lines)
            group_pattern = re.compile(r'\[{}\]\s*\n(?P<hosts>.*?)(?=\n\[|\Z)'.format(re.escape(runner_type)), re.DOTALL)
            match = group_pattern.search(temp_content_after_removal)
            
            if match and not match.group('hosts').strip(): # If the hosts section for this group is empty
                final_inventory_lines = []
                skip_group_section = False
                for line in updated_inventory_lines:
                    if line.strip() == runner_type_group_header.strip():
                        skip_group_section = True
                        continue
                    if skip_group_section and line.strip().startswith('['): # Found next group, stop skipping
                        skip_group_section = False
                    if not skip_group_section:
                        final_inventory_lines.append(line)
                updated_inventory_lines = final_inventory_lines
            elif not match and runner_type_group_header.strip() in temp_content_after_removal:
                 # Case where group header might be at the very end and becomes empty
                 updated_inventory_lines = [line for line in updated_inventory_lines if line.strip() != runner_type_group_header.strip()]

            with open(INVENTORY_FILE, 'w') as f:
                f.write("".join(updated_inventory_lines))
            logger.info(f"Board '{board_name}' successfully removed from inventory.ini.")

            message = f"Board '{board_name}' successfully unregistered and removed."
            is_error = False
        else:
            # Unregistration failed: Keep in registry and inventory, provide error message
            message = f"Failed to unregister board '{board_name}'. Please check the logs ({ANSIBLE_UNREGISTER_BOARD_LOG_FILE}) for details and ensure the board is reachable via SSH."
            is_error = True
    except Exception as e:
        logger.error(f"An unexpected error occurred during unregistration of board '{board_name}': {e}")
        message = f"An unexpected error occurred during unregistration: {e}"
        is_error = True
    
    logger.info(f"Board '{board_name}' unregistration outcome: {'Success' if unregister_success else 'Failure'}.")
    return render_template('remove_board.html', message=message, is_error=is_error)


@app.route('/unregister-runner', methods=['GET'])
def render_unregister_runner_page():
    """
    Renders the form to unregister a specific GitHub Runner.
    """
    return render_template('unregister_runner.html')

@app.route('/unregister-runner', methods=['POST'])
def handle_unregister_runner_post():
    """
    Handles the submission of the form to unregister a specific GitHub Runner.
    """
    node_name = request.form.get('node_name')
    runner_id = request.form.get('runner_id')

    if not all([node_name, runner_id]):
        return render_template('unregister_runner.html', message="Board Name/ID and Runner ID are required.", is_error=True)

    registry = load_registry(RUNNER_REGISTRY_FILE)
    if node_name not in registry["nodes"]:
        return render_template('unregister_runner.html', message=f"Board '{node_name}' not found in the registry.", is_error=True)

    node_runners = registry["nodes"][node_name].get("runners", [])
    runner_found = False
    for runner in node_runners:
        if runner.get("id") == runner_id:
            runner_found = True
            break
    
    if not runner_found:
        return render_template('unregister_runner.html', message=f"Runner ID '{runner_id}' not found on board '{node_name}'.", is_error=True)

    unregister_success = False
    try:
        # Attempt to unregister the GitHub runner using the playbook
        unregister_success = unregister_github_runner_attempt(node_name, runner_id, ANSIBLE_UNREGISTER_RUNNER_LOG_FILE, INVENTORY_FILE, UNREGISTER_GITLAB_RUNNER_PLAYBOOK)

        if unregister_success:
            # Remove the runner from the registry
            registry["nodes"][node_name]["runners"] = [
                r for r in registry["nodes"][node_name]["runners"] if r.get("id") != runner_id
            ]
            registry["nodes"][node_name]["runner_count"] = len(registry["nodes"][node_name]["runners"])
            save_registry(registry, RUNNER_REGISTRY_FILE)
            logger.info(f"Runner '{runner_id}' successfully removed from board '{node_name}' in registry.")
            message = f"GitHub Runner '{runner_id}' successfully unregistered from board '{node_name}' and removed."
            is_error = False
        else:
            message = f"Failed to unregister GitHub Runner '{runner_id}' from board '{node_name}'. Please check the logs ({ANSIBLE_UNREGISTER_RUNNER_LOG_FILE}) for details."
            is_error = True
    except Exception as e:
        logger.error(f"An unexpected error occurred during GitHub runner unregistration: {e}")
        message = f"An unexpected error occurred: {e}"
        is_error = True
    
    return render_template('unregister_runner.html', message=message, is_error=is_error)


# Run the Flask app
if __name__ == '__main__':
    # Create necessary directories if they don't exist
    os.makedirs(os.path.join(APP_ROOT, "ansible"), exist_ok=True)
    os.makedirs(os.path.join(APP_ROOT, "static"), exist_ok=True)
    os.makedirs(os.path.join(APP_ROOT, "templates"), exist_ok=True)
    os.makedirs(os.path.join(APP_ROOT, "logs"), exist_ok=True)

    # Initialize the registry file if it doesn't exist to ensure initial structure
    load_registry(RUNNER_REGISTRY_FILE)

    app.run(debug=True) # Set debug=False for production
