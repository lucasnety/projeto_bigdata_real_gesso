#=====================================================================
# Projeto Integrado de Data Science — Checkpoint 01 (DevOps)
#
# Provisiona 2 máquinas virtuais Linux locais via OpenTofu, usando o
# provider libvirt (KVM/QEMU), configuradas automaticamente por
# cloud-init:
#
#   devops1 -> roda o simulador de dados (pasta /opt/datasci) e expõe
#              os dados via nginx na porta 8080 (uso interno)
#   devops2 -> roda nginx como proxy reverso na porta 80, repassando
#              as requisições para devops1:8080
#
# Pré-requisitos no host (ver README.md):
#   - Linux com suporte a KVM (não funciona dentro do WSL)
#   - libvirt + qemu-kvm instalados e o serviço libvirtd ativo
#   - OpenTofu instalado (tofu >= 1.6)
#=====================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.8"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "libvirt" {
  uri = var.libvirt_uri
}

#--- Armazenamento -----------------------------------------------------

resource "libvirt_pool" "datasci" {
  name = "datasci_pool"
  type = "dir"
  target {
    path = var.pool_path
  }
}

# Imagem base (baixada uma única vez e clonada para cada VM)
resource "libvirt_volume" "base_image" {
  name   = "ubuntu-jammy-base.qcow2"
  pool   = libvirt_pool.datasci.name
  source = var.base_image_url
  format = "qcow2"
}

resource "libvirt_volume" "vm_disk" {
  for_each       = var.vms
  name           = "${each.key}.qcow2"
  pool           = libvirt_pool.datasci.name
  base_volume_id = libvirt_volume.base_image.id
  size           = var.disk_size_gb * 1024 * 1024 * 1024
}

#--- cloud-init ----------------------------------------------------------
# Mesmo arquivo cloud_init.cfg é reaproveitado para as duas VMs,
# parametrizado com o hostname e a chave pública SSH.

resource "libvirt_cloudinit_disk" "init" {
  for_each = var.vms
  name     = "${each.key}-cloudinit.iso"
  pool     = libvirt_pool.datasci.name

  user_data = templatefile("${path.module}/cloud_init.cfg", {
    hostname = each.key
    username = var.admin_username
    ssh_key  = var.ssh_public_key
  })
}

#--- Rede -----------------------------------------------------------------

resource "libvirt_network" "datasci_net" {
  name      = "datasci-net"
  mode      = "nat"
  domain    = "datasci.local"
  addresses = [var.network_cidr]

  dhcp {
    enabled = true
  }
}

#--- Máquinas virtuais ------------------------------------------------------

resource "libvirt_domain" "vm" {
  for_each = var.vms

  name   = each.key
  memory = each.value.memory
  vcpu   = each.value.vcpu

  cloudinit = libvirt_cloudinit_disk.init[each.key].id

  network_interface {
    network_id     = libvirt_network.datasci_net.id
    hostname       = each.key
    wait_for_lease = true
  }

  disk {
    volume_id = libvirt_volume.vm_disk[each.key].id
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }

  graphics {
    type        = "spice"
    listen_type = "address"
    autoport    = true
  }
}

#--- Inventário do Ansible gerado automaticamente ----------------------------
# Depois do `tofu apply`, o inventory.ini é escrito sozinho com o IP
# real de cada VM — não precisa editar nada à mão.

resource "local_file" "ansible_inventory" {
  filename = "${path.module}/ansible/inventory.ini"

  content = templatefile("${path.module}/ansible/inventory.ini.tpl", {
    devops1_ip = libvirt_domain.vm["devops1"].network_interface[0].addresses[0]
    devops2_ip = libvirt_domain.vm["devops2"].network_interface[0].addresses[0]
    username   = var.admin_username
  })
}
