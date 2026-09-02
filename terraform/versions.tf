# versions.tf
# Pins the Terraform version and provider versions. I do this on every root
# module for the same reason I do it in terraform-infra-25c-redhat: a
# teammate (or me, six months from now) running `terraform init` should get
# the exact same provider behavior I tested against, not whatever shipped
# last week.

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # The kubernetes provider lets Terraform create native K8s RBAC objects
    # (Role/RoleBinding) directly, so the least-privilege access I grant the
    # Lambda's IAM role is itself version-controlled IaC instead of a
    # kubectl command someone ran once and forgot about.
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# The kubernetes provider needs to authenticate to the EKS control plane the
# same way `kubectl` does: an STS-signed bearer token. `aws_eks_cluster_auth`
# generates that token using whatever AWS credentials Terraform is already
# running as (my local profile, or a CI role) - no separate kubeconfig file
# needed just to apply this module.
data "aws_eks_cluster" "target" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "target" {
  name = var.eks_cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.target.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.target.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.target.token
}
