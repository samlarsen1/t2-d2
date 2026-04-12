# Secret Manager — secrets are created empty; values must be set manually
# or via CI/CD after first apply.

resource "google_secret_manager_secret" "t212_api_key" {
  secret_id = "t2d2-t212-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "firebase_credentials" {
  secret_id = "t2d2-firebase-credentials"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "webhook_url" {
  count     = var.webhook_url != "" ? 1 : 0
  secret_id = "t2d2-webhook-url"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Output secret resource names for manual population
output "secret_t212_api_key_name" {
  value       = google_secret_manager_secret.t212_api_key.name
  description = "Run: gcloud secrets versions add t2d2-t212-api-key --data-file=-"
}

output "secret_firebase_creds_name" {
  value       = google_secret_manager_secret.firebase_credentials.name
  description = "Run: gcloud secrets versions add t2d2-firebase-credentials --data-file=firebase-credentials.json"
}
