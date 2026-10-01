# EKS + VPC with Terraform — run from this folder

This is the revised version of your uploaded project. `main.tf`, `variables.tf`, `outputs.tf`, `providers.tf`, `versions.tf`, and `backend.tf` are now at the top level. The VPC and EKS still use the official community Terraform AWS modules. There is no separate `infra/` folder in this version.

**Run commands in the extracted `eks-terraform-reviewed` folder. Extract into a new folder; keep your old project and its state until migration is verified.**

The default lab uses `us-east-1`, cluster `eks-lab`, Kubernetes `1.35`, two zones, private worker subnets, one NAT gateway, and one on-demand `t3.medium` worker. The worker group can be scaled to two nodes. These are paid AWS resources. `setup` creates only the backend; `apply` creates the VPC/EKS resources.

## 1. Before starting

Use Linux, macOS, or Ubuntu in WSL on Windows. The helper requires Bash, Python **3.9+**, curl, Git for module downloads, a current **AWS CLI v2**, and stable **Terraform >= 1.10 and < 1.17**. Terraform 1.13.5 was used for the offline checks. This project retains the requested DynamoDB locking; it is deprecated, so future Terraform upgrades need review.

Your AWS CLI must already be signed in to the intended AWS account. An IAM role, EC2 instance role, or IAM Identity Center profile is suitable. With a named profile, select it once in the terminal, for example `export AWS_PROFILE=your-profile`, and authenticate that profile as your organization requires.

Check your identity:

```bash
terraform version
aws --version
python3 --version
aws sts get-caller-identity --region us-east-1
```

Verify the returned account is the one where you want to incur charges. No script can infer which of your AWS accounts you intended on the very first run. Later commands enforce the account captured at setup. Credentials are taken from AWS's normal credential chain; do not put access keys in these Terraform files.

`settings.json` contains all six user settings. Defaults work for a fresh lab when the account, region, version, and instance type are supported. `auto` detects the current IAM role/user and the public IPv4 of the machine running setup. If kubectl will run on a different machine, set `admin_cidr` to **that machine's real public IPv4 followed by `/32`** before setup. Auto-detection behind a proxy or VPN may detect that proxy/VPN's address.

## 2. Choose the correct setup command

### You have never created the old backend or cluster

```bash
cd eks-terraform-reviewed
bash run.sh setup
```

This command performs checks, generates a unique bucket/table name, creates the S3 bucket and DynamoDB locking table, migrates bootstrap state from local disk to S3, writes complete backend and variable values, initializes the root project, and runs Terraform validation. It applies the displayed **backend-only** plan without a yes/no prompt. It does not create EKS yet.

### You already created the backend using the previous project

Use your **actual old `infra/backend.hcl` file**, even if you have not created the cluster yet. For example, if the old project is at `~/eks_cluster`:

```bash
cd eks-terraform-reviewed
bash run.sh setup --reuse-backend ~/eks_cluster/infra/backend.hcl
```

Use the correct path for your machine. This is a one-time selection of an existing backend, not a repeated Terraform input. Match `settings.json` to the old cluster name, region, Kubernetes version, instance type, and intended administrator before starting. Never replace the old state with a new empty state.

Reuse mode verifies the bucket owner/region, DynamoDB key, and any existing EKS state. It preserves the recorded subnet zone order. It supports the original project's default workspace and state key `eks-lab/infra/terraform.tfstate`. Custom state layouts, other workspaces, cross-account backends, or partially recorded subnet layouts need a separate migration review.

Reuse mode leaves ownership of the bucket/table in your **old bootstrap project**. Keep that original bootstrap folder and state. It does not import those resources into the new bootstrap folder or create duplicates. If you created the backend but never saved `backend.hcl`, recover its real values using the old bootstrap outputs and the instructions in `docs/RECOVERY.md`.

## 3. Plan, review, and apply — no values to type

After either setup route succeeds:

```bash
bash run.sh plan
```

Read the plan. For a new lab, it should create the expected VPC and EKS resources. For an existing lab, investigate unexpected deletions or replacements. Then run:

