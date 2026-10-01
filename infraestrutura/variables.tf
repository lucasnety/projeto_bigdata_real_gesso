#=====================================================================
# Variáveis do provisionamento com OpenTofu + libvirt (KVM/QEMU)
#=====================================================================

variable "libvirt_uri" {
  description = "URI de conexão com o daemon libvirt do host"
  type        = string
  default     = "qemu:///system"
}

variable "pool_path" {
  description = "Diretório local onde os discos das VMs serão armazenados"
  type        = string
  default     = "/var/lib/libvirt/images/datasci"
}

variable "base_image_url" {
  description = "URL da imagem cloud (qcow2) usada como base das VMs"
  type        = string
  default     = "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
}

variable "disk_size_gb" {
  description = "Tamanho do disco de cada VM, em GB"
  type        = number
  default     = 10
}

variable "network_cidr" {
  description = "Faixa de endereços da rede NAT privada criada para as VMs"
  type        = string
  default     = "10.20.30.0/24"
}

variable "ssh_public_key" {
  description = "Conteúdo da chave pública SSH usada para acessar as VMs (ex: cat ~/.ssh/id_ed25519.pub). NUNCA commitar a chave privada."
  type        = string
}

variable "admin_username" {
  description = "Usuário administrativo criado pelo cloud-init em cada VM"
  type        = string
  default     = "aluno"
}

variable "vms" {
  description = "Mapa das máquinas virtuais a provisionar: nome -> recursos (memória em MB, vCPUs) e papel"
  type = map(object({
    memory = number
    vcpu   = number
    role   = string # "simulador" (devops1) ou "proxy" (devops2)
  }))
  default = {
    devops1 = {
      memory = 2048
      vcpu   = 2
      role   = "simulador"
    }
    devops2 = {
      memory = 1024
      vcpu   = 1
      role   = "proxy"
    }
  }
}
