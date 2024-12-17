resource "google_compute_instance" "worker_cpu" {
  name         = "worker-cpu-pool-member-${count.index}"
  count = var.worker_count
  machine_type = "e2-standard-2"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "projects/integrador-sdypp/global/images/packer-1734059877"
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    echo "${var.env}" > .env

    # Ejecutar el contenedor Docker y redirigir los logs a un archivo
    docker run -d -p 5000:5000 \
      --name worker-cpu \
      --env-file .env \
      grupo4sdypp2024/tp-integrador-cpu-worker:1.0.1 > worker-cpu.log 2>&1

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

variable "worker_count" {
  type    = number
  default = 2
}
