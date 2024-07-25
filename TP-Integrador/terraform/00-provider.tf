
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">=5.26.0"
    }
  }

  backend "gcs" {
    # bucket  = "sdypp-2024-integrador-bucket-tfstate"
    # prefix  = "terraform/state"
  }

  # required_version = ">= 1.7.5"
}

provider "google" {
  project     = var.project_id
  region      = var.region
  zone        = var.zone
}
