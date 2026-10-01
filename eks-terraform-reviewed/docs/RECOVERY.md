# Existing resources and interrupted setup

The priority is keeping the link between Terraform state and the resources it owns. Preserve the old project, current state, setup metadata, and backend values until the new workflow has been verified. Do not upload raw state/plans when asking for help.

## Existing backend but no saved backend.hcl

In the **original** bootstrap directory, use its original state and credentials:

```bash
terraform output state_bucket_name
terraform output lock_table_name
terraform output -raw infra_backend_config
```

That last output existed in the original uploaded bootstrap configuration. Save its actual contents as the original project's `infra/backend.hcl`, then use the reuse setup command from the revised project. If the old bootstrap configuration was customized and the output is absent, recover the same five fields from its original backend records: `bucket`, `key`, `region`, `encrypt`, and `dynamodb_table`.

The original infra key is `eks-lab/infra/terraform.tfstate`. A path on your computer is not an S3 key. Do not substitute the bootstrap state key for the infra state key.

If the original cluster state was kept **locally**, migrate it using the original configuration after confirming the destination key is correct and empty. This helper's reuse mode expects the original cluster state to be in S3; it deliberately does not import an unmanaged cluster or automatically merge two state files.

## A failure before state migration begins

Keep the same extracted directory. Correct the reported permissions, credentials, CLI, quota, or network issue. Rerun:

```bash
bash run.sh setup
```

The recorded bucket/table names are reused. Any successfully created bootstrap resources remain in its local state and Terraform can plan the remaining work. Do not delete local state or setup metadata to force a fresh start.

## An interrupted bootstrap migration

Setup writes `bootstrap/backend.tf` immediately before migrating state. If migration did not finish and that file exists, the next run stops rather than guessing which state copy is authoritative.

1. Stop other Terraform runs. Make secure copies of the project, local bootstrap state/backups, setup metadata, and any remote state object versions.
2. Identify the exact account, bucket, region, table, and bootstrap key recorded by setup.
3. Check whether the remote bootstrap state object exists and compare it with the local source: lineage, serial, resource addresses, and actual IDs. Do not confuse an access-denied response with a missing object.
4. If the destination is absent, complete migration from the confirmed local source using Terraform's documented state-migration workflow. If it already contains the same completed state, reinitialize against that verified remote state. If copies differ, stop and reconcile them before any write.
5. Only after confirming the bootstrap backend is initialized against the correct complete remote state should `bootstrap_remote` in `.setup.json` be set to `true`. Then rerun setup to initialize the root configuration.

This recovery is intentionally a manual review boundary. The script never automatically overwrites an existing bootstrap state object. Do not set the flag merely to bypass an error. Share the error and redacted backend details for help, not credentials or the state contents.

## Backend reconfiguration versus migration

`terraform init -reconfigure` changes the backend configuration Terraform uses; it does not copy your old state to a new location. `terraform init -migrate-state` attempts to move state. Using either blindly can leave Terraform looking at an empty or wrong state.

After a deliberate migration, verify resource addresses/IDs and review a fresh plan. If an established lab suddenly shows all resources as new, stop before applying.

## A failed root apply

Terraform generally records successful operations even if a later operation fails. Fix the first error, then run a new `bash run.sh plan` and review the result before `bash run.sh apply`. Do not rerun an old saved plan or discard the remote state.

If AWS created a resource but state was not saved, verify the exact resource and Terraform address before any import. Importing unrelated resources would hand this project control over them.

## Destroying backend resources

The normal root destroy retains S3/DynamoDB. Keep them while you need state history or while any Terraform configuration still uses them. Final backend removal requires a separate deliberate state/retention decision, removal of the lifecycle protection, and handling all S3 object versions. Do not attempt it while the backend is serving an active Terraform run.
