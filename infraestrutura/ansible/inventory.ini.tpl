; Gerado automaticamente pelo OpenTofu (recurso local_file em main.tf)
; depois de `tofu apply`. NÃO editar à mão — e por isso este arquivo
; (o inventory.ini final) fica fora do controle de versão (.gitignore).
; Este .tpl (o modelo) é que fica versionado no repositório.

[devops1]
devops1 ansible_host=${devops1_ip}

[devops2]
devops2 ansible_host=${devops2_ip}

[all:vars]
ansible_user=${username}
ansible_ssh_private_key_file=~/.ssh/id_ed25519
ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
ansible_python_interpreter=/usr/bin/python3