```bash
bash run.sh apply
```

Apply uses the exact saved plan, so Terraform does not request `yes` or variable values. The helper refuses a normal plan containing deletes/replacements unless you deliberately use `bash run.sh apply --allow-replacements` after reviewing them. Do not add that flag just to get past an error.

`setup` already ran init. Later you can run `bash run.sh init` or `bash run.sh validate` from the root. Rerun `bash run.sh setup` after changing supported settings, then make a fresh plan. Do not pass `--reuse-backend` again after the first setup. Region/account/cluster-name changes are treated as migrations and deliberately blocked.

### If you prefer the Terraform commands themselves

After successful setup, these also run from the root without variable prompts:

```bash
terraform init -input=false
terraform plan -input=false -out=eks.tfplan
terraform apply -input=false eks.tfplan
```

Use this sequence on its own; do not mix a directly created plan with the helper's `apply`, because that helper expects its own configuration fingerprint. Direct commands do not get all the helper's extra account/state/workspace/replacement checks.

**A bare `terraform apply` normally still asks for approval.** Terraform does not provide a setting in `main.tf` to disable that prompt. Applying a saved plan is the way this project avoids it. `-input=false` means “fail if a value is missing”; it does not invent missing values.

## 4. Check the cluster

```bash
terraform output
aws eks update-kubeconfig --region us-east-1 --name eks-lab
kubectl get nodes
kubectl get pods -A
```

If you changed the region/name, use the command printed by `terraform output -raw configure_kubectl`. Use the IAM identity granted access during setup. Install a kubectl version compatible with your cluster. The public endpoint accepts only the configured `/32`; private access is also enabled for VPC traffic.

## 5. Finish the lab and control costs

Remove application LoadBalancer Services/Ingress resources and review persistent volume retention before deleting the cluster. Otherwise resources created by Kubernetes controllers can outlive the lab or block VPC deletion.

```bash
bash run.sh destroy-plan
```

Review exactly what will be deleted, then:

```bash
bash run.sh destroy-apply
```

This deletes resources managed by the root VPC/EKS state. It retains the backend bucket/table and state history. Those backend resources have deletion protection in Terraform. See `docs/TROUBLESHOOTING.md` for leftover resources and charges.

## Where everything is

| File/folder | Purpose |
|---|---|
| `main.tf` | Calls VPC and EKS modules; supplies their network, access, add-on, and worker settings. |
| `variables.tf` | Declares inputs and checks their shape. Defaults prevent interactive variable questions; setup supplies real values. |
| `outputs.tf` | Prints useful resource IDs, endpoint, and kubectl configuration command. |
| `providers.tf` | Selects AWS region, tags, and the allowed account. |
| `versions.tf` | Constrains Terraform and pins AWS provider version. |
| `backend.tf` | Setup fills in the real S3 bucket, state key, region, lock table, and account. |
| `settings.json` | The six settings you may customize before setup. |
| `bootstrap/` | Separate Terraform root for creating and managing a new backend. The helper runs it for you. |
| `scripts/manage.py`, `run.sh` | Automate checks, setup, and saved-plan commands. |
| `tests/` | Offline tests with mocked AWS/Terraform calls. They never create resources. |
| `docs/REVIEW.md` | Findings, fixes, exact versions, and validation limits. |
| `docs/TROUBLESHOOTING.md` | Errors and less obvious operational challenges. |
| `docs/EXPLAINED.md` | Beginner explanation of the Terraform/AWS pieces. |
| `docs/RECOVERY.md` | Existing backend/state and interrupted setup recovery. |

Setup generates `generated.auto.tfvars.json`, backend configuration, and setup metadata. Keep these with the project securely. Keep the provider lockfiles under version control. Do not commit credentials, state files, saved plans, provider caches, or generated account-specific input files.

**Validation limit:** formatting/syntax checks, dependency initialization without a backend, and 26 offline helper tests passed. Full provider-backed `terraform validate` was blocked here by a local socket restriction. No AWS plan or apply was run. Read `docs/REVIEW.md` before deployment; this is not a claim of a tested live AWS deployment.
