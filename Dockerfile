FROM docker.io/riscv64/debian:trixie

RUN apt-get update && apt-get install -y curl git ca-certificates libicu-dev sudo


WORKDIR /home/runner

RUN chown -R runneruser:runneruser /home/runner

# Download GitHub runner (replace URL with the latest for your architecture)
RUN curl -O -L https://github.com/dkurt/github_actions_riscv/releases/download/v2.321.0/actions-runner-linux-riscv64-2.321.0.tar.gz && \
    tar xzf actions-runner-linux-riscv64-2.321.0.tar.gz && rm actions-runner-linux-riscv64-2.321.0.tar.gz

# Install dependencies for the runner (if any)
RUN bash ./bin/installdependencies.sh

# Install .NET SDK for RISC-V
RUN curl -LO https://github.com/dkurt/dotnet_riscv/releases/download/v9.0.100/dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz && \
    mkdir -p /opt/dotnet && \
    tar -xzf dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz -C /opt/dotnet && \
    rm dotnet-sdk-9.0.100-linux-riscv64-gcc-ubuntu-24.04.tar.gz && \
    ln -s /opt/dotnet/dotnet /usr/local/bin/dotnet

RUN chown -R runneruser:runneruser /home/runner


# Copy entrypoint script
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

# Add a user which will run the github actions
RUN useradd -m runneruser


# Add runneruser to sudoers without password prompt
RUN echo "runneruser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runneruser

USER runneruser

RUN dotnet --info



ENTRYPOINT ["./entrypoint.sh"]

