# EKS + VPC with Terraform modules

A beginner lab with S3 remote state and DynamoDB locking. Commands below use Bash (Linux, macOS or WSL). The files have been prepared, not deployed. Terraform and AWS CLI were unavailable in the authoring environment, so provider/module validation and an AWS plan must be run before deployment.

## 1. Understand what you are creating

| Component | Purpose |
|---|---|
| VPC module | Creates a separate network: 10.0.0.0/16 |
| Two public subnets | Internet gateway routing; NAT gateway in the first subnet |
| Two private subnets | Worker placement across two available zones |
| One NAT gateway | Lets private workers download images and contact AWS APIs |
| EKS module | Creates the Kubernetes control plane, security groups and IAM roles |
| Managed node group | Starts one t3.medium EC2 worker; minimum 1, maximum 2 |
| S3 bucket | Stores Terraform's resource inventory, the state file |
| DynamoDB table | Coordinates locks so two Terraform processes do not change one state concurrently |

**State is stored in S3, not DynamoDB.** DynamoDB is the lock coordinator. Its partition key must be exactly `LockID` of type String.

This is a paid lab. EKS, EC2, EBS, NAT, public IPv4 and other usage can generate charges. One NAT and one worker reduce the lab footprint but do not provide production availability. Two subnets do not mean two workers. A maximum node count alone does not install an autoscaler.

## 2. File map

| File/folder | What it does |
|---|---|
| `bootstrap/main.tf` | Creates and protects the bucket and lock table |
| `bootstrap/versions.tf` | Terraform/provider constraints and AWS region |
| `bootstrap/variables.tf` | Backend input definitions |
| `bootstrap/outputs.tf` | Generates backend connection settings |
| `bootstrap/terraform.tfvars.example` | Your backend settings template |
| `bootstrap/backend.tf.example` | Activated after the backend exists |
| `infra/versions.tf` | AWS provider and partial S3 backend declaration |
| `infra/main.tf` | Calls the reusable VPC and EKS registry modules |
| `infra/variables.tf` | Defines cluster inputs |
| `infra/terraform.tfvars.example` | Your cluster settings template |
| `infra/outputs.tf` | Displays cluster details and kubectl command |

There is no local modules folder: `terraform init` downloads the modules from the Terraform Registry into `.terraform/modules`. `module.vpc.private_subnets` passes VPC outputs into EKS inputs.

## 3. Prepare your workstation and AWS identity

Install Terraform >= 1.10 and < 1.17, current AWS CLI v2, and kubectl compatible with Kubernetes 1.35. This project constrains AWS provider to >= 6.59 and < 7.0, VPC module to 6.x, and EKS module to 21.x.

```bash
terraform version
aws --version
kubectl version --client
```

Configure your AWS profile using your organization's approved authentication method, preferably temporary credentials or SSO. For an existing SSO profile:

```bash
export AWS_PROFILE=your-profile
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity
```

For an IAM-user profile, `aws configure --profile your-profile` is another option. Never place access keys in Terraform files or send them in chat.

The provisioning identity needs permission to manage the lab's S3, DynamoDB, VPC/EC2, EKS, IAM (including PassRole), KMS and CloudWatch resources. Organization policies, permission boundaries and quotas may still restrict provisioning. The EKS access entry controls Kubernetes access; it does not grant AWS provisioning permissions.

Determine these inputs:

- A globally unique S3 name, for example `ali-eks-tfstate-ACCOUNTNUMBER-UNIQUE-SUFFIX`, all lowercase.
- Your current public IPv4 address, followed by `/32`. This is your Internet egress address, not your laptop's private `192.168.x.x` address.
- Your administrator's permanent IAM role or user ARN. Use the IAM console to copy it. An STS `assumed-role` session ARN from `get-caller-identity` cannot be used directly; use the underlying IAM role ARN including any path. Do not use the AWS root identity.

The lab defaults to `us-east-1` and Kubernetes `1.35`. Check availability before applying:

```bash
aws eks describe-cluster-versions --region us-east-1 --output table
```

## 4. Create the backend first

Start in the extracted `eks-terraform` folder:

```bash
cd bootstrap
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```

Set a unique bucket name; keep the region and table name or change them deliberately. Then run:

```bash
terraform init
terraform fmt
terraform validate
terraform plan -out=bootstrap.tfplan
terraform apply bootstrap.tfplan
```

`init` installs providers, `validate` checks configuration, `plan` previews changes, and `apply` creates the reviewed resources. Applying a saved plan executes it directly without another confirmation prompt.

Expected: a private versioned encrypted bucket, an HTTPS-only bucket policy and an on-demand DynamoDB table. The bootstrap state is initially local because an S3 backend cannot use a bucket that does not yet exist. Do not delete that local state before migration.

Generate both backend configuration files:

```bash
terraform output -raw infra_backend_config > ../infra/backend.hcl
terraform output -raw bootstrap_backend_config > backend.hcl
```

These files contain names and paths, not AWS credentials. The two state keys are deliberately different:

- `eks-lab/bootstrap/terraform.tfstate`
- `eks-lab/infra/terraform.tfstate`

Do not point two independent configurations at the same state key.

## 5. Move bootstrap state into S3

Still inside `bootstrap`:

```bash
cp backend.tf.example backend.tf
terraform init -migrate-state -backend-config=backend.hcl
```

Read the migration prompt and answer `yes` to copy the existing state into S3. This moves Terraform's inventory, not the AWS resources.

```bash
terraform state list
terraform plan
```

