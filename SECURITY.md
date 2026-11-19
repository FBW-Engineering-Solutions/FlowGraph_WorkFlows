# Security and operational boundaries

Workflows are data **and potentially executable programs**. They can contain Python,
file operations, external commands, and network requests. Review before executing.
Static CI never executes the workflow or imports user-specified modules.

Do not commit secrets, database exports, server `.env` files, real private datasets,
or deployment credentials. Imported public file paths are examples from the source
catalog, not assurances that those paths exist on your machine.

Do not report exposed credentials in a public issue. Contact the repository owner
privately, rotate/revoke credentials immediately, and arrange history cleanup if
needed. Removing a secret from the latest commit is not sufficient.

CI intentionally uses hosted runners, a read-only token, no deployment secrets,
and the `pull_request` event rather than `pull_request_target`. Do not add production
access to this workflow. Review changes to the workflow, validator, and tests;
passing PR checks alone cannot prove those files were not weakened.

The current milestone does not change production access control, disable website
editing, build/import production SQL, or configure hosting tasks. Follow the staged
cutover plan in README.md before treating Git as the live service's only writer.