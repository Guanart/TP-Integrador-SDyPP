resource "google_compute_instance" "worker_pool_manager" {
  name         = "worker-pool-manager"
  machine_type = "e2-standard-2"
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
    sudo docker compose up -d > worker-pool-manager.log 2>&1

    # Instalar Python3 si no está instalado
    apt-get update
    apt-get install -y python3

    # Levantar un servidor HTTP que sirva los logs
    nohup python3 -m http.server 8080 &
  EOT
}

variable "env" {
  type    = string
}