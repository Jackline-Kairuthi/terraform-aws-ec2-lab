# Problems you can meet — and what they mean

Start with the **first meaningful error**, not the last summary line. Keep the current state and configuration. Correct the cause, create a fresh plan, and review it before retrying apply.

## Setup and init

| Symptom/challenge | Why it happens | What to check/do |
|---|---|---|
| Terraform asks for an S3 bucket | You ran root init before setup, or backend values are missing. | Run the appropriate setup route in README. A `.tfvars` variable cannot fill a Terraform backend block. |
| `No valid credential sources`, `ExpiredToken`, SSO login error | AWS is not signed in or the session expired. | Run `aws sts get-caller-identity`; refresh your selected profile/SSO session. Temporary credentials need a session token. |
| Wrong AWS account/profile | Your terminal is using different credentials than expected. | Check STS Account and Arn. Set the intended AWS profile. Environment access keys can take precedence over profile credentials. First-run account selection still requires your review. |
| `AccessDenied` while detecting a role/user | STS identity lookup works, but IAM lookup is not permitted. | The helper needs `iam:GetRole` or `iam:GetUser` to verify the permanent ARN, including role paths. Ask for those permissions. |
| `Invalid choice: describe-cluster-versions` | AWS CLI is too old. | Update AWS CLI v2. The helper checks regional Kubernetes support with this API. |
| `NoSuchBucket`, `403`, or wrong bucket owner | Incorrect name, account, permissions, or missing bucket. | Reuse the original backend file, verify bucket ownership/permissions, and distinguish access denied from not found. Do not invent a replacement bucket to bypass the error. |
| `PermanentRedirect`, wrong region | The backend region does not match the bucket's actual region. | Match the original bucket's region. This helper expects the backend and cluster in the same account/region. |
| DynamoDB `ResourceNotFoundException` | Wrong table name/region, or table was never created. | Confirm the existing table in that region. Its partition key must be exactly `LockID`, type String. |
| Backend initialized but later table access fails | S3 access and DynamoDB access are separate permissions. | State operations need table DescribeTable/GetItem/PutItem/DeleteItem in addition to S3 state read/write/list access. |
| `Backend configuration changed` | Cached configuration and the backend block differ. | Determine whether this is a real migration. Do not blindly use `-reconfigure` or `-migrate-state`; see RECOVERY.md. |
| Provider/module download, certificate, proxy, or checksum error | Registry/GitHub/release hosts are unreachable, TLS trust is wrong, or a package/cache is damaged. | Fix network/proxy/CA trust. Retry with authenticated packages. Do not disable TLS or discard checksum protection. Git must be available when module sources are fetched through Git. |
| `Failed to load plugin schemas` | Terraform cannot start a provider, sometimes because sandbox/socket permissions block it. | Check provider architecture, executable permissions, and the environment's restrictions. This was the restriction encountered during this review. |
| Unknown variable/default message says setup required | Generated inputs are absent, or you are in the wrong directory. | Run setup from the project root. Do not manually enter sentinel values such as `SETUP_REQUIRED`. |
| Setup stopped after creating some resources | Terraform or AWS returned an error part-way through. | Retain setup metadata and local state. Rerun setup for a pre-migration failure; handle interrupted state migration as described in RECOVERY.md. |

## Plan and apply

| Symptom/challenge | Why it happens | What to check/do |
|---|---|---|
| `AccessDenied`, `UnauthorizedOperation`, `iam:PassRole` denied | Permission to use the AWS CLI does not imply permission to create EKS infrastructure. | The deployment identity needs appropriate EKS, EC2/VPC, IAM role/policy/PassRole, Auto Scaling, KMS, CloudWatch Logs, S3, and DynamoDB permissions. Account policies, permission boundaries, SCPs, and region restrictions can still deny operations. |
| Quota or capacity error | Account vCPU, Elastic IP, NAT, VPC, EKS, or other quotas are exhausted; an AZ may temporarily lack capacity. | Check AWS Service Quotas and the exact resource/error. Instance offerings are not a capacity reservation. Do not change established subnet AZs casually. |
| Unsupported Kubernetes version | Support changed or the version is not available in that region. | Setup deliberately requires standard support. Check EKS support before changing `kubernetes_version`. Existing clusters require supported sequential upgrades, not arbitrary version jumps or downgrades. |
| Invalid principal ARN | An STS session, root ARN, service-linked role, incorrect path, or deleted IAM identity was supplied. | Use the verified permanent IAM role/user ARN. An EKS access-policy ARN is different from your administrator's IAM ARN. |
| Invalid VPC/subnet/security group ID | A manually supplied ID is stale or belongs to another account/region. | This project takes IDs directly from module outputs, so you should not need to paste these IDs. Recheck any manual customizations. |
| Existing cluster or IAM role already exists | AWS has the resource but the selected state does not track it, or a custom name conflicts. | Find the original state first. Intentional import requires a reviewed resource-to-address mapping. Do not randomly rename the cluster to hide a state problem. |
| Plan wants to create everything for an existing cluster | Wrong bucket/key/workspace, lost state, or unrelated project. | Stop before apply. Verify the original state key and default workspace. A correct bucket with a wrong key is still the wrong state. |
| Unexpected `-/+` or `must be replaced` | A change requires replacement; subnet ordering, CIDR, names, or resource addresses may have changed. | Read the exact change. Helper apply blocks this by default. Only use the explicit override for a deliberate, reviewed replacement. |
| `Error acquiring the state lock` | Another run is active, or a previous run died and left a lock. | Wait/check the other run. The helper waits up to 60 seconds. Use force-unlock only after verifying no writer is active and identifying the exact stale lock. Do not routinely disable locking. |
| `Saved plan is stale` or configuration changed | State or configuration changed after the plan was generated. | Generate and review a fresh plan. Do not reuse an old plan after another apply, an IP/settings change, or a dependency update. |
| EKS creation takes many minutes | Control plane and node group creation are asynchronous AWS operations. | Check the AWS EKS status/events. Avoid launching a second apply in another terminal. A timeout may leave valid partial resources tracked in state. |
| Add-on conflict/unhealthy | Existing Kubernetes configuration conflicts, or nodes are not ready. | Check EKS add-on health and node status. Review whether custom settings would be overwritten before resolving a conflict. |