Expected: the backend resources remain in state and the plan reports no changes. S3 now stores both backend infrastructure state and, after the next step, EKS/VPC state under separate keys. The bucket and table have `prevent_destroy`; retain them during ordinary cluster cleanup.

## 6. Create the VPC and EKS cluster

```bash
cd ../infra
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```

Replace `admin_cidr` and `admin_principal_arn`. Ensure you can authenticate as the specified administrator later. Then:

```bash
terraform init -backend-config=backend.hcl
terraform fmt
terraform validate
terraform plan -out=eks.tfplan
terraform apply eks.tfplan
```

Review the account, region, node size and paid resources in the plan before applying. Creation can take tens of minutes. Terraform handles dependencies: the network and routing must exist before worker startup. No Kubernetes or Helm provider is needed for this infrastructure stage.

Commit the generated `.terraform.lock.hcl` files if using Git. They lock providers, not module versions. For a repeatable team project, record the selected module versions from `.terraform/modules/modules.json` and replace the module ranges with those exact versions before sharing.

## 7. Connect and verify

Use AWS credentials for the administrator specified in `admin_principal_arn`. If using a different profile, switch `AWS_PROFILE` before running these commands. The identity also needs AWS `eks:DescribeCluster` permission.

```bash
aws eks update-kubeconfig --region us-east-1 --name eks-lab
kubectl get nodes -o wide
kubectl get pods -n kube-system
kubectl auth can-i create deployments --namespace default
terraform state list
```

Use your chosen region/name if you changed the defaults. `terraform output -raw configure_kubectl` prints the matching kubeconfig command.

Expected: one Ready node, CoreDNS/VPC CNI/kube-proxy healthy, and `yes` for the authorization check. Nodes have no public IPs; they reach the Internet through NAT and the EKS API through the private endpoint. Your laptop reaches the public API only from the allowed `/32`.

Optional application check (no cloud load balancer created):

```bash
kubectl create deployment nginx --image=nginx:stable
kubectl rollout status deployment/nginx --timeout=180s
kubectl port-forward deployment/nginx 8080:80
```

Open http://localhost:8080. Use Ctrl+C to stop port-forwarding. To remove the test app:

```bash
kubectl delete deployment nginx
```

In S3, inspect the two object keys and their versions. DynamoDB's active lock record is temporary, so it may disappear after Terraform completes; a consistency record can remain.

## 8. Common problems

| Symptom | Check and correction |
|---|---|
| NoSuchBucket during init | Finish bootstrap; regenerate backend.hcl; check profile and bucket region |
| BucketAlreadyExists | Choose another globally unique bucket name before successful creation |
| AccessDenied | Inspect the exact failed AWS action, active identity and organizational policies |
| Invalid principal ARN | Supply a real IAM role/user ARN, including any role path; not STS session ARN |
| kubectl timeout | Verify your current public IP matches admin_cidr; update Terraform if it changed |
| kubectl Unauthorized/Forbidden | Check `aws sts get-caller-identity` and use the configured administrator |
| Nodes fail to join | Inspect node group health, NAT/routes, EC2 capacity, IAM and regional version availability |
| State lock error | Check if another plan/apply is running and wait; do not disable locking |
| DynamoDB deprecation warning | Expected for this requested legacy locking setup; see migration below |

Never force-unlock an active operation. After interruption, inspect the current state and plan again; do not reuse a stale saved plan blindly.

## 9. Remove the paid cluster after practice

Remove any Services/Ingresses/controllers that created load balancers and any unneeded persistent volumes while the cluster still works. Otherwise AWS resources created outside Terraform can remain or block VPC deletion.

From `infra` with the provisioning profile restored:

```bash
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan
```

This deletes the infrastructure managed by `infra`, including EKS, workers and NAT. Keep the backend bucket/table so the final state remains accessible. They can still have small storage/request charges. Check AWS for resources created by your workloads and retained volumes/snapshots.

Do not run `terraform destroy` in `bootstrap` as routine cleanup. Full backend retirement is separate: confirm no state consumers remain, securely archive/migrate state, and deliberately remove protection only when retiring the backend itself. Versioned buckets also retain old object versions.

## 10. DynamoDB locking and the modern alternative

DynamoDB locking is included as requested, but HashiCorp has deprecated it. The current replacement is S3 native locking (`use_lockfile = true`). To transition a team safely:

1. Ensure every Terraform client supports S3 locking (Terraform >= 1.10).
2. Add `use_lockfile = true` to both backend.hcl files while retaining `dynamodb_table`. Update the output templates too if regenerating these files.
3. Grant GetObject, PutObject and DeleteObject on each state key's `.tflock` object, in addition to state/bucket permissions.
4. Reinitialize each root with `terraform init -reconfigure -backend-config=backend.hcl` and coordinate adoption by all clients.
5. Once all clients use S3 locking, remove `dynamodb_table` and reinitialize again. Retire the DynamoDB table only after all consumers have migrated.

For the requested DynamoDB backend, runtime access includes S3 ListBucket, GetObject/PutObject on the relevant state keys, and DynamoDB DescribeTable/GetItem/PutItem/DeleteItem on the lock table. Infrastructure provisioning requires additional permissions.

## References

- [HashiCorp S3 backend and locking](https://developer.hashicorp.com/terraform/language/backend/s3)
- [VPC module documentation](https://github.com/terraform-aws-modules/terraform-aws-vpc)
- [EKS module documentation](https://github.com/terraform-aws-modules/terraform-aws-eks)
- [AWS EKS supported versions](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html)
- [Terraform installation](https://developer.hashicorp.com/terraform/install)
- [AWS CLI installation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
