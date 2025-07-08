FROM docker.io/riscv64/ubuntu:24.04

RUN apt-get update && apt-get install -y docker.io curl git ca-certificates libicu-dev sudo


WORKDIR /home/runner



# Download GitHub runner (replace URL with the latest for your architecture)
RUN curl -O -L https://github.com/dkurt/github_actions_riscv/releases/download/v2.321.0/actions-runner-linux-riscv64-2.321.0.tar.gz && \
    tar xzf actions-runner-linux-riscv64-2.321.0.tar.gz && rm actions-runner-linux-riscv64-2.321.0.tar.gz

# Install dependencies for the runner (if any)
RUN bash ./bin/installdependencies.sh


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

