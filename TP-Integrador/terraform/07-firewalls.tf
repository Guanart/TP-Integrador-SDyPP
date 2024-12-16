# # https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_firewall
resource "google_compute_firewall" "allow-http-https-ssh-rabbit" {
    name    = "allow-http-https-ssh-rabbit"
    network = google_compute_network.main.name

    allow {
        protocol = "tcp"
        ports    = ["22", "80", "443", "5672", "5000", "5001", "5002", "8001", "15672"]
    }

    source_ranges = ["0.0.0.0/0"]
}

# Firewall para workers en la nube
resource "google_compute_firewall" "allow-http-https-ssh" {
    name    = "allow-http-https-ssh-rabbit-flask"
    network = "default"

    allow {
        protocol = "tcp"
        ports    = ["22", "80", "443", "5000", "5001", "5002", "5672", "15672"]
    }

    source_ranges = ["0.0.0.0/0"]
}
