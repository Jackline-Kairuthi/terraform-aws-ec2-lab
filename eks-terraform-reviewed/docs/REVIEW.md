# Review of the uploaded Terraform project

Reviewed 1 October 2026. The upload contained templates and example inputs, but no actual backend configuration, deployed state, real account IDs, or credentials. Therefore no specific wrong ARN, resource ID, or bucket name could be confirmed from the upload.

The original `bootstrap/` and `infra/` design was valid. Each directory was an independent Terraform root. Terraform reads the `.tf` files in its working directory; it does not automatically execute child folders. A parent `main.tf` was not missing for that original design. This revision moves the former `infra` configuration to the top level to match your preferred workflow.

## Findings and changes

| Finding in the original files | Consequence | Revision |
|---|---|---|
| Empty `backend "s3" {}` required separate backend configuration. | Plain `terraform init` asks for the bucket and other required backend fields. | Setup writes literal, complete backend values before root init. |
| Example files required manual copying and editing. | Required variables could prompt; example account/ARN/IP values could fail AWS validation. | Setup detects real values and writes auto-loaded JSON inputs. |
| Backend resources must exist before an S3 backend initializes. | Adding all resources to one root cannot solve the first-run dependency. | Automated bootstrap first, then state migration, then root init. |
| First two sorted AZ names were used. | A selected AZ might be disallowed for EKS or not offer the chosen instance type. | Query AZ IDs and instance offerings, exclude documented EKS exclusions, require two suitable zones. |
| User supplied the administrator ARN. | Root, STS session ARNs, incorrect role paths, deleted identities, or the wrong account can fail. | Resolve permanent IAM ARN through IAM; verify account/path; reject unsupported principals. |
| User supplied the public endpoint CIDR. | A placeholder/private address or another machine's address can make kubectl unreachable. | Detect IPv4 `/32`, validate it, and allow an explicit real address in settings. |
| No account guard in provider/backend. | Switching AWS profiles could read or change a different account's infrastructure. | Capture the account and enforce `allowed_account_ids`; check STS in helper commands. |
| Broad provider/module version ranges and no included provider lockfiles. | A later init can select different releases. | Pin direct modules/provider and include generated provider lockfiles. |
| New state can be confused with existing infrastructure. | Terraform can plan duplicate resources or fail with “already exists.” | Explicit backend reuse; verify state cluster ARN; preserve recorded subnet AZ order. |
| Normal apply asks for approval. | User must type `yes`; unattended runs can fail. | Save the plan and apply that file, with interactive input disabled. |
| No helper guard against accidental destructive changes. | Wrong settings could replace resources. | Normal helper apply blocks deletes/replacements by default and rejects plans after configuration changes. |

Resource addresses `module.vpc` and `module.eks` are retained. Moving files out of `infra/` does not itself change those addresses when the same state is used. Changing the backend **key**, module labels, subnet ordering, or cluster name is a different matter and can cause major changes. Reuse still requires reviewing a fresh plan; exact version pins can introduce upgrades relative to an older deployment.

## Versions and remaining moving parts

| Component | Selected version/range |
|---|---|
| Terraform | Stable `>= 1.10, < 1.17`; offline checks used 1.13.5. |
| AWS provider | `6.67.0` |
| VPC module | `6.7.3` |
| EKS module | `21.26.0` |
| Kubernetes default | `1.35`; setup checks actual regional standard-support availability. |
| Worker image family | `AL2023_x86_64_STANDARD` |

The top-level module versions are pinned. Terraform's provider lockfile does **not** lock transitive module versions. The downloaded EKS module selected KMS module 4.0.0 during this review. Add-on versions and AMI releases are also resolved by the module/provider; new compatible releases can appear in later plans. Review those changes. This is a learning project, not a fully frozen production release process.

DynamoDB locking is retained because it was requested. HashiCorp now deprecates this locking method in favor of S3 lockfiles. The upper Terraform bound is a conservative compatibility boundary, not a statement that removal occurs exactly in 1.17. Review backend migration before changing this bound.

## What was actually checked

| Check | Result |
|---|---|
| Inspect all uploaded Terraform files and restructure the root | Completed. |
| Parse/format all revised HCL using `terraform fmt -check -recursive` | Passed. |
| Download modules and authenticated provider packages; init with backend disabled | Passed using downloaded dependencies. Backend connectivity was not tested. |
| Compare EKS module input/output names and nested input structure against downloaded source | Completed; selected arguments match the selected module. |
| Bash syntax and Python compilation | Passed. |
| 26 offline helper tests | Passed. Includes account/ARN/CIDR/AZ/state checks, setup order, interrupted migration, stale plans, and replacement protection. |
| Full `terraform validate` for root and bootstrap | **Blocked by this execution environment.** Provider startup returned `listen unix /tmp/plugin...: socket: operation not permitted`. This is not a successful validation result. |
| Real S3/DynamoDB backend initialization, AWS plan/apply, node readiness, kubectl access | **Not run.** No AWS credentials were provided for a live test. |

One local provider download left incomplete cache files; the actual provider binary matched the originally authenticated package hash. The cache was repaired without disabling checksums. Provider caches and validation logs are not included in the deliverable.

`terraform fmt` confirms HCL parses; it does not replace provider-backed validation or a real plan. No AWS infrastructure can be guaranteed error-free using source review alone. Setup runs `terraform validate` on your machine, and the subsequent plan checks your actual account.

To repeat the offline helper tests:

```bash
python3 -m unittest discover -s tests -v
bash -n run.sh
terraform fmt -check -recursive
```

To validate without creating any resources, before setup:

```bash
terraform init -backend=false -input=false
terraform validate
terraform -chdir=bootstrap init -backend=false -input=false
terraform -chdir=bootstrap validate
```

Backend-disabled init only installs dependencies. It does not make this configuration ready for a real plan; run the appropriate setup route afterward.

## Primary references

- [Terraform S3 backend, locking, state keys, and permissions](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform backend configuration and initialization](https://developer.hashicorp.com/terraform/language/backend)
- [AWS EKS subnet/AZ requirements](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html)
- [AWS CLI EKS version support query](https://docs.aws.amazon.com/cli/latest/reference/eks/describe-cluster-versions.html)
- [Selected EKS module source](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/v21.26.0)
- [Selected VPC module source](https://github.com/terraform-aws-modules/terraform-aws-vpc/tree/v6.7.3)
