# Enable required GCP APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# Artifact Registry repository for Docker images
resource "google_artifact_registry_repository" "t2d2" {
  location      = var.region
  repository_id = "t2d2"
  format        = "DOCKER"
  description   = "T2-D2 container images"

  depends_on = [google_project_service.apis]
}

# Service account for Cloud Run Jobs
resource "google_service_account" "t2d2_runner" {
  account_id   = "t2d2-runner"
  display_name = "T2-D2 Cloud Run Job Runner"
}

# Allow runner SA to access secrets
resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.t2d2_runner.email}"
}

# Allow runner SA to write logs
resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.t2d2_runner.email}"
}

# Service account for Cloud Scheduler to invoke Cloud Run Jobs
resource "google_service_account" "t2d2_scheduler" {
  account_id   = "t2d2-scheduler"
  display_name = "T2-D2 Cloud Scheduler Invoker"
}

resource "google_project_iam_member" "run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.t2d2_scheduler.email}"
}