The helper validates key identifiers and known prerequisites. It does **not** prove all permissions, SCP exceptions, quotas, real-time capacity, or service health. Those depend on your account and AWS at execution time.

## After apply: the cluster exists but something does not work

| Symptom/challenge | Likely cause and next step |
|---|---|
| kubectl times out | Your current public IP does not match the configured `/32`, a VPN/proxy changed the exit address, or private DNS/network routing is involved. For a normal IP change, rerun setup from the intended kubectl machine, then plan/apply the endpoint update. This Terraform configuration uses AWS APIs, so that update does not need kubectl access first. |
| kubectl says `Unauthorized`/`Forbidden` | Your current IAM identity is not the one in the EKS access entry, kubeconfig points to another cluster, or a recreated role has a new underlying principal identity. Confirm `aws sts get-caller-identity`, current kubeconfig context, and the EKS access entry. Updating kubeconfig alone does not grant permissions. |
| Worker nodes fail to join | Check NAT/route tables, VPC DNS, security groups, node IAM permissions, ECR/STS reachability, and node group health messages. The VPC dependency ensures routing is created first, but external policy/network changes can still break it. |
| Pods remain Pending | One `t3.medium` node has limited memory, CPU, and pod IP capacity. Review `kubectl describe pod` and node allocatable resources. `max_size = 2` does not install Cluster Autoscaler or automatically add a node. |
| PVC remains Pending | EBS CSI add-on and its IAM permissions are not installed by this template. A storage provisioner and suitable StorageClass are separate work. |
| Ingress/LoadBalancer does not appear | Subnet discovery tags do not install an ingress or AWS Load Balancer Controller. Install and configure the appropriate controller and IAM permissions for your application. |
| API is private from another VPC/VPN | Private endpoint access still needs routing, DNS, and security-group access. The public `/32` allowlist does not establish VPN connectivity. |

## Less obvious design limits

- **One NAT gateway:** saves compared with one per AZ, but outbound access is not resilient to that gateway's AZ failing. Traffic from the other AZ may incur cross-AZ charges.
- **One worker:** this is a small learning lab, not a highly available application platform. Two subnets do not imply two running worker nodes.
- **Networking overlaps:** the fixed `10.0.0.0/16` VPC and `/24` subnets may overlap an office/VPN/peered network. Choose addressing before deployment; changing it later can replace subnets and workers.
- **IP exhaustion:** the VPC CNI consumes subnet addresses for nodes/pods. A large scaling change can run out of IPs before it runs out of EC2 quota.
- **Broad Kubernetes admin:** the selected administrator receives cluster-wide administrator access. Production should use reviewed, narrower access roles.
- **CNI permissions:** the module's default worker IAM policy supports this lab's VPC CNI. Separate workload/CNI IAM roles are a production hardening task.
- **State and plans are sensitive:** state can contain credentials or secrets for future resources even when an output is marked sensitive. Versioning and encryption do not make a public bucket acceptable.
- **SSO sessions and long runs:** sessions can expire during provisioning. Use your normal renewable credentials/profile flow; never paste keys into backend configuration to work around it.
- **Charges continue while idle:** EKS control plane, EC2, disks, NAT, public IPv4, logs, KMS, and other created resources can incur charges. Closing the terminal does not stop them. Check AWS billing and destroy the lab when finished.
- **Destroy can be blocked:** controller-created load balancers, ENIs, or retained volumes can keep VPC dependencies alive. Remove application resources and inspect their retention policies before cluster deletion. Root destroy retains the backend by design.
- **DynamoDB locking is deprecated:** this version keeps it for your requested exercise. Plan a coordinated move to S3 lockfiles before future tool upgrades; all writers must follow the same locking arrangement during transition.

For an error report, provide the command, first relevant error, Terraform/AWS CLI versions, and whether this is new setup or backend reuse. Remove secrets and do not post raw state or saved plans.
