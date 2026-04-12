locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/t2d2/scheduler:${var.image_tag}"

  # Common environment variables for all job executions
  common_env = [
    {
      name  = "T212_BASE_URL"
      value = var.t212_base_url
    },
    {
      name  = "STRATEGY_MODE"
      value = var.strategy_mode
    },
    {
      name  = "DRY_RUN"
      value = tostring(var.dry_run)
    },
    {
      name  = "FCM_TOPIC"
      value = var.fcm_topic
    },
    {
      name  = "FIREBASE_CREDENTIALS"
      value = "/secrets/firebase/credentials.json"
    },
    {
      name  = "LOG_LEVEL"
      value = "INFO"
    },
  ]
}

# Cloud Run Job — one job definition, invoked per-session by Cloud Scheduler
resource "google_cloud_run_v2_job" "t2d2_scheduler" {
  name     = "t2d2-scheduler"
  location = var.region

  template {
    template {
      service_account = google_service_account.t2d2_runner.email

      # Job timeout: 10 minutes per session run
      timeout = "600s"

      containers {
        image = local.image

        # Session passed at invocation time via args override in scheduler
        args = ["--session", "eu_morning"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.value.name
            value = env.value.value
          }
        }

        # Trading212 API key from Secret Manager
        env {
          name = "T212_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.t212_api_key.secret_id
              version = "latest"
            }
          }
        }

        # Firebase credentials mounted as a volume
        volume_mounts {
          name       = "firebase-secret"
          mount_path = "/secrets/firebase"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      volumes {
        name = "firebase-secret"
        secret {
          secret = google_secret_manager_secret.firebase_credentials.secret_id
          items {
            version = "latest"
            path    = "credentials.json"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.t2d2,
  ]

  lifecycle {
    ignore_changes = [
      # Image tag is managed by CI/CD, not Terraform
      template[0].template[0].containers[0].image,
    ]
  }
}
