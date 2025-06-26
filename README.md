# GitHub Actions on RISC-V

This repository sets up github actions inside a podman container on a RISC-V machine. The setup is tested on Milk-V Pioneer Box.

It uses https://github.com/dkurt/github_actions_riscv as the GitHub actions for RISC-V *(for now)*.

Running the [setup.sh](/setup.sh) on the RISC-V machine with sudo privileges will automatically build the github actions on the machine.

Alternatively, if you are provisioning multiple RISC-V runners, you can also use [ansible playbook](/ansible/playbook.yaml) for consistency. For using the playbook, you will have to set up the board's IP and port inside the [inventory.ini](/ansible/inventory.ini) and change the `hosts` to the name of the board or the group of the boards which you would like to set up inside the [playbook.yaml](/ansible/playbook.yaml)