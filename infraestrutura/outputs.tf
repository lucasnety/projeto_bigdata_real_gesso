output "vm_ips" {
  description = "Endereço IP atribuído a cada máquina virtual"
  value = {
    for name, vm in libvirt_domain.vm :
    name => try(vm.network_interface[0].addresses[0], "ainda sem IP (aguarde o boot)")
  }
}

output "ssh_devops1" {
  description = "Comando pronto para acessar a VM do simulador"
  value       = "ssh ${var.admin_username}@${try(libvirt_domain.vm["devops1"].network_interface[0].addresses[0], "<ip-pendente>")}"
}

output "ssh_devops2" {
  description = "Comando pronto para acessar a VM do proxy"
  value       = "ssh ${var.admin_username}@${try(libvirt_domain.vm["devops2"].network_interface[0].addresses[0], "<ip-pendente>")}"
}

output "url_proxy" {
  description = "URL pública (via devops2, porta 80) para ver os dados do simulador"
  value       = "http://${try(libvirt_domain.vm["devops2"].network_interface[0].addresses[0], "<ip-pendente>")}/"
}
