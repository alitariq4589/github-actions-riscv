#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

echo "Starting setup for board."

# --- Task: Install packages ---
echo "Installing packages: podman, docker.io..."
# The 'async' and 'poll' functionality from Ansible's apt module is not directly replicated.
# apt will run synchronously.
sudo apt update
sudo apt install -y podman docker.io

# --- Task: Add subuid line if missing ---
echo "Checking /etc/subuid for github-runner-user entry..."
SUB_UID_CHANGED=0
if ! grep -q "^github-runner-user:262144:65536$" /etc/subuid; then
    echo "Adding github-runner-user:262144:65536 to /etc/subuid"
    echo "github-runner-user:262144:65536" | sudo tee -a /etc/subuid
    SUB_UID_CHANGED=1
else
    echo "/etc/subuid entry for github-runner-user already exists."
fi

# --- Task: Add subgid line if missing ---
echo "Checking /etc/subgid for github-runner-user entry..."
SUB_GID_CHANGED=0
if ! grep -q "^github-runner-user:262144:65536$" /etc/subgid; then
    echo "Adding github-runner-user:262144:65536 to /etc/subgid"
    echo "github-runner-user:262144:65536" | sudo tee -a /etc/subgid
else
    echo "/etc/subgid entry for github-runner-user already exists."
fi

# --- Task: Run podman system migrate if subuid/subgid was changed ---
if [ "$SUB_UID_CHANGED" -eq 1 ] || [ "$SUB_GID_CHANGED" -eq 1 ]; then
    echo "Subuid or subgid was changed. Running 'podman system migrate' as github-runner-user..."
    sudo -u github-runner-user podman system migrate
else
    echo "No changes to subuid/subgid. Skipping 'podman system migrate'."
fi

# --- Task: Add user lingering ---
echo "Enabling user lingering for github-runner-user..."
# This command needs to be run as root to enable lingering for a specific user
# However, the Ansible task 'become_user: github-runner-user' context might imply loginctl is run by github-runner-user itself.
# loginctl enable-linger is typically run by root against a user.
# Let's run it as root, targeting github-runner-user.
loginctl enable-linger github-runner-user

# --- Task: Create a temporary directory in /home/github-runner-user ---
CURRENT_EPOCH=$(date +%s)
TEMP_DIR_PATH="/home/github-runner-user/dockerbuild_${CURRENT_EPOCH}"
echo "Creating temporary directory: ${TEMP_DIR_PATH} as github-runner-user..."
sudo -u github-runner-user mkdir -p "${TEMP_DIR_PATH}"
echo "Temporary directory created: ${TEMP_DIR_PATH}"


# --- Task: Write Dockerfile to temporary directory ---
echo "Writing Dockerfile to ${TEMP_DIR_PATH}/Dockerfile..."
sudo -u github-runner-user bash -c "cat << 'EOF_DOCKERFILE' > \"${TEMP_DIR_PATH}/Dockerfile\"
FROM docker.io/riscv64/debian:trixie
RUN apt-get update && apt-get install -y curl git ca-certificates libicu-dev sudo
WORKDIR /home/runner

# Download GitHub runner (replace URL with the latest for your architecture)
RUN curl -O -L https://github.com/dkurt/github_actions_riscv/releases/download/v2.321.0/actions-runner-linux-riscv64-2.321.0.tar.gz && \\
    tar xzf actions-runner-linux-riscv64-2.321.0.tar.gz && rm actions-runner-linux-riscv64-2.321.0.tar.gz

# Install dependencies for the runner (if any)
RUN bash ./bin/installdependencies.sh

# Install .NET SDK for RISC-V
RUN curl -LO https://github.com/dkurt/dotnet_riscv/releases/download/v9.0.100/dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz && \\
    mkdir -p /opt/dotnet && \\
    tar -xzf dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz -C /opt/dotnet && \\
    rm dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz && \\
    ln -s /opt/dotnet/dotnet /usr/local/bin/dotnet

# Copy entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Add a user which will run the github actions
RUN useradd -m runneruser
RUN chown -R runneruser:runneruser /home/runner

# Add runneruser to sudoers without password prompt
RUN echo "runneruser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runneruser
USER runneruser

ENTRYPOINT ["./entrypoint.sh"]
EOF_DOCKERFILE"
echo "Dockerfile written."


# --- Task: Write entrypoint.sh to temporary directory ---
echo "Writing entrypoint.sh to ${TEMP_DIR_PATH}/entrypoint.sh..."
sudo -u github-runner-user bash -c "cat << 'EOF_ENTRYPOINT' > \"${TEMP_DIR_PATH}/entrypoint.sh\"
#!/bin/bash
set -e
if [[ ! -f \".runner\" ]]; then
  if [[ -z \"\$GITHUB_REPO\" || -z \"\$RUNNER_TOKEN\" ]]; then
    echo \"Missing GITHUB_REPO or RUNNER_TOKEN\"
    exit 1
  fi
  ./config.sh \\
    --url \"\${GITHUB_REPO}\" \\
    --token \"\${RUNNER_TOKEN}\" \\
    --unattended \\
    --replace
  fi

  ./run.sh
EOF_ENTRYPOINT"
echo "entrypoint.sh written."

# --- Task: Build Podman image ---
echo "Building Podman image 'github-action' from ${TEMP_DIR_PATH} as github-runner-user..."
sudo -u github-runner-user podman build -t github-action "${TEMP_DIR_PATH}"
echo "Podman image 'github-action' built successfully."

echo "Setup script finished."