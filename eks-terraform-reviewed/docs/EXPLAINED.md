# Easy notes: what each part does

Think of Terraform as a builder using a written design. AWS is where the actual resources live. The state file is Terraform's record of what it already built.

| Word | Simple meaning in this project |
|---|---|
| Terraform configuration | The `.tf` files describing the resources you want. |
| Root module | The folder where you run Terraform. All its `.tf` files are read together. |
| Module | Reusable Terraform code. The VPC module builds networking; the EKS module builds the cluster and related resources. |
| Provider | The plugin that talks to an API. The AWS provider makes AWS API requests. |
| Variable | A configurable input, such as the cluster name. |
| Output | A useful value Terraform prints after deployment, such as the VPC ID. |
| State | Terraform's mapping from configuration addresses to real AWS resources. |
| Backend | Where Terraform keeps state and how it coordinates access to it. |
| S3 bucket | The storage container for state files. The real bucket must exist before S3 backend init. |
| State key | The object's path inside the bucket, for example `eks-lab/infra/terraform.tfstate`. It is not the bucket name. |
| DynamoDB table | Coordinates a lock so two Terraform runs do not write the same state simultaneously. It does not store the full Terraform state file. |
| LockID, type S | The table's partition-key attribute, with String type. Terraform creates lock-item values; you do not invent a LockID for each run. |
| IAM ARN | The full identifier of an AWS identity. An IAM role ARN is permanent; an STS assumed-role session ARN describes one temporary login session. |
| Account ID | The 12-digit AWS account identifier. It is different from a resource ID such as `vpc-...`. |

## Why bootstrap remains separate

Terraform initializes its backend **before** it builds resources. An S3 backend therefore cannot depend on a bucket that the same initial apply has not created yet.

`bootstrap/` first uses local state to create the bucket and locking table. Setup then moves that bootstrap state to S3 under `eks-lab/bootstrap/terraform.tfstate`. The root VPC/EKS project uses a different object, `eks-lab/infra/terraform.tfstate`, in the same bucket. Two configurations must not use the same state key.

The Python helper runs those steps in order. You remain in the root folder. A `module "bootstrap"` inside the root would not solve the backend-first requirement.

## What the main settings build

| Setting/resource | Purpose |
|---|---|
| `cidr = "10.0.0.0/16"` | The address range for the VPC. |
| Two availability zones | Place subnets across two separate AWS zones, as EKS requires. |
| Public subnets | Have internet-gateway routing. They host the NAT gateway and can support internet-facing load balancers. |
| Private subnets | Host workers without giving them public IPv4 addresses. |
| Internet gateway | Connects the VPC's public routing to the internet. |
| NAT gateway | Lets private workers initiate internet connections, such as downloading container images. |
| DNS settings | Let instances and cluster components resolve names correctly. |
| Subnet `elb`/`internal-elb` tags | Help compatible load-balancer controllers discover suitable public/private subnets. |
| EKS control plane | AWS-managed Kubernetes API and control-plane services. |
| Managed node group | EC2 workers managed through EKS. This lab starts one worker. |
| `min_size`, `desired_size`, `max_size` | Lower limit, requested count, and upper limit. These settings alone do not install an autoscaler. |
| `AL2023_x86_64_STANDARD` | Amazon Linux 2023 worker image family for x86 processors. ARM instance types require a different image family. |
| Public + private endpoint | Allow Kubernetes API access through the VPC and through the restricted public endpoint. |
| `/32` | Exactly one IPv4 address is allowed by that CIDR. Use the operator machine's internet-facing address. |
| Access entry + admin policy | Give the selected IAM identity Kubernetes cluster-admin permissions. AWS deployment permissions and Kubernetes access are separate. |
| `vpc-cni` | Gives pods networking using the AWS VPC. Installed before workers in this configuration. |
| `kube-proxy` | Implements Kubernetes Service networking rules on nodes. |
| `coredns` | Provides name resolution inside the cluster. |
| `depends_on = [module.vpc]` | Makes the EKS module wait for the VPC module's resources, including routing. |
| `module.vpc.vpc_id` | Takes the ID from the resource Terraform created, avoiding a manually pasted VPC ID. |

## Backend protection settings

S3 versioning retains older state-object versions for recovery. Server-side encryption protects stored objects. Public-access blocking prevents public sharing. The bucket policy denies non-TLS requests. `force_destroy = false` prevents emptying a populated bucket automatically, and `prevent_destroy = true` blocks a planned destroy of the protected resource while that rule remains in the configuration.

These settings do not replace IAM permissions, secure state handling, or backup/recovery procedures. Removing the resource or lifecycle rule from the configuration changes the protection.

## The commands

| Command | What it does |
|---|---|
| `setup` | Checks your environment, creates or reuses the backend, fills values, initializes, and validates. |
| `terraform init` | Installs providers/modules and initializes the selected backend. It does not create the EKS cluster. |
| `terraform validate` | Checks whether the configuration is internally valid. It does not prove AWS permissions or capacity. |
| `terraform plan` | Compares configuration, state, and real resources to propose changes. |
| `-out=eks.tfplan` | Saves that particular plan for review and later apply. |
| `terraform apply eks.tfplan` | Executes the saved plan without asking for another yes/no confirmation. |
| `terraform output` | Shows the configured output values. |
| `destroy-plan` / `destroy-apply` | Prepare and execute a reviewed deletion plan for the root-managed resources. |

`main.tf`, `variables.tf`, and `outputs.tf` are helpful naming conventions. Terraform combines the files; it does not execute `main.tf` first, then `variables.tf`, then `outputs.tf`. Resource references determine the dependency order.
