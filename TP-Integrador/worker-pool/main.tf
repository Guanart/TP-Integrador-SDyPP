resource "google_compute_instance" "worker_pool_manager" {
  name         = "worker-pool-manager"
  machine_type = "e2-small"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "projects/integrador-sdypp/global/images/worker-pool"
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    cd /home/packer
    sudo git clone https://github.com/Guanart/SDyPP-2024-grupo-4.git
    cd /home/packer/SDyPP-2024-grupo-4/TP-Integrador/worker-pool
    sudo echo "${var.env}" > .env
    sudo docker compose up -d
  EOT
}

variable "env" {
  type    = string
}