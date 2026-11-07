terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # State is local by default, which suits one operator and a short-lived demo. The state holds
  # the generated database password, so treat it as a secret (it is gitignored).
  #
  # To share state, create the bucket by hand, uncomment this, and run
  # `terraform init -migrate-state`.
  #
  # backend "s3" {
  #   bucket       = "CHANGE-ME-terraform-state"
  #   key          = "incident-copilot/demo/terraform.tfstate"
  #   region       = "us-east-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
